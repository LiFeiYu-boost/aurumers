"""趋势信号服务 + 持仓建议逻辑(供 app.py 调用)。

- 加载离线打包的集成模型(models/trend_ensemble_v1.joblib),不在请求里重训。
- 按"当日"缓存信号:同一天内复用,跨天自动重算。
- 数据源:默认 akshare SGE + FRED 宏观(生产);设环境变量可指向本地 CSV(调试):
    SIGNAL_GOLD_CSV=/tmp/sge_hist.csv  SIGNAL_MACRO_DIR=/tmp
- 持仓建议:由信号驱动(方向倾向 + 可展开的具体调整区间);成本价只用于显示浮盈亏。
  合规:输出一律框定为"趋势信号参考",非投资建议。
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from chains import trend_signal

BASE_DIR = Path(__file__).resolve().parent
BUNDLE_PATH = os.environ.get("SIGNAL_BUNDLE", str(BASE_DIR / "models" / "trend_ensemble_v1.joblib"))

DISCLAIMER = (
    "本结果由趋势模型对历史数据归纳得出,仅为研究参考,不构成任何投资建议;"
    "黄金价格受多种因素影响、模型在震荡市可能失效,据此操作风险自负。"
)

_bundle = None
_cache: dict = {}


def _get_bundle():
    global _bundle
    if _bundle is None:
        _bundle = trend_signal.load_bundle(BUNDLE_PATH)
    return _bundle


def _compute() -> tuple[dict, list]:
    """一次特征计算,同时产出信号 + 多周期展望。"""
    b = _get_bundle()
    g = trend_signal.load_gold_sge(os.environ.get("SIGNAL_GOLD_CSV"))
    m = trend_signal.load_macro(os.environ.get("SIGNAL_MACRO_DIR"))
    df = trend_signal.build_features(g, m)
    sig = trend_signal.compute_signal(df, b["models"], cot_net_z=_load_cot_z())
    sig["trained_at"] = b.get("trained_at")
    sig["train_span"] = b.get("train_span")
    outlook = trend_signal.compute_outlook(df, b["models"], b.get("outlook_meta"))
    return sig, outlook


def _cached() -> tuple[dict, list]:
    today = date.today().isoformat()
    if _cache.get("day") == today and _cache.get("sig") is not None:
        return _cache["sig"], _cache["outlook"]
    sig, outlook = _compute()
    _cache.update(day=today, sig=sig, outlook=outlook)
    return sig, outlook


def get_signal(force: bool = False) -> dict:
    """返回当日信号(当天缓存)。"""
    if force:
        _cache.clear()
    return _cached()[0]


def get_outlook() -> list:
    """返回当日多周期方向展望(1/2/3 个月,当天缓存)。"""
    return _cached()[1]


def _load_cot_z() -> float | None:
    """COT 投机净持仓 z 分数(拥挤度);取不到则 None。"""
    path = os.environ.get("SIGNAL_COT_CSV", "/tmp/cot_gold.csv")
    if not os.path.exists(path):
        return None
    try:
        import pandas as pd
        c = pd.read_csv(path, parse_dates=["date"]).sort_values("date")
        n = c["net_spec_pct"]
        mu = n.rolling(104, min_periods=52).mean().iloc[-1]
        sd = n.rolling(104, min_periods=52).std().iloc[-1]
        return round(float((n.iloc[-1] - mu) / sd), 2)
    except Exception:
        return None


def build_advice(grams: float, cost_per_g: float | None = None) -> dict:
    """给定持仓克数(+可选成本价)→ 信号驱动的持仓建议。"""
    sig = get_signal()
    price = sig["price_cny_per_g"]
    current_value = round(grams * price, 2)
    target = sig["target_exposure"]
    direction, conf, crowding = sig["direction"], sig["confidence"], sig.get("crowding")

    pnl = None
    if cost_per_g:
        cost_basis = round(grams * cost_per_g, 2)
        pnl = {
            "cost_basis": cost_basis,
            "pnl": round(current_value - cost_basis, 2),
            "pnl_pct": round((price / cost_per_g - 1) * 100, 2),
        }

    detail = {"type": "hold", "sell_grams_range": None, "sell_value_range": None}
    if direction == "看多":
        action = "持有 / 顺势"
        headline = ("趋势看多,建议继续持有。若计划加仓,当前为顺势窗口"
                    "(但勿超出你为黄金设定的配置上限)。") if conf == "高" else \
                   "趋势偏多但力度一般,建议以持有为主、不急于动作。"
    elif direction == "中性":
        action = "持有观望"
        headline = "趋势不明朗,建议持有不动、观望,等信号转明确再决定。"
    else:  # 看空
        reduce_frac = 1 - target
        lo = max(0.0, reduce_frac - 0.10)
        hi = min(1.0, reduce_frac + 0.10)
        detail = {
            "type": "reduce",
            "sell_grams_range": [round(grams * lo, 1), round(grams * hi, 1)],
            "sell_value_range": [round(grams * lo * price, 0), round(grams * hi * price, 0)],
        }
        action = "减仓 / 降低敞口"
        headline = ("趋势转弱,建议降低黄金敞口、锁定部分仓位。"
                    if conf == "高" else
                    "出现趋势走弱迹象,可考虑适度减仓。")

    if crowding == "偏高":
        risk_note = "⚠ 投机持仓偏拥挤,短期回调风险升高,加仓尤其谨慎。"
    elif crowding == "偏低":
        risk_note = "投机持仓不拥挤,当前趋势的资金面支撑相对健康。"
    else:
        risk_note = "趋势跟随信号在横盘震荡行情中可能反复,留意自身风险承受。"

    return {
        "holdings": {
            "grams": grams,
            "price_per_g": price,
            "current_value": current_value,
            "pnl": pnl,
        },
        "signal": {
            "asof": sig["asof"],
            "direction": direction,
            "confidence": conf,
            "prob_up": sig["prob_up"],
            "horizon_agreement": sig["horizon_agreement"],
            "target_exposure": target,
            "crowding": crowding,
            "horizon": "未来约 1 个月(10/20/40 交易日趋势集成)",
        },
        "advice": {"action": action, "headline": headline, "detail": detail, "risk_note": risk_note},
        "disclaimer": DISCLAIMER,
    }
