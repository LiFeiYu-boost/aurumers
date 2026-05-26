import { api, subscribeStream } from "../api/client";
import { renderPriceChart } from "../charts/priceChart";
import { renderTrendDonut } from "../charts/donut";
import { toast } from "../components/Toast";
import {
  chunkText,
  escapeHtml,
  formatNumber,
  formatPercent,
  formatSource,
  safeUrl,
  setButtonState,
  trendCssClass,
  statusCssClass,
} from "../utils";
import type {
  AccuracySnapshot,
  AnalysisRecord,
  DailyPrediction,
  KPISummary,
  TimeSeriesPoint,
  DistributionSnapshot,
} from "../api/schemas";

// Module-level state lets SSE handlers push a single new point into the chart
// without a full /api/analytics/timeseries re-fetch. loadAll() rewrites these
// on every range change, so SSE-appended points get replaced by server-of-truth
// on the next reload — no permanent drift possible.
let _dashPoints: TimeSeriesPoint[] = [];
let _dashPriceEl: HTMLElement | null = null;

const RANGES = [
  { key: "24h", label: "24 小时" },
  { key: "7d", label: "7 天" },
  { key: "30d", label: "30 天" },
  { key: "all", label: "全部" },
];

const CSS = `
.dash { padding: 28px 0; }
.dash-hero {
  display: grid;
  grid-template-columns: 1.5fr 1fr;
  gap: 24px;
  margin-bottom: 28px;
}
.dash-hero .left h1 {
  margin: 8px 0 12px;
  font-size: clamp(28px, 3.4vw, 40px);
  font-weight: 600;
  letter-spacing: -0.022em;
}
.dash-hero .left p {
  margin: 0 0 22px;
  font-size: 15px;
  color: var(--c-text-soft);
  max-width: 60ch;
  line-height: 1.6;
}
.dash-hero .actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: center;
}
.dash-hero .right {
  display: flex;
  flex-direction: column;
  gap: 12px;
  align-items: flex-start;
  text-align: left;
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  padding: 22px 24px;
  box-shadow: var(--shadow-sm);
}
.dash-hero .right .right-label {
  font-size: 11px;
  color: var(--c-text-mute);
  letter-spacing: 0.12em;
  text-transform: uppercase;
}
.dash-hero .price {
  font-size: clamp(36px, 4vw, 48px);
  font-weight: 600;
  letter-spacing: -0.03em;
  line-height: 1;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}
.dash-hero .price-meta { color: var(--c-text-mute); font-size: 13px; }

.kpi-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; }

.panel-row {
  margin-top: 28px;
  display: grid;
  grid-template-columns: 1.55fr 1fr;
  gap: 20px;
}
.panel {
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  padding: 22px 24px;
  box-shadow: var(--shadow-sm);
}
.panel h2 { margin: 0 0 4px; font-size: 16px; font-weight: 600; letter-spacing: -0.01em; }
.panel p.sub { margin: 0 0 18px; font-size: 13px; color: var(--c-text-mute); }
.chart { width: 100%; height: 320px; }
.chart-mini { width: 100%; height: 240px; }

.detail-block {
  margin-top: 20px;
  display: grid;
  grid-template-columns: 1.55fr 1fr;
  gap: 20px;
}
.detail-summary {
  font-size: 14px;
  color: var(--c-text);
  line-height: 1.7;
}
.detail-meta {
  display: flex;
  gap: 8px;
  margin-top: 8px;
  flex-wrap: wrap;
}
.detail-list { display: flex; flex-direction: column; gap: 8px; margin-top: 12px; }
.detail-list li {
  position: relative;
  padding-left: 14px;
  font-size: 14px;
  color: var(--c-text-soft);
  line-height: 1.6;
}
.detail-list li::before {
  content: ""; position: absolute; left: 0; top: 0.7em;
  width: 4px; height: 4px; border-radius: 50%;
  background: var(--c-text-faint);
}
.detail-section h3 {
  margin: 16px 0 6px;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--c-text-mute);
  font-weight: 500;
}
.news-list a {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 8px 0;
  color: var(--c-text-soft);
  border-bottom: 1px solid var(--c-border);
  transition: color var(--dur-fast) var(--ease-out);
}
.news-list a:last-child { border-bottom: 0; }
.news-list a:hover { color: var(--c-text); }
.news-list a .num { color: var(--c-text-faint); font-size: 12px; min-width: 18px; }

@media (max-width: 960px) {
  .dash-hero { grid-template-columns: 1fr; }
  .dash-hero .right { align-items: flex-start; text-align: left; }
  .kpi-grid { grid-template-columns: 1fr 1fr; }
  .panel-row { grid-template-columns: 1fr; }
  .detail-block { grid-template-columns: 1fr; }
}
@media (max-width: 760px) {
  .kpi-grid { grid-template-columns: 1fr; }
}
`;

