"""离线训练并打包黄金趋势信号模型(在能拿到长史数据的机器上跑,如 Mac)。

为什么离线:长史美元金价源(yahoo/stooq/FRED金价)在生产 VPS 上都拿不到;
而模型一旦训好就是个小文件。故此处训练 → joblib 打包 → scp 上 VPS,
VPS 只负责每日轻量推断(akshare SGE + FRED 宏观)。

训练数据 = 合成 XAU/CNY(GC=F 美元金价 × 美元兑人民币汇率 ÷ 31.1035),
2004+,已经过 scripts/research_edge.py 的样本外 walk-forward 验证(只多、4/4子区间)。

用法:
    # 走代理拉新数据训练
    HTTPS_PROXY=socks5h://127.0.0.1:7890 .venv/bin/python scripts/train_trend_model.py
    # 用本地已下载的 /tmp CSV 训练(快)
    .venv/bin/python scripts/train_trend_model.py --from-cache
产物:models/trend_ensemble_v1.joblib(含3个模型+特征表+元数据)
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

import sys
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from chains.trend_signal import build_features, train_models, compute_signal, FEATURES  # noqa: E402

OZ2G = 31.1035
OUT = ROOT / "models" / "trend_ensemble_v1.joblib"


def _proxy_opener():
    import urllib.request
    px = os.environ.get("HTTPS_PROXY") or os.environ.get("FRED_PROXY")
    h = urllib.request.ProxyHandler({"https": px, "http": px}) if px else urllib.request.ProxyHandler({})
    return urllib.request.build_opener(h)


def fred(series_id: str, cache: bool) -> pd.Series:
    path = f"/tmp/fred_{series_id}.csv"
    if cache and os.path.exists(path):
        s = pd.read_csv(path, parse_dates=["observation_date"]).set_index("observation_date")
    else:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
        with _proxy_opener().open(url, timeout=40) as r:
            s = pd.read_csv(r, parse_dates=["observation_date"]).set_index("observation_date")
    return pd.to_numeric(s.iloc[:, 0], errors="coerce")


def load_gcf(cache: bool) -> pd.DataFrame:
    if cache and os.path.exists("/tmp/gcf_hist.csv"):
        g = pd.read_csv("/tmp/gcf_hist.csv", index_col=0, parse_dates=[0]).sort_index()
    else:
        import yfinance as yf
        g = yf.download("GC=F", start="2004-01-01", progress=False, auto_adjust=True)
        if isinstance(g.columns, pd.MultiIndex):
            g.columns = g.columns.get_level_values(0)
    g.index.name = "Date"
    return g[["Open", "High", "Low", "Close"]].astype(float).dropna()


def build_xaucny(cache: bool) -> pd.DataFrame:
    g = load_gcf(cache)
    fx = fred("DEXCHUS", cache)
    fx_al = fx.reindex(g.index.union(fx.index)).sort_index().ffill().reindex(g.index)
    xau = g[["Open", "High", "Low", "Close"]].mul(fx_al, axis=0).div(OZ2G).dropna()
    xau.index.name = "Date"
    return xau


def load_macro(cache: bool) -> pd.DataFrame:
    ids = {"dfii10": "DFII10", "dgs10": "DGS10", "dgs2": "DGS2", "dxy": "DTWEXBGS", "vix": "VIXCLS"}
    return pd.DataFrame({k: fred(v, cache) for k, v in ids.items()}).sort_index()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-cache", action="store_true", help="用 /tmp 已下载 CSV,不联网")
    a = ap.parse_args()

    print("[1/3] 取数 + 合成 XAU/CNY ...")
    gold = build_xaucny(a.from_cache)
    macro = load_macro(a.from_cache)
    df = build_features(gold, macro)
    print(f"      金价 {gold.index.min().date()} → {gold.index.max().date()} ({len(gold)} 天)")

    print("[2/3] 训练 H10/20/40 集成 ...")
    models = train_models(df)
    sig = compute_signal(df, models)

    print("[3/3] 打包 ...")
    OUT.parent.mkdir(exist_ok=True)
    bundle = {
        "models": models,
        "features": FEATURES,
        "version": "trend_ensemble_h10_20_40_v1",
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "train_span": [str(gold.index.min().date()), str(gold.index.max().date())],
        "train_rows": int(len(df.dropna(subset=FEATURES))),
        "train_basis": "synthetic XAU/CNY (GC=F x DEXCHUS / 31.1035)",
    }
    joblib.dump(bundle, OUT)
    print(f"      已保存 {OUT} ({OUT.stat().st_size//1024} KB)")
    print("\n当前信号(训练数据末日,自检用):")
    print(json.dumps(sig, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
