from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, time as dtime

from chains.daily_lock import lock_daily_ohlc
from chains.daily_runner import is_today_predicted, run_daily_prediction
from chains.events import hub as event_hub
from chains.runner import run_gold_analysis_once
from chains.verifier import verify_prediction
from config import settings

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - py < 3.9
    ZoneInfo = None  # type: ignore


logger = logging.getLogger(__name__)

_BJ_TZ = ZoneInfo("Asia/Shanghai") if ZoneInfo else None
_DAILY_TIME = dtime(2, 50)
_LOCK_TIME = dtime(3, 5)
_VERIFY_TIME = dtime(3, 10)

_tasks: list[asyncio.Task] = []


def _now_beijing() -> datetime:
    if _BJ_TZ:
        return datetime.now(tz=_BJ_TZ)
    # If zoneinfo unavailable, assume server is already on Asia/Shanghai (deploy.sh enforces this).
    return datetime.now()


def _next_fire(at: dtime, *, now: datetime | None = None) -> datetime:
    current = now or _now_beijing()
    candidate = current.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
    if candidate <= current:
        candidate += timedelta(days=1)
    return candidate


async def _interval_loop() -> None:
    interval = max(int(settings.scheduler_interval_seconds), 60)
    logger.info("Interval scheduler started: interval=%ss", interval)
    try:
        await asyncio.sleep(2)
        while True:
            try:
                record = await asyncio.to_thread(run_gold_analysis_once, "scheduler")
                await event_hub.publish("analysis_record_added", record.model_dump(mode="json"))
                logger.info(
                    "Interval scheduler run finished status=%s latency_ms=%s",
                    record.status.value,
                    record.latency_ms,
                )
            except Exception:
                logger.exception("Interval scheduler run failed; will retry next cycle")
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info("Interval scheduler stopped")
        raise


async def _wall_clock_loop(name: str, fire_time: dtime, action) -> None:
    logger.info("Wall-clock scheduler '%s' started at %s Beijing", name, fire_time)
    try:
        # Cold start catch-up: if we're past fire_time today and action condition isn't satisfied, run once.
        try:
            await action(reason="cold-start")
        except Exception:
            logger.exception("Cold-start run for %s failed", name)
        while True:
            now = _now_beijing()
            fire_at = _next_fire(fire_time, now=now)
            sleep_seconds = max(15, int((fire_at - now).total_seconds()))
            await asyncio.sleep(sleep_seconds)
            try:
                await action(reason="scheduled")
            except Exception:
                logger.exception("Scheduled run for %s failed", name)
            await asyncio.sleep(60)  # avoid double-fire within same minute
    except asyncio.CancelledError:
        logger.info("Wall-clock scheduler '%s' stopped", name)
        raise


async def _daily_action(*, reason: str) -> None:
    today = _now_beijing().strftime("%Y-%m-%d")
    if reason == "cold-start" and is_today_predicted(today):
        logger.info("daily: today already predicted, skip cold-start")
        return
    prediction = await asyncio.to_thread(run_daily_prediction, today)
    if prediction is None:
        # run_daily_prediction 周末/节假日跳过时返回 None(内部已记 skip 日志)
        logger.info("daily(%s): no prediction for %s, skip publish", reason, today)
        return
    await event_hub.publish("daily_prediction_ready", prediction.model_dump(mode="json"))
    logger.info(
        "daily(%s) done date=%s tomorrow=%s confidence=%.2f",
        reason,
        prediction.prediction_date,
        prediction.tomorrow_direction.value,
        prediction.tomorrow_confidence or 0,
    )


async def _lock_action(*, reason: str) -> None:
    """Phase 2 03:05 cron: lock today's SGE + COMEX OHLC into daily_ohlc.

    Idempotent (INSERT OR IGNORE), so cold-start firing is safe and matches
    the pattern of `_daily_action` / `_verify_action`. Errors are logged
    but never raised because the verifier (03:10) is the next downstream
    consumer and shouldn't be blocked by a transient akshare hiccup.
    """
    target = _now_beijing().strftime("%Y-%m-%d")
    result = await asyncio.to_thread(lock_daily_ohlc, target)
    logger.info(
        "lock(%s) date=%s inserted=%s skipped=%s errors=%s",
        reason,
        result.get("date"),
        result.get("inserted"),
        result.get("skipped"),
        result.get("errors"),
    )


async def _verify_action(*, reason: str) -> None:
    """Catch up on any unverified predictions from the last 7 days.

    Idempotent: `verify_prediction` short-circuits if already verified or if
    the next-day anchor is unavailable (weekend, network glitch, etc).
    Running it on a sliding window guarantees Friday's prediction eventually
    gets compared against Monday's close.
    """
    now = _now_beijing()
    for days_back in range(1, 8):
        target = (now - timedelta(days=days_back)).strftime("%Y-%m-%d")
        refreshed = await asyncio.to_thread(verify_prediction, target)
        if refreshed and refreshed.verified_correct is not None and refreshed.verified_at is not None:
            # Newly verified this run — surface to subscribers.
            from datetime import datetime as _dt
            try:
                stamp = _dt.strptime(refreshed.verified_at, "%Y-%m-%d %H:%M:%S")
                fresh = (datetime.now() - stamp).total_seconds() < 300
            except (ValueError, TypeError):
                fresh = False
            if fresh:
                await event_hub.publish("prediction_verified", refreshed.model_dump(mode="json"))
                logger.info(
                    "verify(%s) date=%s correct=%s",
                    reason,
                    target,
                    refreshed.verified_correct,
                )


def start_scheduler() -> None:
    global _tasks
    loop = asyncio.get_event_loop()
    _tasks = [t for t in _tasks if not t.done()]

    if settings.scheduler_enabled and not any(t.get_name() == "interval" for t in _tasks):
        task = loop.create_task(_interval_loop(), name="interval")
        _tasks.append(task)
    elif not settings.scheduler_enabled:
        logger.info("Interval scheduler disabled via SCHEDULER_ENABLED=0")

    if settings.scheduler_daily_enabled:
        if not any(t.get_name() == "daily" for t in _tasks):
            _tasks.append(loop.create_task(
                _wall_clock_loop("daily", _DAILY_TIME, _daily_action),
                name="daily",
            ))
        if not any(t.get_name() == "lock" for t in _tasks):
            _tasks.append(loop.create_task(
                _wall_clock_loop("lock", _LOCK_TIME, _lock_action),
                name="lock",
            ))
        if not any(t.get_name() == "verify" for t in _tasks):
            _tasks.append(loop.create_task(
                _wall_clock_loop("verify", _VERIFY_TIME, _verify_action),
                name="verify",
            ))
    else:
        logger.info("Daily scheduler disabled via SCHEDULER_DAILY_ENABLED=0")


async def stop_scheduler() -> None:
    global _tasks
    for task in _tasks:
        if not task.done():
            task.cancel()
    for task in _tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass
    _tasks = []
