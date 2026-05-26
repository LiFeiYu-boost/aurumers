"""One-shot migration: add ``data_origin`` column + index + tag placeholder rows.

What this does
--------------
1. ``ALTER TABLE daily_predictions ADD COLUMN data_origin TEXT NOT NULL DEFAULT 'live'``
   — SQLite back-fills every existing row with the default 'live'.
2. ``CREATE INDEX IF NOT EXISTS idx_daily_predictions_origin``
3. ``UPDATE ... SET data_origin = 'placeholder_legacy' WHERE prompt_version IN
   ('daily-v1', 'daily-v2-prob3')`` — 288 rows from the pre-Phase-A qwen-plus
   era that default to '震荡' for almost every direction call. They were
   reconstructed without the current pipeline and would systematically tilt
   any "model accuracy" aggregate downward. Tagging them out means the live
   metrics, Hermes Sunday reflection, and Insights vs-baseline view all
   exclude them by default, but the rows themselves remain in DB for audit.

Idempotent
----------
The ALTER step uses ``_add_columns_if_missing`` which catches "duplicate
column" errors. The UPDATE is a no-op when re-run because the rows already
hold 'placeholder_legacy'.

Note: ``init_storage()`` will also add the column on next app startup via
``_ensure_columns``; this script exists so you can run the migration without
booting the app (e.g., on a VPS where you want to verify state before
restarting the FastAPI process).

Usage
-----
    python -m storage.migrations.add_data_origin                # apply
    python -m storage.migrations.add_data_origin --dry-run      # report only
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from storage.record_manager import DB_PATH, _add_columns_if_missing  # noqa: E402


PLACEHOLDER_PROMPT_VERSIONS = ("daily-v1", "daily-v2-prob3")


def _count_by_origin(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT data_origin, COUNT(*) AS n FROM daily_predictions GROUP BY data_origin"
    ).fetchall()
    return {row["data_origin"]: row["n"] for row in rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report only, no writes.")
    args = parser.parse_args()

    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row

        cols_before = {row["name"] for row in conn.execute("PRAGMA table_info(daily_predictions)").fetchall()}
        has_origin_before = "data_origin" in cols_before
        print(f"[before] data_origin column present: {has_origin_before}")

        if args.dry_run:
            # Need the column to count; if absent, we project the migration result.
            placeholders = ",".join("?" for _ in PLACEHOLDER_PROMPT_VERSIONS)
            n_placeholder = conn.execute(
                f"SELECT COUNT(*) AS n FROM daily_predictions WHERE prompt_version IN ({placeholders})",
                PLACEHOLDER_PROMPT_VERSIONS,
            ).fetchone()["n"]
            n_total = conn.execute("SELECT COUNT(*) AS n FROM daily_predictions").fetchone()["n"]
            print(f"[dry-run] would tag {n_placeholder} rows as placeholder_legacy "
                  f"(rest of {n_total - n_placeholder} rows default to 'live')")
            return 0

        # Step 1 + 2: ensure column + index
        _add_columns_if_missing(
            conn,
            "daily_predictions",
            {"data_origin": "TEXT NOT NULL DEFAULT 'live'"},
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_daily_predictions_origin "
            "ON daily_predictions(data_origin)"
        )

        # Step 3: tag placeholder rows
        placeholders = ",".join("?" for _ in PLACEHOLDER_PROMPT_VERSIONS)
        cursor = conn.execute(
            f"UPDATE daily_predictions "
            f"   SET data_origin = 'placeholder_legacy' "
            f" WHERE prompt_version IN ({placeholders}) "
            f"   AND data_origin != 'placeholder_legacy'",
            PLACEHOLDER_PROMPT_VERSIONS,
        )
        n_updated = cursor.rowcount

        conn.commit()
        print(f"[after] tagged {n_updated} new rows as placeholder_legacy")
        for origin, n in _count_by_origin(conn).items():
            print(f"  data_origin={origin}: {n}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
