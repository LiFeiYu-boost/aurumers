import hashlib
from typing import Any

from schemas import AnalysisInput


def _seed_from_input(analysis_input: AnalysisInput) -> int:
    digest = hashlib.md5(
        f"{analysis_input.price_raw}|{analysis_input.generated_at.isoformat()}".encode("utf-8")
    ).hexdigest()
    return int(digest[:8], 16)


def _pick_trend(price_value: float | None, seed: int) -> str:
    if price_value is None:
        return "未知"
    bucket = (seed % 100) / 100.0
    if bucket < 0.42:
        return "上涨"
    if bucket < 0.78:
        return "震荡"
    return "下跌"


def build_mock_output(analysis_input: AnalysisInput) -> dict[str, Any]:
    seed = _seed_from_input(analysis_input)
    trend = _pick_trend(analysis_input.price_value, seed)
    price_text = (
        f"{analysis_input.price_value:.2f}"
        if analysis_input.price_value is not None
        else analysis_input.price_raw
    )
    titles = [item.title for item in analysis_input.news[:3]] or ["暂无外部新闻"]
    summary = (
        f"当前金价 {price_text}，结合 {len(analysis_input.news)} 条相关新闻，"
        f"短线判断偏向{trend}。"
    )
    reasons: list[str] = []
    if analysis_input.news:
        reasons.append(f"新闻焦点：{titles[0][:24]}")
    if len(analysis_input.news) > 1:
        reasons.append(f"次级关注：{titles[1][:24]}")
    if analysis_input.price_value is not None:
        reasons.append(f"价格中枢约 {analysis_input.price_value:.2f}，未出现极端跳变")
    if not reasons:
        reasons.append("数据样本不足，仅供演示")
    advice_map = {
        "上涨": "可关注回调机会，控制单笔仓位，避免追高。",
        "下跌": "建议观望或轻仓试探，等趋势企稳再行动。",
        "震荡": "区间操作为主，严格止损，不押单边方向。",
        "未知": "数据不足，建议等待更明确信号后再决策。",
    }
    confidence = 0.42 if analysis_input.news else 0.28
    return {
        "summary": summary,
        "trend": trend,
        "reasons": reasons[:3],
        "advice": advice_map[trend],
        "confidence": confidence,
    }


def _coerce_close(value: Any) -> float | None:
    """Accept either a float, a None, or a formatted string like '1035.63 CNY/g'."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text.upper() == "N/A":
        return None
    head = text.split()[0]
    try:
        return float(head)
    except ValueError:
        return None


def _mock_prob_triple(direction: str, confidence: float) -> tuple[float, float, float]:
    """Distribute (1 - confidence) across the two non-chosen directions with a 0.05 floor.

    Mirrors the production reconstruction heuristic so mock + reconstructed paths
    look identical in shape to consumers (Brier/log-loss test code, UI).
    """
    floor = 0.05
    base = max(floor, min(1.0 - 2 * floor, float(confidence)))
    other = max(floor, (1.0 - base) / 2.0)
    table = {
        "上涨": (base, other, other),
        "下跌": (other, base, other),
        "平": (other, other, base),
    }
    triple = table.get(direction, (other, other, base))
    total = sum(triple)
    return tuple(round(v / total, 4) for v in triple)


def build_daily_prediction_mock(payload: dict[str, Any]) -> dict[str, Any]:
    """Deterministic daily-prediction stand-in for MOCK_LLM mode."""
    sge = _coerce_close(payload.get("today_close_sge"))
    comex = _coerce_close(payload.get("today_close_comex"))
    prediction_date = str(payload.get("prediction_date", ""))
    accuracy = payload.get("accuracy_window_30d")
    miss_pattern = payload.get("recent_miss_pattern", "")

    digest = hashlib.md5(f"{prediction_date}|{sge}|{comex}".encode("utf-8")).hexdigest()
    seed = int(digest[:8], 16)
    bucket = (seed % 100) / 100.0
    if sge is None and comex is None:
        tomorrow_direction = "平"
        confidence = 0.25
    elif bucket < 0.42:
        tomorrow_direction = "上涨"
        confidence = 0.55
    elif bucket < 0.74:
        tomorrow_direction = "平"
        confidence = 0.45
    else:
        tomorrow_direction = "下跌"
        confidence = 0.5

    prob_up, prob_down, prob_flat = _mock_prob_triple(tomorrow_direction, confidence)

    today_direction = payload.get("today_direction_hint") or "平"
    primary_close = sge if sge is not None else comex
    close_text = f"{primary_close:.2f}" if primary_close is not None else "—"

    accuracy_text = (
        f"过去 30 天准确率 {accuracy * 100:.0f}%"
        if isinstance(accuracy, (int, float)) and accuracy
        else "样本不足"
    )

    return {
        "today_summary": f"今日金价 {close_text}，结合双源数据，定性{today_direction}。",
        "today_direction": today_direction,
        "tomorrow_direction": tomorrow_direction,
        "tomorrow_confidence": confidence,
        "prob_up": prob_up,
        "prob_down": prob_down,
        "prob_flat": prob_flat,
        "tomorrow_advice": {
            "上涨": "观察突破有效性，控制单笔仓位，避免追高。",
            "下跌": "考虑减仓或观望，保留弹药等待企稳信号。",
            "平": "区间操作为主，严格止损，不押单边方向。",
        }[tomorrow_direction],
        "tomorrow_reasoning": "（Mock）综合双源收盘、新闻情绪与历史命中率给出保守判断。",
        "risk_factors": [
            "Mock 模式占位，补真实模型后启用真实推理",
            "数据源任一失效时方向自动回落到 平",
            (miss_pattern or "样本不足，置信度天然偏低"),
        ][:3],
        "calibration_note": (
            f"{accuracy_text}；{miss_pattern or '近期暂未识别明显失误模式'}。"
            "（Mock 模式占位，补真实模型后启用真实推理）"
        ),
    }
