from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from chains.baselines import predict_ma5, predict_persistence
from chains.broadcast import broadcast_manager
from chains.calibration import (
    CALIBRATOR_VERSION_GLOBAL,
    CalibrationResult,
    apply_calibration,
    fit_calibrator,
)
from chains.flat_gate import enforce_flat_ceiling, evaluate_flat_gate
from chains.input_builder import news_to_text
from chains.learned_hints_loader import load_recent_hints
from chains.mock_llm import build_daily_prediction_mock
from chains.parser import TREND_MAPPING
from chains.regime import classify_regime
from config import settings
from prompts.daily_prompt import PROMPT_VERSION as DAILY_PROMPT_VERSION, build_daily_prompt
from schemas import (
    AccuracySnapshot,
    BroadcastEvent,
    CloseSourceStatus,
    DailyPrediction,
    RegimeLabel,
    Trend,
)
from storage.record_manager import (
    compute_accuracy,
    get_daily_prediction,
    get_daily_predictions,
    get_latest_records,
    init_storage,
    save_daily_prediction,
)
from tools.gold_close import fetch_dual_close, fetch_dual_close_from_ohlc
from tools.macro import (
    fetch_dxy_proxy,
    fetch_dxy_proxy_historical,
    fetch_us10y_real,
    fetch_us10y_real_historical,
)
from tools.news import get_gold_news
from tools.technicals import atr14, atr14_percentile, dist_from_ma20_z, rsi14


logger = logging.getLogger(__name__)
DAILY_LOCK = threading.Lock()


# Two-stage decision threshold: if the trend mass (prob_up + prob_down) is
# at or above this, we refuse to land argmax on FLAT — the model thinks
# something is moving, so we force a directional pick rather than hedge.
TREND_GATE_TAU = 0.55

CALIBRATION_HISTORY_WINDOW_DAYS = 120


def _env_disabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _decide_today_direction(
    *,
    today: float | None,
    yesterday: float | None,
) -> Trend:
    """Direction from yesterday → today close (must be same market / same unit)."""
    if today is None or yesterday is None:
        return Trend.UNKNOWN
    delta = today - yesterday
    threshold = max(yesterday * 0.0015, 0.5)
    if delta > threshold:
        return Trend.UP
    if delta < -threshold:
        return Trend.DOWN
    return Trend.FLAT


def _pick_same_source_anchor(
    today_sge: float | None,
    today_comex: float | None,
    history: list[DailyPrediction],
    today_iso: str,
) -> tuple[float | None, float | None, str | None]:
    """Return (today, yesterday, source) closes from the SAME market.

    ``source`` is the literal "sge" / "comex" / None so callers (e.g. the MA
    baseline) can read OHLC history from the matching table — mixing markets
    would silently violate unit semantics (CNY/g vs USD/oz).

    Prefers SGE if today has SGE; else COMEX. Falls back across sources only when
    the same source is missing on both sides.
    """
    today_dt: datetime
    try:
        today_dt = datetime.strptime(today_iso, "%Y-%m-%d")
    except ValueError:
        today_dt = datetime.now()

    def candidate(getter):
        for pred in history:
            if pred.prediction_date >= today_iso:
                continue
            try:
                pred_dt = datetime.strptime(pred.prediction_date, "%Y-%m-%d")
            except ValueError:
                continue
            # 14 days handles weekend + China Spring Festival (legal 8 days +
            # neighbouring weekends ≈ 10 days). 7 was too tight — the first
            # trading day after Spring Festival used to degrade today_direction
            # to UNKNOWN and persistence baseline along with it.
            if (today_dt - pred_dt).days > 14:
                break
            value = getter(pred)
            if value is not None:
                return value
        return None

    if today_sge is not None:
        anchor = candidate(lambda p: p.today_close_sge)
        if anchor is not None:
            return today_sge, anchor, "sge"
    if today_comex is not None:
        anchor = candidate(lambda p: p.today_close_comex)
        if anchor is not None:
            return today_comex, anchor, "comex"
    return None, None, None


_PROB_FLOOR = 0.05


