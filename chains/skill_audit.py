"""Read-side observability for Hermes skill self-evolution.

Background: SKILL.md tells Hermes to (eventually) drop hint files into
``/root/.hermes/skills/gold_buy_predictor/hints/`` after the Sunday reflection
cron. Whether that actually happens has historically been unverifiable —
this module + the daily diff cron in deploy.sh make it observable.

Daily cron writes a unified diff of the live skill dir vs the previous day's
snapshot to ``/opt/aurumers/hermes_workdir/audits/YYYY-MM-DD.diff``. A diff
file is written even when there's no change (size 0). 30 zero-byte days in a
row → nothing is evolving, and the Insights page surfaces that bluntly.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel


AUDIT_DIR = Path(os.environ.get("AURUMERS_SKILL_AUDIT_DIR", "/opt/aurumers/hermes_workdir/audits"))
HINT_DIR = Path(os.environ.get("AURUMERS_SKILL_HINT_DIR", "/root/.hermes/skills/gold_buy_predictor/hints"))


_DATE_FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.diff$")


class SkillAuditEntry(BaseModel):
    date: str
    bytes: int
    has_change: bool


class SkillAuditSummary(BaseModel):
    last_change_date: str | None
    days_since_last_change: int | None
    audits_in_window: int
    nonempty_in_window: int
    hint_count: int
    most_recent: list[SkillAuditEntry]
    error: str | None = None


def _list_audits() -> list[SkillAuditEntry]:
    if not AUDIT_DIR.is_dir():
        return []
    entries: list[SkillAuditEntry] = []
    for path in AUDIT_DIR.iterdir():
        if not path.is_file():
            continue
        match = _DATE_FILE_RE.match(path.name)
        if not match:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        entries.append(SkillAuditEntry(date=match.group(1), bytes=size, has_change=size > 0))
    entries.sort(key=lambda e: e.date, reverse=True)
    return entries


def _count_hints() -> int:
    if not HINT_DIR.is_dir():
        return 0
    return sum(1 for p in HINT_DIR.iterdir() if p.is_file() and p.suffix.lower() == ".md")


def get_skill_audit_summary(window_days: int = 30, recent_n: int = 7) -> SkillAuditSummary:
    """Return what the Insights page needs in one shot.

    Never raises — surfaces missing dirs as ``audits_in_window=0`` so the
    frontend can render "未演化 / 等待 cron 落盘"."""
    try:
        entries = _list_audits()
    except OSError as exc:
        return SkillAuditSummary(
            last_change_date=None,
            days_since_last_change=None,
            audits_in_window=0,
            nonempty_in_window=0,
            hint_count=0,
            most_recent=[],
            error=f"audit_dir_io: {exc}",
        )

    cutoff = (datetime.now() - timedelta(days=window_days)).strftime("%Y-%m-%d")
    in_window = [e for e in entries if e.date >= cutoff]
    nonempty = [e for e in in_window if e.has_change]

    last_change = next((e for e in entries if e.has_change), None)
    days_since: int | None = None
    if last_change is not None:
        try:
            last_dt = datetime.strptime(last_change.date, "%Y-%m-%d")
            days_since = max(0, (datetime.now() - last_dt).days)
        except ValueError:
            days_since = None

    return SkillAuditSummary(
        last_change_date=last_change.date if last_change else None,
        days_since_last_change=days_since,
        audits_in_window=len(in_window),
        nonempty_in_window=len(nonempty),
        hint_count=_count_hints(),
        most_recent=entries[:recent_n],
    )