export function renderDashboard(): HTMLElement {
  const root = document.createElement("div");
  root.dataset.title = "看板";
  root.innerHTML = `
    <style>${CSS}</style>
    <aurumers-shell>
      <div class="dash shell">
        <section class="dash-hero" data-anim="0">
          <div class="left">
            <span class="section-eyebrow">实时与每日预测</span>
            <h1>把每一个判断<br/>留痕到数据库。</h1>
            <p>30 分钟自动分析维持监控密度，02:50 北京时间凝练成一份正式预测，错对都会留下凭据。</p>
            <div class="actions">
              <button id="run-btn" class="btn btn-primary" data-state="">
                <span class="spinner"></span>
                <svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="6 4 20 12 6 20 6 4"/></svg>
                <span data-label>立即跑一次分析</span>
              </button>
              <button id="daily-btn" class="btn btn-ghost">
                <span data-label>触发今日预测</span>
              </button>
              <a href="/app/predictions" class="btn btn-ghost" data-route>预测中心</a>
            </div>
          </div>
          <div class="right">
            <span class="right-label">最新分析快照</span>
            <aurumers-chip id="hero-trend" label="未知"></aurumers-chip>
            <div class="price num" id="hero-price">—</div>
            <div class="price-meta" id="hero-time">等待首次分析</div>
            <div class="price-meta" id="hero-market" style="font-size:12px;color:var(--c-text-mute);"></div>
          </div>
        </section>

        <section data-anim="2">
          <aurumers-section-header eyebrow="关键指标" titleText="区间快照">
            <aurumers-range-toggle id="range-toggle" label="时间范围"></aurumers-range-toggle>
          </aurumers-section-header>
          <div class="kpi-grid">
            <aurumers-kpi id="kpi-price" label="最新金价" value="0" foot="—"></aurumers-kpi>
            <aurumers-kpi id="kpi-avg" label="区间均价" value="0" foot="—"></aurumers-kpi>
            <aurumers-kpi id="kpi-vol" label="价格波动率" value="0" foot="—"></aurumers-kpi>
            <aurumers-kpi id="kpi-acc" label="预测准确率" value="0" suffix="%" foot="近 30 天样本"></aurumers-kpi>
          </div>
        </section>

        <section class="panel-row" data-anim="4">
          <div class="panel">
            <aurumers-section-header eyebrow="价格与趋势" titleText="价格 + 趋势叠加" desc="深金线为价格走势，散点颜色对应当时模型给出的趋势判断。"></aurumers-section-header>
            <div class="chart" id="chart-price"></div>
          </div>
          <div class="panel">
            <aurumers-section-header eyebrow="趋势分布" titleText="近窗口趋势占比"></aurumers-section-header>
            <div class="chart-mini" id="chart-trend"></div>
          </div>
        </section>

        <section class="detail-block" data-anim="6">
          <div class="panel">
            <aurumers-section-header eyebrow="最新分析" titleText="最近一次 30 分钟分析" desc=""></aurumers-section-header>
            <div class="detail-meta">
              <aurumers-chip id="detail-trend" label="未知"></aurumers-chip>
              <aurumers-chip id="detail-status" label="—"></aurumers-chip>
              <span class="muted" id="detail-meta">等待首次分析</span>
            </div>
            <div class="detail-section">
              <h3>摘要</h3>
              <div class="detail-summary" id="detail-summary">—</div>
            </div>
            <div class="detail-section">
              <h3>原因</h3>
              <ul class="detail-list" id="detail-reasons"></ul>
            </div>
            <div class="detail-section">
              <h3>操作建议</h3>
              <div class="detail-summary" id="detail-advice">—</div>
            </div>
            <div class="detail-section">
              <h3>相关新闻</h3>
              <ul class="news-list" id="detail-news"></ul>
            </div>
          </div>
          <div class="panel">
            <aurumers-section-header eyebrow="今日预测" titleText="02:50 调度结果" desc="每日 02:50 北京时间自动产出，未到点显示最近一次。"></aurumers-section-header>
            <div id="daily-card">等待数据…</div>
          </div>
        </section>
      </div>
      <aurumers-toast-stack></aurumers-toast-stack>
    </aurumers-shell>
  `;

  setupRangeToggle(root);
  setupRunButton(root);
  setupDailyButton(root);
  void loadAll(root, "24h");
  setupSse(root);
  return root;
}

