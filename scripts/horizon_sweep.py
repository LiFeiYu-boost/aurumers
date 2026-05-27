"""精细周期扫描:方向可预测性从第几天开始真正显现?
对 H=1,3,5,8,10,12,15,18,20,25,30 各做 walk-forward,报命中率 + 趋势策略 Sharpe。
用法: .venv/bin/python scripts/horizon_sweep.py --gold /tmp/xaucny_hist.csv
"""
from __future__ import annotations
import argparse
import numpy as np
import pandas as pd
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sklearn.ensemble import HistGradientBoostingClassifier
from chains.trend_signal import build_features, load_gold_sge, load_macro, FEATURES

TD = 252
HS = [5, 10, 20, 30, 45, 60, 90, 120]


def sharpe(r):
    r = r.dropna()
    return r.mean() / r.std() * np.sqrt(TD) if len(r) and r.std() else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="/tmp/xaucny_hist.csv")
    ap.add_argument("--macro", default="/tmp")
    ap.add_argument("--min-train", type=int, default=1000)
    a = ap.parse_args()
    g = load_gold_sge(a.gold)
    m = load_macro(a.macro)
    base = build_features(g, m)
    c = base["Close"]
    base["next_ret"] = c.shift(-1) / c - 1
    bh = sharpe(base["next_ret"].iloc[a.min_train:])
    print(f"\n样本外 {len(base)-a.min_train} 日 | 买入持有 Sharpe {bh:.3f}\n")
    print(f"{'周期H':>5} {'模型命中':>8} {'无脑猜涨':>8} {'真技能':>7} {'趋势Sharpe':>11}")
    for H in HS:
        base["y"] = (c.shift(-H) / c - 1 > 0).astype(int)
        d = base.dropna(subset=FEATURES + ["y", "next_ret"]).copy()
        X, y = d[FEATURES].values, d["y"].values
        n = len(d); proba = np.full(n, np.nan); s = a.min_train
        while s < n:
            e = min(s + 63, n)
            mdl = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.03,
                max_depth=3, l2_regularization=1.0, min_samples_leaf=40, random_state=42)
            mdl.fit(X[:s], y[:s]); proba[s:e] = mdl.predict_proba(X[s:e])[:, 1]; s = e
        d["p"] = proba; d = d[~np.isnan(d["p"])]
        acc = ((d["p"] > 0.5).astype(int) == d["y"]).mean()
        up_rate = d["y"].mean()
        naive = max(up_rate, 1 - up_rate)        # 无脑猜多数类的命中
        skill = acc - naive                       # 模型相对基准的真技能(>0 才有意义)
        pos = pd.Series(0.0, index=d.index); pos[d["p"] > 0.52] = 1.0  # 只多
        sr = sharpe(pos * d["next_ret"] - pos.diff().abs().fillna(0) * 0.0001)
        print(f"{H:>5} {acc*100:>7.1f}% {naive*100:>7.1f}% {skill*100:>+6.1f}pp {sr:>11.3f}")


if __name__ == "__main__":
    main()
