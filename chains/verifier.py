from __future__ import annotations

import logging
from datetime import datetime, timedelta

from chains.broadcast import broadcast_manager
from schemas import BroadcastEvent, CloseSourceStatus, DailyPrediction, Trend
from storage.record_manager import (
    get_daily_prediction,
    get_records_for_date,
    update_daily_outcome,
    update_record_outcome,
)
from tools.gold_close import fetch_dual_close, fetch_dual_close_from_ohlc
from tools.market_time import is_post_close_window

try:
    from zoneinfo import ZoneInfo

    _BJ_TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # pragma: no cover - zoneinfo unavailable; deploy enforces Asia/Shanghai
    _BJ_TZ = None


logger = logging.getLogger(__name__)


def _today_beijing() -> str:
    """今天的北京日期 (YYYY-MM-DD)，用于判定 next_day 是否就是'今天'。"""
    if _BJ_TZ is not None:
        return datetime.now(tz=_BJ_TZ).strftime("%Y-%m-%d")
    return datetime.now().strftime("%Y-%m-%d")


def _direction_from_close(anchor_close: float, actual_close: float) -> Trend:
    delta = actual_close - anchor_close
    threshold = max(anchor_close * 0.0015, 0.5)
    if delta > threshold:
        return Trend.UP
    if delta < -threshold:
        return Trend.DOWN
    return Trend.FLAT