function setupRangeToggle(root: HTMLElement) {
  const toggle = root.querySelector<HTMLElement>("#range-toggle") as any;
  if (toggle) {
    toggle.options = RANGES;
    toggle.value = "24h";
    toggle.addEventListener("range-change", (event: Event) => {
      const value = (event as CustomEvent<{ value: string }>).detail.value;
      void loadAll(root, value);
    });
  }
}

function setupRunButton(root: HTMLElement) {
  const button = root.querySelector<HTMLButtonElement>("#run-btn");
  if (!button) return;
  button.addEventListener("click", async () => {
    if (button.dataset.state === "loading") return;
    setButtonState(button, "loading", "正在分析");
    try {
      const record = await api.runAnalysis();
      renderLatestRecord(root, record);
      toast("分析完成", "success");
      const range = (root.querySelector<HTMLElement>("#range-toggle") as any)?.value || "24h";
      void loadAll(root, range);
    } catch (err: any) {
      toast(err?.message || "分析失败", "error");
    } finally {
      setButtonState(button, "", "立即跑一次分析");
    }
  });
}

function setupDailyButton(root: HTMLElement) {
  const button = root.querySelector<HTMLButtonElement>("#daily-btn");
  if (!button) return;
  button.addEventListener("click", async () => {
    button.disabled = true;
    setButtonState(button, "", "调用中…");
    try {
      const prediction = await api.runDaily();
      renderDailyCard(root, prediction);
      toast(`今日预测：明日${prediction.tomorrow_direction}`, "success");
    } catch (err: any) {
      toast(err?.message || "调用失败", "error");
    } finally {
      button.disabled = false;
      setButtonState(button, "", "触发今日预测");
    }
  });
}

async function loadAll(root: HTMLElement, range: string) {
  try {
    const [series, kpi, dist, summary, accuracy, today, price] = await Promise.all([
      api.timeseries(range),
      api.kpis(range),
      api.distribution(range),
      api.dashboard(1),
      api.accuracy("30d"),
      api.todayPrediction(),
      api.price(),
    ]);
    renderHero(root, summary?.latest, price);
    renderKpis(root, kpi, accuracy);
    _dashPoints = series.points || [];
    _dashPriceEl = root.querySelector<HTMLElement>("#chart-price");
    if (_dashPriceEl) renderPriceChart(_dashPriceEl, _dashPoints);
    renderTrendDonut(root.querySelector<HTMLElement>("#chart-trend")!, dist.trend_counts);
    if (summary?.latest) renderLatestRecord(root, summary.latest);
    renderDailyCard(root, today);
  } catch (err: any) {
    toast(err?.message || "数据加载失败", "error");
  }
}

