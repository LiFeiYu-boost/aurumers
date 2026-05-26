"""诚实的"日线方向择时能否做出真优势"研究管线。

验收标准(用户锁定):择时策略的【样本外 walk-forward Sharpe】必须跑赢【买入持有】。
靶子:日线方向,但只在高置信时出手(选择性预测),空仓/做空规避回撤来提升风险调整收益。

防自欺三原则:
  1) 所有特征在 t 日只用 ≤t 的信息,预测 t→t+1 收益;宏观因子额外滞后 1 日(发布延迟)。
  2) 严格 walk-forward:扩张窗口,每季度重训,只在训练集之外的日子评估。
  3) 阈值固定(0.55/0.45)非拟合 OOS;交易成本计入;Sharpe 与买入持有在同一 OOS 区间比。

数据源:GC=F(yfinance,2004+,OHLC) + FRED 宏观(实际收益率/名义利率/美元/VIX)。
用法:  .venv/bin/python scripts/research_edge.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

GOLD_CSV = "/tmp/gcf_hist.csv"
COT_CSV = "/tmp/cot_gold.csv"
COT_FEATURES = ["cot_net", "cot_net_z", "cot_net_chg4"]
FRED = {
    "dfii10": "/tmp/fred_DFII10.csv",     # 10y 实际收益率(TIPS)——黄金第一驱动
    "dgs10": "/tmp/fred_DGS10.csv",       # 10y 名义
    "dgs2": "/tmp/fred_DGS2.csv",         # 2y 名义
    "dxy": "/tmp/fred_DTWEXBGS.csv",      # 广义美元指数
    "vix": "/tmp/fred_VIXCLS.csv",        # 风险情绪
}
TRADING_DAYS = 252


def load_gold(path: str = GOLD_CSV) -> pd.DataFrame:
    head = pd.read_csv(path, nrows=0)
    if "Date" in head.columns:  # SGE 格式:有具名 Date 列
        g = pd.read_csv(path, parse_dates=["Date"]).set_index("Date").sort_index()
    else:                        # GC=F 格式:首列为无名日期索引
        g = pd.read_csv(path, index_col=0, parse_dates=[0]).sort_index()
        g.index.name = "Date"
    g = g[["Open", "High", "Low", "Close"]].astype(float)
    g = g[g["Close"] > 0].dropna()
    return g


def load_fred() -> pd.DataFrame:
    cols = {}
    for name, path in FRED.items():
        s = pd.read_csv(path, parse_dates=["observation_date"]).set_index("observation_date")
        col = s.columns[0]
        v = pd.to_numeric(s[col], errors="coerce")  # FRED 用 '.' 表示缺失
        cols[name] = v
    df = pd.DataFrame(cols).sort_index()
    return df


def load_cot(path: str = COT_CSV) -> pd.DataFrame:
    """CFTC COMEX 黄金 COT 周报 → 投机净持仓特征。
    防泄漏:报告日是周二,周五盘后发布,故标记为'次周一可用'(report+6天)。"""
    c = pd.read_csv(path, parse_dates=["date"]).sort_values("date")
    c["cot_net"] = c["net_spec_pct"]
    mu = c["cot_net"].rolling(104, min_periods=52).mean()
    sd = c["cot_net"].rolling(104, min_periods=52).std()
    c["cot_net_z"] = (c["cot_net"] - mu) / sd       # 2年滚动 z 分数:持仓拥挤度
    c["cot_net_chg4"] = c["cot_net"].diff(4)         # 4周净持仓变化
    c["avail"] = c["date"] + pd.Timedelta(days=6)
    return c[["avail"] + COT_FEATURES].dropna().sort_values("avail")


def build_features(g: pd.DataFrame, m: pd.DataFrame, cot: pd.DataFrame | None = None) -> pd.DataFrame:
    df = g.copy()
    c = df["Close"]
    ret1 = c.pct_change()

    # —— 价格/动量/波动(全部因果) ——
    df["ret_1"] = ret1
    df["ret_5"] = c.pct_change(5)
    df["ret_10"] = c.pct_change(10)
    df["ret_20"] = c.pct_change(20)
    # RSI14
    delta = c.diff()
    up = delta.clip(lower=0).rolling(14).mean()
    dn = (-delta.clip(upper=0)).rolling(14).mean()
    df["rsi_14"] = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    # ATR14 / close
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - c.shift()).abs(),
        (df["Low"] - c.shift()).abs(),
    ], axis=1).max(axis=1)
    df["atr_norm"] = tr.rolling(14).mean() / c
    # 距 MA20 的 z 分数
    ma20 = c.rolling(20).mean()
    sd20 = c.rolling(20).std()
    df["ma20_z"] = (c - ma20) / sd20
    df["ma50_dist"] = c / c.rolling(50).mean() - 1
    # 已实现波动 + 波动状态
    df["rv_20"] = ret1.rolling(20).std() * np.sqrt(TRADING_DAYS)
    df["vol_regime"] = ret1.rolling(10).std() / ret1.rolling(60).std()
    df["dow"] = df.index.dayofweek

    # —— 宏观因子(对齐到金价交易日,前向填充=因果,再滞后1日防发布泄漏) ——
    m2 = m.reindex(df.index.union(m.index)).sort_index().ffill().reindex(df.index)
    m2 = m2.shift(1)
    df["real_yield"] = m2["dfii10"]
    df["real_yield_chg5"] = m2["dfii10"].diff(5)
    df["dgs10_chg5"] = m2["dgs10"].diff(5)
    df["slope_10_2"] = m2["dgs10"] - m2["dgs2"]
    df["dxy_chg5"] = m2["dxy"].pct_change(5)
    df["dxy_chg20"] = m2["dxy"].pct_change(20)
    df["vix"] = m2["vix"]
    df["vix_chg5"] = m2["vix"].diff(5)

    # —— COT 投机持仓(正交数据,merge_asof 按可用日回填,严格因果) ——
    if cot is not None:
        daily = df.index.to_frame(index=False, name="Date").sort_values("Date")
        merged = pd.merge_asof(daily, cot, left_on="Date", right_on="avail",
                               direction="backward").set_index("Date")
        for col in COT_FEATURES:
            df[col] = merged[col].reindex(df.index)

    # —— 目标:明日方向 ——
    df["next_ret"] = c.shift(-1) / c - 1
    df["y"] = (df["next_ret"] > 0).astype(int)
    return df


FEATURES = [
    "ret_1", "ret_5", "ret_10", "ret_20", "rsi_14", "atr_norm", "ma20_z",
    "ma50_dist", "rv_20", "vol_regime", "dow",
    "real_yield", "real_yield_chg5", "dgs10_chg5", "slope_10_2",
    "dxy_chg5", "dxy_chg20", "vix", "vix_chg5",
]


def walk_forward(df: pd.DataFrame, min_train=1000, step=63) -> pd.DataFrame:
    """扩张窗口 walk-forward,每 step 日重训一次,收集 OOS 的 P(up)。"""
    d = df.dropna(subset=FEATURES + ["y", "next_ret"]).copy()
    X = d[FEATURES].values
    y = d["y"].values
    n = len(d)
    proba = np.full(n, np.nan)
    start = min_train
    while start < n:
        end = min(start + step, n)
        model = HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.03, max_depth=3,
            l2_regularization=1.0, min_samples_leaf=40, random_state=42,
        )
        model.fit(X[:start], y[:start])
        proba[start:end] = model.predict_proba(X[start:end])[:, 1]
        start = end
    d["p_up"] = proba
    return d[~np.isnan(d["p_up"])].copy()


def perf(rets: pd.Series) -> dict:
    rets = rets.dropna()
    if len(rets) == 0 or rets.std() == 0:
        return {"sharpe": 0, "cagr": 0, "maxdd": 0, "vol": 0}
    sharpe = rets.mean() / rets.std() * np.sqrt(TRADING_DAYS)
    cum = (1 + rets).cumprod()
    cagr = cum.iloc[-1] ** (TRADING_DAYS / len(rets)) - 1
    dd = (cum / cum.cummax() - 1).min()
    return {"sharpe": sharpe, "cagr": cagr, "maxdd": dd, "vol": rets.std() * np.sqrt(TRADING_DAYS)}


def strategy(d: pd.DataFrame, up=0.55, dn=0.45, cost=0.0001, allow_short=True) -> dict:
    pos = pd.Series(0.0, index=d.index)
    pos[d["p_up"] >= up] = 1.0
    if allow_short:
        pos[d["p_up"] <= dn] = -1.0
    turnover = pos.diff().abs().fillna(pos.abs())
    strat_ret = pos * d["next_ret"] - turnover * cost
    # 命中率(只看出手日)
    active = pos != 0
    hit = ((np.sign(pos) == np.sign(d["next_ret"])) & active).sum() / max(active.sum(), 1)
    out = perf(strat_ret)
    out["coverage"] = active.mean()
    out["hit"] = hit
    out["long_share"] = (pos > 0).mean()
    return out


def strategy_long_bias(d: pd.DataFrame, dn=0.45, short_at=None, cost=0.0001) -> dict:
    """默认做多(吃牛市漂移),只在高置信看跌时让开(空仓或做空)。"""
    pos = pd.Series(1.0, index=d.index)
    pos[d["p_up"] <= dn] = 0.0
    if short_at is not None:
        pos[d["p_up"] <= short_at] = -1.0
    turnover = pos.diff().abs().fillna(pos.abs())
    strat_ret = pos * d["next_ret"] - turnover * cost
    out = perf(strat_ret)
    out["coverage"] = (pos != 0).mean()
    out["long_share"] = (pos > 0).mean()
    return out


def strategy_voltarget(d: pd.DataFrame, target=0.10, cap=1.5, cost=0.0001,
                       tilt=False) -> dict:
    """波动率目标:按近20日已实现波动缩放多头敞口,使组合波动≈target。
    tilt=True 时再用 P(up) 在 [0.5,1.5] 之间轻度加权(方向倾斜)。"""
    rv = d["rv_20"].clip(lower=0.03)
    pos = (target / rv).clip(upper=cap)
    if tilt:
        pos = pos * (0.5 + d["p_up"]).clip(0.0, 1.5)
    turnover = pos.diff().abs().fillna(pos.abs())
    strat_ret = pos * d["next_ret"] - turnover * cost
    out = perf(strat_ret)
    out["coverage"] = (pos > 0).mean()
    out["avg_pos"] = pos.mean()
    return out


def horizon_experiment(df: pd.DataFrame, min_train: int = 1000):
    """测不同预测周期的方向可预测性 + 趋势跟随策略 Sharpe。
    H=1 日线(噪声) vs H=5/10/20(动量结构应更强)。"""
    print("\n【最后一条预测路径 — 拉长周期(动量效应)】")
    print("  预测'未来H日方向',每日按最新预测持有多/空仓,与买入持有比 Sharpe")
    base = df.copy()
    c = base["Close"]
    for H in [1, 5, 10, 20]:
        base["y"] = (c.shift(-H) / c - 1 > 0).astype(int)
        base["next_ret"] = c.shift(-1) / c - 1  # 实际持仓按日结算
        d = base.dropna(subset=FEATURES + ["y", "next_ret"]).copy()
        X, y = d[FEATURES].values, d["y"].values
        n = len(d)
        proba = np.full(n, np.nan)
        start = min_train
        while start < n:
            end = min(start + 63, n)
            mdl = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.03,
                max_depth=3, l2_regularization=1.0, min_samples_leaf=40, random_state=42)
            mdl.fit(X[:start], y[:start]); proba[start:end] = mdl.predict_proba(X[start:end])[:, 1]
            start = end
        d["p_up"] = proba; d = d[~np.isnan(d["p_up"])]
        acc = ((d["p_up"] > 0.5).astype(int) == d["y"]).mean()
        # 趋势跟随:p>0.5 多,<0.5 空(或只多)
        pos = pd.Series(0.0, index=d.index); pos[d["p_up"] > 0.52] = 1.0; pos[d["p_up"] < 0.48] = -1.0
        sret = pos * d["next_ret"] - pos.diff().abs().fillna(0) * 0.0001
        bh_s = perf(d["next_ret"])["sharpe"]; st = perf(sret)
        v = "✅" if st["sharpe"] > bh_s else "❌"
        print(f"  H={H:2d}日: 方向命中 {acc*100:.1f}% | 趋势策略 Sharpe {st['sharpe']:.3f}{v}(B&H {bh_s:.3f}) | 年化 {st['cagr']*100:5.1f}%")
        if H == 20:
            d20, pos20 = d, pos  # 留作子区间检验
    # H=20 子区间稳健 + 只多版本(去掉做空看是否仍赢)
    print("\n  ↳ H=20 稳健检验(多空 / 只多·空仓):")
    bounds = ["2010-01-01", "2014-01-01", "2018-01-01", "2022-01-01", "2027-01-01"]
    for a, b in zip(bounds[:-1], bounds[1:]):
        sub = d20[(d20.index >= a) & (d20.index < b)]
        if len(sub) < 60: continue
        ps = pos20[sub.index]
        ls = ps.clip(lower=0)  # 只多
        bh_s = perf(sub["next_ret"])["sharpe"]
        msr = perf(ps * sub["next_ret"] - ps.diff().abs().fillna(0)*0.0001)["sharpe"]
        lsr = perf(ls * sub["next_ret"] - ls.diff().abs().fillna(0)*0.0001)["sharpe"]
        print(f"    {a[:4]}–{b[:4]}: B&H {bh_s:6.3f} | 多空 {msr:6.3f}{'✅' if msr>bh_s else '❌'} | 只多 {lsr:6.3f}{'✅' if lsr>bh_s else '❌'}")
    print()


def efficiency_ratio(c: pd.Series, n: int = 20) -> pd.Series:
    """Kaufman 效率比:|净变化| / Σ|日变化|。≈1 强趋势,≈0 震荡。"""
    change = (c - c.shift(n)).abs()
    vol = c.diff().abs().rolling(n).sum()
    return change / vol.replace(0, np.nan)


def _fit_horizon(d: pd.DataFrame, X, ycol: str, min_train: int, step: int = 63):
    y = d[ycol].values
    n = len(d)
    proba = np.full(n, np.nan)
    start = min_train
    while start < n:
        end = min(start + step, n)
        mdl = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.03,
            max_depth=3, l2_regularization=1.0, min_samples_leaf=40, random_state=42)
        mdl.fit(X[:start], y[:start])
        proba[start:end] = mdl.predict_proba(X[start:end])[:, 1]
        start = end
    return proba


def _lf(d, pos, cost=0.0001):
    """给定仓位序列,算只多策略表现。"""
    sret = pos * d["next_ret"] - pos.diff().abs().fillna(pos.abs()) * cost
    return perf(sret)


def ensemble_experiment(df: pd.DataFrame, min_train: int = 1000, label: str = ""):
    print(f"\n{'='*64}\n多周期集成 + 状态门控 [{label}]\n{'='*64}")
    c = df["Close"]
    base = df.copy()
    base["next_ret"] = c.shift(-1) / c - 1
    base["er20"] = efficiency_ratio(c, 20)
    horizons = [10, 20, 40]
    for H in horizons:
        base[f"y{H}"] = (c.shift(-H) / c - 1 > 0).astype(int)
    need = FEATURES + ["next_ret", "er20"] + [f"y{H}" for H in horizons]
    d = base.dropna(subset=need).copy()
    X = d[FEATURES].values
    for H in horizons:
        d[f"p{H}"] = _fit_horizon(d, X, f"y{H}", min_train)
    d["p_ens"] = d[[f"p{H}" for H in horizons]].mean(axis=1)
    d = d[d["p_ens"].notna()].copy()
    span = f"{d.index.min().date()} → {d.index.max().date()} ({len(d)}d)"
    bh = perf(d["next_ret"])
    print(f"样本外 {span} | 买入持有 Sharpe {bh['sharpe']:.3f} 回撤 {bh['maxdd']*100:.1f}%")

    # 各策略(全为只多/否则空仓)
    strats = {}
    strats["单H=20 (旧基准)"] = (d["p20"] > 0.5).astype(float)
    strats["集成 H10/20/40"] = (d["p_ens"] > 0.5).astype(float)
    pos_gate = ((d["p_ens"] > 0.5) & (d["er20"] > 0.30)).astype(float)
    strats["集成+状态门控(ER>.30)"] = pos_gate
    strats["集成+信心缩放仓位"] = ((d["p_ens"] - 0.5) * 8).clip(0, 1.0)
    pos_both = (((d["p_ens"] - 0.5) * 8).clip(0, 1.0)) * (d["er20"] > 0.30).astype(float)
    strats["集成+门控+信心缩放"] = pos_both

    print("\n  策略(只多/空仓):")
    results = {}
    for name, pos in strats.items():
        r = _lf(d, pos); results[name] = (pos, r)
        v = "✅" if r["sharpe"] > bh["sharpe"] else "❌"
        print(f"  {name:24s} Sharpe {r['sharpe']:.3f}{v} | 年化 {r['cagr']*100:5.1f}% | 回撤 {r['maxdd']*100:6.1f}%")

    # 子区间稳健性(真正的赢家:纯集成 / 集成+信心缩放)
    pos_ens = (d["p_ens"] > 0.5).astype(float)
    pos_scale = ((d["p_ens"] - 0.5) * 8).clip(0, 1.0)
    print("\n  子区间稳健性(B&H / 纯集成 / 集成+信心缩放):")
    bounds = ["2010-01-01", "2014-01-01", "2018-01-01", "2022-01-01", "2027-01-01"]
    for a, b in zip(bounds[:-1], bounds[1:]):
        sub = d[(d.index >= a) & (d.index < b)]
        if len(sub) < 60:
            continue
        bh_s = perf(sub["next_ret"])["sharpe"]
        e = _lf(sub, pos_ens[sub.index])["sharpe"]
        sc = _lf(sub, pos_scale[sub.index])["sharpe"]
        print(f"    {a[:4]}–{b[:4]}: B&H {bh_s:6.3f} | 纯集成 {e:6.3f}{'✅' if e>bh_s else '❌'} | 集成+缩放 {sc:6.3f}{'✅' if sc>bh_s else '❌'}")
    print()


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default=GOLD_CSV, help="金价 CSV 路径")
    ap.add_argument("--min-train", type=int, default=1000, help="walk-forward 初始训练窗口(交易日)")
    ap.add_argument("--label", default="GC=F", help="数据源标签")
    ap.add_argument("--mode", default="full", choices=["full", "ensemble"], help="full=原始全套;ensemble=只跑多周期集成实验")
    ap.add_argument("--cot", action="store_true", help="加入 CFTC COT 投机持仓特征")
    args = ap.parse_args()

    g = load_gold(args.gold)
    m = load_fred()
    cot = None
    if args.cot:
        cot = load_cot()
        FEATURES.extend(COT_FEATURES)
        print(f"[已加入 COT 特征: {COT_FEATURES}]")
    df = build_features(g, m, cot=cot)
    if args.mode == "ensemble":
        ensemble_experiment(df, min_train=args.min_train, label=args.label)
        return
    d = walk_forward(df, min_train=args.min_train)
    span = f"{d.index.min().date()} → {d.index.max().date()} ({len(d)} 交易日)"
    print(f"\n{'='*64}\n数据源 [{args.label}]  样本外区间: {span}\n{'='*64}")

    bh = perf(d["next_ret"])  # 买入持有(同区间)
    print("\n【买入持有 基准 — 必须跑赢的及格线】")
    print(f"  Sharpe {bh['sharpe']:.3f} | 年化 {bh['cagr']*100:5.1f}% | 最大回撤 {bh['maxdd']*100:6.1f}% | 年化波动 {bh['vol']*100:.1f}%")

    # 模型本身的方向分类能力
    auc_acc = ((d["p_up"] > 0.5).astype(int) == d["y"]).mean()
    print(f"\n【模型方向命中(全样本外,无择时)】 准确率 {auc_acc*100:.1f}%  (P(up)均值 {d['p_up'].mean():.3f})")

    print("\n【选择性择时策略】(P≥0.55 做多 / P≤0.45 做空 / 否则空仓;含1bp成本)")
    for short, lbl in [(True, "多空"), (False, "只多/空仓")]:
        s = strategy(d, allow_short=short)
        verdict = "✅ 跑赢" if s["sharpe"] > bh["sharpe"] else "❌ 未跑赢"
        print(f"  [{lbl}] Sharpe {s['sharpe']:.3f} {verdict}基准 | 年化 {s['cagr']*100:5.1f}% | 回撤 {s['maxdd']*100:6.1f}% | "
              f"出手率 {s['coverage']*100:.0f}% | 出手命中 {s['hit']*100:.1f}%")

    print("\n【阈值敏感性(只多/空仓,诊断用)】")
    for up in [0.52, 0.55, 0.58, 0.60]:
        s = strategy(d, up=up, dn=1 - up, allow_short=False)
        print(f"  阈值 {up:.2f}: Sharpe {s['sharpe']:.3f} | 出手率 {s['coverage']*100:3.0f}% | 命中 {s['hit']*100:.1f}% | 年化 {s['cagr']*100:5.1f}%")

    print("\n【变体A — 默认做多,只在高置信看跌时让开(吃住牛市漂移)】")
    for dn, sh, lbl in [(0.45, None, "P≤.45空仓"), (0.40, None, "P≤.40空仓"), (0.42, 0.35, "P≤.42空仓/≤.35做空")]:
        s = strategy_long_bias(d, dn=dn, short_at=sh)
        v = "✅ 跑赢" if s["sharpe"] > bh["sharpe"] else "❌"
        print(f"  [{lbl}] Sharpe {s['sharpe']:.3f} {v} | 年化 {s['cagr']*100:5.1f}% | 回撤 {s['maxdd']*100:6.1f}% | 在场 {s['coverage']*100:.0f}%")

    print("\n【变体B — 波动率目标仓位(已知最稳的 Sharpe 提升器)】")
    for tgt, tilt, lbl in [(0.10, False, "目标10%vol"), (0.12, False, "目标12%vol"), (0.12, True, "目标12%+方向倾斜")]:
        s = strategy_voltarget(d, target=tgt, tilt=tilt)
        v = "✅ 跑赢" if s["sharpe"] > bh["sharpe"] else "❌"
        print(f"  [{lbl}] Sharpe {s['sharpe']:.3f} {v} | 年化 {s['cagr']*100:5.1f}% | 回撤 {s['maxdd']*100:6.1f}% | 均仓位 {s.get('avg_pos',0):.2f}")

    # —— 决定性稳健检验:子区间是否处处站得住 ——
    print("\n【稳健性 — 分子区间 Sharpe(B&H / 默认多·让开 / 波动目标+倾斜)】")
    bounds = ["2010-01-01", "2014-01-01", "2018-01-01", "2022-01-01", "2027-01-01"]
    for a, b in zip(bounds[:-1], bounds[1:]):
        sub = d[(d.index >= a) & (d.index < b)]
        if len(sub) < 60:
            continue
        bh_s = perf(sub["next_ret"])["sharpe"]
        lb_s = strategy_long_bias(sub, dn=0.40)["sharpe"]
        vt_s = strategy_voltarget(sub, target=0.12, tilt=True)["sharpe"]
        w1 = "✅" if lb_s > bh_s else "❌"
        w2 = "✅" if vt_s > bh_s else "❌"
        print(f"  {a[:4]}–{b[:4]}: B&H {bh_s:6.3f} | 默认多·让开 {lb_s:6.3f}{w1} | 波动目标+倾斜 {vt_s:6.3f}{w2}")

    horizon_experiment(df, min_train=args.min_train)


if __name__ == "__main__":
    main()
