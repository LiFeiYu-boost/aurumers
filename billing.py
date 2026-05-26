"""LLM 用量计费(task #62 阶段3)。

按 DashScope 官方单价 × 估算 token 计算成本(分),累计到 daily_usage;免费用户
每日上限 settings.free_daily_cents(默认 300=3元),超出扣钱包余额,都不足则拦截
(HTTP 402)。系统调用(scheduler/check_daily —— 中间件 localhost 豁免不设
request.state.user)不计费。

说明:聊天为流式且优先经 Hermes 网关,拿真实 usage_metadata 复杂,当前按字符
估算 token(对"软性每日额度"足够);后续可替换为 LLM 返回的真实 usage。
"""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import HTTPException

import storage.auth_store as auth_store
from config import settings

EST_CHARS_PER_TOKEN = 2.0

# 每 1k token 的成本(人民币分),(input, output)。按 DashScope 官方价量级。
_PRICING: dict[str, tuple[float, float]] = {
    "qwen-turbo": (0.03, 0.06),
    "qwen-plus": (0.08, 0.20),
    "qwen-max": (0.24, 0.96),
    "deepseek-r1": (0.40, 1.60),
    "deepseek": (0.20, 0.80),  # deepseek-v3 等
}
_DEFAULT_PRICE = (0.20, 0.80)


def _price(model: str) -> tuple[float, float]:
    m = (model or "").lower()
    for key, price in _PRICING.items():
        if key in m:
            return price
    return _DEFAULT_PRICE


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text or "") / EST_CHARS_PER_TOKEN))


def cost_cents(model: str, in_text: str, out_text: str) -> float:
    p_in, p_out = _price(model)
    return estimate_tokens(in_text) / 1000.0 * p_in + estimate_tokens(out_text) / 1000.0 * p_out


def daily_limit_cents(user: dict) -> float:
    v = user.get("daily_free_cents")
    return float(v) if v is not None else float(settings.free_daily_cents)


def assert_can_spend(user: dict) -> None:
    """LLM 调用前预检:今日免费额度未用尽 或 钱包有余额,否则 402。"""
    usage = auth_store.get_today_usage(user["id"], _today())
    if usage["cost_cents"] < daily_limit_cents(user):
        return
    if user.get("balance_cents", 0) > 0:
        return
    limit = daily_limit_cents(user)
    raise HTTPException(
        status_code=402,
        detail=f"今日免费额度(¥{limit / 100:.2f})已用完且钱包余额不足,请充值或明日再试",
    )


def charge(user: dict, model: str, in_text: str, out_text: str) -> None:
    """调用后扣费:先消耗今日免费额度,超出部分扣钱包。"""
    cost = cost_cents(model, in_text, out_text)
    if cost <= 0:
        return
    usage = auth_store.get_today_usage(user["id"], _today())
    free_left = max(0.0, daily_limit_cents(user) - usage["cost_cents"])
    from_wallet = max(0.0, cost - free_left)
    auth_store.add_usage(
        user["id"], _today(), estimate_tokens(in_text), estimate_tokens(out_text), cost
    )
    if from_wallet > 0:
        auth_store.charge_wallet(user["id"], from_wallet)


def charge_for_record(user: dict, record) -> None:
    """分析记录扣费(input_snapshot 作输入文本,raw_output 作输出文本)。"""
    try:
        snap = getattr(record, "input_snapshot", None)
        in_text = json.dumps(snap, ensure_ascii=False) if snap else ""
    except Exception:
        in_text = ""
    charge(
        user,
        getattr(record, "model_name", "") or settings.model_name,
        in_text,
        getattr(record, "raw_output", "") or "",
    )
