"""Backfill daily_ohlc table with historical SGE Au(T+D) and COMEX GC data via akshare.

Why this script
---------------
huilvbiao only returns the live snapshot — Aurumers has no historical OHLC source. To
support Phase 1 metrics (regime classification needs 30d realized vol) and Phase 2
technical indicators (ATR, RSI, MA20 distance), we materialize a local
``daily_ohlc`` table that is locked at insert time and never rewritten by the
scraper. This is the only line of defense against look-ahead bias when later
phases compute "yesterday's RSI" from "today's data."

Lock semantics
--------------
``INSERT OR IGNORE`` — once a (date, source) pair exists, this script will never
touch it. ``locked_at`` is the timestamp of the original insert, period. To
correct a row, delete it manually via SQL and re-run; do not add a "force" flag
here, because the entire point of the table is that historical truth is
immutable from the prediction pipeline's perspective.

Phase 2 note: the actual akshare fetchers + insert helpers live in
``tools/gold_history.py`` and are also used by ``chains/daily_lock.py`` (the
03:05 cron). This script is now a thin CLI on top of that module.

Usage
-----
    python scripts/scrape_historical_ohlc.py                       # dry-run, prints rows
    python scripts/scrape_historical_ohlc.py --apply               # insert into DB
    python scripts/scrape_historical_ohlc.py --apply --start 2026-01-01 --end 2026-05-10
    python scripts/scrape_historical_ohlc.py --apply --source sge  # single source
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from storage.record_manager import DB_PATH, init_storage  # noqa: E402
from tools.gold_history import (  # noqa: E402
    fetch_history,
    filter_rows,
    insert_ohlc_row,
    load_existing_dates,
)


SOURCES = ("sge", "comex")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Persist changes (default: dry-run).")
    parser.add_argument("--start", default="2026-01-01", help="Start date YYYY-MM-DD inclusive.")
    parser.add_argument(
        "--end",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="End date YYYY-MM-DD inclusive (default today).",
    )
    parser.add_argument("--source", choices=("all", *SOURCES), default="all")
    args = parser.parse_args()

    targets = SOURCES if args.source == "all" else (args.source,)
    print(f"range {args.start} → {args.end} sources={targets} apply={args.apply}")

    init_storage()
    locked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    inserted_total = 0
    skipped_total = 0

    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        for source in targets:
            print(f"\n--- fetching {source} ---")
            rows = fetch_history(source)
            ranged = filter_rows(rows, args.start, args.end)
            existing = load_existing_dates(conn, source)
            print(f"  upstream rows in range: {len(ranged)}; already locked: {len(existing)}")

            inserted = 0
            skipped = 0
            for row in ranged:
                if row["date"] in existing:
                    skipped += 1
                    continue
                if not args.apply:
                    print(
                        f"  DRY {source} {row['date']} O={row['open']} H={row['high']} "
                        f"L={row['low']} C={row['close']}"
                    )
                else:
                    insert_ohlc_row(conn, source, row, locked_at)
                inserted += 1
            if args.apply:
                conn.commit()
            inserted_total += inserted
            skipped_total += skipped
            print(f"  {source}: {inserted} {'inserted' if args.apply else 'would-insert'}, {skipped} skipped (locked)")

    suffix = "applied" if args.apply else "dry-run"
    print(f"\n{suffix}: total {inserted_total} {'inserted' if args.apply else 'would-insert'}, {skipped_total} skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
