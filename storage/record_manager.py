from collections.abc import Iterable
from contextlib import closing
from datetime import datetime, timedelta
import json
import sqlite3
import statistics
from pathlib import Path

from schemas import (
    AccuracyMetricsV2,
    AccuracySnapshot,
    AnalysisRecord,
    AnalysisStatus,
    CalibrationBucket,
    ChatMessage,
    ChatRole,
    ChatSession,
    CloseSourceStatus,
    DailyPrediction,
    DashboardSummary,
    DistributionSnapshot,
    KPISummary,
    NewsItem,
    PricePoint,
    RawProbSummary,
    RegimeLabel,
    ReliabilityBin,
    TimeSeriesPoint,
    Trend,
)


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "gold_records.db"

RANGE_TO_HOURS = {
    "1h": 1,
    "6h": 6,
    "24h": 24,
    "3d": 72,
    "7d": 24 * 7,
    "30d": 24 * 30,
    "all": None,
}


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def _add_columns_if_missing(
    connection: sqlite3.Connection,
    table: str,
    expected: dict[str, str],
) -> None:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    existing = {row["name"] for row in rows}
    for name, ddl in expected.items():
        if name not in existing:
            try:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
            except sqlite3.OperationalError as exc:
                if "duplicate column" not in str(exc).lower():
                    raise


def _ensure_columns(connection: sqlite3.Connection) -> None:
    analysis_expected = {
        "id": "TEXT PRIMARY KEY",
        "time": "TEXT NOT NULL",
        "source": "TEXT NOT NULL",
        "status": "TEXT NOT NULL",
        "price_raw": "TEXT NOT NULL DEFAULT 'N/A'",
        "price_value": "REAL",
        "news": "TEXT NOT NULL DEFAULT '[]'",
        "summary": "TEXT NOT NULL DEFAULT ''",
        "trend": "TEXT NOT NULL DEFAULT '未知'",
        "reasons": "TEXT NOT NULL DEFAULT '[]'",
        "advice": "TEXT NOT NULL DEFAULT ''",
        "raw_output": "TEXT NOT NULL DEFAULT ''",
        "model_name": "TEXT NOT NULL DEFAULT ''",
        "prompt_version": "TEXT NOT NULL DEFAULT ''",
        "latency_ms": "INTEGER NOT NULL DEFAULT 0",
        "error": "TEXT",
        "input_snapshot": "TEXT NOT NULL DEFAULT '{}'",
        "confidence": "REAL",
        "news_count": "INTEGER NOT NULL DEFAULT 0",
        "usd_index": "REAL",
        "predicted_for_date": "TEXT",
        "outcome_close": "REAL",
        "outcome_direction": "TEXT",
        "outcome_correct": "INTEGER",
        "verified_at": "TEXT",
    }
    _add_columns_if_missing(connection, "analysis_records", analysis_expected)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_analysis_records_time ON analysis_records(time)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_analysis_records_predicted_for_date ON analysis_records(predicted_for_date)"
    )

    daily_expected = {
        "prob_up": "REAL",
        "prob_down": "REAL",
        "prob_flat": "REAL",
        "prob_source": "TEXT NOT NULL DEFAULT 'model'",
        "regime_label": "TEXT",
        "brier_score": "REAL",
        "log_loss": "REAL",
        "dxy_value": "REAL",
        "dxy_5d_change_pct": "REAL",
        "us10y_real_yield": "REAL",
        "us10y_5d_change_pct": "REAL",
        "atr14": "REAL",
        "rsi14": "REAL",
        "dist_ma20_z": "REAL",
        # Baseline parallel predictions — recorded at the same time as the model
        # prediction, verified at the same time, used to make "model is improving"
        # a falsifiable claim. persistence = yesterday's actual direction;
        # ma5 = today close vs N-day MA direction (N=5 by default).
        # baseline_anchor_source pins which market (sge/comex) the baselines
        # were computed against so the verifier doesn't accidentally compare
        # SGE-direction baselines vs a COMEX-derived actual_direction (or
        # vice versa) on dual-source days.
        "baseline_persistence_direction": "TEXT",
        "baseline_persistence_correct": "INTEGER",
        "baseline_ma_direction": "TEXT",
        "baseline_ma_correct": "INTEGER",
        "baseline_anchor_source": "TEXT",
        # Post-processing layer (P0): raw model output + gate/calibrator metadata.
        # prob_up/prob_down/prob_flat hold the *post-processed* values used for
        # decisions and downstream metrics; prob_*_raw hold the model's untouched output.
        "prob_up_raw": "REAL",
        "prob_down_raw": "REAL",
        "prob_flat_raw": "REAL",
        "trend_gate_decision": "TEXT",
        "flat_gate_fired": "TEXT",
        "calibrator_version": "TEXT",
        "calibrator_status": "TEXT",
        "calibrator_scales": "TEXT",
        # Provenance tag separating real live predictions from historical
        # backtest replays (no news context) and legacy placeholder rows.
        # Aggregation functions default to filtering on data_origin='live'
        # to keep accuracy / calibration metrics honest.
        "data_origin": "TEXT NOT NULL DEFAULT 'live'",
    }
    _add_columns_if_missing(connection, "daily_predictions", daily_expected)


CHAT_SESSIONS_DDL = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '新对话',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0
)
"""

CHAT_MESSAGES_DDL = """
CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

DAILY_OHLC_DDL = """
CREATE TABLE IF NOT EXISTS daily_ohlc (
    date TEXT NOT NULL,
    source TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    locked_at TEXT NOT NULL,
    UNIQUE(date, source)
)
"""