def verify_prediction(
    prediction_date: str,
    *,
    historical_mode: bool = False,
    force: bool = False,
) -> DailyPrediction | None:
    """Verify the daily prediction made for `prediction_date` using the next-day close.

    Same-source comparison is mandatory: SGE (CNY/g) and COMEX (USD/oz) live in
    different units — comparing across markets would silently corrupt direction.

    historical_mode=True: pull next-day close from the locked daily_ohlc table
    instead of the live feed. Used by the backtest pipeline. Note the live feed
    ignores its date argument (it only ever returns the quote "right now"), so
    verification of any past next_day auto-routes to daily_ohlc even without this
    flag — only a next_day that equals today uses the live feed.

    force=True: re-run even if the row was already verified. Use when the
    original verification ran against a stale / wrong actual close (data
    source flicker, late OHLC backfill correcting an earlier mistake). Gated
    by admin auth at the endpoint level — exposing it unauthenticated would
    let anyone rewrite history.
    """
    prediction = get_daily_prediction(prediction_date)
    if prediction is None:
        logger.info("verify: no prediction for %s", prediction_date)
        return None
    if prediction.verified_correct is not None and not force:
        return prediction

    next_dt = datetime.strptime(prediction_date, "%Y-%m-%d") + timedelta(days=1)
    # Walk past weekends so Friday's prediction can be checked against Monday's close.
    while next_dt.weekday() >= 5:
        next_dt += timedelta(days=1)
    next_day = next_dt.strftime("%Y-%m-%d")

    # The live feed (fetch_dual_close) ignores its date argument — it always
    # returns the quote "right now". That is a valid proxy for next_day's close
    # ONLY when next_day is today (the normal 03:10 verify of yesterday's
    # prediction). For any older next_day — a catch-up after a missed / weekend /
    # network-glitch verification — the live quote is the WRONG trading day and
    # would compare the anchor against today's price, fabricating a direction.
    # Route those to the locked daily_ohlc, which is pinned to next_day. Even when
    # next_day IS today, the live quote only equals today's close inside the
    # post-close window (weekday 02:30–09:00 Beijing) — a cold-start catch-up
    # firing intraday would otherwise persist a mid-session price as the close,
    # permanently (the verified_correct short-circuit above never re-runs).
    if historical_mode or next_day != _today_beijing() or not is_post_close_window():
        sge, comex, status = fetch_dual_close_from_ohlc(next_day)
    else:
        sge, comex, status = fetch_dual_close(next_day)

    # Source pinning: if predict-time recorded which market the baselines /
    # today_direction were computed against (baseline_anchor_source), prefer
    # that same market for verify so actual_direction is in identical units.
    # Otherwise fall back to SGE-first heuristic for legacy rows.
    anchor_close: float | None = None
    actual_close: float | None = None
    pinned_source = prediction.baseline_anchor_source
    if pinned_source == "sge" and prediction.today_close_sge is not None and sge is not None:
        anchor_close = prediction.today_close_sge
        actual_close = sge
    elif pinned_source == "comex" and prediction.today_close_comex is not None and comex is not None:
        anchor_close = prediction.today_close_comex
        actual_close = comex
    elif pinned_source is None:
        # Legacy / pre-pin rows: fall back to SGE-first.
        if prediction.today_close_sge is not None and sge is not None:
            anchor_close = prediction.today_close_sge
            actual_close = sge
        elif prediction.today_close_comex is not None and comex is not None:
            anchor_close = prediction.today_close_comex
            actual_close = comex

    if anchor_close is None or actual_close is None:
        logger.info(
            "verify: same-source pair missing for %s (pinned=%s, anchor sge=%s comex=%s, actual sge=%s comex=%s)",
            prediction_date,
            pinned_source,
            prediction.today_close_sge,
            prediction.today_close_comex,
            sge,
            comex,
        )
        return prediction

    # If the "next-day" quote is byte-identical to the anchor, the markets
    # haven't moved (or haven't reopened) — refuse to verify by default.
    # force=True bypasses this so an admin can re-verify after the upstream
    # feed has been corrected (e.g. OHLC backfill changed yesterday's anchor,
    # and the original verification now has a stale anchor_close that
    # coincidentally matches the new actual_close at byte level).
    if abs(actual_close - anchor_close) < 1e-6 and not force:
        logger.info(
            "verify: next-day quote unchanged from anchor for %s; markets likely closed",
            prediction_date,
        )
        return prediction

    actual_direction = _direction_from_close(anchor_close, actual_close)
    correct = prediction.tomorrow_direction == actual_direction

    # Baselines were recorded at predict time; verify them against the same
    # actual_direction so the comparison is apples-to-apples. None means the
    # baseline couldn't be computed (e.g., insufficient OHLC history).
    persistence_correct: bool | None = None
    if prediction.baseline_persistence_direction is not None:
        persistence_correct = (
            prediction.baseline_persistence_direction == actual_direction
        )
    ma_correct: bool | None = None
    if prediction.baseline_ma_direction is not None:
        ma_correct = prediction.baseline_ma_direction == actual_direction

    update_daily_outcome(
        prediction_date,
        actual_close,
        actual_direction,
        correct,
        baseline_persistence_correct=persistence_correct,
        baseline_ma_correct=ma_correct,
    )

    # Phase 1: per-row metrics — best-effort, never blocks verification main flow
    try:
        from chains.metrics import brier_multiclass, log_loss as compute_log_loss
        from chains.regime import classify_regime
        from storage.record_manager import update_daily_metrics

        refreshed_pred = get_daily_prediction(prediction_date)
        if refreshed_pred is not None:
            brier = brier_multiclass(
                refreshed_pred.prob_up,
                refreshed_pred.prob_down,
                refreshed_pred.prob_flat,
                actual_direction,
            )
            ll = compute_log_loss(
                refreshed_pred.prob_up,
                refreshed_pred.prob_down,
                refreshed_pred.prob_flat,
                actual_direction,
            )
            regime = classify_regime(prediction_date)
            update_daily_metrics(prediction_date, brier=brier, log_loss=ll, regime=regime)
    except Exception:
        logger.exception("phase1 per-row metrics persist failed")

    # Mirror onto analysis_records that targeted the same date
    for record in get_records_for_date(prediction_date):
        update_record_outcome(record.id, actual_close, actual_direction, record.trend == actual_direction)

    refreshed = get_daily_prediction(prediction_date)
    try:
        broadcast_manager.dispatch(BroadcastEvent(
            type="prediction_verified",
            title=f"Aurumers · {prediction_date} 预测已校验",
            body=(
                f"预测方向 {prediction.tomorrow_direction.value}，"
                f"实际方向 {actual_direction.value}，"
                f"结果：{'命中' if correct else '未中'}（实际收盘 {actual_close}）"
            ),
            payload={
                "prediction_date": prediction_date,
                "predicted": prediction.tomorrow_direction.value,
                "actual": actual_direction.value,
                "correct": correct,
                "actual_close": actual_close,
            },
        ))
    except Exception:
        logger.exception("verify broadcast failed")
    return refreshed
