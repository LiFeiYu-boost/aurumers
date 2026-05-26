"""Sequential historical backtest — generate synthetic_backtest predictions over a date range.

Why sequential
--------------
Each day's prompt payload references `accuracy_window_30d` and `recent_predictions`,
both of which depend on the *prior* synth-backtest rows already in DB. Running in
chronological order makes each day's context realistic. Running in parallel would
either feed empty context (degrading prompt) or leak future synth predictions
(lookahead). We pay the wall-clock cost (~5-10 min per 365 days) for correctness.

Concurrency
-----------
For real LLM mode we still need DashScope API throughput. Since each day strictly
depends on prior days, we cannot parallelize across dates. The --concurrency flag
exists only for future use (e.g., parallel verifier on already-existing rows) and
currently has no effect on the daily_runner loop.

Usage
-----
    python scripts/backtest_historical.py --dry-run                 # plan only
    python scripts/backtest_historical.py --apply --start 2025-01-01 --end 2026-05-08
    python scripts/backtest_historical.py --apply --skip-existing   # default: skip dates that already have a row
    python scripts/backtest_historical.py --apply --start 2026-04-01 --end 2026-04-10  # narrow probe
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from storage.record_manager import DB_PATH, init_storage  # noqa: E402


logger = logging.getLogger("backtest")


def _candidate_dates(start: str, end: str) -> list[str]:
    """All dates in daily_ohlc within [start, end] that have at least one source close."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT DISTINCT date FROM daily_ohlc
             WHERE date >= ? AND date <= ? AND close IS NOT NULL
             ORDER BY date ASC
            """,
            (start, end),
        ).fetchall()
    return [row["date"] for row in rows]


def _existing_rows(dates: list[str]) -> set[str]:
    if not dates:
        return set()
    placeholders = ",".join("?" for _ in dates)
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT prediction_date FROM daily_predictions WHERE prediction_date IN ({placeholders})",
            dates,
        ).fetchall()
    return {row["prediction_date"] for row in rows}


def _run_one(date: str) -> tuple[bool, str]:
    """Run prediction + verifier for a single date in historical mode. Returns (ok, msg)."""
    from chains import daily_runner, verifier

    last_err: str = ""
    for attempt in range(1, 4):
        try:
            pred = daily_runner.run_daily_prediction(date, historical_mode=True)
            if pred.error:
                last_err = f"daily_runner error: {pred.error}"
                # Exponential backoff for transient (rate limit, network) — 2s, 4s, 8s
                time.sleep(2 ** attempt)
                continue
            verifier.verify_prediction(date, historical_mode=True)
            return True, "ok"
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            logger.warning("backtest %s attempt %d failed: %s", date, attempt, last_err)
            time.sleep(2 ** attempt)
    return False, last_err


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2025-01-01", help="Start date YYYY-MM-DD inclusive.")
    parser.add_argument(
        "--end",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="End date YYYY-MM-DD inclusive (default today).",
    )
    parser.add_argument("--apply", action="store_true", help="Actually run; default is dry-run.")
    parser.add_argument(
        "--skip-existing",
        dest="skip_existing",
        action="store_true",
        default=True,
        help="Skip dates that already have a daily_predictions row (default on).",
    )
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="Re-run dates that already have a row (overwrites).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Reserved for future parallelism; currently has no effect (sequential).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    init_storage()
    candidates = _candidate_dates(args.start, args.end)
    print(f"daily_ohlc dates in [{args.start}, {args.end}]: {len(candidates)}")
    if not candidates:
        print("nothing to backtest — daily_ohlc empty for that range. run scripts/scrape_historical_ohlc.py first.")
        return 0

    if args.skip_existing:
        existing = _existing_rows(candidates)
        candidates = [d for d in candidates if d not in existing]
        print(f"after skipping {len(existing)} existing rows: {len(candidates)} remaining")

    if not candidates:
        print("nothing to do.")
        return 0

    if not args.apply:
        print("DRY RUN — would run sequentially:")
        for d in candidates[:5]:
            print(f"  {d}")
        if len(candidates) > 5:
            print(f"  ... and {len(candidates) - 5} more")
        return 0

    started = time.monotonic()
    successes = 0
    failures = 0
    for i, date in enumerate(candidates, start=1):
        ok, msg = _run_one(date)
        if ok:
            successes += 1
        else:
            failures += 1
            logger.error("FAIL %s: %s", date, msg)
        if i % 10 == 0 or i == len(candidates):
            elapsed = time.monotonic() - started
            rate = i / elapsed if elapsed else 0
            remaining = (len(candidates) - i) / rate if rate else 0
            print(
                f"progress {i}/{len(candidates)} ok={successes} fail={failures} "
                f"elapsed={elapsed:.0f}s eta={remaining:.0f}s"
            )

    print(f"\nbacktest done: {successes} ok, {failures} failed, {len(candidates)} attempted")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
