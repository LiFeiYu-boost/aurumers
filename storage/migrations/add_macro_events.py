"""One-shot migration: create the ``macro_events`` table + indexes.

What this does
--------------
1. ``CREATE TABLE IF NOT EXISTS macro_events`` (see record_manager.MACRO_EVENTS_DDL)
2. Two indexes: ``idx_macro_events_date`` and ``idx_macro_events_type``

Idempotent
----------
Both DDL statements use ``IF NOT EXISTS``. Re-running this script is a no-op
once the table is in place. ``init_storage()`` would also create the table on
next FastAPI boot via the new lines added to record_manager.init_storage —
this script exists so the schema can be migrated on the VPS without
restarting uvicorn.

Usage
-----
    python -m storage.migrations.add_macro_events                # apply
    python -m storage.migrations.add_macro_events --dry-run      # report only
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

from storage.record_manager import DB_PATH, MACRO_EVENTS_DDL  # noqa: E402


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report only, no writes.")
    args = parser.parse_args()

    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        present = _table_exists(conn, "macro_events")
        print(f"[before] macro_events table present: {present}")

        if args.dry_run:
            print("[dry-run] would create table + 2 indexes if missing")
            return 0

        conn.execute(MACRO_EVENTS_DDL)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_macro_events_date ON macro_events(date)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_macro_events_type ON macro_events(event_type)"
        )
        conn.commit()

        n = conn.execute("SELECT COUNT(*) FROM macro_events").fetchone()[0]
        print(f"[after] macro_events present: True; rows={n}")
        for row in conn.execute("PRAGMA index_list('macro_events')").fetchall():
            print(f"  index: {row['name']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
