"""Heuristic backfill of (prob_up, prob_down, prob_flat) for legacy daily_predictions
rows that were saved before Phase 0 introduced the three-probability vector.

Reconstruction rule
-------------------
For each row with tomorrow_direction != UNKNOWN and any of the three prob columns
NULL (and prob_source != 'reconstructed' yet), distribute probability mass:
    prob[direction]      = clamp(confidence, [floor, 1 - 2*floor]); default 0.4
    prob[other two]      = max(floor, (1 - prob[direction]) / 2)
then renormalize so the triple sums to 1. floor = 0.05.

Source tag
----------
Updated rows are tagged prob_source='reconstructed' so downstream metrics
(Brier / log-loss / ECE) can optionally exclude reconstructed rows when reporting
the model's true calibration.

Usage
-----
    python scripts/backfill_probs.py            # dry-run, prints intended changes
    python scripts/backfill_probs.py --apply    # commits changes

Run from the repo root with the project's `.venv` active so config.DB_PATH resolves
to the canonical gold_records.db.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from storage.record_manager import DB_PATH, init_storage  # noqa: E402


_FLOOR = 0.05
_DEFAULT_CONF = 0.4
_DIRECTION_INDEX = {"上涨": 0, "下跌": 1, "震荡": 2, "平": 2}


def _reconstruct(direction: str, confidence: float | None) -> tuple[float, float, float] | None:
    idx = _DIRECTION_INDEX.get((direction or "").strip())
    if idx is None:
        return None
    base_conf = confidence if confidence is not None else _DEFAULT_CONF
    base = max(_FLOOR, min(1.0 - 2 * _FLOOR, float(base_conf)))
    other = max(_FLOOR, (1.0 - base) / 2.0)
    triple = [other, other, other]
    triple[idx] = base
    total = sum(triple)
    return tuple(round(v / total, 4) for v in triple)  # type: ignore[return-value]


def _select_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    cur = conn.execute(
        """
        SELECT id, prediction_date, tomorrow_direction, tomorrow_confidence,
               prob_up, prob_down, prob_flat, prob_source
        FROM daily_predictions
        WHERE tomorrow_direction != '未知'
          AND (prob_up IS NULL OR prob_down IS NULL OR prob_flat IS NULL)
          AND (prob_source IS NULL OR prob_source != 'reconstructed')
        ORDER BY prediction_date ASC
        """
    )
    return list(cur.fetchall())


def _apply_update(conn: sqlite3.Connection, row_id: str, triple: tuple[float, float, float]) -> None:
    conn.execute(
        """
        UPDATE daily_predictions
           SET prob_up = ?, prob_down = ?, prob_flat = ?, prob_source = 'reconstructed'
         WHERE id = ?
        """,
        (*triple, row_id),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Persist changes (default: dry-run).")
    args = parser.parse_args()

    init_storage()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    updated = 0
    skipped = 0
    try:
        with closing(conn):
            rows = _select_rows(conn)
            if not rows:
                print("no rows need backfill")
                return 0
            print(f"found {len(rows)} candidate rows")
            for row in rows:
                triple = _reconstruct(row["tomorrow_direction"], row["tomorrow_confidence"])
                if triple is None:
                    skipped += 1
                    print(f"  - skip {row['prediction_date']} ({row['id']}): unknown direction")
                    continue
                action = "APPLY" if args.apply else "DRY"
                print(
                    f"  {action} {row['prediction_date']} dir={row['tomorrow_direction']} "
                    f"conf={row['tomorrow_confidence']} -> "
                    f"up={triple[0]} down={triple[1]} flat={triple[2]}"
                )
                if args.apply:
                    _apply_update(conn, row["id"], triple)
                    updated += 1
            if args.apply:
                conn.commit()
    finally:
        pass

    suffix = "applied" if args.apply else "dry-run"
    print(f"{suffix}: {updated} updated, {skipped} skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