def _resolve_prob_triple(
    raw: dict[str, Any],
    *,
    direction: Trend,
    confidence: float | None,
) -> tuple[float | None, float | None, float | None, str]:
    """Return (prob_up, prob_down, prob_flat, prob_source).

    Prefer the model's own (prob_up, prob_down, prob_flat) when present and sane;
    fall back to a heuristic reconstruction from (direction, confidence) so old
    prompts and partial outputs still produce a usable distribution for Brier/log-loss.
    """

    def _coerce(value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if number < 0 or number > 1.5:
            return None
        return number

    triple = (_coerce(raw.get("prob_up")), _coerce(raw.get("prob_down")), _coerce(raw.get("prob_flat")))
    if all(v is not None for v in triple):
        total = sum(triple)
        # Match prompt 铁律 #4: a faithful model output sums in [0.95, 1.05].
        # Outside that range the triple isn't trustworthy — fall through to
        # reconstructed so headline metrics aren't silently propped up by a
        # severely-violating output.
        if total > 0 and 0.95 <= total <= 1.05:
            normalized = tuple(round(v / total, 4) for v in triple)
            return (*normalized, "model")

    if direction is Trend.UNKNOWN:
        return None, None, None, "model"

    base_conf = confidence if confidence is not None else 0.4
    base_conf = max(_PROB_FLOOR, min(1.0 - 2 * _PROB_FLOOR, float(base_conf)))
    other = max(_PROB_FLOOR, (1.0 - base_conf) / 2.0)
    table = {
        Trend.UP: (base_conf, other, other),
        Trend.DOWN: (other, base_conf, other),
        Trend.FLAT: (other, other, base_conf),
    }
    triple_recon = table.get(direction)
    if triple_recon is None:
        return None, None, None, "model"
    total = sum(triple_recon)
    return (
        round(triple_recon[0] / total, 4),
        round(triple_recon[1] / total, 4),
        round(triple_recon[2] / total, 4),
        "reconstructed",
    )


def _apply_post_processing(
    *,
    raw_up: float | None,
    raw_down: float | None,
    raw_flat: float | None,
    calibration: CalibrationResult,
    atr_pct: float | None,
    rsi: float | None,
    dist_ma20_z: float | None,
    calibration_disabled: bool,
    flat_gate_disabled: bool,
    trend_gate_disabled: bool,
) -> dict[str, Any]:
    """Run calibration → flat-gate → trend-gate on the raw model triple.

    Returns a dict carrying the final triple plus audit metadata. When any
    raw probability is missing we short-circuit and surface the gate/calibrator
    as ``no_raw_triple`` — downstream metrics will still treat the row as
    unverified-eligible because the raw columns will simply be NULL.
    """
    if raw_up is None or raw_down is None or raw_flat is None:
        return {
            "prob_up": None,
            "prob_down": None,
            "prob_flat": None,
            "trend_gate_decision": "no_raw_triple",
            "flat_gate_fired": [],
            "calibrator_status": "no_raw_triple",
            "calibrator_scales": None,
            "calibrator_version": None,
        }

    # 1) Calibration
    if calibration_disabled or calibration.status != "ok":
        cal_up, cal_down, cal_flat = raw_up, raw_down, raw_flat
        applied_calibrator_status = (
            "disabled_env_flag" if calibration_disabled else calibration.status
        )
        applied_scales = (
            None if calibration_disabled else calibration.scales
        )
    else:
        cal_up, cal_down, cal_flat = apply_calibration(
            raw_up, raw_down, raw_flat, calibration.scales,
        )
        applied_calibrator_status = "ok"
        applied_scales = calibration.scales

    # 2) Flat gate
    if flat_gate_disabled:
        gate_decision = "disabled_env_flag"
        fired: list[str] = []
    else:
        gate = evaluate_flat_gate(atr_pct, rsi, dist_ma20_z)
        fired = list(gate.fired)
        cal_up, cal_down, cal_flat, was_capped = enforce_flat_ceiling(
            cal_up, cal_down, cal_flat, allow_high_flat=gate.allow_high_flat,
        )
        if was_capped:
            gate_decision = "flat_blocked_by_gate"
        else:
            gate_decision = "flat_allowed" if gate.allow_high_flat else "passthrough"

    # 3) Two-stage trend gate. If trend mass exceeds τ but argmax is still
    #    FLAT, force flat down to the floor (0.05) and rebalance up/down by
    #    their existing ratio. We rely on argmax in the caller for the final
    #    direction call, so we don't pick up/down here — we just ensure the
    #    argmax doesn't land on FLAT against the model's own trend signal.
    if not trend_gate_disabled:
        trend_mass = cal_up + cal_down
        if trend_mass >= TREND_GATE_TAU and cal_flat >= max(cal_up, cal_down):
            new_flat = 0.05
            freed = cal_flat - new_flat
            if trend_mass > 0:
                cal_up += freed * (cal_up / trend_mass)
                cal_down += freed * (cal_down / trend_mass)
            else:
                cal_up += freed / 2
                cal_down += freed / 2
            cal_flat = new_flat
            # Preserve any flat-gate annotation but escalate the decision.
            gate_decision = (
                "trend_forced"
                if gate_decision in ("passthrough", "flat_allowed", "disabled_env_flag")
                else f"{gate_decision}+trend_forced"
            )

    # Final renormalisation so the persisted triple sums to 1.0 exactly.
    total = cal_up + cal_down + cal_flat
    if total > 0:
        cal_up /= total
        cal_down /= total
        cal_flat /= total

    return {
        "prob_up": round(cal_up, 4),
        "prob_down": round(cal_down, 4),
        "prob_flat": round(cal_flat, 4),
        "trend_gate_decision": gate_decision,
        "flat_gate_fired": fired,
        "calibrator_status": applied_calibrator_status,
        "calibrator_scales": applied_scales,
        "calibrator_version": calibration.version,
    }


def _parse_daily_output(raw: dict[str, Any]) -> dict[str, Any]:
    def _trend(value: Any) -> Trend:
        text = str(value or "").strip()
        return TREND_MAPPING.get(text) or TREND_MAPPING.get(text.lower()) or Trend.UNKNOWN

    risk = raw.get("risk_factors") or []
    if isinstance(risk, str):
        risk = [item.strip("- ").strip() for item in risk.splitlines() if item.strip()]
    risk = [str(item).strip() for item in risk if str(item).strip()][:3]

    confidence_raw = raw.get("tomorrow_confidence")
    try:
        confidence_value = float(confidence_raw) if confidence_raw not in (None, "") else None
    except (TypeError, ValueError):
        confidence_value = None
    if confidence_value is not None:
        confidence_value = max(0.0, min(1.0, confidence_value))

    direction = _trend(raw.get("tomorrow_direction"))
    prob_up, prob_down, prob_flat, prob_source = _resolve_prob_triple(
        raw, direction=direction, confidence=confidence_value,
    )

    if prob_up is not None and prob_down is not None and prob_flat is not None:
        triples = {Trend.UP: prob_up, Trend.DOWN: prob_down, Trend.FLAT: prob_flat}
        argmax_dir = max(triples, key=triples.get)
        if direction is Trend.UNKNOWN or prob_source == "model":
            direction = argmax_dir
            confidence_value = triples[argmax_dir]

    return {
        "today_summary": str(raw.get("today_summary") or "").strip(),
        "today_direction": _trend(raw.get("today_direction")),
        "tomorrow_direction": direction,
        "tomorrow_confidence": confidence_value,
        "prob_up": prob_up,
        "prob_down": prob_down,
        "prob_flat": prob_flat,
        "prob_source": prob_source,
        "tomorrow_advice": str(raw.get("tomorrow_advice") or "").strip(),
        "tomorrow_reasoning": str(raw.get("tomorrow_reasoning") or "").strip(),
        "risk_factors": risk,
        "calibration_note": str(raw.get("calibration_note") or "").strip(),
    }


_HIGH_CONF_FOR_REPLAY = 0.7
_REASONING_REPLAY_CHARS = 140


def _format_recent_predictions(predictions: list[DailyPrediction]) -> str:
    """Last 7 days, one row each. High-confidence (≥0.7) misses additionally
    surface their truncated ``reasoning_summary`` so the LLM sees what
    *kind* of argument failed last time.

    Rows whose ``data_origin`` is ``backtest_no_news`` get a ``[回溯]`` prefix
    so the LLM can see they were produced by the no-news historical replay —
    those predictions lack the news context the live path uses, so their
    hit/miss pattern is a weaker signal than live rows. The prompt rule (see
    daily_prompt.py) tells the LLM to treat them as supplementary only.
    """
    if not predictions:
        return "暂无历史预测记录"
    lines: list[str] = []
    for pred in predictions[:7]:
        outcome = "未验证"
        if pred.verified_correct is True:
            outcome = "命中"
        elif pred.verified_correct is False:
            outcome = "未中"
        prefix = "[回溯] " if pred.data_origin == "backtest_no_news" else ""
        line = (
            f"- {prefix}{pred.prediction_date}: 预测 {pred.tomorrow_direction.value}, "
            f"置信 {pred.tomorrow_confidence or 0:.2f}, 结果 {outcome}"
        )
        if (
            pred.verified_correct is False
            and pred.tomorrow_confidence is not None
            and pred.tomorrow_confidence >= _HIGH_CONF_FOR_REPLAY
            and (pred.reasoning_summary or "").strip()
        ):
            snippet = pred.reasoning_summary.strip().replace("\n", " ")
            if len(snippet) > _REASONING_REPLAY_CHARS:
                snippet = snippet[: _REASONING_REPLAY_CHARS - 1].rstrip() + "…"
            line += f"\n    ↪ 当时理由：{snippet}"
        lines.append(line)
    return "\n".join(lines)


def _format_distribution(records_24h_trend_counts: dict[str, int]) -> str:
    items = sorted(records_24h_trend_counts.items(), key=lambda kv: -kv[1])
    return ", ".join(f"{k} {v}" for k, v in items if v > 0) or "近 24h 无 30 分钟分析记录"


_OUNCES_PER_GRAM = 31.1034768  # troy ounce → gram


def _spread_normalized(sge_cny_per_g: float | None, comex_usd_per_oz: float | None) -> str:
    """Express both quotes in CNY/oz (rough USD/CNY=7.2 fallback) for human-readable spread.

    The two markets quote in different (currency, weight) pairs — directly subtracting them is
    nonsense. We compute SGE-equivalent in CNY/oz vs an indicative COMEX in CNY/oz using a
    fixed FX (this is for prompt context only, not pricing).
    """
    if sge_cny_per_g is None or comex_usd_per_oz is None:
        return "N/A（任一数据源缺失）"
    sge_cny_per_oz = sge_cny_per_g * _OUNCES_PER_GRAM
    comex_cny_per_oz = comex_usd_per_oz * 7.2  # indicative USD→CNY
    diff = sge_cny_per_oz - comex_cny_per_oz
    return f"SGE≈{sge_cny_per_oz:.0f} CNY/oz vs COMEX≈{comex_cny_per_oz:.0f} CNY/oz (USD/CNY 取 7.2)，差 {diff:+.0f} CNY/oz"


def _fmt_macro_value(snapshot: dict, *, unit: str) -> str:
    """Format a macro snapshot dict for prompt rendering.

    ``snapshot`` follows the ``tools.macro`` contract — ``missing=True`` /
    ``value=None`` means the source is unavailable. Render as a clear
    "数据源不可达" string so the LLM sees the degradation and the铁律 #5
    fallback path activates.
    """
    if not snapshot or snapshot.get("missing") or snapshot.get("value") is None:
        return "数据源不可达，本次不参考"
    value_date = snapshot.get("value_date") or "?"
    return f"{snapshot['value']:.4g}{unit} (截至 {value_date})"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "数据不足"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def _fmt_indicator(value: float | None, *, unit: str = "") -> str:
    if value is None:
        return "数据不足，本次不参考"
    return f"{value:.4g}{unit}"


def _build_payload(
    *,
    prediction_date: str,
    sge: float | None,
    comex: float | None,
    today_direction: Trend,
    accuracy: AccuracySnapshot,
    recent_predictions: list[DailyPrediction],
    news_text: str,
    distribution_text: str,
    dxy: dict,
    us10y: dict,
    atr14_value: float | None,
    rsi14_value: float | None,
    dist_ma20_z_value: float | None,
    regime: RegimeLabel,
) -> dict[str, Any]:
    calibration_text = ", ".join(
        f"[{b.bucket_low:.1f}-{b.bucket_high:.1f}]={b.hit_rate*100:.0f}% (n={b.sample_size})"
        for b in accuracy.accuracy_by_confidence
    ) or "样本不足"
    return {
        "prediction_date": prediction_date,
        "today_close_sge": (f"{sge:.2f} CNY/g" if sge is not None else "N/A"),
        "today_close_comex": (f"{comex:.2f} USD/oz" if comex is not None else "N/A"),
        "close_spread": _spread_normalized(sge, comex),
        "today_direction_hint": today_direction.value,
        "regime_label": regime.value,
        "accuracy_window_30d": accuracy.overall_accuracy,
        "calibration_buckets": calibration_text,
        "recent_miss_pattern": accuracy.recent_miss_pattern or "暂未识别",
        "recent_predictions": _format_recent_predictions(recent_predictions),
        "recent_distribution": distribution_text,
        "news_text": news_text,
        "dxy_value": _fmt_macro_value(dxy, unit=""),
        "dxy_5d_change": _fmt_pct(dxy.get("change_5d_pct") if dxy else None),
        "us10y_real": _fmt_macro_value(us10y, unit="%"),
        "us10y_5d_change": _fmt_pct(us10y.get("change_5d_pct") if us10y else None),
        "atr14_sge": _fmt_indicator(atr14_value, unit=" CNY/g"),
        "rsi14_sge": _fmt_indicator(rsi14_value),
        "dist_ma20_z_sge": _fmt_indicator(dist_ma20_z_value, unit="σ"),
        "learned_hints": load_recent_hints(),
    }


def _run_chain(payload: dict[str, Any]) -> tuple[dict[str, Any], str, str | None]:
    """Returns (parsed_dict, raw_output_str, error_str|None)."""
    if settings.mock_llm:
        result = build_daily_prediction_mock(payload)
        return result, json.dumps(result, ensure_ascii=False), None

    try:
        from langchain_core.output_parsers import StrOutputParser
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=settings.model_name,
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
            timeout=settings.request_timeout,
            max_retries=settings.max_retries,
            temperature=0.1,
        )
        chain = build_daily_prompt() | llm | StrOutputParser()
        prompt_payload = {
            **payload,
            "today_close_sge": payload["today_close_sge"] if payload["today_close_sge"] is not None else "N/A",
            "today_close_comex": payload["today_close_comex"] if payload["today_close_comex"] is not None else "N/A",
            "accuracy_window_30d": (
                f"{payload['accuracy_window_30d'] * 100:.1f}%"
                if isinstance(payload["accuracy_window_30d"], (int, float)) and payload["accuracy_window_30d"]
                else "样本不足"
            ),
        }
        raw = chain.invoke(prompt_payload)
    except Exception as exc:
        logger.warning("daily LLM chain failed: %s", exc, exc_info=True)
        return build_daily_prediction_mock(payload), "", f"daily-llm-failed: {exc}"

    text = raw.strip()
    if text.startswith("```"):
        text = "\n".join(text.splitlines()[1:])
        if text.endswith("```"):
            text = text[: text.rfind("```")]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return build_daily_prediction_mock(payload), raw, "missing-json-object"
    try:
        result = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        return build_daily_prediction_mock(payload), raw, f"json-decode: {exc}"
    return result, raw, None


