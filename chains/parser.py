import json
from typing import Any

from pydantic import ValidationError

from schemas import AnalysisLLMOutput, Trend


TREND_MAPPING = {
    "上涨": Trend.UP,
    "上升": Trend.UP,
    "偏强": Trend.UP,
    "走强": Trend.UP,
    "看涨": Trend.UP,
    "下跌": Trend.DOWN,
    "下降": Trend.DOWN,
    "偏弱": Trend.DOWN,
    "走弱": Trend.DOWN,
    "看跌": Trend.DOWN,
    "震荡": Trend.FLAT,
    "持平": Trend.FLAT,
    "平": Trend.FLAT,
    "盘整": Trend.FLAT,
    "横盘": Trend.FLAT,
    "未知": Trend.UNKNOWN,
    "up": Trend.UP,
    "down": Trend.DOWN,
    "flat": Trend.FLAT,
    "neutral": Trend.FLAT,
    "unknown": Trend.UNKNOWN,
}


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped


def _extract_json_payload(result: str) -> dict[str, Any]:
    text = _strip_code_fence(result or "")
    if not text:
        return {}

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or start >= end:
        return {}

    return json.loads(text[start : end + 1])


def parse_result(result: str) -> tuple[AnalysisLLMOutput, str | None]:
    try:
        payload = _extract_json_payload(result)
    except json.JSONDecodeError as exc:
        return AnalysisLLMOutput(), f"模型输出不是合法 JSON: {exc}"

    if not payload:
        return AnalysisLLMOutput(), "模型输出为空或缺少 JSON 对象"

    raw_trend = str(payload.get("trend", "")).strip()
    payload["trend"] = (
        TREND_MAPPING.get(raw_trend)
        or TREND_MAPPING.get(raw_trend.lower())
        or Trend.UNKNOWN
    )
    reasons = payload.get("reasons", [])
    if isinstance(reasons, str):
        reasons = [item.strip("- ").strip() for item in reasons.splitlines() if item.strip()]
    payload["reasons"] = [str(item).strip() for item in reasons if str(item).strip()][:3]

    try:
        return AnalysisLLMOutput.model_validate(payload), None
    except ValidationError as exc:
        return AnalysisLLMOutput(), f"结构化字段校验失败: {exc}"