function renderHero(root: HTMLElement, record: AnalysisRecord | null | undefined, price?: { comex_open: boolean | null; sge_open: boolean | null; data_label: string | null; data_timestamp: string | null }) {
  const heroPrice = root.querySelector<HTMLDivElement>("#hero-price");
  const heroTime = root.querySelector<HTMLDivElement>("#hero-time");
  const heroMarket = root.querySelector<HTMLDivElement>("#hero-market");
  const heroChip = root.querySelector<HTMLElement>("#hero-trend") as any;
  if (heroPrice) heroPrice.textContent = formatNumber(record?.price_value, 2, record?.price_raw || "—");
  if (heroTime) heroTime.textContent = record?.time || "等待首次分析";
  if (heroChip) heroChip.label = record?.trend || "未知";
  if (heroMarket) {
    if (!price) {
      heroMarket.textContent = "";
    } else if (price.comex_open === false) {
      const stamp = price.data_timestamp ? `（截至 ${price.data_timestamp}）` : "";
      heroMarket.textContent = `周末/休市 · 上次收盘 ${stamp}`;
    } else if (price.comex_open === true) {
      heroMarket.textContent = `${price.data_label || "实时"} · COMEX 开盘中`;
    } else {
      heroMarket.textContent = price.data_label || "";
    }
  }
}

function renderKpis(root: HTMLElement, kpi: KPISummary, accuracy: AccuracySnapshot) {
  const price = root.querySelector<HTMLElement>("#kpi-price") as any;
  const avg = root.querySelector<HTMLElement>("#kpi-avg") as any;
  const vol = root.querySelector<HTMLElement>("#kpi-vol") as any;
  const acc = root.querySelector<HTMLElement>("#kpi-acc") as any;

  if (price) {
    price.value = formatNumber(kpi.latest_price ?? kpi.avg_price);
    price.foot = kpi.last_updated ? `更新于 ${kpi.last_updated.slice(11, 16)}` : "—";
  }
  if (avg) {
    avg.value = formatNumber(kpi.avg_price);
    avg.foot = kpi.min_price && kpi.max_price ? `区间 ${formatNumber(kpi.min_price)} – ${formatNumber(kpi.max_price)}` : "—";
  }
  if (vol) {
    vol.value = formatNumber(kpi.volatility);
    vol.foot = `${kpi.total_runs ?? 0} 次分析 · 平均 ${(kpi.avg_latency_ms ?? 0).toFixed(0)}ms`;
  }
  if (acc) {
    acc.value = ((accuracy.overall_accuracy ?? 0) * 100).toFixed(0);
    acc.suffix = "%";
    acc.foot = `${accuracy.verified_predictions} / ${accuracy.total_predictions} 已验证 · 当前连命中 ${accuracy.current_streak}`;
  }
}

function renderLatestRecord(root: HTMLElement, record: AnalysisRecord) {
  const trendChip = root.querySelector<HTMLElement>("#detail-trend") as any;
  const statusChip = root.querySelector<HTMLElement>("#detail-status") as any;
  const meta = root.querySelector<HTMLDivElement>("#detail-meta");
  const summary = root.querySelector<HTMLDivElement>("#detail-summary");
  const advice = root.querySelector<HTMLDivElement>("#detail-advice");
  const reasons = root.querySelector<HTMLUListElement>("#detail-reasons");
  const news = root.querySelector<HTMLUListElement>("#detail-news");
  if (trendChip) trendChip.label = record.trend;
  if (statusChip) statusChip.label = record.status;
  if (meta) meta.textContent = `${record.time} · 模型 ${record.model_name || "—"} · 来源 ${formatSource(record.source)}`;
  if (summary) summary.textContent = record.summary || "暂无总结";
  if (advice) advice.textContent = record.advice || "暂无建议";
  if (reasons) {
    reasons.innerHTML = "";
    const items = record.reasons.filter(Boolean);
    if (!items.length) {
      const li = document.createElement("li");
      li.textContent = "暂无原因分析";
      reasons.appendChild(li);
    } else {
      for (const r of items) {
        const li = document.createElement("li");
        li.textContent = r;
        reasons.appendChild(li);
      }
    }
  }
  if (news) {
    news.innerHTML = "";
    const list = record.news || [];
    if (!list.length) {
      const li = document.createElement("li");
      li.className = "muted";
      li.textContent = "暂无相关新闻";
      news.appendChild(li);
    } else {
      list.forEach((item, idx) => {
        const li = document.createElement("li");
        const a = document.createElement("a");
        a.href = safeUrl(item.link);
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        const num = document.createElement("span");
        num.className = "num";
        num.textContent = String(idx + 1).padStart(2, "0");
        const title = document.createElement("span");
        title.textContent = item.title || "(无标题)";
        a.append(num, title);
        li.appendChild(a);
        news.appendChild(li);
      });
    }
  }
}