def _broadcast_ready(prediction: DailyPrediction) -> None:
    body_lines = [
        f"今日 SGE 收盘：{prediction.today_close_sge if prediction.today_close_sge is not None else '—'}",
        f"今日 COMEX 收盘：{prediction.today_close_comex if prediction.today_close_comex is not None else '—'}",
        f"今日定性：{prediction.today_direction.value}",
        f"明日预测：{prediction.tomorrow_direction.value}（置信 {prediction.tomorrow_confidence or 0:.2f}）",
        f"建议：{prediction.tomorrow_advice}",
    ]
    if prediction.calibration_note:
        body_lines.append("校准：" + prediction.calibration_note)
    event = BroadcastEvent(
        type="daily_prediction_ready",
        title=f"Aurumers · {prediction.prediction_date} 每日金价预测",
        body="\n".join(body_lines),
        payload={
            "prediction_date": prediction.prediction_date,
            "tomorrow_direction": prediction.tomorrow_direction.value,
            "tomorrow_confidence": prediction.tomorrow_confidence,
            "model_name": prediction.model_name,
        },
    )
    broadcast_manager.dispatch(event)


def run_daily_prediction(
    prediction_date: str | None = None,
    *,
    historical_mode: bool = False,
) -> DailyPrediction:
    """Run a daily prediction.

    historical_mode=True: backtest path
        - close pulled from locked daily_ohlc table (no live network call)
        - news + 30-min distribution forced empty (avoid future-leak into past dates)
        - prob_source persisted as 'synthetic_backtest' (excluded from v2 metrics by default)
        - DAILY_LOCK skipped (caller is a sequential script)
        - SSE broadcast skipped (avoid event flood for backfilled rows)
    """
    init_storage()
    today_iso = prediction_date or datetime.now().strftime("%Y-%m-%d")
    if not historical_mode:
        weekday = datetime.strptime(today_iso, "%Y-%m-%d").weekday()
        if weekday >= 5:  # 5=Sat, 6=Sun
            logger.info("daily: weekend skip for %s (weekday=%d)", today_iso, weekday)
            return get_daily_prediction(today_iso)
    lock_held = False
    if not historical_mode:
        if not DAILY_LOCK.acquire(timeout=2):
            cached = get_daily_prediction(today_iso)
            if cached is not None:
                logger.info("daily: lock busy, returning cached prediction for %s", today_iso)
                return cached
            DAILY_LOCK.acquire()
        lock_held = True
    try:
        if historical_mode:
            sge, comex, source = fetch_dual_close_from_ohlc(today_iso)
        else:
            sge, comex, source = fetch_dual_close(today_iso)

        # Same-source anchor pair: SGE-vs-SGE OR COMEX-vs-COMEX, never crossed.
        # In historical_mode we anchor the window at today_iso so the query
        # doesn't return wall-clock-recent rows that are FUTURE relative to
        # the backtest day — that's a silent lookahead and was Round 3 C1.
        # In historical_mode we also include prior backtest rows in the
        # window — without this, a 2023 backtest sees no priors at all
        # because live rows only exist from 2025+; the LLM would face an
        # empty recent_predictions block for the entire 2023-24 backfill.
        history_origins = ("live", "backtest_no_news") if historical_mode else None
        recent_predictions = get_daily_predictions(
            window_days=14,
            before_date=today_iso if historical_mode else None,
            data_origins=history_origins,
        )
        today_close_for_dir, yesterday_close_for_dir, anchor_source = _pick_same_source_anchor(
            sge, comex, recent_predictions, today_iso,
        )
        today_direction = _decide_today_direction(
            today=today_close_for_dir,
            yesterday=yesterday_close_for_dir,
        )

        # If both sources are unavailable, refuse to fabricate a prediction.
        # Persist a placeholder row tagged UNKNOWN with a clear error, no LLM call.
        if sge is None and comex is None:
            placeholder = DailyPrediction(
                id=str(uuid4()),
                predicted_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                prediction_date=today_iso,
                today_close_sge=None,
                today_close_comex=None,
                today_close_source=source,
                today_direction=Trend.UNKNOWN,
                tomorrow_direction=Trend.UNKNOWN,
                tomorrow_confidence=None,
                prob_source=("synthetic_backtest" if historical_mode else "model"),
                tomorrow_advice="数据源全部失效，无法预测",
                reasoning_summary="SGE 与 COMEX 收盘数据均未获取到，未调用模型。",
                risk_factors=[],
                calibration_note="数据缺失，已跳过本次预测。",
                prompt_version=DAILY_PROMPT_VERSION,
                model_name="(skipped)",
                accuracy_window_30d=None,
                raw_output="",
                error="dual_close_unavailable",
                data_origin=("backtest_no_news" if historical_mode else "live"),
            )
            save_daily_prediction(placeholder)
            logger.warning("daily prediction skipped: dual close unavailable for %s", today_iso)
            return placeholder

        # historical_mode anchors the window at today_iso so the accuracy
        # signal injected into prompt + persisted as accuracy_window_30d
        # never includes verified outcomes from rows whose prediction_date
        # is in the future relative to the backtest day.
        accuracy = compute_accuracy(
            "30d",
            before_date=today_iso if historical_mode else None,
            data_origins=history_origins,
        )
        if historical_mode:
            # Lookahead防护：禁止把今日新闻 / 30 分钟分析喂给历史日期
            news_text = "（历史回测，不参考新闻）"
            distribution_text = "（历史回测，无 30 分钟分析）"
        else:
            news = get_gold_news(limit=5)
            recent_records = get_latest_records(48)
            trend_counts: dict[str, int] = {}
            for record in recent_records:
                trend_counts[record.trend.value] = trend_counts.get(record.trend.value, 0) + 1
            news_text = news_to_text(news)
            distribution_text = _format_distribution(trend_counts)

        # Phase 2 features. Macro routes split by mode (live cache vs historical
        # series); technical indicators always read from the locked daily_ohlc
        # table so they're naturally lookahead-safe in either mode.
        if historical_mode:
            dxy_snapshot = fetch_dxy_proxy_historical(today_iso)
            us10y_snapshot = fetch_us10y_real_historical(today_iso)
        else:
            dxy_snapshot = fetch_dxy_proxy()
            us10y_snapshot = fetch_us10y_real()
        atr14_value = atr14(today_iso, source="sge")
        atr14_pct_value = atr14_percentile(today_iso, source="sge", window=60)
        rsi14_value = rsi14(today_iso, source="sge")
        dist_ma20_z_value = dist_from_ma20_z(today_iso, source="sge")
        regime_value = classify_regime(today_iso)

        payload = _build_payload(
            prediction_date=today_iso,
            sge=sge,
            comex=comex,
            today_direction=today_direction,
            accuracy=accuracy,
            recent_predictions=recent_predictions,
            news_text=news_text,
            distribution_text=distribution_text,
            dxy=dxy_snapshot,
            us10y=us10y_snapshot,
            atr14_value=atr14_value,
            rsi14_value=rsi14_value,
            dist_ma20_z_value=dist_ma20_z_value,
            regime=regime_value,
        )

        parsed, raw_output, error = _run_chain(payload)
        normalized = _parse_daily_output(parsed)

        # Post-processing pipeline: calibrate → flat-gate → trend-gate.
        # The raw triple persisted into prob_*_raw is what the LLM (or
        # reconstruction path) actually produced; prob_* below carries the
        # adjusted values used for the headline direction call and Brier/ECE.
        raw_up = normalized["prob_up"]
        raw_down = normalized["prob_down"]
        raw_flat = normalized["prob_flat"]

        cal_disabled = _env_disabled("AURUMERS_DISABLE_CALIBRATION")
        gate_disabled = _env_disabled("AURUMERS_DISABLE_FLAT_GATE")
        trend_disabled = _env_disabled("AURUMERS_DISABLE_TREND_GATE")

        if cal_disabled:
            calibration = CalibrationResult(
                scales={"up": 1.0, "down": 1.0, "flat": 1.0},
                status="disabled_env_flag",
                version=CALIBRATOR_VERSION_GLOBAL,
                sample_size=0,
                predicted_rate={"up": 0.0, "down": 0.0, "flat": 0.0},
                actual_rate={"up": 0.0, "down": 0.0, "flat": 0.0},
            )
        else:
            # historical_mode must NOT see verified outcomes from rows whose
            # prediction_date is in the future relative to today_iso —
            # otherwise the calibrator is fit on tomorrow's data, the very
            # definition of lookahead.
            calibration_history = get_daily_predictions(
                window_days=CALIBRATION_HISTORY_WINDOW_DAYS,
                before_date=today_iso if historical_mode else None,
                data_origins=history_origins,
            )
            calibration = fit_calibrator(calibration_history, regime=regime_value)

        post = _apply_post_processing(
            raw_up=raw_up,
            raw_down=raw_down,
            raw_flat=raw_flat,
            calibration=calibration,
            atr_pct=atr14_pct_value,
            rsi=rsi14_value,
            dist_ma20_z=dist_ma20_z_value,
            calibration_disabled=cal_disabled,
            flat_gate_disabled=gate_disabled,
            trend_gate_disabled=trend_disabled,
        )

        # Final argmax + confidence come from post-processed probs (when
        # available). If post-processing was skipped (no_raw_triple), fall
        # back to whatever _parse_daily_output produced.
        final_up = post["prob_up"]
        final_down = post["prob_down"]
        final_flat = post["prob_flat"]
        if final_up is not None and final_down is not None and final_flat is not None:
            triple_map = {Trend.UP: final_up, Trend.DOWN: final_down, Trend.FLAT: final_flat}
            argmax_direction = max(triple_map, key=triple_map.get)
            final_direction = argmax_direction
            final_confidence: float | None = triple_map[argmax_direction]
        else:
            final_direction = normalized["tomorrow_direction"]
            final_confidence = normalized["tomorrow_confidence"]
        if final_confidence is not None:
            try:
                final_confidence = max(0.0, min(1.0, float(final_confidence)))
            except (TypeError, ValueError):
                final_confidence = None

        # prob_source priority:
        #   historical_mode → "synthetic_backtest" (always)
        #   otherwise LLM error path → "mock" (don't pretend the model spoke)
        #   otherwise normalized output ("model" / "reconstructed")
        if historical_mode:
            prob_source_final = "synthetic_backtest"
        elif error:
            prob_source_final = "mock"
        else:
            prob_source_final = normalized["prob_source"]

        # Falsifiability baselines — record at predict time, verified alongside
        # the model. Anchor close uses the same-source pair already chosen above
        # for today_direction so MA(5) is in the same units; if no anchor was
        # picked (both feeds down), the MA baseline silently degrades to UNKNOWN.
        baseline_persistence = predict_persistence(today_direction)
        baseline_ma = (
            predict_ma5(today_close_for_dir, today_iso, source=anchor_source)
            if anchor_source is not None
            else Trend.UNKNOWN
        )
        prediction = DailyPrediction(
            id=str(uuid4()),
            predicted_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            prediction_date=today_iso,
            today_close_sge=sge,
            today_close_comex=comex,
            today_close_source=source,
            today_direction=normalized["today_direction"] if normalized["today_direction"] is not Trend.UNKNOWN else today_direction,
            tomorrow_direction=final_direction,
            tomorrow_confidence=final_confidence,
            prob_up=final_up,
            prob_down=final_down,
            prob_flat=final_flat,
            prob_source=prob_source_final,
            prob_up_raw=raw_up,
            prob_down_raw=raw_down,
            prob_flat_raw=raw_flat,
            trend_gate_decision=post["trend_gate_decision"],
            flat_gate_fired=post["flat_gate_fired"],
            calibrator_version=post["calibrator_version"],
            calibrator_status=post["calibrator_status"],
            calibrator_scales=post["calibrator_scales"],
            regime_label=regime_value if regime_value != RegimeLabel.UNKNOWN else None,
            dxy_value=dxy_snapshot.get("value") if dxy_snapshot else None,
            dxy_5d_change_pct=dxy_snapshot.get("change_5d_pct") if dxy_snapshot else None,
            us10y_real_yield=us10y_snapshot.get("value") if us10y_snapshot else None,
            us10y_5d_change_pct=us10y_snapshot.get("change_5d_pct") if us10y_snapshot else None,
            atr14=atr14_value,
            rsi14=rsi14_value,
            dist_ma20_z=dist_ma20_z_value,
            baseline_persistence_direction=(
                baseline_persistence if baseline_persistence is not Trend.UNKNOWN else None
            ),
            baseline_ma_direction=(
                baseline_ma if baseline_ma is not Trend.UNKNOWN else None
            ),
            # Pin so the verifier compares actual_direction in the SAME market
            # the baselines were computed against. Set even when baselines are
            # UNKNOWN (anchor exists, baselines just degraded for other reasons).
            baseline_anchor_source=anchor_source,
            tomorrow_advice=normalized["tomorrow_advice"] or "暂无建议",
            reasoning_summary=normalized["tomorrow_reasoning"] or normalized["today_summary"],
            risk_factors=normalized["risk_factors"],
            calibration_note=normalized["calibration_note"],
            prompt_version=DAILY_PROMPT_VERSION,
            model_name=("mock" if (settings.mock_llm or error) else settings.model_name),
            accuracy_window_30d=accuracy.overall_accuracy,
            raw_output=raw_output,
            error=error,
            # Provenance tag — historical_mode skips news + DAILY_LOCK + broadcast
            # and pulls close/macro from locked snapshots. Tagging these
            # 'backtest_no_news' means aggregation queries can exclude them by
            # default so headline metrics keep reflecting real production-model
            # performance, not the structurally weaker no-news replay.
            data_origin=("backtest_no_news" if historical_mode else "live"),
        )
        save_daily_prediction(prediction)
        if not historical_mode:
            try:
                _broadcast_ready(prediction)
            except Exception:
                logger.exception("broadcast dispatch failed")
        logger.info(
            "daily prediction stored date=%s source=%s tomorrow=%s confidence=%.2f",
            prediction.prediction_date,
            source.value,
            prediction.tomorrow_direction.value,
            prediction.tomorrow_confidence or 0,
        )
        return prediction
    finally:
        if lock_held:
            try:
                DAILY_LOCK.release()
            except RuntimeError:
                pass


def is_today_predicted(prediction_date: str | None = None) -> bool:
    today_iso = prediction_date or datetime.now().strftime("%Y-%m-%d")
    return any(p.prediction_date == today_iso for p in get_daily_predictions(window_days=2))
