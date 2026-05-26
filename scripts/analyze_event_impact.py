"""Analyse 24h gold-price impact per macro event_type — output Hermes learnings.

Algorithm
---------
1. Read all closes from ``daily_ohlc`` (per source: sge, comex). Compute
   per-source daily log-return ``r_t = log(close_t / close_{t-1})``.
2. Compute rolling 30-day std of returns per source.
3. Tag a date as "big move" when ``|r_t| > 1.5 * σ_30(date_t)``.
4. For each row in ``macro_events``: find the next trading day's r (per
   source), join to the event row.
5. Aggregate per ``event_type``:
   - n_total
   - n_big_move
   - big_move_rate
   - mean_abs_return_pct  (24h, average over both sources where available)
   - direction_skew = (n_up − n_down) / n_total ∈ [−1, +1]
   - if surprise data exists: split mean return by sign of surprise
6. Reverse map: list the most-recent N big-move days and which events
   occurred ≤ 1 trading day before them.

Output
------
Writes a single Markdown file to
``/opt/aurumers/hermes_workdir/learnings/macro_event_impact.md`` (path
overridable via ``$AURUMERS_MACRO_LEARNINGS_DIR``) — Hermes' Sunday reflection
loop reads ``learnings/*.md`` from the past 7 days. Re-running the script
overwrites the file, refreshing its mtime so Hermes picks it up next Sunday.

Also writes a machine-readable JSON to ``data/event_impact_summary.json`` for
future UI / audit.

Usage
-----
    python scripts/analyze_event_impact.py                        # dry-run
    python scripts/analyze_event_impact.py --apply                # write files
    python scripts/analyze_event_impact.py --apply --sigma 2.0    # tune threshold
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import statistics
import sys
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from storage.record_manager import DB_PATH, init_storage  # noqa: E402


DEFAULT_LEARNINGS_DIR = Path(
    os.environ.get(
        "AURUMERS_MACRO_LEARNINGS_DIR",
        "/opt/aurumers/hermes_workdir/learnings",
    )
)
DEFAULT_JSON_OUT = REPO_ROOT / "data" / "event_impact_summary.json"


_MAX_GAP_DAYS = 7  # weekend + holiday slack; beyond this we skip the return
_MAX_DAILY_LOG_RETURN = math.log(1.10)  # ~9.5% cap


def _load_returns(conn: sqlite3.Connection, source: str) -> dict[str, float]:
    """date → log-return for the given source.

    Skips returns spanning gaps > 7 calendar days — e.g., the SGE OHLC
    sometimes has multi-month holes (akshare upstream silently drops
    pre-Spring-Festival or backfill-failed ranges); a naive consecutive
    log-return across such a gap fabricates double-digit "moves" that wreck
    the rolling-σ baseline downstream.

    Also caps |log_return| at ~9.5% (≈10% raw) to discard akshare-upstream
    data quality outliers. Verified case: SGE Au(T+D) 2026-03-23 shows
    close=920.99 (-11.5% from 1040.60 prev day, vs COMEX -1.8% same day) —
    almost certainly a margin-product flash event or upstream scraping
    artifact, NOT a real market-wide gold crash. Treating these as missing
    is safer than letting one outlier inflate rolling σ for 30 days.
    Detected by round-1 adversarial audit (C1).
    """
    rows = conn.execute(
        "SELECT date, close FROM daily_ohlc WHERE source = ? AND close IS NOT NULL ORDER BY date ASC",
        (source,),
    ).fetchall()
    out: dict[str, float] = {}
    prev_date: str | None = None
    prev_close: float | None = None
    for row in rows:
        if prev_close is not None and prev_close > 0 and row["close"] > 0:
            try:
                gap = (
                    datetime.strptime(row["date"], "%Y-%m-%d")
                    - datetime.strptime(prev_date, "%Y-%m-%d")
                ).days
            except ValueError:
                gap = _MAX_GAP_DAYS + 1
            if gap <= _MAX_GAP_DAYS:
                r = math.log(row["close"] / prev_close)
                if abs(r) <= _MAX_DAILY_LOG_RETURN:
                    out[row["date"]] = r
        prev_date = row["date"]
        prev_close = row["close"]
    return out


def _rolling_sigma(
    returns: dict[str, float], window: int = 30
) -> dict[str, float]:
    """date → rolling std of returns over the prior `window` trading days."""
    dates_sorted = sorted(returns.keys())
    values = [returns[d] for d in dates_sorted]
    out: dict[str, float] = {}
    for i, date in enumerate(dates_sorted):
        if i < window:
            continue
        slice_ = values[i - window:i]
        if len(slice_) >= 2:
            out[date] = statistics.pstdev(slice_)
    return out


def _next_trading_day(
    after: str, available_dates: set[str]
) -> str | None:
    """Walk forward day by day; return the first date in `available_dates`."""
    cursor = datetime.strptime(after, "%Y-%m-%d")
    for _ in range(15):  # 14-day cap covers Spring Festival worst case
        cursor += timedelta(days=1)
        candidate = cursor.strftime("%Y-%m-%d")
        if candidate in available_dates:
            return candidate
    return None


def _aggregate_per_event_type(
    rows: list[dict],
) -> list[dict]:
    """Aggregate rows by event_type. Each row already has 'next_return' / 'is_big_move'.

    Returns sorted list of summaries (most informative event_type first).
    """
    by_type: dict[str, list[dict]] = {}
    for row in rows:
        by_type.setdefault(row["event_type"], []).append(row)

    summaries: list[dict] = []
    for event_type, items in by_type.items():
        with_return = [r for r in items if r["next_return"] is not None]
        if not with_return:
            continue
        n = len(with_return)
        n_big = sum(1 for r in with_return if r["is_big_move"])
        n_up = sum(1 for r in with_return if r["next_return"] > 0)
        n_down = sum(1 for r in with_return if r["next_return"] < 0)
        mean_abs = sum(abs(r["next_return"]) for r in with_return) / n
        mean_signed = sum(r["next_return"] for r in with_return) / n

        # Surprise stratification (when available)
        with_surprise = [r for r in with_return if r["surprise_pct"] is not None]
        surprise_up: list[float] = [r["next_return"] for r in with_surprise if r["surprise_pct"] > 0]
        surprise_down: list[float] = [r["next_return"] for r in with_surprise if r["surprise_pct"] < 0]

        summaries.append({
            "event_type": event_type,
            "country": items[0]["country"],
            "n": n,
            "n_big_move": n_big,
            "big_move_rate": round(n_big / n, 3),
            "mean_abs_return_pct": round(mean_abs * 100, 3),
            "direction_skew": round((n_up - n_down) / n, 3),
            "mean_signed_return_pct": round(mean_signed * 100, 3),
            "n_with_surprise": len(with_surprise),
            "mean_return_when_surprise_pos_pct": (
                round(sum(surprise_up) / len(surprise_up) * 100, 3) if surprise_up else None
            ),
            "mean_return_when_surprise_neg_pct": (
                round(sum(surprise_down) / len(surprise_down) * 100, 3) if surprise_down else None
            ),
        })
    # Sort by sample size desc → biggest signals first
    summaries.sort(key=lambda s: s["n"], reverse=True)
    return summaries


def _format_markdown(
    summaries: list[dict],
    big_move_rows: list[dict],
    n_events: int,
    n_trading_days: int,
    n_big_move_days: int,
    sigma: float,
    date_range: tuple[str, str],
) -> str:
    lines: list[str] = []
    lines.append("# 宏观事件 × 金价 24h 影响汇总")
    lines.append("")
    lines.append(f"数据范围：{date_range[0]} → {date_range[1]}")
    lines.append(
        f"共 {n_events} 事件 / {n_trading_days} 交易日 / {n_big_move_days} 大波动日"
        f"（阈值 ±{sigma}σ）"
    )
    lines.append("")
    lines.append("## 事件类型 × 次日影响（按样本数排序）")
    lines.append("")
    lines.append("| 事件 | 国家 | 样本 | 大波动率 | 均 \\|return\\| | 方向偏向 | 均 signed return |")
    lines.append("|---|---|---|---|---|---|---|")
    for s in summaries:
        skew_label = (
            f"偏多 +{s['direction_skew']:.2f}" if s["direction_skew"] > 0.10
            else f"偏空 {s['direction_skew']:.2f}" if s["direction_skew"] < -0.10
            else "中性"
        )
        lines.append(
            f"| {s['event_type']} | {s['country']} | {s['n']} | "
            f"{s['big_move_rate'] * 100:.0f}% | {s['mean_abs_return_pct']:.2f}% | "
            f"{skew_label} | {s['mean_signed_return_pct']:+.2f}% |"
        )

    lines.append("")
    lines.append("## 关键洞察")
    lines.append("")
    insights = _derive_insights(summaries, n_big_move_days, n_trading_days)
    for i, ins in enumerate(insights, 1):
        lines.append(f"{i}. {ins}")
    if not insights:
        lines.append("（样本不足，暂无统计显著洞察）")

    lines.append("")
    lines.append(f"## 大波动日反查（最近 {len(big_move_rows)} 个）")
    lines.append("")
    if big_move_rows:
        lines.append("| 日期 | source | 当日 \\|return\\| | 触发事件（≤1 个交易日内） |")
        lines.append("|---|---|---|---|")
        for row in big_move_rows:
            evs = "; ".join(row["events_within_1d"][:3]) or "无可识别事件"
            lines.append(
                f"| {row['date']} | {row['source']} | "
                f"{abs(row['return']) * 100:.2f}% | {evs} |"
            )
    else:
        lines.append("（暂无大波动日记录）")

    lines.append("")
    lines.append(
        f"> 由 scripts/analyze_event_impact.py 生成 · "
        f"更新时间 {datetime.now().isoformat(timespec='seconds')}"
    )
    return "\n".join(lines) + "\n"


def _derive_insights(summaries: list[dict], n_big_days: int, n_trading_days: int) -> list[str]:
    """Pick the top-3 statistically interesting findings to lead the markdown.

    Significance test uses a binomial confidence interval (round-2 audit M):
    an event_type is flagged only when its observed big_move_rate exceeds
    the baseline by more than ~2 SEs of a binomial proportion sampled at
    that event_type's n. This prevents "us_nfp 42% vs baseline 24%" being
    declared a signal when the gap is within Bernoulli noise for n=33.
    """
    out: list[str] = []
    base = n_big_days / max(n_trading_days, 1)

    def _significant_excess(p: float, n: int) -> bool:
        # 2-SE one-sided binomial test against the baseline rate.
        # When base==0 (no big-move days globally), SE collapses to ~0 and
        # any p>0 would pass — round-3 audit LOW. Explicit guard.
        if n < 8 or base <= 0 or n_big_days < 5:
            return False
        se = math.sqrt(base * (1 - base) / n)
        return p > base + 2 * se

    # Top by big_move_rate vs baseline, only flagged if statistically significant.
    by_big = sorted(
        [s for s in summaries if _significant_excess(s["big_move_rate"], s["n"])],
        key=lambda s: s["big_move_rate"] - base,
        reverse=True,
    )
    if by_big:
        s = by_big[0]
        out.append(
            f"**{s['event_type']}** 触发大波动概率 {s['big_move_rate'] * 100:.0f}% "
            f"（基线 {base * 100:.0f}%），样本 {s['n']}，"
            f"均 |return| {s['mean_abs_return_pct']:.2f}%（>2 SE 显著）"
        )

    # Strongest direction skew
    by_skew = sorted(
        [s for s in summaries if s["n"] >= 8 and abs(s["direction_skew"]) > 0.20],
        key=lambda s: abs(s["direction_skew"]),
        reverse=True,
    )
    if by_skew:
        s = by_skew[0]
        direction = "偏多" if s["direction_skew"] > 0 else "偏空"
        out.append(
            f"**{s['event_type']}** 次日金价{direction}（n={s['n']}，"
            f"signed return 均 {s['mean_signed_return_pct']:+.2f}%）"
        )

    # Surprise-conditioned strongest divergence
    by_surprise_div = []
    for s in summaries:
        if (
            s["mean_return_when_surprise_pos_pct"] is not None
            and s["mean_return_when_surprise_neg_pct"] is not None
            and s["n_with_surprise"] >= 8
        ):
            divergence = s["mean_return_when_surprise_pos_pct"] - s["mean_return_when_surprise_neg_pct"]
            by_surprise_div.append((s, divergence))
    by_surprise_div.sort(key=lambda x: abs(x[1]), reverse=True)
    if by_surprise_div:
        s, div = by_surprise_div[0]
        out.append(
            f"**{s['event_type']} surprise 信号显著**："
            f"超预期时金价 {s['mean_return_when_surprise_pos_pct']:+.2f}%，"
            f"低预期时 {s['mean_return_when_surprise_neg_pct']:+.2f}%（差距 {div:+.2f}pp，"
            f"n={s['n_with_surprise']}）"
        )

    return out[:3]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write markdown + JSON files (default: print summary only).")
    parser.add_argument("--sigma", type=float, default=2.0, help="Big-move threshold in std units (default 2.0; raised from 1.5 in round-2 audit because gold log-returns are heavy-tailed and 1.5σ gave a 24% baseline rate vs normal-distribution 13%).")
    parser.add_argument("--big-move-list-n", type=int, default=30, help="How many big-move days to list (default 30).")
    parser.add_argument("--learnings-dir", default=str(DEFAULT_LEARNINGS_DIR))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    args = parser.parse_args()

    init_storage()
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row

        # Returns + sigma per source
        sources = ("sge", "comex")
        returns_by_source: dict[str, dict[str, float]] = {}
        sigma_by_source: dict[str, dict[str, float]] = {}
        for source in sources:
            r = _load_returns(conn, source)
            returns_by_source[source] = r
            sigma_by_source[source] = _rolling_sigma(r, window=30)

        # All trading days across both sources
        all_trading_days = set()
        for source in sources:
            all_trading_days.update(returns_by_source[source].keys())
        n_trading_days = len(all_trading_days)

        # Big-move dates per source
        big_move_per_source: dict[str, set[str]] = {}
        for source in sources:
            r = returns_by_source[source]
            sig = sigma_by_source[source]
            big_move_per_source[source] = {
                d for d, ret in r.items()
                if d in sig and abs(ret) > args.sigma * sig[d]
            }
        all_big_move_days = (big_move_per_source["sge"] | big_move_per_source["comex"])

        # Load events + join to next trading day's return
        ev_rows = conn.execute(
            "SELECT date, event_type, country, actual_value, forecast_value, surprise_pct, label FROM macro_events ORDER BY date ASC"
        ).fetchall()

        joined_rows: list[dict] = []
        for ev in ev_rows:
            event_date = ev["date"]
            row_summary = {
                "event_date": event_date,
                "event_type": ev["event_type"],
                "country": ev["country"],
                "surprise_pct": ev["surprise_pct"],
                "next_return": None,
                "is_big_move": False,
            }
            # Choose return: average across sources where available; tag big_move
            # if EITHER source flagged the next day big.
            next_returns: list[float] = []
            next_big_flags: list[bool] = []
            for source in sources:
                r = returns_by_source[source]
                sig = sigma_by_source[source]
                next_day = _next_trading_day(event_date, set(r.keys()))
                if next_day is None:
                    continue
                next_r = r[next_day]
                next_returns.append(next_r)
                if next_day in sig:
                    next_big_flags.append(abs(next_r) > args.sigma * sig[next_day])
            if next_returns:
                row_summary["next_return"] = sum(next_returns) / len(next_returns)
                row_summary["is_big_move"] = any(next_big_flags)
            joined_rows.append(row_summary)

        summaries = _aggregate_per_event_type(joined_rows)

        # Reverse map: most-recent N big-move days → events within ≤1 prior trading day
        events_by_date: dict[str, list[str]] = {}
        for ev in ev_rows:
            events_by_date.setdefault(ev["date"], []).append(f"{ev['event_type']}/{ev['country']}")

        big_move_rows: list[dict] = []
        for source in sources:
            r = returns_by_source[source]
            for date in sorted(big_move_per_source[source], reverse=True)[: args.big_move_list_n]:
                # Find events on this date OR up to 1 trading day prior
                evs_today = events_by_date.get(date, [])
                # Walk back to prior trading day for that source
                prior_evs: list[str] = []
                cursor = datetime.strptime(date, "%Y-%m-%d")
                for _ in range(7):
                    cursor -= timedelta(days=1)
                    candidate = cursor.strftime("%Y-%m-%d")
                    if candidate in r:
                        prior_evs = events_by_date.get(candidate, [])
                        break
                big_move_rows.append({
                    "date": date,
                    "source": source,
                    "return": r[date],
                    "events_within_1d": evs_today + prior_evs,
                })
        # Combine + sort by date desc, dedupe (date,source)
        seen = set()
        deduped: list[dict] = []
        for row in sorted(big_move_rows, key=lambda x: x["date"], reverse=True):
            key = (row["date"], row["source"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(row)
        big_move_rows = deduped[: args.big_move_list_n]

        date_range = ("(no data)", "(no data)")
        if all_trading_days:
            date_range = (min(all_trading_days), max(all_trading_days))

        markdown = _format_markdown(
            summaries=summaries,
            big_move_rows=big_move_rows,
            n_events=len(joined_rows),
            n_trading_days=n_trading_days,
            n_big_move_days=len(all_big_move_days),
            sigma=args.sigma,
            date_range=date_range,
        )
        json_payload = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "sigma_threshold": args.sigma,
            "n_events": len(joined_rows),
            "n_trading_days": n_trading_days,
            "n_big_move_days": len(all_big_move_days),
            "date_range": date_range,
            "by_event_type": summaries,
            "big_move_days": [
                {**r, "return_pct": round(r["return"] * 100, 3)} for r in big_move_rows
            ],
        }

    print(markdown)

    if args.apply:
        learnings_dir = Path(args.learnings_dir)
        learnings_dir.mkdir(parents=True, exist_ok=True)
        # Atomic write via tempfile + replace — daily 02:50 Hermes prompt
        # reads this file; a non-atomic write_text() opens with "w" which
        # truncates first, exposing a brief window where the reader sees
        # empty/partial content (round-4 audit LOW).
        def _atomic_write(target: Path, content: str) -> None:
            tmp = target.with_suffix(target.suffix + ".tmp")
            tmp.write_text(content, encoding="utf-8")
            os.replace(tmp, target)

        md_path = learnings_dir / "macro_event_impact.md"
        _atomic_write(md_path, markdown)
        print(f"\nwrote {md_path}")

        json_path = Path(args.json_out)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(json_path, json.dumps(json_payload, ensure_ascii=False, indent=2))
        print(f"wrote {json_path}")
    else:
        print("\n[dry-run] no files written; pass --apply to persist")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