# Macro events feed Hermes Sunday reflection: each row is one
# release/decision (FOMC / NFP / CPI / China LPR / GDELT geopolitical spike),
# tagged with a stable event_type so the analysis script can aggregate
# 24h gold-price impact per category. UNIQUE(date, event_type, country)
# guards against re-collection duplicates.
MACRO_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS macro_events (
    date TEXT NOT NULL,
    event_type TEXT NOT NULL,
    country TEXT NOT NULL,
    importance INTEGER NOT NULL DEFAULT 2,
    actual_value REAL,
    forecast_value REAL,
    prior_value REAL,
    surprise_pct REAL,
    label TEXT NOT NULL DEFAULT '',
    raw_payload TEXT NOT NULL DEFAULT '{}',
    locked_at TEXT NOT NULL,
    UNIQUE(date, event_type, country)
)
"""


DAILY_PREDICTIONS_DDL = """
CREATE TABLE IF NOT EXISTS daily_predictions (
    id TEXT PRIMARY KEY,
    predicted_at TEXT NOT NULL,
    prediction_date TEXT NOT NULL UNIQUE,
    today_close_sge REAL,
    today_close_comex REAL,
    today_close_source TEXT NOT NULL DEFAULT 'neither',
    today_direction TEXT NOT NULL DEFAULT '未知',
    tomorrow_direction TEXT NOT NULL DEFAULT '未知',
    tomorrow_confidence REAL,
    prob_up REAL,
    prob_down REAL,
    prob_flat REAL,
    prob_source TEXT NOT NULL DEFAULT 'model',
    prob_up_raw REAL,
    prob_down_raw REAL,
    prob_flat_raw REAL,
    trend_gate_decision TEXT,
    flat_gate_fired TEXT,
    calibrator_version TEXT,
    calibrator_status TEXT,
    calibrator_scales TEXT,
    regime_label TEXT,
    brier_score REAL,
    log_loss REAL,
    dxy_value REAL,
    dxy_5d_change_pct REAL,
    us10y_real_yield REAL,
    us10y_5d_change_pct REAL,
    atr14 REAL,
    rsi14 REAL,
    dist_ma20_z REAL,
    baseline_persistence_direction TEXT,
    baseline_persistence_correct INTEGER,
    baseline_ma_direction TEXT,
    baseline_ma_correct INTEGER,
    baseline_anchor_source TEXT,
    tomorrow_advice TEXT NOT NULL DEFAULT '',
    reasoning_summary TEXT NOT NULL DEFAULT '',
    risk_factors TEXT NOT NULL DEFAULT '[]',
    calibration_note TEXT NOT NULL DEFAULT '',
    prompt_version TEXT NOT NULL DEFAULT '',
    model_name TEXT NOT NULL DEFAULT '',
    accuracy_window_30d REAL,
    raw_output TEXT NOT NULL DEFAULT '',
    error TEXT,
    verified_at TEXT,
    verified_actual_close REAL,
    verified_actual_direction TEXT,
    verified_correct INTEGER,
    data_origin TEXT NOT NULL DEFAULT 'live'
)
"""


def init_storage() -> None:
    with closing(_connect()) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS analysis_records (
                id TEXT PRIMARY KEY,
                time TEXT NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                price_raw TEXT NOT NULL DEFAULT 'N/A',
                price_value REAL,
                news TEXT NOT NULL DEFAULT '[]',
                summary TEXT NOT NULL DEFAULT '',
                trend TEXT NOT NULL DEFAULT '未知',
                reasons TEXT NOT NULL DEFAULT '[]',
                advice TEXT NOT NULL DEFAULT '',
                raw_output TEXT NOT NULL DEFAULT '',
                model_name TEXT NOT NULL DEFAULT '',
                prompt_version TEXT NOT NULL DEFAULT '',
                latency_ms INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                input_snapshot TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        connection.execute(DAILY_PREDICTIONS_DDL)
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_daily_predictions_date ON daily_predictions(prediction_date)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_daily_predictions_origin ON daily_predictions(data_origin)"
        )
        connection.execute(DAILY_OHLC_DDL)
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_daily_ohlc_date ON daily_ohlc(date)"
        )
        connection.execute(MACRO_EVENTS_DDL)
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_macro_events_date ON macro_events(date)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_macro_events_type ON macro_events(event_type)"
        )
        connection.execute(CHAT_SESSIONS_DDL)
        connection.execute(CHAT_MESSAGES_DDL)
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_sessions_client ON chat_sessions(client_id, updated_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id, created_at ASC)"
        )
        _ensure_columns(connection)
        connection.commit()


def save_record(record: AnalysisRecord) -> None:
    with closing(_connect()) as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO analysis_records (
                id, time, source, status, price_raw, price_value, news, summary, trend,
                reasons, advice, raw_output, model_name, prompt_version, latency_ms,
                error, input_snapshot, confidence, news_count, usd_index,
                predicted_for_date, outcome_close, outcome_direction, outcome_correct, verified_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.time,
                record.source,
                record.status.value,
                record.price_raw,
                record.price_value,
                json.dumps([item.model_dump(mode="json") for item in record.news], ensure_ascii=False),
                record.summary,
                record.trend.value,
                json.dumps(record.reasons, ensure_ascii=False),
                record.advice,
                record.raw_output,
                record.model_name,
                record.prompt_version,
                record.latency_ms,
                record.error,
                json.dumps(record.input_snapshot, ensure_ascii=False),
                record.confidence,
                record.news_count,
                record.usd_index,
                record.predicted_for_date,
                record.outcome_close,
                record.outcome_direction.value if record.outcome_direction else None,
                int(record.outcome_correct) if record.outcome_correct is not None else None,
                record.verified_at,
            ),
        )
        connection.commit()


def _row_get(row: sqlite3.Row, key: str, default=None):
    try:
        value = row[key]
    except (IndexError, KeyError):
        return default
    return value if value is not None else default


def _row_to_record(row: sqlite3.Row) -> AnalysisRecord:
    news = [NewsItem.model_validate(item) for item in json.loads(row["news"] or "[]")]
    return AnalysisRecord(
        id=row["id"],
        time=row["time"],
        source=row["source"],
        status=AnalysisStatus(row["status"]),
        price_raw=row["price_raw"],
        price_value=row["price_value"],
        news=news,
        summary=row["summary"],
        trend=Trend(row["trend"]),
        reasons=json.loads(row["reasons"] or "[]"),
        advice=row["advice"],
        raw_output=row["raw_output"],
        model_name=row["model_name"],
        prompt_version=row["prompt_version"],
        latency_ms=row["latency_ms"],
        error=row["error"],
        input_snapshot=json.loads(row["input_snapshot"] or "{}"),
        confidence=_row_get(row, "confidence"),
        news_count=_row_get(row, "news_count", 0) or 0,
        usd_index=_row_get(row, "usd_index"),
        predicted_for_date=_row_get(row, "predicted_for_date"),
        outcome_close=_row_get(row, "outcome_close"),
        outcome_direction=_safe_trend(row["outcome_direction"]) if _row_get(row, "outcome_direction") else None,
        outcome_correct=bool(_row_get(row, "outcome_correct")) if _row_get(row, "outcome_correct") is not None else None,
        verified_at=_row_get(row, "verified_at"),
    )


def get_all_records() -> list[AnalysisRecord]:
    init_storage()
    with closing(_connect()) as connection:
        rows = connection.execute("SELECT * FROM analysis_records ORDER BY time DESC").fetchall()
    return [_row_to_record(row) for row in rows]


def get_latest_records(n: int) -> list[AnalysisRecord]:
    init_storage()
    with closing(_connect()) as connection:
        rows = connection.execute(
            "SELECT * FROM analysis_records ORDER BY time DESC LIMIT ?",
            (max(n, 1),),
        ).fetchall()
    return [_row_to_record(row) for row in rows]


def delete_record(record_id: str) -> tuple[bool, str]:
    init_storage()
    with closing(_connect()) as connection:
        cursor = connection.execute("DELETE FROM analysis_records WHERE id = ?", (record_id,))
        connection.commit()

    if cursor.rowcount == 0:
        return False, "未找到对应记录"
    return True, "删除成功"


def _resolve_range(range_: str) -> tuple[str, int | None]:
    key = (range_ or "24h").strip().lower()
    if key not in RANGE_TO_HOURS:
        key = "24h"
    return key, RANGE_TO_HOURS[key]


def _records_in_range(connection: sqlite3.Connection, hours: int | None) -> list[sqlite3.Row]:
    if hours is None:
        return list(
            connection.execute(
                "SELECT * FROM analysis_records ORDER BY time ASC"
            ).fetchall()
        )
    cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    return list(
        connection.execute(
            "SELECT * FROM analysis_records WHERE time >= ? ORDER BY time ASC",
            (cutoff,),
        ).fetchall()
    )


def _safe_trend(value) -> Trend:
    try:
        return Trend(value)
    except ValueError:
        return Trend.UNKNOWN


def _safe_status(value) -> AnalysisStatus:
    try:
        return AnalysisStatus(value)
    except ValueError:
        return AnalysisStatus.FAILED


def query_timeseries(range_: str = "24h") -> tuple[str, list[TimeSeriesPoint]]:
    init_storage()
    key, hours = _resolve_range(range_)
    with closing(_connect()) as connection:
        rows = _records_in_range(connection, hours)
    points: list[TimeSeriesPoint] = []
    for row in rows:
        summary = (row["summary"] or "")[:120]
        points.append(
            TimeSeriesPoint(
                id=row["id"],
                time=row["time"],
                price=row["price_value"],
                trend=_safe_trend(row["trend"]),
                status=_safe_status(row["status"]),
                summary=summary,
                confidence=_row_get(row, "confidence"),
                source=row["source"],
                model_name=row["model_name"],
            )
        )
    return key, points


def query_distribution(range_: str = "24h") -> tuple[str, DistributionSnapshot]:
    init_storage()
    key, hours = _resolve_range(range_)
    with closing(_connect()) as connection:
        rows = _records_in_range(connection, hours)

    trend_counts = {trend.value: 0 for trend in Trend}
    status_counts = {status.value: 0 for status in AnalysisStatus}
    hourly: dict[str, dict[str, int]] = {}

    for row in rows:
        trend_value = _safe_trend(row["trend"]).value
        status_value = _safe_status(row["status"]).value
        trend_counts[trend_value] += 1
        status_counts[status_value] += 1
        bucket = (row["time"] or "")[:13]
        bucket_data = hourly.setdefault(
            bucket,
            {status.value: 0 for status in AnalysisStatus},
        )
        bucket_data[status_value] += 1

    hourly_status = []
    for bucket in sorted(hourly):
        item = {"bucket": bucket}
        for status in AnalysisStatus:
            item[status.value] = hourly[bucket].get(status.value, 0)
        hourly_status.append(item)

    snapshot = DistributionSnapshot(
        trend_counts=trend_counts,
        status_counts=status_counts,
        hourly_status=hourly_status,
        total_records=len(rows),
    )
    return key, snapshot


def compute_kpis(range_: str = "24h") -> KPISummary:
    init_storage()
    key, hours = _resolve_range(range_)
    with closing(_connect()) as connection:
        rows = _records_in_range(connection, hours)

    if not rows:
        return KPISummary(range=key)

    prices = [row["price_value"] for row in rows if row["price_value"] is not None]
    latencies = [row["latency_ms"] for row in rows if row["latency_ms"] is not None]
    success_count = sum(1 for row in rows if _safe_status(row["status"]) is AnalysisStatus.SUCCESS)

    avg_price = round(sum(prices) / len(prices), 2) if prices else None
    min_price = round(min(prices), 2) if prices else None
    max_price = round(max(prices), 2) if prices else None
    volatility = round(statistics.pstdev(prices), 4) if len(prices) >= 2 else 0.0
    avg_latency = round(sum(latencies) / len(latencies), 1) if latencies else 0.0
    success_rate = round(success_count / len(rows), 4) if rows else 0.0

    latest = rows[-1]
    return KPISummary(
        range=key,
        total_runs=len(rows),
        success_rate=success_rate,
        avg_latency_ms=avg_latency,
        avg_price=avg_price,
        min_price=min_price,
        max_price=max_price,
        volatility=volatility,
        latest_price=latest["price_value"],
        latest_trend=_safe_trend(latest["trend"]),
        last_updated=latest["time"],
    )


def get_dashboard_summary(limit: int = 24) -> DashboardSummary:
    records = list(reversed(get_latest_records(limit)))
    trend_counts = {trend.value: 0 for trend in Trend}
    status_counts = {status.value: 0 for status in AnalysisStatus}
    price_points: list[PricePoint] = []

    for record in records:
        trend_counts[record.trend.value] += 1
        status_counts[record.status.value] += 1
        price_points.append(PricePoint(time=record.time, price=record.price_value, trend=record.trend))

    latest = records[-1] if records else None
    return DashboardSummary(
        latest=latest,
        price_points=price_points,
        trend_counts=trend_counts,
        status_counts=status_counts,
        total_records=len(records),
    )


def _safe_close_source(value) -> CloseSourceStatus:
    try:
        return CloseSourceStatus(value)
    except ValueError:
        return CloseSourceStatus.NEITHER


def _safe_regime(value) -> RegimeLabel | None:
    if value is None or value == "":
        return None
    try:
        return RegimeLabel(value)
    except ValueError:
        return None


def _row_to_daily(row: sqlite3.Row) -> DailyPrediction:
    raw_direction = row["verified_actual_direction"]
    return DailyPrediction(
        id=row["id"],
        predicted_at=row["predicted_at"],
        prediction_date=row["prediction_date"],
        today_close_sge=row["today_close_sge"],
        today_close_comex=row["today_close_comex"],
        today_close_source=_safe_close_source(row["today_close_source"]),
        today_direction=_safe_trend(row["today_direction"]),
        tomorrow_direction=_safe_trend(row["tomorrow_direction"]),
        tomorrow_confidence=row["tomorrow_confidence"],
        prob_up=_row_get(row, "prob_up", None),
        prob_down=_row_get(row, "prob_down", None),
        prob_flat=_row_get(row, "prob_flat", None),
        prob_source=_row_get(row, "prob_source", "model") or "model",
        prob_up_raw=_row_get(row, "prob_up_raw", None),
        prob_down_raw=_row_get(row, "prob_down_raw", None),
        prob_flat_raw=_row_get(row, "prob_flat_raw", None),
        trend_gate_decision=_row_get(row, "trend_gate_decision", None),
        flat_gate_fired=json.loads(_row_get(row, "flat_gate_fired", None) or "[]"),
        calibrator_version=_row_get(row, "calibrator_version", None),
        calibrator_status=_row_get(row, "calibrator_status", None),
        calibrator_scales=json.loads(_row_get(row, "calibrator_scales", None) or "null"),
        regime_label=_safe_regime(_row_get(row, "regime_label", None)),
        brier_score=_row_get(row, "brier_score", None),
        log_loss=_row_get(row, "log_loss", None),
        dxy_value=_row_get(row, "dxy_value", None),
        dxy_5d_change_pct=_row_get(row, "dxy_5d_change_pct", None),
        us10y_real_yield=_row_get(row, "us10y_real_yield", None),
        us10y_5d_change_pct=_row_get(row, "us10y_5d_change_pct", None),
        atr14=_row_get(row, "atr14", None),
        rsi14=_row_get(row, "rsi14", None),
        dist_ma20_z=_row_get(row, "dist_ma20_z", None),
        baseline_persistence_direction=(
            _safe_trend(_row_get(row, "baseline_persistence_direction", None))
            if _row_get(row, "baseline_persistence_direction", None) else None
        ),
        baseline_persistence_correct=(
            bool(_row_get(row, "baseline_persistence_correct", None))
            if _row_get(row, "baseline_persistence_correct", None) is not None else None
        ),
        baseline_ma_direction=(
            _safe_trend(_row_get(row, "baseline_ma_direction", None))
            if _row_get(row, "baseline_ma_direction", None) else None
        ),
        baseline_ma_correct=(
            bool(_row_get(row, "baseline_ma_correct", None))
            if _row_get(row, "baseline_ma_correct", None) is not None else None
        ),
        baseline_anchor_source=_row_get(row, "baseline_anchor_source", None),
        tomorrow_advice=row["tomorrow_advice"] or "",
        reasoning_summary=row["reasoning_summary"] or "",
        risk_factors=json.loads(row["risk_factors"] or "[]"),
        calibration_note=row["calibration_note"] or "",
        prompt_version=row["prompt_version"] or "",
        model_name=row["model_name"] or "",
        accuracy_window_30d=row["accuracy_window_30d"],
        raw_output=row["raw_output"] or "",
        error=row["error"],
        verified_at=row["verified_at"],
        verified_actual_close=row["verified_actual_close"],
        verified_actual_direction=_safe_trend(raw_direction) if raw_direction else None,
        verified_correct=bool(row["verified_correct"]) if row["verified_correct"] is not None else None,
        data_origin=_row_get(row, "data_origin", "live") or "live",
    )


def save_daily_prediction(prediction: DailyPrediction) -> None:
    """Upsert by prediction_date.

    Re-running ``run_daily_prediction`` (manual replay / inbox path / cron retry)
    used to wipe rows that the verifier had already populated — verified_*,
    baseline_*_correct, brier_score, log_loss, regime_label. Those columns are
    "verify-owned" and must survive a predict-time re-save.

    Implementation: ON CONFLICT(prediction_date) DO UPDATE, with COALESCE
    guarding verify-owned columns so they only take a new value when the
    caller actually has one. The predict-owned columns overwrite as before
    (they reflect the freshest input data + LLM call).
    """
    init_storage()
    with closing(_connect()) as connection:
        connection.execute(
            """
            INSERT INTO daily_predictions (
                id, predicted_at, prediction_date,
                today_close_sge, today_close_comex, today_close_source,
                today_direction, tomorrow_direction, tomorrow_confidence,
                prob_up, prob_down, prob_flat, prob_source,
                prob_up_raw, prob_down_raw, prob_flat_raw,
                trend_gate_decision, flat_gate_fired,
                calibrator_version, calibrator_status, calibrator_scales,
                regime_label, brier_score, log_loss,
                dxy_value, dxy_5d_change_pct, us10y_real_yield, us10y_5d_change_pct,
                atr14, rsi14, dist_ma20_z,
                baseline_persistence_direction, baseline_persistence_correct,
                baseline_ma_direction, baseline_ma_correct,
                baseline_anchor_source,
                tomorrow_advice,
                reasoning_summary, risk_factors, calibration_note,
                prompt_version, model_name, accuracy_window_30d, raw_output, error,
                verified_at, verified_actual_close, verified_actual_direction, verified_correct,
                data_origin
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(prediction_date) DO UPDATE SET
                id = excluded.id,
                predicted_at = excluded.predicted_at,
                today_close_sge = excluded.today_close_sge,
                today_close_comex = excluded.today_close_comex,
                today_close_source = excluded.today_close_source,
                today_direction = excluded.today_direction,
                tomorrow_direction = excluded.tomorrow_direction,
                tomorrow_confidence = excluded.tomorrow_confidence,
                prob_up = excluded.prob_up,
                prob_down = excluded.prob_down,
                prob_flat = excluded.prob_flat,
                prob_source = excluded.prob_source,
                prob_up_raw = excluded.prob_up_raw,
                prob_down_raw = excluded.prob_down_raw,
                prob_flat_raw = excluded.prob_flat_raw,
                trend_gate_decision = excluded.trend_gate_decision,
                -- flat_gate_fired: keep existing non-null value when re-save
                -- passes NULL (happens because the save_daily_prediction
                -- python writes None for empty list, so a fresh re-compute
                -- that found no gate fired would otherwise wipe the original
                -- non-empty list).
                flat_gate_fired = COALESCE(excluded.flat_gate_fired, flat_gate_fired),
                calibrator_version = excluded.calibrator_version,
                calibrator_status = excluded.calibrator_status,
                calibrator_scales = excluded.calibrator_scales,
                regime_label = COALESCE(excluded.regime_label, regime_label),
                brier_score = COALESCE(excluded.brier_score, brier_score),
                log_loss = COALESCE(excluded.log_loss, log_loss),
                dxy_value = excluded.dxy_value,
                dxy_5d_change_pct = excluded.dxy_5d_change_pct,
                us10y_real_yield = excluded.us10y_real_yield,
                us10y_5d_change_pct = excluded.us10y_5d_change_pct,
                atr14 = excluded.atr14,
                rsi14 = excluded.rsi14,
                dist_ma20_z = excluded.dist_ma20_z,
                -- baseline_*_direction is COALESCEd together with _correct
                -- so direction & correct stay coupled. Re-runs preserve the
                -- first-write baseline; if you must reset, delete the row.
                baseline_persistence_direction = COALESCE(baseline_persistence_direction, excluded.baseline_persistence_direction),
                baseline_persistence_correct = COALESCE(excluded.baseline_persistence_correct, baseline_persistence_correct),
                baseline_ma_direction = COALESCE(baseline_ma_direction, excluded.baseline_ma_direction),
                baseline_ma_correct = COALESCE(excluded.baseline_ma_correct, baseline_ma_correct),
                -- baseline_anchor_source is locked together with the directions
                -- so verifier always reads the predict-time pin.
                baseline_anchor_source = COALESCE(baseline_anchor_source, excluded.baseline_anchor_source),
                tomorrow_advice = excluded.tomorrow_advice,
                reasoning_summary = excluded.reasoning_summary,
                risk_factors = excluded.risk_factors,
                calibration_note = excluded.calibration_note,
                prompt_version = excluded.prompt_version,
                model_name = excluded.model_name,
                accuracy_window_30d = excluded.accuracy_window_30d,
                raw_output = excluded.raw_output,
                error = excluded.error,
                verified_at = COALESCE(excluded.verified_at, verified_at),
                verified_actual_close = COALESCE(excluded.verified_actual_close, verified_actual_close),
                verified_actual_direction = COALESCE(excluded.verified_actual_direction, verified_actual_direction),
                verified_correct = COALESCE(excluded.verified_correct, verified_correct),
                -- data_origin is first-write-wins: once a row is recorded as
                -- 'live' or 'backtest_no_news', re-saves do not flip it.
                -- (Re-running daily_runner in the wrong mode would otherwise
                -- silently relabel an existing row, corrupting the audit trail.)
                data_origin = COALESCE(data_origin, excluded.data_origin)
            """,
            (
                prediction.id,
                prediction.predicted_at,
                prediction.prediction_date,
                prediction.today_close_sge,
                prediction.today_close_comex,
                prediction.today_close_source.value,
                prediction.today_direction.value,
                prediction.tomorrow_direction.value,
                prediction.tomorrow_confidence,
                prediction.prob_up,
                prediction.prob_down,
                prediction.prob_flat,
                prediction.prob_source,
                prediction.prob_up_raw,
                prediction.prob_down_raw,
                prediction.prob_flat_raw,
                prediction.trend_gate_decision,
                json.dumps(prediction.flat_gate_fired, ensure_ascii=False) if prediction.flat_gate_fired else None,
                prediction.calibrator_version,
                prediction.calibrator_status,
                json.dumps(prediction.calibrator_scales, ensure_ascii=False) if prediction.calibrator_scales else None,
                prediction.regime_label.value if prediction.regime_label else None,
                prediction.brier_score,
                prediction.log_loss,
                prediction.dxy_value,
                prediction.dxy_5d_change_pct,
                prediction.us10y_real_yield,
                prediction.us10y_5d_change_pct,
                prediction.atr14,
                prediction.rsi14,
                prediction.dist_ma20_z,
                prediction.baseline_persistence_direction.value if prediction.baseline_persistence_direction else None,
                int(prediction.baseline_persistence_correct) if prediction.baseline_persistence_correct is not None else None,
                prediction.baseline_ma_direction.value if prediction.baseline_ma_direction else None,
                int(prediction.baseline_ma_correct) if prediction.baseline_ma_correct is not None else None,
                prediction.baseline_anchor_source,
                prediction.tomorrow_advice,
                prediction.reasoning_summary,
                json.dumps(prediction.risk_factors, ensure_ascii=False),
                prediction.calibration_note,
                prediction.prompt_version,
                prediction.model_name,
                prediction.accuracy_window_30d,
                prediction.raw_output,
                prediction.error,
                prediction.verified_at,
                prediction.verified_actual_close,
                prediction.verified_actual_direction.value if prediction.verified_actual_direction else None,
                int(prediction.verified_correct) if prediction.verified_correct is not None else None,
                prediction.data_origin,
            ),
        )
        connection.commit()


def get_daily_prediction(prediction_date: str) -> DailyPrediction | None:
    init_storage()
    with closing(_connect()) as connection:
        row = connection.execute(
            "SELECT * FROM daily_predictions WHERE prediction_date = ?",
            (prediction_date,),
        ).fetchone()
    return _row_to_daily(row) if row else None


DEFAULT_DATA_ORIGINS: tuple[str, ...] = ("live",)


def get_daily_predictions(
    window_days: int | None = 30,
    *,
    before_date: str | None = None,
    data_origins: Iterable[str] | None = None,
) -> list[DailyPrediction]:
    """Return predictions newest-first within the window.

    By default the window is anchored at wall-clock today (``datetime.now``)
    — fine for the live API endpoint. For historical_mode / backtest paths,
    pass ``before_date`` so the window is anchored at the prediction date
    being computed; otherwise the query returns wall-clock-recent rows that
    are FUTURE relative to the backtest day, leaking forward into the prompt
    and into calibration fitting.

    When ``before_date`` is provided, the result is filtered to rows strictly
    before that date — the backtest day's own row is excluded so re-runs
    don't pull their previous output back in.

    ``data_origins`` filters by the provenance tag. Default is ``('live',)`` —
    backtest replays and placeholder_legacy rows are excluded so live
    dashboard metrics, Hermes reflection material, and prompt
    `recent_predictions` injection don't mix data of unequal quality. Pass an
    explicit set (e.g. ``{'live', 'backtest_no_news'}``) to opt-in.
    """
    init_storage()
    if before_date is not None:
        try:
            anchor_dt = datetime.strptime(before_date, "%Y-%m-%d")
        except ValueError:
            anchor_dt = datetime.now()
    else:
        anchor_dt = datetime.now()

    origins = tuple(data_origins) if data_origins is not None else DEFAULT_DATA_ORIGINS

    conditions: list[str] = []
    params: list[object] = []

    if window_days is not None:
        cutoff = (anchor_dt - timedelta(days=window_days)).strftime("%Y-%m-%d")
        conditions.append("prediction_date >= ?")
        params.append(cutoff)
    if before_date is not None:
        conditions.append("prediction_date < ?")
        params.append(before_date)
    if origins:
        placeholders = ",".join("?" for _ in origins)
        conditions.append(f"data_origin IN ({placeholders})")
        params.extend(origins)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = f"SELECT * FROM daily_predictions {where} ORDER BY prediction_date DESC"

    with closing(_connect()) as connection:
        rows = connection.execute(sql, tuple(params)).fetchall()
    return [_row_to_daily(row) for row in rows]


def get_latest_daily_prediction() -> DailyPrediction | None:
    """Latest LIVE prediction. Filters out backtest_no_news + placeholder_legacy
    so the homepage card / chat greeting / fallback path never accidentally
    surface a backtest row as if it were today's live prediction (round-1
    adversarial audit M1).
    """
    init_storage()
    with closing(_connect()) as connection:
        row = connection.execute(
            "SELECT * FROM daily_predictions WHERE data_origin = 'live' ORDER BY prediction_date DESC LIMIT 1"
        ).fetchone()
    return _row_to_daily(row) if row else None


def update_daily_outcome(
    prediction_date: str,
    actual_close: float,
    actual_direction: Trend,
    correct: bool,
    *,
    baseline_persistence_correct: bool | None = None,
    baseline_ma_correct: bool | None = None,
) -> bool:
    init_storage()
    verified_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with closing(_connect()) as connection:
        cursor = connection.execute(
            """
            UPDATE daily_predictions
            SET verified_at = ?,
                verified_actual_close = ?,
                verified_actual_direction = ?,
                verified_correct = ?,
                baseline_persistence_correct = COALESCE(?, baseline_persistence_correct),
                baseline_ma_correct = COALESCE(?, baseline_ma_correct)
            WHERE prediction_date = ?
            """,
            (
                verified_at,
                actual_close,
                actual_direction.value,
                int(correct),
                int(baseline_persistence_correct) if baseline_persistence_correct is not None else None,
                int(baseline_ma_correct) if baseline_ma_correct is not None else None,
                prediction_date,
            ),
        )
        connection.commit()
    return cursor.rowcount > 0


WINDOW_DAYS_MAP = {
    "7d": 7,
    "30d": 30,
    "90d": 90,
    "180d": 180,
    "365d": 365,
    "1y": 365,
    "all": None,
}


def _resolve_window(window: str) -> tuple[str, int | None]:
    key = (window or "30d").strip().lower()
    if key not in WINDOW_DAYS_MAP:
        key = "30d"
    return key, WINDOW_DAYS_MAP[key]


_HIGH_CONF_THRESHOLD = 0.7
_OVERCONFIDENT_HIT_RATE_TRIGGER = 0.55
_REGIME_LAG_TRIGGER_PP = 0.10
_MIN_GROUP_FOR_PATTERN = 3
# Regime stratification is looser — Aurumers's regime classifier outputs
# `transition` for weeks at a time in choppy markets, so requiring 3-per-group
# across 2 groups leaves the axis silent on most calendar days. With ≥2 per
# group we catch genuine signal earlier; the dominant-vs-overall fallback
# below covers single-regime stretches.
_MIN_GROUP_FOR_REGIME = 2
_MAX_REASONING_CHARS = 200


def _compose_miss_pattern(verified: list[DailyPrediction]) -> str:
    """Multi-axis miss pattern, replaces the old "most-missed direction" hint.

    The old single line (一行字 most_common direction) gave the LLM almost no
    useful signal. Now we surface up to four orthogonal axes, each opt-in
    based on minimum-sample gates so we don't spam the prompt with noise:

    1. **Direction skew** — most-missed direction (kept; cheap to compute).
    2. **Overconfidence** — high-confidence (>0.7) bucket hit rate; if it's
       below 0.55 the model is systematically overconfident.
    3. **Regime lag** — which regime is dragging accuracy (>10pp below avg).
    4. **Recent high-conf miss reasoning** — up to 2 latest cases of
       (confidence ≥ 0.7 AND verified_correct=False), with their truncated
       ``reasoning_summary`` so the LLM can see what *kind* of argument
       failed last time.

    Each axis is one bullet line. Empty axes are silently dropped.
    """
    if not verified:
        return ""

    lines: list[str] = []

    # Axis 1: direction skew (preserves old behaviour)
    miss_dirs = [p.tomorrow_direction.value for p in verified if not p.verified_correct]
    if miss_dirs:
        from collections import Counter
        common_dir, common_count = Counter(miss_dirs).most_common(1)[0]
        lines.append(
            f"- 方向偏差：近 {len(verified)} 次验证里，「{common_dir}」方向预测失误最多（{common_count} 次）"
        )

    # Axis 2: overconfidence — only fire if we have ≥3 high-conf samples
    high_conf = [
        p for p in verified
        if p.tomorrow_confidence is not None and p.tomorrow_confidence >= _HIGH_CONF_THRESHOLD
    ]
    if len(high_conf) >= _MIN_GROUP_FOR_PATTERN:
        hits = sum(1 for p in high_conf if p.verified_correct)
        rate = hits / len(high_conf)
        if rate < _OVERCONFIDENT_HIT_RATE_TRIGGER:
            lines.append(
                f"- 过度自信：高置信桶（≥{_HIGH_CONF_THRESHOLD:.0%}）"
                f"实际命中率仅 {rate:.0%}（n={len(high_conf)}），"
                f"建议本次主动下调一档置信度"
            )

    # Axis 3: regime lag.
    # Path A — when ≥2 regimes each have ≥_MIN_GROUP_FOR_REGIME samples,
    # find the worst regime that's ≥10pp below the cross-regime average.
    # Path B — single-regime stretches (very common in production because the
    # classifier outputs `transition` for weeks). Compare the dominant regime
    # vs the overall accuracy and warn if it's a drag.
    regime_groups: dict[str, list[DailyPrediction]] = {}
    for p in verified:
        key = p.regime_label.value if p.regime_label else None
        if key is None:
            continue
        regime_groups.setdefault(key, []).append(p)
    eligible_regimes = {
        k: v for k, v in regime_groups.items() if len(v) >= _MIN_GROUP_FOR_REGIME
    }
    rates = {
        k: sum(1 for p in v if p.verified_correct) / len(v)
        for k, v in eligible_regimes.items()
    }
    fired_regime_axis = False
    if len(eligible_regimes) >= 2:
        avg = sum(rates.values()) / len(rates)
        worst_key = min(rates, key=rates.get)
        if avg - rates[worst_key] >= _REGIME_LAG_TRIGGER_PP:
            lines.append(
                f"- regime 拖累：「{worst_key}」regime 命中率 {rates[worst_key]:.0%}，"
                f"显著低于平均 {avg:.0%}（n={len(eligible_regimes[worst_key])}），"
                f"今日若是该 regime，请额外提高 prob_flat 或显式说明反驳依据"
            )
            fired_regime_axis = True
    if not fired_regime_axis and eligible_regimes:
        # Fallback: dominant regime vs overall.
        overall_rate = sum(1 for p in verified if p.verified_correct) / len(verified)
        dominant_key = max(eligible_regimes, key=lambda k: len(eligible_regimes[k]))
        if overall_rate - rates[dominant_key] >= _REGIME_LAG_TRIGGER_PP:
            lines.append(
                f"- regime 拖累：「{dominant_key}」regime 占样本主体但命中率 {rates[dominant_key]:.0%}，"
                f"低于整体 {overall_rate:.0%}（n={len(eligible_regimes[dominant_key])}），"
                f"今日若是该 regime，请额外提高 prob_flat 或显式说明反驳依据"
            )

    # Axis 4: recent high-conf miss reasoning (most informative signal)
    high_conf_misses = sorted(
        [
            p for p in verified
            if p.verified_correct is False
            and p.tomorrow_confidence is not None
            and p.tomorrow_confidence >= _HIGH_CONF_THRESHOLD
            and (p.reasoning_summary or "").strip()
        ],
        key=lambda p: p.prediction_date,
        reverse=True,
    )[:2]
    for miss in high_conf_misses:
        snippet = miss.reasoning_summary.strip().replace("\n", " ")
        if len(snippet) > _MAX_REASONING_CHARS:
            snippet = snippet[: _MAX_REASONING_CHARS - 1].rstrip() + "…"
        lines.append(
            f"- 高置信失败案例（{miss.prediction_date}，置信 {miss.tomorrow_confidence:.0%}，"
            f"预测「{miss.tomorrow_direction.value}」实际「"
            f"{miss.verified_actual_direction.value if miss.verified_actual_direction else '未知'}」）："
            f"{snippet}"
        )

    return "\n".join(lines)


def compute_accuracy(
    window: str = "30d",
    *,
    before_date: str | None = None,
    data_origins: Iterable[str] | None = None,
) -> AccuracySnapshot:
    """Compute accuracy snapshot.

    ``before_date`` mirrors :func:`get_daily_predictions` — pass it from
    historical_mode / backtest call sites so the window is anchored at
    the backtest day, not wall-clock today. Without this, recomputing
    accuracy for a 2024 prediction silently includes 2026 verified
    outcomes (lookahead).

    ``data_origins`` filters by provenance. Default ``None`` resolves to
    ``('live',)`` so headline metrics never mix backtest rows or legacy
    placeholders into the live denominator.
    """
    key, days = _resolve_window(window)
    predictions = get_daily_predictions(days, before_date=before_date, data_origins=data_origins)
    verified = [p for p in predictions if p.verified_correct is not None]
    correct = [p for p in verified if p.verified_correct]

    accuracy_by_direction: dict[str, float] = {}
    for direction in (Trend.UP, Trend.DOWN, Trend.FLAT):
        in_dir = [p for p in verified if p.tomorrow_direction is direction]
        if in_dir:
            hits = sum(1 for p in in_dir if p.verified_correct)
            accuracy_by_direction[direction.value] = round(hits / len(in_dir), 4)

    confidence_buckets = compute_calibration_buckets(window, before_date=before_date, data_origins=data_origins)

    streak_current = 0
    for prediction in predictions:
        if prediction.verified_correct is None:
            continue
        if prediction.verified_correct:
            streak_current += 1
        else:
            break

    longest = 0
    running = 0
    for prediction in reversed(predictions):
        if prediction.verified_correct is None:
            running = 0
            continue
        if prediction.verified_correct:
            running += 1
            longest = max(longest, running)
        else:
            running = 0

    pattern = _compose_miss_pattern(verified)

    overall = round(len(correct) / len(verified), 4) if verified else 0.0
    last_updated = predictions[0].predicted_at if predictions else None

    # Baselines: same denominator (verified rows where the baseline was also
    # recorded). Pre-baseline rows have None for the baseline cols and drop out
    # naturally — that's why baseline_verified_count may be < verified for a
    # while after rollout.
    persistence_rows = [
        p for p in verified if p.baseline_persistence_correct is not None
    ]
    ma_rows = [p for p in verified if p.baseline_ma_correct is not None]
    baseline_persistence_accuracy = (
        round(sum(1 for p in persistence_rows if p.baseline_persistence_correct) / len(persistence_rows), 4)
        if persistence_rows else None
    )
    baseline_ma_accuracy = (
        round(sum(1 for p in ma_rows if p.baseline_ma_correct) / len(ma_rows), 4)
        if ma_rows else None
    )
    baseline_verified_count = max(len(persistence_rows), len(ma_rows))

    return AccuracySnapshot(
        window_days=days if days is not None else 0,
        total_predictions=len(predictions),
        verified_predictions=len(verified),
        correct_predictions=len(correct),
        overall_accuracy=overall,
        accuracy_by_direction=accuracy_by_direction,
        accuracy_by_confidence=confidence_buckets,
        current_streak=streak_current,
        longest_streak=longest,
        last_updated=last_updated,
        recent_miss_pattern=pattern,
        baseline_persistence_accuracy=baseline_persistence_accuracy,
        baseline_ma_accuracy=baseline_ma_accuracy,
        baseline_verified_count=baseline_verified_count,
    )


def compute_calibration_buckets(
    window: str = "30d",
    n_buckets: int = 5,
    *,
    before_date: str | None = None,
    data_origins: Iterable[str] | None = None,
) -> list[CalibrationBucket]:
    _, days = _resolve_window(window)
    predictions = get_daily_predictions(days, before_date=before_date, data_origins=data_origins)
    verified = [p for p in predictions if p.verified_correct is not None and p.tomorrow_confidence is not None]
    if not verified:
        return []

    edges = [i / n_buckets for i in range(n_buckets + 1)]
    buckets: list[CalibrationBucket] = []
    for i in range(n_buckets):
        low, high = edges[i], edges[i + 1]
        in_bucket = [
            p for p in verified
            if (p.tomorrow_confidence is not None
                and (low <= p.tomorrow_confidence < high or (i == n_buckets - 1 and p.tomorrow_confidence == high)))
        ]
        if not in_bucket:
            continue
        hits = sum(1 for p in in_bucket if p.verified_correct)
        buckets.append(CalibrationBucket(
            bucket_low=round(low, 2),
            bucket_high=round(high, 2),
            sample_size=len(in_bucket),
            correct_count=hits,
            hit_rate=round(hits / len(in_bucket), 4),
        ))
    return buckets


def update_daily_metrics(
    prediction_date: str,
    *,
    brier: float | None,
    log_loss: float | None,
    regime: RegimeLabel | None,
) -> bool:
    """Persist Phase 1 per-row metrics. Touches only metrics columns; never alters
    verified_* fields (verifier owns those)."""
    init_storage()
    with closing(_connect()) as connection:
        cursor = connection.execute(
            """
            UPDATE daily_predictions
               SET brier_score = ?,
                   log_loss = ?,
                   regime_label = ?
             WHERE prediction_date = ?
            """,
            (
                brier,
                log_loss,
                regime.value if regime else None,
                prediction_date,
            ),
        )
        connection.commit()
    return cursor.rowcount > 0


_PSEUDO_PROB_SOURCES = frozenset(
    {"reconstructed", "synthetic_backtest", "synthetic_backtest_v1", "mock"}
)


def compute_accuracy_v2(
    window: str = "30d",
    include_reconstructed: bool = False,
    include_synthetic: bool = False,
    include_synthetic_v1: bool = False,
    include_raw: bool = False,
    *,
    before_date: str | None = None,
    data_origins: Iterable[str] | None = None,
) -> AccuracyMetricsV2:
    """Phase 1 metrics: v1 fields + multiclass Brier + log-loss + ECE + regime stratification.

    By default excludes pseudo prob_sources ('reconstructed' + 'synthetic_backtest' + 'synthetic_backtest_v1')
    so headline metrics reflect real production-model performance. Each pseudo source
    can be opted back in independently:

    - ``include_reconstructed``  — heuristically rebuilt prob triples from confidence + direction
    - ``include_synthetic``      — current Phase 2 backtest rows (prompt v3, full macro+tech)
    - ``include_synthetic_v1``   — legacy Phase 1.5 backtest rows (prompt v2, no macro/tech)

    Mixing v1 + v2 conflates feature-set differences and is rarely useful for
    headline metrics; the flag is kept for ad-hoc historical comparisons.
    """
    excluded = set(_PSEUDO_PROB_SOURCES)
    if include_reconstructed:
        excluded.discard("reconstructed")
    if include_synthetic:
        excluded.discard("synthetic_backtest")
    if include_synthetic_v1:
        excluded.discard("synthetic_backtest_v1")
    from chains.metrics import (
        brier_multiclass,
        log_loss as log_loss_fn,
        expected_calibration_error,
        reliability_diagram,
    )

    base = compute_accuracy(window, before_date=before_date, data_origins=data_origins)
    _, days = _resolve_window(window)
    predictions = get_daily_predictions(days, before_date=before_date, data_origins=data_origins)
    verified_all = [p for p in predictions if p.verified_correct is not None]

    sample_count_by_source: dict[str, int] = {}
    for p in verified_all:
        sample_count_by_source[p.prob_source] = sample_count_by_source.get(p.prob_source, 0) + 1

    verified = [p for p in verified_all if p.prob_source not in excluded]

    has_full_probs = [
        p for p in verified
        if p.prob_up is not None and p.prob_down is not None and p.prob_flat is not None
        and p.verified_actual_direction is not None
    ]

    brier_values: list[float] = []
    ll_values: list[float] = []
    for p in has_full_probs:
        b = brier_multiclass(p.prob_up, p.prob_down, p.prob_flat, p.verified_actual_direction)
        l = log_loss_fn(p.prob_up, p.prob_down, p.prob_flat, p.verified_actual_direction)
        if b is not None:
            brier_values.append(b)
        if l is not None:
            ll_values.append(l)

    avg_brier = round(sum(brier_values) / len(brier_values), 6) if brier_values else None
    avg_log_loss = round(sum(ll_values) / len(ll_values), 6) if ll_values else None

    ece = expected_calibration_error(verified, n_bins=5) if verified else None
    diagram = reliability_diagram(verified, n_bins=5) if verified else []

    accuracy_by_regime: dict[str, float] = {}
    brier_by_regime: dict[str, float] = {}
    by_regime: dict[str, list[DailyPrediction]] = {}
    for p in verified:
        key = p.regime_label.value if p.regime_label else "unlabeled"
        by_regime.setdefault(key, []).append(p)
    for key, group in by_regime.items():
        if not group:
            continue
        hits = sum(1 for p in group if p.verified_correct)
        accuracy_by_regime[key] = round(hits / len(group), 4)
        brier_in_group = [p.brier_score for p in group if p.brier_score is not None]
        if brier_in_group:
            brier_by_regime[key] = round(sum(brier_in_group) / len(brier_in_group), 6)

    raw_summary: RawProbSummary | None = None
    if include_raw:
        raw_eligible = [
            p for p in verified
            if p.prob_up_raw is not None
            and p.prob_down_raw is not None
            and p.prob_flat_raw is not None
            and p.verified_actual_direction is not None
        ]
        raw_briers: list[float] = []
        raw_lls: list[float] = []
        raw_confidences: list[tuple[float, bool]] = []
        raw_correct = 0
        for p in raw_eligible:
            up_r, dn_r, fl_r = p.prob_up_raw, p.prob_down_raw, p.prob_flat_raw
            b = brier_multiclass(up_r, dn_r, fl_r, p.verified_actual_direction)
            ll = log_loss_fn(up_r, dn_r, fl_r, p.verified_actual_direction)
            if b is not None:
                raw_briers.append(b)
            if ll is not None:
                raw_lls.append(ll)
            triple = {Trend.UP: up_r, Trend.DOWN: dn_r, Trend.FLAT: fl_r}
            raw_direction = max(triple, key=triple.get)
            hit = raw_direction == p.verified_actual_direction
            if hit:
                raw_correct += 1
            raw_confidences.append((triple[raw_direction], hit))

        raw_n = len(raw_eligible)
        raw_ece: float | None = None
        if raw_confidences:
            n_bins = 5
            edges = [i / n_bins for i in range(n_bins + 1)]
            weighted_gap = 0.0
            for i in range(n_bins):
                lo, hi = edges[i], edges[i + 1]
                bucket = [
                    (c, h) for c, h in raw_confidences
                    if (lo <= c < hi or (i == n_bins - 1 and c == hi))
                ]
                if not bucket:
                    continue
                avg_conf = sum(c for c, _ in bucket) / len(bucket)
                hit_rate = sum(1 for _, h in bucket if h) / len(bucket)
                weighted_gap += (len(bucket) / raw_n) * abs(avg_conf - hit_rate)
            raw_ece = round(weighted_gap, 6)

        raw_summary = RawProbSummary(
            sample_size=raw_n,
            brier_multiclass=(
                round(sum(raw_briers) / len(raw_briers), 6) if raw_briers else None
            ),
            log_loss=(
                round(sum(raw_lls) / len(raw_lls), 6) if raw_lls else None
            ),
            ece=raw_ece,
            accuracy=round(raw_correct / raw_n, 4) if raw_n else None,
        )

    return AccuracyMetricsV2(
        window_days=base.window_days,
        total_predictions=base.total_predictions,
        verified_predictions=len(verified),
        correct_predictions=sum(1 for p in verified if p.verified_correct),
        overall_accuracy=(
            round(sum(1 for p in verified if p.verified_correct) / len(verified), 4)
            if verified else 0.0
        ),
        accuracy_by_direction=base.accuracy_by_direction,
        accuracy_by_confidence=base.accuracy_by_confidence,
        current_streak=base.current_streak,
        longest_streak=base.longest_streak,
        last_updated=base.last_updated,
        recent_miss_pattern=base.recent_miss_pattern,
        brier_multiclass=avg_brier,
        log_loss=avg_log_loss,
        ece=ece,
        accuracy_by_regime=accuracy_by_regime,
        brier_by_regime=brier_by_regime,
        reliability_diagram=diagram,
        sample_count_by_source=sample_count_by_source,
        excluded_reconstructed=("reconstructed" in excluded),
        excluded_synthetic=(
            "synthetic_backtest" in excluded and "synthetic_backtest_v1" in excluded
        ),
        raw_summary=raw_summary,
    )


def update_record_outcome(
    record_id: str,
    actual_close: float,
    actual_direction: Trend,
    correct: bool,
) -> bool:
    init_storage()
    verified_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with closing(_connect()) as connection:
        cursor = connection.execute(
            """
            UPDATE analysis_records
            SET outcome_close = ?,
                outcome_direction = ?,
                outcome_correct = ?,
                verified_at = ?
            WHERE id = ?
            """,
            (
                actual_close,
                actual_direction.value,
                int(correct),
                verified_at,
                record_id,
            ),
        )
        connection.commit()
    return cursor.rowcount > 0


def get_records_for_date(predicted_for_date: str) -> list[AnalysisRecord]:
    init_storage()
    with closing(_connect()) as connection:
        rows = connection.execute(
            "SELECT * FROM analysis_records WHERE predicted_for_date = ?",
            (predicted_for_date,),
        ).fetchall()
    return [_row_to_record(row) for row in rows]


# =========================================================================
# Chat sessions / messages
# =========================================================================

def _row_to_session(row: sqlite3.Row) -> ChatSession:
    return ChatSession(
        id=row["id"],
        client_id=row["client_id"],
        title=row["title"] or "新对话",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        message_count=row["message_count"] or 0,
        archived=bool(row["archived"]),
    )


def _row_to_chat_message(row: sqlite3.Row) -> ChatMessage:
    return ChatMessage(
        id=row["id"],
        session_id=row["session_id"],
        role=ChatRole(row["role"]) if row["role"] in {r.value for r in ChatRole} else ChatRole.USER,
        content=row["content"] or "",
        created_at=row["created_at"],
    )


# 多租户隔离(2026-05-26):chat_sessions.client_id 列此后存放 **user_id**(登录用户 id)。
# 所有 chat 按 user_id 严格隔离;A 租户拿 B 的 session_id 也查不到(下方 WHERE 双条件)。
# 历史上按浏览器随机 client_id 存的会话,因与任何 user_id 都对不上,自动隐身(作废)。
def create_chat_session(session_id: str, user_id: str, title: str = "新对话") -> ChatSession:
    init_storage()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with closing(_connect()) as connection:
        connection.execute(
            "INSERT INTO chat_sessions (id, client_id, title, created_at, updated_at, message_count, archived) "
            "VALUES (?, ?, ?, ?, ?, 0, 0)",
            (session_id, user_id, title, now, now),
        )
        connection.commit()
    return ChatSession(
        id=session_id, client_id=user_id, title=title,
        created_at=now, updated_at=now, message_count=0, archived=False,
    )


def list_chat_sessions(user_id: str, include_archived: bool = False) -> list[ChatSession]:
    init_storage()
    with closing(_connect()) as connection:
        if include_archived:
            rows = connection.execute(
                "SELECT * FROM chat_sessions WHERE client_id = ? ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM chat_sessions WHERE client_id = ? AND archived = 0 ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
    return [_row_to_session(row) for row in rows]


def get_chat_session(session_id: str, user_id: str) -> ChatSession | None:
    """Returns the session only if (id, user_id) match — guards cross-tenant IDOR."""
    init_storage()
    with closing(_connect()) as connection:
        row = connection.execute(
            "SELECT * FROM chat_sessions WHERE id = ? AND client_id = ?",
            (session_id, user_id),
        ).fetchone()
    return _row_to_session(row) if row else None


def archive_chat_session(session_id: str, user_id: str) -> bool:
    init_storage()
    with closing(_connect()) as connection:
        cursor = connection.execute(
            "UPDATE chat_sessions SET archived = 1, updated_at = ? WHERE id = ? AND client_id = ?",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), session_id, user_id),
        )
        connection.commit()
    return cursor.rowcount > 0


def update_chat_session_title(session_id: str, user_id: str, title: str) -> bool:
    init_storage()
    with closing(_connect()) as connection:
        cursor = connection.execute(
            "UPDATE chat_sessions SET title = ?, updated_at = ? WHERE id = ? AND client_id = ?",
            (title[:64], datetime.now().strftime("%Y-%m-%d %H:%M:%S"), session_id, user_id),
        )
        connection.commit()
    return cursor.rowcount > 0


def list_chat_messages(session_id: str, user_id: str, limit: int = 200) -> list[ChatMessage]:
    """Returns messages for the session — only if user_id owns it."""
    init_storage()
    if not get_chat_session(session_id, user_id):
        return []
    with closing(_connect()) as connection:
        # rowid is sqlite's monotonic insertion sequence — guarantees user/assistant
        # pair stays ordered even when both rows land in the same second.
        rows = connection.execute(
            "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at ASC, rowid ASC LIMIT ?",
            (session_id, max(1, min(limit, 1000))),
        ).fetchall()
    return [_row_to_chat_message(row) for row in rows]


def append_chat_message(
    *,
    message_id: str,
    session_id: str,
    role: ChatRole,
    content: str,
) -> ChatMessage:
    init_storage()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Atomic: both inserts/updates land or roll back together.
    with closing(_connect()) as connection:
        with connection:
            connection.execute(
                "INSERT INTO chat_messages (id, session_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
                (message_id, session_id, role.value, content, now),
            )
            connection.execute(
                "UPDATE chat_sessions SET message_count = message_count + 1, updated_at = ? WHERE id = ?",
                (now, session_id),
            )
    return ChatMessage(id=message_id, session_id=session_id, role=role, content=content, created_at=now)


def count_chat_messages(session_id: str) -> int:
    init_storage()
    with closing(_connect()) as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS c FROM chat_messages WHERE session_id = ?", (session_id,),
        ).fetchone()
    return int(row["c"] or 0) if row else 0
