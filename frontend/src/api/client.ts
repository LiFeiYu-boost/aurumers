import type {
  AccuracyMetricsV2,
  AccuracySnapshot,
  AnalysisRecord,
  CalibrationBucket,
  ChannelStatus,
  ChatGreeting,
  ChatMessage,
  ChatSession,
  DailyPrediction,
  DistributionSnapshot,
  Envelope,
  KPISummary,
  SkillAuditSummary,
  TimeSeriesPoint,
} from "./schemas";

export interface AuthUser {
  id: string;
  username: string;
  role: string;
  status: string;
  balance_cents: number;
  daily_free_cents: number | null;
  created_at: string;
  today_cost_cents?: number;
  daily_free_limit_cents?: number;
  free_remaining_cents?: number;
}

class ApiError extends Error {
  constructor(message: string, public status?: number) {
    super(message);
    this.name = "ApiError";
  }
}

function _readAdminToken(): string | null {
  try {
    const value = localStorage.getItem("aurumers.adminToken");
    return value && value.trim() ? value.trim() : null;
  } catch {
    return null;
  }
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  attempts = 1,
): Promise<T> {
  let lastError: unknown;
  for (let i = 0; i < attempts; i += 1) {
    try {
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
        ...((init.headers || {}) as Record<string, string>),
      };
      const token = _readAdminToken();
      if (token && !headers["X-Admin-Token"]) {
        headers["X-Admin-Token"] = token;
      }
      const response = await fetch(path, {
        ...init,
        headers,
      });
      let body: Envelope<T> | null = null;
      try {
        body = (await response.json()) as Envelope<T>;
      } catch {
        body = null;
      }
      if (!response.ok) {
        const detail = body && "error" in body && body.error
          ? body.error
          : `HTTP ${response.status}`;
        throw new ApiError(detail, response.status);
      }
      if (!body || body.success === false) {
        throw new ApiError(
          body && "error" in body && body.error ? body.error : "请求失败",
          response.status,
        );
      }
      return body.data;
    } catch (error) {
      lastError = error;
      if (i === attempts - 1) break;
      await new Promise((r) => setTimeout(r, 200 * (i + 1)));
    }
  }
  throw lastError instanceof Error ? lastError : new ApiError("请求失败");
}

