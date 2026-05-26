"""生产级黄金趋势信号 —— 多周期集成(H=10/20/40)。

来源:scripts/research_edge.py 的严格 walk-forward 验证。结论是:
  - 日线方向=噪声;有效的是「未来约 1 个月趋势」。
  - 多周期集成(10/20/40 日三个梯度提升模型的 P(up) 平均)样本外 Sharpe ~1.0、
    只做多不做空、回撤比死扛砍半,跨美元/人民币、多个子区间复现。
  - COT 持仓作模型特征反而拖累(丢弃),但可作产品端「拥挤度」定性提示。

本模块把该信号做成生产可调用的接口:
  - load_gold_sge() / load_macro()  取数(akshare SGE + FRED,均支持 CSV 回退)
  - build_features(df)               与回测同一套因果特征(无 COT、无门控)
  - train_models(df)                 训练 H=10/20/40 三个模型(全历史,非 walk-forward)
  - compute_signal(df, models)       产出结构化信号 dict(方向/置信/目标敞口/各周期一致性/拥挤度)

设计取舍:推断只需最新一天特征,训练用全部历史;生产里按周/月重训即可。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

HORIZONS = (10, 20, 40)
TRADING_DAYS = 252
OZ2G = 31.1035

FEATURES = [
    "ret_1", "ret_5", "ret_10", "ret_20", "rsi_14", "atr_norm", "ma20_z",
    "ma50_dist", "rv_20", "vol_regime", "dow",
    "real_yield", "real_yield_chg5", "dgs10_chg5", "slope_10_2",
    "dxy_chg5", "dxy_chg20", "vix", "vix_chg5",
]

# FRED 序列 → 内部名(可被 FRED_PROXY 环境变量影响取数)
_FRED = {
    "dfii10": "DFII10", "dgs10": "DGS10", "dgs2": "DGS2",
    "dxy": "DTWEXBGS", "vix": "VIXCLS",
}


# ----------------------------- 取数 -----------------------------
def load_gold_sge(csv: str | None = None) -> pd.DataFrame:
    """SGE Au(T+D) 日线 OHLC。优先 akshare(国内稳),失败回退 CSV。"""
    if csv and os.path.exists(csv):
        g = pd.read_csv(csv, parse_dates=["Date"]).set_index("Date").sort_index()
    else:
        from tools.gold_history import fetch_sge_history
        rows = fetch_sge_history()
        g = pd.DataFrame(rows).rename(columns={
            "date": "Date", "open": "Open", "high": "High", "low": "Low", "close": "Close"})
        g["Date"] = pd.to_datetime(g["Date"])
        g = g.set_index("Date").sort_index()
    g = g[["Open", "High", "Low", "Close"]].astype(float)
    return g[g["Close"] > 0].dropna()


def _fred_csv(series_id: str) -> pd.Series:
    import urllib.request
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    proxy = os.environ.get("FRED_PROXY")
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"https": proxy, "http": proxy}) if proxy
        else urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=40) as r:
        df = pd.read_csv(r, parse_dates=["observation_date"]).set_index("observation_date")
    return pd.to_numeric(df.iloc[:, 0], errors="coerce")


def load_macro(csv_dir: str | None = None) -> pd.DataFrame:
    """FRED 宏观因子。csv_dir 提供时从 fred_<ID>.csv 读,否则联网拉。"""
    cols = {}
    for name, sid in _FRED.items():
        if csv_dir and os.path.exists(os.path.join(csv_dir, f"fred_{sid}.csv")):
            s = pd.read_csv(os.path.join(csv_dir, f"fred_{sid}.csv"),
                            parse_dates=["observation_date"]).set_index("observation_date")
            cols[name] = pd.to_numeric(s.iloc[:, 0], errors="coerce")
        else:
            cols[name] = _fred_csv(sid)
    return pd.DataFrame(cols).sort_index()


# --------------------------- 特征工程 ---------------------------
def build_features(g: pd.DataFrame, m: pd.DataFrame) -> pd.DataFrame:
    df = g.copy()
    c = df["Close"]
    ret1 = c.pct_change()
    df["ret_1"], df["ret_5"] = ret1, c.pct_change(5)
    df["ret_10"], df["ret_20"] = c.pct_change(10), c.pct_change(20)
    delta = c.diff()
    up = delta.clip(lower=0).rolling(14).mean()
    dn = (-delta.clip(upper=0)).rolling(14).mean()
    df["rsi_14"] = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    tr = pd.concat([df["High"] - df["Low"],
                    (df["High"] - c.shift()).abs(),
                    (df["Low"] - c.shift()).abs()], axis=1).max(axis=1)
    df["atr_norm"] = tr.rolling(14).mean() / c
    df["ma20_z"] = (c - c.rolling(20).mean()) / c.rolling(20).std()
    df["ma50_dist"] = c / c.rolling(50).mean() - 1
    df["rv_20"] = ret1.rolling(20).std() * np.sqrt(TRADING_DAYS)
    df["vol_regime"] = ret1.rolling(10).std() / ret1.rolling(60).std()
    df["dow"] = df.index.dayofweek

    m2 = m.reindex(df.index.union(m.index)).sort_index().ffill().reindex(df.index).shift(1)
    df["real_yield"] = m2["dfii10"]
    df["real_yield_chg5"] = m2["dfii10"].diff(5)
    df["dgs10_chg5"] = m2["dgs10"].diff(5)
    df["slope_10_2"] = m2["dgs10"] - m2["dgs2"]
    df["dxy_chg5"] = m2["dxy"].pct_change(5)
    df["dxy_chg20"] = m2["dxy"].pct_change(20)
    df["vix"] = m2["vix"]
    df["vix_chg5"] = m2["vix"].diff(5)
    return df


# --------------------------- 训练/推断 ---------------------------
def _new_model() -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.03, max_depth=3,
        l2_regularization=1.0, min_samples_leaf=40, random_state=42)


def train_models(df: pd.DataFrame) -> dict[int, HistGradientBoostingClassifier]:
    """对每个周期 H 训练一个模型(用全部有标签的历史)。"""
    c = df["Close"]
    models = {}
    for H in HORIZONS:
        y = (c.shift(-H) / c - 1 > 0).astype(int)
        d = df.assign(_y=y).dropna(subset=FEATURES + ["_y"])
        mdl = _new_model()
        mdl.fit(d[FEATURES].values, d["_y"].values)
        models[H] = mdl
    return models


def compute_signal(df: pd.DataFrame, models: dict[int, HistGradientBoostingClassifier],
                   cot_net_z: float | None = None) -> dict:
    """对最新一天产出结构化信号。"""
    latest = df.dropna(subset=FEATURES).iloc[-1:]
    X = latest[FEATURES].values
    probs = {H: float(models[H].predict_proba(X)[0, 1]) for H in HORIZONS}
    prob = float(np.mean(list(probs.values())))
    target = float(np.clip((prob - 0.5) * 8, 0.0, 1.0))  # 信心缩放目标敞口 0~1
    agree = sum(p > 0.5 for p in probs.values())          # 0~3 个周期看多

    if prob >= 0.55 and agree == 3:
        direction, conf = "看多", "高"
    elif prob >= 0.52:
        direction, conf = "看多", "中"
    elif prob <= 0.45 and agree == 0:
        direction, conf = "看空", "高"
    elif prob <= 0.48:
        direction, conf = "看空", "中"
    else:
        direction, conf = "中性", "低"

    crowding = None
    if cot_net_z is not None:
        crowding = "偏高" if cot_net_z >= 1.0 else ("偏低" if cot_net_z <= -1.0 else "正常")

    return {
        "asof": latest.index[-1].strftime("%Y-%m-%d"),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "price_cny_per_g": round(float(latest["Close"].iloc[-1]), 2),
        "prob_up": round(prob, 4),
        "prob_by_horizon": {f"H{H}": round(probs[H], 4) for H in HORIZONS},
        "direction": direction,
        "confidence": conf,
        "horizon_agreement": agree,          # 3 个周期里几个看多
        "target_exposure": round(target, 3),  # 建议黄金敞口(占你黄金配置的比例)
        "crowding": crowding,
        "model": "trend_ensemble_h10_20_40_v1",
    }


def generate(gold_csv: str | None = None, macro_csv_dir: str | None = None,
             cot_net_z: float | None = None) -> dict:
    """一站式:取数→训练→出信号(慢,每次重训;离线/调试用)。"""
    g = load_gold_sge(gold_csv)
    m = load_macro(macro_csv_dir)
    df = build_features(g, m)
    models = train_models(df)
    return compute_signal(df, models, cot_net_z=cot_net_z)


def load_bundle(path: str) -> dict:
    """加载离线打包好的模型(joblib)。生产推断用,不重训。"""
    return joblib.load(path)


def infer(bundle: dict, gold_csv: str | None = None, macro_csv_dir: str | None = None,
          cot_net_z: float | None = None) -> dict:
    """用已训练 bundle 对最新数据出信号(快)。"""
    g = load_gold_sge(gold_csv)
    m = load_macro(macro_csv_dir)
    df = build_features(g, m)
    return compute_signal(df, bundle["models"], cot_net_z=cot_net_z)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold-csv")
    ap.add_argument("--macro-dir")
    ap.add_argument("--cot-z", type=float)
    a = ap.parse_args()
    print(json.dumps(generate(a.gold_csv, a.macro_dir, a.cot_z), ensure_ascii=False, indent=2))
