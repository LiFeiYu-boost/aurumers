from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class Trend(str, Enum):
    UP = "上涨"
    DOWN = "下跌"
    FLAT = "震荡"
    UNKNOWN = "未知"


class AnalysisStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class NewsItem(BaseModel):
    title: str
    link: str | None = None
    source: str = "unknown"
    published_at: str | None = None


class AnalysisInput(BaseModel):
    price_raw: str = "N/A"
    price_value: float | None = None
    news: list[NewsItem] = Field(default_factory=list)
    source: str = "manual"
    generated_at: datetime = Field(default_factory=datetime.now)


class AnalysisLLMOutput(BaseModel):
    summary: str = "暂无总结"
    trend: Trend = Trend.UNKNOWN
    reasons: list[str] = Field(default_factory=list)
    advice: str = "暂无建议"
    confidence: float | None = None

    @field_validator("summary", "advice", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("reasons", mode="before")
    @classmethod
    def normalize_reasons(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [item.strip("- ").strip() for item in value.splitlines() if item.strip()][:3]
        return [str(item).strip() for item in value if str(item).strip()][:3]

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, value: Any) -> float | None:
        if value is None or value == "" or isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if number < 0:
            return 0.0
        if number > 1:
            return 1.0
        return round(number, 4)


class AnalysisRecord(BaseModel):
    id: str
    time: str
    source: str
    status: AnalysisStatus
    price_raw: str = "N/A"
    price_value: float | None = None
    news: list[NewsItem] = Field(default_factory=list)
    summary: str = "暂无总结"
    trend: Trend = Trend.UNKNOWN
    reasons: list[str] = Field(default_factory=list)
    advice: str = "暂无建议"
    raw_output: str = ""
    model_name: str = ""
    prompt_version: str = ""
    latency_ms: int = 0
    error: str | None = None
    input_snapshot: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = None
    news_count: int = 0
    usd_index: float | None = None
    predicted_for_date: str | None = None
    outcome_close: float | None = None
    outcome_direction: Trend | None = None
    outcome_correct: bool | None = None
    verified_at: str | None = None


class PricePoint(BaseModel):
    time: str
    price: float | None = None
    trend: Trend = Trend.UNKNOWN


class DashboardSummary(BaseModel):
    latest: AnalysisRecord | None = None
    price_points: list[PricePoint] = Field(default_factory=list)
    trend_counts: dict[str, int] = Field(default_factory=dict)
    status_counts: dict[str, int] = Field(default_factory=dict)
    total_records: int = 0


class TimeSeriesPoint(BaseModel):
    id: str
    time: str
    price: float | None = None
    trend: Trend = Trend.UNKNOWN
    status: AnalysisStatus = AnalysisStatus.FAILED
    summary: str = ""
    confidence: float | None = None
    source: str = ""
    model_name: str = ""


class DistributionSnapshot(BaseModel):
    trend_counts: dict[str, int] = Field(default_factory=dict)
    status_counts: dict[str, int] = Field(default_factory=dict)
    hourly_status: list[dict[str, Any]] = Field(default_factory=list)
    total_records: int = 0


class KPISummary(BaseModel):
    range: str = "24h"
    total_runs: int = 0
    success_rate: float = 0.0
    avg_latency_ms: float = 0.0
    avg_price: float | None = None
    min_price: float | None = None
    max_price: float | None = None
    volatility: float | None = None
    latest_price: float | None = None
    latest_trend: Trend = Trend.UNKNOWN
    last_updated: str | None = None


class CloseSourceStatus(str, Enum):
    BOTH = "both"
    SGE_ONLY = "sge_only"
    COMEX_ONLY = "comex_only"
    NEITHER = "neither"


class RegimeLabel(str, Enum):
    BULL = "bull"
    BEAR = "bear"
    CHOPPY = "choppy"
    TRANSITION = "transition"
    UNKNOWN = "unknown"


class DailyPrediction(BaseModel):
    id: str
    predicted_at: str
    prediction_date: str
    today_close_sge: float | None = None
    today_close_comex: float | None = None
    today_close_source: CloseSourceStatus = CloseSourceStatus.NEITHER
    today_direction: Trend = Trend.UNKNOWN
    tomorrow_direction: Trend = Trend.UNKNOWN
    tomorrow_confidence: float | None = None
    prob_up: float | None = None
    prob_down: float | None = None
    prob_flat: float | None = None
    prob_source: str = "model"
    # Raw model output preserved before post-processing (calibration + gates).
    # When present, prob_up/prob_down/prob_flat hold the post-processed values
    # actually used for the headline direction call and downstream metrics.
    prob_up_raw: float | None = None
    prob_down_raw: float | None = None
    prob_flat_raw: float | None = None
    trend_gate_decision: str | None = None
    flat_gate_fired: list[str] = Field(default_factory=list)
    calibrator_version: str | None = None
    calibrator_status: str | None = None
    calibrator_scales: dict[str, Any] | None = None
    regime_label: RegimeLabel | None = None
    brier_score: float | None = None
    log_loss: float | None = None
    dxy_value: float | None = None
    dxy_5d_change_pct: float | None = None
    us10y_real_yield: float | None = None
    us10y_5d_change_pct: float | None = None
    atr14: float | None = None
    rsi14: float | None = None
    dist_ma20_z: float | None = None
    # Baseline parallel predictions — same direction calls computed at predict
    # time without any LLM input, verified alongside the model so we can compare
    # honestly. persistence = yesterday's actual direction; ma = today vs MA(5).
    baseline_persistence_direction: Trend | None = None
    baseline_persistence_correct: bool | None = None
    baseline_ma_direction: Trend | None = None
    baseline_ma_correct: bool | None = None
    # Pins the market (sge / comex) the baselines were computed against, so
    # the verifier compares apples-to-apples even on dual-source days.
    baseline_anchor_source: str | None = None
    tomorrow_advice: str = ""
    reasoning_summary: str = ""
    risk_factors: list[str] = Field(default_factory=list)
    calibration_note: str = ""
    prompt_version: str = ""
    model_name: str = ""
    accuracy_window_30d: float | None = None
    raw_output: str = ""
    error: str | None = None
    verified_at: str | None = None
    verified_actual_close: float | None = None
    verified_actual_direction: Trend | None = None
    verified_correct: bool | None = None
    # Provenance tag. 'live' = real-time prediction with full news context;
    # 'backtest_no_news' = historical replay where news was deliberately
    # skipped to avoid lookahead; 'placeholder_legacy' = pre-Phase-A rows
    # that default to '震荡' and should be excluded from honest metrics.
    data_origin: str = "live"

    @field_validator(
        "tomorrow_confidence",
        "prob_up", "prob_down", "prob_flat",
        "prob_up_raw", "prob_down_raw", "prob_flat_raw",
        mode="before",
    )
    @classmethod
    def _clamp_unit_interval(cls, value: Any) -> float | None:
        if value is None or value == "" or isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return max(0.0, min(1.0, round(number, 4)))

    @field_validator("prob_source", mode="before")
    @classmethod
    def _normalize_prob_source(cls, value: Any) -> str:
        text = str(value or "").strip().lower()
        return text if text in {"model", "reconstructed", "synthetic_backtest", "synthetic_backtest_v1", "mock"} else "model"

    @model_validator(mode="after")
    def _validate_prob_triple(self) -> "DailyPrediction":
        triple = (self.prob_up, self.prob_down, self.prob_flat)
        present = [v for v in triple if v is not None]
        if not present:
            return self
        if len(present) < 3:
            self.prob_up = self.prob_down = self.prob_flat = None
            return self
        total = sum(present)
        if total <= 0 or not (0.5 <= total <= 1.5):
            self.prob_up = self.prob_down = self.prob_flat = None
            return self
        self.prob_up = round(self.prob_up / total, 4)
        self.prob_down = round(self.prob_down / total, 4)
        self.prob_flat = round(self.prob_flat / total, 4)
        return self


class CalibrationBucket(BaseModel):
    bucket_low: float
    bucket_high: float
    sample_size: int
    correct_count: int
    hit_rate: float


class AccuracySnapshot(BaseModel):
    window_days: int
    total_predictions: int
    verified_predictions: int
    correct_predictions: int
    overall_accuracy: float
    accuracy_by_direction: dict[str, float] = Field(default_factory=dict)
    accuracy_by_confidence: list[CalibrationBucket] = Field(default_factory=list)
    current_streak: int = 0
    longest_streak: int = 0
    last_updated: str | None = None
    recent_miss_pattern: str = ""
    # Falsifiability baselines — same window, same denominator. Null when no
    # verified baseline rows exist yet (early days / pre-baseline schema rows).
    baseline_persistence_accuracy: float | None = None
    baseline_ma_accuracy: float | None = None
    baseline_verified_count: int = 0


class ReliabilityBin(BaseModel):
    bucket_low: float
    bucket_high: float
    sample_size: int
    avg_confidence: float
    hit_rate: float


class RawProbSummary(BaseModel):
    """Headline metrics recomputed from the model's raw (pre-calibration) triple.

    Surfaced only when the metrics endpoint is called with ``include_raw=true``;
    intended for A/B comparison panels in the Insights view, not the default
    runtime path. ``sample_size`` may be lower than the v2 ``verified_predictions``
    if older rows pre-date the prob_*_raw columns.
    """
    sample_size: int = 0
    brier_multiclass: float | None = None
    log_loss: float | None = None
    ece: float | None = None
    accuracy: float | None = None


class AccuracyMetricsV2(AccuracySnapshot):
    """Phase 1 extension of AccuracySnapshot with multiclass scoring + regime stratification.

    Inherits all v1 fields so frontends still using v1 schema continue to work
    when handed a v2 object.
    """
    brier_multiclass: float | None = None
    log_loss: float | None = None
    ece: float | None = None
    accuracy_by_regime: dict[str, float] = Field(default_factory=dict)
    brier_by_regime: dict[str, float] = Field(default_factory=dict)
    reliability_diagram: list[ReliabilityBin] = Field(default_factory=list)
    sample_count_by_source: dict[str, int] = Field(default_factory=dict)
    excluded_reconstructed: bool = True
    excluded_synthetic: bool = True
    raw_summary: RawProbSummary | None = None


class BroadcastEvent(BaseModel):
    type: str
    title: str
    body: str
    payload: dict[str, Any] = Field(default_factory=dict)
    severity: str = "info"
    occurred_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


class ChatRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatMessage(BaseModel):
    id: str
    session_id: str
    role: ChatRole
    content: str
    created_at: str


class ChatSession(BaseModel):
    id: str
    client_id: str
    title: str = "新对话"
    created_at: str
    updated_at: str
    message_count: int = 0
    archived: bool = False


class ChatGreeting(BaseModel):
    market_summary: str
    latest_prediction: DailyPrediction | None = None
    suggested_questions: list[str] = Field(default_factory=list)
    opening_message: str
