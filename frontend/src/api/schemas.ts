// Mirror of backend Pydantic models — keep manually in sync until codegen.

export type Trend = "上涨" | "下跌" | "震荡" | "未知";
export type AnalysisStatus = "success" | "partial" | "failed";
export type CloseSourceStatus = "both" | "sge_only" | "comex_only" | "neither";

export interface NewsItem {
  title: string;
  link: string | null;
  source: string;
  published_at: string | null;
}

export interface AnalysisRecord {
  id: string;
  time: string;
  source: string;
  status: AnalysisStatus;
  price_raw: string;
  price_value: number | null;
  news: NewsItem[];
  summary: string;
  trend: Trend;
  reasons: string[];
  advice: string;
  raw_output: string;
  model_name: string;
  prompt_version: string;
  latency_ms: number;
  error: string | null;
  input_snapshot: Record<string, unknown>;
  confidence: number | null;
  news_count: number;
  usd_index: number | null;
  predicted_for_date: string | null;
  outcome_close: number | null;
  outcome_direction: Trend | null;
  outcome_correct: boolean | null;
  verified_at: string | null;
}

export interface TimeSeriesPoint {
  id: string;
  time: string;
  price: number | null;
  trend: Trend;
  status: AnalysisStatus;
  summary: string;
  confidence: number | null;
  source: string;
  model_name: string;
}

export interface DistributionSnapshot {
  range?: string;
  trend_counts: Record<string, number>;
  status_counts: Record<string, number>;
  hourly_status: Array<Record<string, number | string>>;
  total_records: number;
}

export interface KPISummary {
  range: string;
  total_runs: number;
  success_rate: number;
  avg_latency_ms: number;
  avg_price: number | null;
  min_price: number | null;
  max_price: number | null;
  volatility: number | null;
  latest_price: number | null;
  latest_trend: Trend;
  last_updated: string | null;
}

export type RegimeLabel = "bull" | "bear" | "choppy" | "transition" | "unknown";

export interface DailyPrediction {
  id: string;
  predicted_at: string;
  prediction_date: string;
  today_close_sge: number | null;
  today_close_comex: number | null;
  today_close_source: CloseSourceStatus;
  today_direction: Trend;
  tomorrow_direction: Trend;
  tomorrow_confidence: number | null;
  prob_up: number | null;
  prob_down: number | null;
  prob_flat: number | null;
  prob_source: string;
  regime_label: RegimeLabel | null;
  brier_score: number | null;
  log_loss: number | null;
  // Phase 2 macro + technical features
  dxy_value: number | null;
  dxy_5d_change_pct: number | null;
  us10y_real_yield: number | null;
  us10y_5d_change_pct: number | null;
  atr14: number | null;
  rsi14: number | null;
  dist_ma20_z: number | null;
  baseline_persistence_direction: Trend | null;
  baseline_persistence_correct: boolean | null;
  baseline_ma_direction: Trend | null;
  baseline_ma_correct: boolean | null;
  baseline_anchor_source: string | null;
  tomorrow_advice: string;
  reasoning_summary: string;
  risk_factors: string[];
  calibration_note: string;
  prompt_version: string;
  model_name: string;
  accuracy_window_30d: number | null;
  raw_output: string;
  error: string | null;
  verified_at: string | null;
  verified_actual_close: number | null;
  verified_actual_direction: Trend | null;
  verified_correct: boolean | null;
  data_origin: "live" | "backtest_no_news" | "placeholder_legacy";
  is_today?: boolean;
}

export interface CalibrationBucket {
  bucket_low: number;
  bucket_high: number;
  sample_size: number;
  correct_count: number;
  hit_rate: number;
}

export interface AccuracySnapshot {
  window_days: number;
  total_predictions: number;
  verified_predictions: number;
  correct_predictions: number;
  overall_accuracy: number;
  accuracy_by_direction: Record<string, number>;
  accuracy_by_confidence: CalibrationBucket[];
  current_streak: number;
  longest_streak: number;
  last_updated: string | null;
  recent_miss_pattern: string;
  baseline_persistence_accuracy: number | null;
  baseline_ma_accuracy: number | null;
  baseline_verified_count: number;
}

export interface ReliabilityBin {
  bucket_low: number;
  bucket_high: number;
  sample_size: number;
  avg_confidence: number;
  hit_rate: number;
}

export interface RawProbSummary {
  sample_size: number;
  brier_multiclass: number | null;
  log_loss: number | null;
  ece: number | null;
  accuracy: number | null;
}

export interface AccuracyMetricsV2 extends AccuracySnapshot {
  brier_multiclass: number | null;
  log_loss: number | null;
  ece: number | null;
  accuracy_by_regime: Record<string, number>;
  brier_by_regime: Record<string, number>;
  reliability_diagram: ReliabilityBin[];
  sample_count_by_source: Record<string, number>;
  excluded_reconstructed: boolean;
  excluded_synthetic: boolean;
  raw_summary: RawProbSummary | null;
}

export interface ChannelStatus {
  configured: string[];
  available: string[];
}

export interface SkillAuditEntry {
  date: string;
  bytes?: number;  // admin/localhost only — public response strips this
  has_change: boolean;
}

export interface SkillAuditSummary {
  last_change_date: string | null;
  days_since_last_change: number | null;
  audits_in_window: number;
  nonempty_in_window: number;
  hint_count: number;
  most_recent: SkillAuditEntry[];
  error: string | null;
}

export type ChatRole = "user" | "assistant" | "system";

export interface ChatMessage {
  id: string;
  session_id: string;
  role: ChatRole;
  content: string;
  created_at: string;
}

export interface ChatSession {
  id: string;
  client_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  archived: boolean;
}

export interface ChatGreeting {
  market_summary: string;
  latest_prediction: DailyPrediction | null;
  suggested_questions: string[];
  opening_message: string;
}

export interface SuccessEnvelope<T> {
  success: true;
  data: T;
  error: null;
}
export interface ErrorEnvelope {
  success: false;
  data: null;
  error: string;
}
export type Envelope<T> = SuccessEnvelope<T> | ErrorEnvelope;