function renderDailyCard(root: HTMLElement, prediction: DailyPrediction | null) {
  const host = root.querySelector<HTMLDivElement>("#daily-card");
  if (!host) return;
  if (!prediction) {
    host.innerHTML = `<div class="muted">尚未生成今日预测，可手动点击触发。</div>`;
    return;
  }
  const status = prediction.verified_correct === null
    ? `<aurumers-chip label="未验证"></aurumers-chip>`
    : prediction.verified_correct
      ? `<aurumers-chip label="命中" variant="up"></aurumers-chip>`
      : `<aurumers-chip label="未中" variant="down"></aurumers-chip>`;
  host.innerHTML = `
    <div class="detail-meta" style="margin-top:0;">
      <aurumers-chip label="${escapeHtml(prediction.tomorrow_direction)}"></aurumers-chip>
      <span class="muted">置信 ${formatPercent(prediction.tomorrow_confidence)}</span>
      ${status}
    </div>
    <div class="detail-section">
      <h3>今日定性</h3>
      <div class="detail-summary">${escapeHtml(prediction.today_direction)} · SGE ${formatNumber(prediction.today_close_sge)} · COMEX ${formatNumber(prediction.today_close_comex)}</div>
    </div>
    <div class="detail-section">
      <h3>明日预测理由</h3>
      <div class="detail-summary">${escapeHtml(prediction.reasoning_summary || "—")}</div>
    </div>
    <div class="detail-section">
      <h3>操作建议</h3>
      <div class="detail-summary">${escapeHtml(prediction.tomorrow_advice || "—")}</div>
    </div>
    <div class="detail-section">
      <h3>校准说明</h3>
      <div class="detail-summary muted">${escapeHtml(chunkText(prediction.calibration_note, 280))}</div>
    </div>
  `;
}

function setupSse(root: HTMLElement) {
  subscribeStream({
    analysis_record_added: (payload: any) => {
      if (!root.isConnected) return;
      if (!payload) return;
      const record = payload as AnalysisRecord;
      renderLatestRecord(root, record);
      toast("收到一条新分析", "info");
      appendChartPoint(record);
    },
    daily_prediction_ready: (payload: any) => {
      if (!root.isConnected) return;
      renderDailyCard(root, payload as DailyPrediction);
      toast("收到今日预测", "success");
    },
    prediction_verified: (payload: any) => {
      if (!root.isConnected) return;
      renderDailyCard(root, payload as DailyPrediction);
      toast("预测已校验", "info");
    },
  });
}

function appendChartPoint(record: AnalysisRecord) {
  if (record.price_value == null || !_dashPriceEl) return;
  const point: TimeSeriesPoint = {
    id: record.id,
    time: record.time,
    price: record.price_value,
    trend: record.trend,
    status: record.status,
    summary: record.summary,
    confidence: record.confidence ?? null,
    source: record.source,
    model_name: record.model_name,
  };
  const idx = _dashPoints.findIndex((p) => p.id === point.id);
  if (idx >= 0) _dashPoints[idx] = point;
  else _dashPoints.push(point);
  renderPriceChart(_dashPriceEl, _dashPoints);
}