export const api = {
  // Auth / 用户体系 (task #62) — 同源 fetch 自动携带会话 cookie
  auth: {
    register: (username: string, password: string) =>
      request<AuthUser>("/api/auth/register", { method: "POST", body: JSON.stringify({ username, password }) }),
    login: (username: string, password: string) =>
      request<AuthUser>("/api/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
    logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
    me: () => request<AuthUser>("/api/auth/me"),
  },

  // 钱包 (task #62 阶段4)
  wallet: {
    info: () => request<{ balance_cents: number; today_cost_cents: number; daily_free_limit_cents: number; free_remaining_cents: number }>("/api/wallet"),
    redeem: (code: string) =>
      request<{ added_cents: number; balance_cents: number }>("/api/wallet/redeem", { method: "POST", body: JSON.stringify({ code }) }),
  },

  // 管理后台 (task #62 阶段5)
  admin: {
    users: () => request<AuthUser[]>("/api/admin/users"),
    updateUser: (id: string, fields: Record<string, unknown>) =>
      request<AuthUser>(`/api/admin/users/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(fields) }),
    listCodes: () => request<Array<{ code: string; cents: number; used_by: string | null; created_at: string }>>("/api/admin/codes"),
    createCodes: (cents: number, count: number) =>
      request<{ codes: string[]; cents: number }>("/api/admin/codes", { method: "POST", body: JSON.stringify({ cents, count }) }),
  },

  // Live spot price + market state (huilvbiao mirror)
  price: () => request<{
    price_raw: string;
    price_value: number | null;
    data_timestamp: string | null;
    data_label: string | null;
    comex_open: boolean | null;
    sge_open: boolean | null;
    fetched_at: string;
  }>("/api/price"),

  // Analysis pipeline
  runAnalysis: () => request<AnalysisRecord>("/api/analysis/run", { method: "POST" }, 1),

  records: () => request<AnalysisRecord[]>("/api/records"),
  recordsLatest: (n = 30) => request<AnalysisRecord[]>(`/api/records/latest?n=${n}`),
  deleteRecord: (id: string) => request<{ message: string }>(`/api/records/${encodeURIComponent(id)}`, { method: "DELETE" }),

  // Analytics
  timeseries: (range = "24h") => request<{ range: string; points: TimeSeriesPoint[] }>(`/api/analytics/timeseries?range=${range}`),
  distribution: (range = "24h") => request<DistributionSnapshot>(`/api/analytics/distribution?range=${range}`),
  kpis: (range = "24h") => request<KPISummary>(`/api/analytics/kpis?range=${range}`),
  dashboard: (limit = 24) => request<any>(`/api/dashboard/summary?limit=${limit}`),

  // Predictions
  runDaily: (date?: string) => request<DailyPrediction>(`/api/predictions/daily/run${date ? `?date=${date}` : ""}`, { method: "POST" }),
  verifyDaily: (date?: string) => request<{ prediction: DailyPrediction; verified: boolean }>(`/api/predictions/daily/verify${date ? `?date=${date}` : ""}`, { method: "POST" }),
  todayPrediction: () => request<DailyPrediction | null>("/api/predictions/today"),
  dailyPredictions: (range = "30d", includeBacktest = false) =>
    request<{ range: string; items: DailyPrediction[] }>(
      `/api/predictions/daily?range=${range}&include_backtest=${includeBacktest}`,
    ),
  accuracy: (window = "30d", includeBacktest = false) =>
    request<AccuracySnapshot>(
      `/api/predictions/accuracy?window=${window}&include_backtest=${includeBacktest}`,
    ),
  calibration: (window = "30d", buckets = 5, includeBacktest = false) =>
    request<CalibrationBucket[]>(
      `/api/predictions/calibration?window=${window}&buckets=${buckets}&include_backtest=${includeBacktest}`,
    ),
  metricsDetailed: (
    window = "90d",
    includeSynthetic = true,
    includeSyntheticV1 = false,
    includeReconstructed = false,
    includeRaw = false,
    includeBacktest = false,
  ) =>
    request<AccuracyMetricsV2>(
      `/api/predictions/metrics/detailed?window=${window}` +
        `&include_synthetic=${includeSynthetic}` +
        `&include_synthetic_v1=${includeSyntheticV1}` +
        `&include_reconstructed=${includeReconstructed}` +
        `&include_raw=${includeRaw}` +
        `&include_backtest=${includeBacktest}`,
    ),

  // Skill self-evolution audit
  skillAudit: (windowDays = 30, recentN = 7) =>
    request<SkillAuditSummary>(`/api/skill_audit/recent?window_days=${windowDays}&recent_n=${recentN}`),

  // Notifications
  channels: () => request<ChannelStatus>("/api/notifications/channels"),
  testNotification: (token: string) => request<{ results: Record<string, boolean> }>("/api/notifications/test", {
    method: "POST",
    headers: { "X-Admin-Token": token },
  }),

  // Hermes chat
  chat: {
    greeting: () => request<ChatGreeting>("/api/chat/greeting"),
    // 多租户:chat 不再传 client_id,后端按登录会话(同源 cookie)的 user_id 隔离。
    listSessions: () => request<ChatSession[]>("/api/chat/sessions"),
    createSession: (title?: string) =>
      request<ChatSession>("/api/chat/sessions", {
        method: "POST",
        body: JSON.stringify({ title }),
      }),
    deleteSession: (sessionId: string) =>
      request<{ archived: boolean; session_id: string }>(
        `/api/chat/sessions/${encodeURIComponent(sessionId)}`,
        { method: "DELETE" },
      ),
    listMessages: (sessionId: string) =>
      request<ChatMessage[]>(
        `/api/chat/sessions/${encodeURIComponent(sessionId)}/messages`,
      ),
    streamMessage: async function* (
      sessionId: string,
      content: string,
    ): AsyncGenerator<string, void, void> {
      const url = `/api/chat/sessions/${encodeURIComponent(sessionId)}/message`;
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      });
      if (!response.ok) {
        let detail = `HTTP ${response.status}`;
        try {
          const body = await response.json();
          if (body && typeof body === "object" && "detail" in body) {
            detail = String((body as Record<string, unknown>).detail);
          } else if (body && typeof body === "object" && "error" in body) {
            detail = String((body as Record<string, unknown>).error);
          }
        } catch { /* ignore */ }
        throw new ApiError(detail, response.status);
      }
      const reader = response.body?.getReader();
      if (!reader) return;
      const decoder = new TextDecoder();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        if (value) {
          const text = decoder.decode(value, { stream: true });
          if (text) yield text;
        }
      }
      const tail = decoder.decode();
      if (tail) yield tail;
    },
  },
};

let _cachedClientId: string | null = null;

function _generateClientId(): string {
  try {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID();
    }
  } catch { /* ignore */ }
  return `c_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 12)}_${Math.random().toString(36).slice(2, 10)}`;
}

export function getOrCreateClientId(): string {
  if (_cachedClientId && _cachedClientId.length >= 8 && _cachedClientId.length <= 128) {
    return _cachedClientId;
  }
  try {
    const stored = localStorage.getItem("aurumers.clientId");
    if (stored && stored.length >= 8 && stored.length <= 128) {
      _cachedClientId = stored;
      return stored;
    }
  } catch { /* localStorage disabled — proceed to generation */ }

  const fresh = _generateClientId();
  _cachedClientId = fresh;
  try {
    localStorage.setItem("aurumers.clientId", fresh);
  } catch { /* ignore — keep in-memory */ }
  return fresh;
}

// Server-Sent Events helper
export function subscribeStream(handlers: Partial<Record<string, (payload: unknown) => void>>): () => void {
  if (typeof EventSource === "undefined") return () => undefined;
  const source = new EventSource("/api/stream");
  for (const [type, handler] of Object.entries(handlers)) {
    if (!handler) continue;
    source.addEventListener(type, (ev: MessageEvent) => {
      try {
        const payload = ev.data ? JSON.parse(ev.data) : null;
        handler(payload);
      } catch (err) {
        // ignore malformed
      }
    });
  }
  source.onerror = () => {
    // EventSource auto-reconnects with backoff; nothing to do.
  };
  return () => source.close();
}

export { ApiError };
