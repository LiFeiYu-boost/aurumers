import * as echarts from "echarts/core";
import { LineChart, ScatterChart } from "echarts/charts";
import { GridComponent, MarkLineComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { api } from "../api/client";
import { toast } from "../components/Toast";
import { escapeHtml, formatPercent } from "../utils";
import type {
  AccuracyMetricsV2,
  AccuracySnapshot,
  DailyPrediction,
  SkillAuditSummary,
} from "../api/schemas";

echarts.use([LineChart, ScatterChart, GridComponent, MarkLineComponent, TooltipComponent, CanvasRenderer]);

const CSS = `
.ins { padding: 28px 0; }
.ins h1 { margin: 0 0 4px; font-size: clamp(28px, 3.4vw, 36px); font-weight: 600; letter-spacing: -0.022em; }
.ins p.lead { margin: 0 0 24px; color: var(--c-text-soft); max-width: 60ch; }

.vs-baseline {
  margin-bottom: 16px;
  padding: 18px 20px;
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-sm);
}
.vs-baseline-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.vs-baseline-head .lbl {
  font-size: 11px;
  color: var(--c-text-mute);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  font-weight: 500;
}
.vs-baseline-head .note {
  font-size: 12px;
  color: var(--c-text-mute);
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}
.vs-baseline-head .note.short { color: var(--c-text-soft); font-style: italic; }
.vs-baseline-head .backtest-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--c-text-mute);
  cursor: pointer;
  user-select: none;
  margin-left: auto;
  padding: 4px 10px;
  border: 1px solid var(--c-border);
  border-radius: 999px;
  background: var(--c-bg-soft);
  transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
}
.vs-baseline-head .backtest-toggle:hover { background: var(--c-surface); }
.vs-baseline-head .backtest-toggle input { accent-color: var(--c-accent); cursor: pointer; }
.vs-baseline-head .backtest-toggle.on {
  color: var(--c-accent);
  border-color: var(--c-accent-line);
  background: var(--c-accent-soft);
}
.vs-baseline-foot {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--c-border);
  font-size: 11px;
  color: var(--c-text-soft);
  line-height: 1.5;
  display: none;
}
.vs-baseline-foot.show { display: block; }
.vs-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}
.vs-cell {
  border: 1px solid var(--c-border);
  border-radius: 10px;
  padding: 12px 14px;
  background: var(--c-bg-soft);
}
.vs-cell.aurumers { background: var(--c-surface); border-color: var(--c-accent-line); }
.vs-cell.short { opacity: 0.6; }
.vs-cell .who {
  font-size: 11px;
  color: var(--c-text-mute);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  font-weight: 500;
}
.vs-cell .pct {
  margin-top: 6px;
  font-size: 28px;
  font-weight: 600;
  letter-spacing: -0.02em;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  line-height: 1.05;
}
.vs-cell .delta {
  margin-top: 4px;
  font-size: 12px;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  color: var(--c-text-mute);
}
.vs-cell .delta.up { color: var(--c-up); }
.vs-cell .delta.down { color: var(--c-down); }

.cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
.card {
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  padding: 22px 24px;
  box-shadow: var(--shadow-sm);
}
.card .label {
  font-size: 11px; color: var(--c-text-mute); letter-spacing: 0.08em;
  text-transform: uppercase; font-weight: 500;
}
.card .value {
  margin-top: 8px;
  font-size: 36px;
  font-weight: 600;
  letter-spacing: -0.03em;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}
.card .desc { margin-top: 6px; font-size: 13px; color: var(--c-text-mute); }

.section { margin-top: 28px; }
.panel {
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  padding: 22px 24px;
  box-shadow: var(--shadow-sm);
}
.misses {
  margin-top: 16px;
  padding: 14px 16px;
  background: var(--c-bg-soft);
  border-left: 2px solid var(--c-flat);
  border-radius: 8px;
  font-size: 13px;
  color: var(--c-text-soft);
  line-height: 1.6;
}
.directions { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 16px; }
.direction {
  border: 1px solid var(--c-border);
  border-radius: 10px;
  padding: 14px;
}
.direction .lbl { font-size: 11px; color: var(--c-text-mute); text-transform: uppercase; letter-spacing: 0.1em; }
.direction .val { margin-top: 8px; font-size: 22px; font-weight: 600; font-family: var(--font-mono); letter-spacing: -0.02em; }

.timeline {
  margin-top: 18px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.timeline .row {
  display: grid;
  grid-template-columns: 110px 1fr auto;
  gap: 14px;
  padding: 12px;
  border: 1px solid var(--c-border);
  border-radius: 8px;
  align-items: center;
  font-size: 13px;
}
.timeline .row.correct { border-left: 3px solid var(--c-up); }
.timeline .row.wrong { border-left: 3px solid var(--c-down); }
.timeline .row.pending { border-left: 3px solid var(--c-flat); }
.timeline .date { font-family: var(--font-mono); font-variant-numeric: tabular-nums; color: var(--c-text-mute); }
.timeline .summary { color: var(--c-text); }

.phase2-cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; margin-top: 16px; }
.phase2-cards .card .lbl-row {
  display: flex; align-items: baseline; justify-content: space-between; gap: 8px;
}
.phase2-cards .card .label { font-size: 11px; color: var(--c-text-mute); letter-spacing: 0.08em; text-transform: uppercase; }
.phase2-cards .card .pill {
  font-size: 10px; padding: 2px 6px; border-radius: 4px;
  font-family: var(--font-mono); font-variant-numeric: tabular-nums;
}
.phase2-cards .card .pill.good { color: var(--c-up); background: var(--c-up-soft); }
.phase2-cards .card .pill.bad { color: var(--c-down); background: var(--c-down-soft); }
.phase2-cards .card .pill.muted { color: var(--c-text-mute); background: var(--c-bg-soft); }
.phase2-cards .card .desc { margin-top: 8px; font-size: 12px; color: var(--c-text-mute); line-height: 1.5; }

.regime-table { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 14px; }
.regime-table th, .regime-table td {
  padding: 10px 8px; border-bottom: 1px solid var(--c-border); text-align: left;
}
.regime-table th {
  font-weight: 500; color: var(--c-text-mute);
  font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em;
}
.regime-table td.num {
  font-family: var(--font-mono); font-variant-numeric: tabular-nums;
}
.regime-table tr:last-child td { border-bottom: 0; }
.regime-table .regime-tag {
  display: inline-block; padding: 2px 8px; border-radius: 4px;
  font-size: 11px; font-weight: 500;
}
.regime-table .regime-tag.bull { color: var(--c-up); background: var(--c-up-soft); }
.regime-table .regime-tag.bear { color: var(--c-down); background: var(--c-down-soft); }
.regime-table .regime-tag.choppy,
.regime-table .regime-tag.transition,
.regime-table .regime-tag.unknown,
.regime-table .regime-tag.unlabeled { color: var(--c-text-mute); background: var(--c-bg-soft); }

.raw-vs-cal {
  margin-top: 16px;
  border: 1px solid var(--c-border);
  border-radius: 8px;
  padding: 14px 16px;
  background: var(--c-bg-soft);
}
.raw-vs-cal-title {
  font-size: 11px;
  color: var(--c-text-mute);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-bottom: 10px;
}
.rvs-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.rvs-table th, .rvs-table td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--c-border);
  text-align: right;
}
.rvs-table th:first-child, .rvs-table td:first-child {
  text-align: left;
  color: var(--c-text-mute);
  font-weight: 500;
}
.rvs-table th {
  font-weight: 500; color: var(--c-text-mute); font-size: 11px;
  text-transform: uppercase; letter-spacing: 0.08em;
}
.rvs-table td.num {
  font-family: var(--font-mono); font-variant-numeric: tabular-nums;
}
.rvs-table td.delta.better { color: var(--c-up); }
.rvs-table td.delta.worse { color: var(--c-down); }
.rvs-table td.delta.neutral { color: var(--c-text-mute); }
.rvs-table tr:last-child td { border-bottom: 0; }

.reliability-wrap {
  margin-top: 16px;
  border: 1px solid var(--c-border);
  border-radius: 8px;
  padding: 12px 14px;
  background: var(--c-bg-soft);
}
.reliability-wrap .reliability-chart { width: 100%; height: 240px; }
.reliability-wrap .empty {
  height: 240px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--c-text-mute);
  font-size: 13px;
}

.skill-status {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin-top: 14px;
}
.skill-status .stat {
  border: 1px solid var(--c-border);
  border-radius: 10px;
  padding: 12px 14px;
  background: var(--c-bg-soft);
}
.skill-status .stat .lbl {
  font-size: 11px;
  color: var(--c-text-mute);
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.skill-status .stat .val {
  margin-top: 6px;
  font-size: 22px;
  font-weight: 600;
  letter-spacing: -0.02em;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  line-height: 1.05;
}
.skill-status .stat .desc {
  margin-top: 4px;
  font-size: 12px;
  color: var(--c-text-mute);
}
.skill-status .stat.cold .val { color: var(--c-text-mute); }
.skill-status .stat.live .val { color: var(--c-accent); }
.skill-recent {
  margin-top: 14px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.skill-recent .day {
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  border: 1px solid var(--c-border);
  color: var(--c-text-mute);
  background: var(--c-bg);
}
.skill-recent .day.changed {
  border-color: var(--c-accent-line);
  color: var(--c-accent);
  background: var(--c-accent-soft);
}

@media (max-width: 760px) {
  .cards, .phase2-cards { grid-template-columns: 1fr; }
  .directions { grid-template-columns: 1fr; }
  .timeline .row { grid-template-columns: 1fr; }
  .vs-row { grid-template-columns: 1fr; }
  .skill-status { grid-template-columns: 1fr; }
}
`;

export function renderInsights(): HTMLElement {
  const root = document.createElement("div");
  root.dataset.title = "洞察";
  root.innerHTML = `
    <style>${CSS}</style>
    <aurumers-shell>
      <div class="ins shell">
        <span class="section-eyebrow" data-anim="0">洞察</span>
        <h1 data-anim="0">命中率与失误模式</h1>
        <p class="lead" data-anim="1">查看模型在不同时间窗的总命中率、按方向的偏差，以及最近被识别出的失误模式。所有数据来自系统每日 03:10 自动校验的结果。</p>

        <section class="vs-baseline" data-anim="2" id="vs-baseline">
          <div class="vs-baseline-head">
            <span class="lbl">vs 基线</span>
            <span class="note" id="vs-baseline-note">—</span>
            <label class="backtest-toggle" id="backtest-toggle" title="纳入历史回测数据（无当日新闻语境，命中信号弱于 live）">
              <input type="checkbox" id="backtest-toggle-input" />
              <span>含 backtest</span>
            </label>
          </div>
          <div class="vs-row" id="vs-baseline-row"></div>
          <div class="vs-baseline-foot" id="vs-baseline-foot">
            当前指标已纳入 backtest_no_news 行（历史回测重放，缺当日新闻语境）。
            其命中率结构性低于 live —— 用于扩大样本量看 baseline 对照，
            不代表 live pipeline 的真实表现。
          </div>
        </section>

        <section class="cards" data-anim="2">
          <div class="card">
            <div class="label">总体准确率</div>
            <div class="value" id="ins-accuracy">—</div>
            <div class="desc" id="ins-accuracy-desc">等待样本</div>
          </div>
          <div class="card">
            <div class="label">已验证 / 总数</div>
            <div class="value" id="ins-verified">—</div>
            <div class="desc" id="ins-verified-desc">最近窗口的覆盖度</div>
          </div>
          <div class="card">
            <div class="label">连续命中</div>
            <div class="value" id="ins-streak">—</div>
            <div class="desc" id="ins-streak-desc">当前连续 / 历史最长</div>
          </div>
        </section>

        <section class="section" data-anim="4">
          <div class="panel">
            <aurumers-section-header eyebrow="按方向" titleText="不同预测方向的命中率"></aurumers-section-header>
            <div class="directions" id="ins-directions"></div>
          </div>
        </section>

        <section class="section" data-anim="5">
          <div class="panel">
            <aurumers-section-header
              eyebrow="概率指标 · 主目标"
              titleText="Brier · log-loss · ECE"
              desc="模型质量的核心三指标；目标是把这三项压下来，方向命中率次之。窗口 90 天。"
            ></aurumers-section-header>
            <div class="phase2-cards" id="phase2-cards"></div>
            <div class="raw-vs-cal" id="raw-vs-cal" hidden>
              <div class="raw-vs-cal-title">校准前 vs 校准后</div>
              <table class="rvs-table">
                <thead>
                  <tr>
                    <th></th>
                    <th>校准前（raw）</th>
                    <th>校准后</th>
                    <th>Δ</th>
                  </tr>
                </thead>
                <tbody id="rvs-body"></tbody>
              </table>
            </div>
            <table class="regime-table" id="regime-table">
              <thead><tr><th>Regime</th><th>样本</th><th>命中率</th><th>Brier</th></tr></thead>
              <tbody></tbody>
            </table>
            <div class="reliability-wrap">
              <div class="reliability-chart" id="reliability-chart"></div>
            </div>
          </div>
        </section>

        <section class="section" data-anim="6">
          <div class="panel">
            <aurumers-section-header
              eyebrow="系统状态"
              titleText="Hermes skill 自演化审计"
              desc="每日 04:00 系统 cron 比对当前 skill 与昨日快照；空文件 = 当天没改。30 天 0 改 → self-evolve 没在跑。"
            ></aurumers-section-header>
            <div class="skill-status" id="skill-status"></div>
            <div class="skill-recent" id="skill-recent"></div>
          </div>
        </section>

        <section class="section" data-anim="6">
          <div class="panel">
            <aurumers-section-header eyebrow="模型自我反思" titleText="近期失误模式 + Hermes 评论"></aurumers-section-header>
            <div class="misses" id="ins-misses">暂无失误模式</div>
            <div class="timeline" id="ins-timeline"></div>
          </div>
        </section>
      </div>
      <aurumers-toast-stack></aurumers-toast-stack>
    </aurumers-shell>
  `;

  // The toggle is the single source of truth for whether aggregations include
  // backtest replays. Default off — the landing view should reflect live-only
  // pipeline performance, with backtest as an explicit opt-in. State lives on
  // the DOM input (no extra closure variable) so toggling and re-loading stay
  // consistent across re-renders.
  const toggleInput = root.querySelector<HTMLInputElement>("#backtest-toggle-input");
  const toggleWrap = root.querySelector<HTMLElement>("#backtest-toggle");
  const foot = root.querySelector<HTMLElement>("#vs-baseline-foot");
  if (toggleInput && toggleWrap) {
    toggleInput.addEventListener("change", () => {
      const on = toggleInput.checked;
      toggleWrap.classList.toggle("on", on);
      foot?.classList.toggle("show", on);
      void load(root, on);
    });
  }

  void load(root, false);
  return root;
}

async function load(root: HTMLElement, includeBacktest: boolean) {
  // backtest_no_news rows are all from 2023-01-03 → 2024-12-31, i.e. months
  // outside any 30-day or even 90-day window from today. With the live-only
  // default "30d" range, flipping the toggle on changes nothing visible —
  // making the UI look broken (round-2 H). When the user opts in, expand
  // the window to "all" so the backtest sample actually surfaces.
  const v1Range = includeBacktest ? "all" : "30d";
  const v2Window = includeBacktest ? "all" : "90d";
  try {
    const [accuracy, daily] = await Promise.all([
      api.accuracy(v1Range, includeBacktest),
      api.dailyPredictions(v1Range, includeBacktest),
    ]);
    renderVsBaseline(root, accuracy);
    renderCards(root, accuracy);
    renderDirections(root, accuracy);
    renderTimeline(root, daily.items, accuracy);
  } catch (err: any) {
    toast(err?.message || "数据加载失败", "error");
  }

  try {
    const metrics = await api.metricsDetailed(v2Window, true, false, false, true, includeBacktest);
    renderPhase2Metrics(root, metrics);
    renderRawVsCalibrated(root, metrics);
  } catch (err: any) {
    // Independent — surface in console but don't toast over the v1 cards.
    console.warn("metrics/detailed load failed", err);
    renderPhase2Empty(root, "Phase 2 指标加载失败");
  }

  try {
    const audit = await api.skillAudit(30, 14);
    renderSkillAudit(root, audit);
  } catch (err: any) {
    console.warn("skill_audit load failed", err);
    renderSkillAuditEmpty(root, "审计数据加载失败");
  }
}

function fmtNum(value: number | null, decimals: number, fallback = "—"): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return fallback;
  return value.toFixed(decimals);
}

function brierTone(value: number | null): { cls: string; hint: string } {
  if (value === null) return { cls: "muted", hint: "样本不足" };
  // random guess on 3-class is ~0.667; ideal 0; v1 baseline ~0.78
  if (value <= 0.55) return { cls: "good", hint: "优于均匀猜测" };
  if (value >= 0.7) return { cls: "bad", hint: "高于随机猜测" };
  return { cls: "muted", hint: "接近均匀基线" };
}

function eceTone(value: number | null): { cls: string; hint: string } {
  if (value === null) return { cls: "muted", hint: "样本不足" };
  if (value <= 0.10) return { cls: "good", hint: "校准良好" };
  if (value >= 0.20) return { cls: "bad", hint: "校准偏差较大" };
  return { cls: "muted", hint: "中等校准" };
}

function logLossTone(value: number | null): { cls: string; hint: string } {
  if (value === null) return { cls: "muted", hint: "样本不足" };
  if (value <= 0.85) return { cls: "good", hint: "对数损失低" };
  if (value >= 1.20) return { cls: "bad", hint: "对数损失高" };
  return { cls: "muted", hint: "中等对数损失" };
}

function renderPhase2Metrics(root: HTMLElement, metrics: AccuracyMetricsV2) {
  const cards = root.querySelector<HTMLElement>("#phase2-cards");
  if (!cards) return;
  const verifiedCount = metrics.sample_count_by_source?.synthetic_backtest ?? metrics.verified_predictions;
  const brier = brierTone(metrics.brier_multiclass);
  const ll = logLossTone(metrics.log_loss);
  const ece = eceTone(metrics.ece);
  const rangeText = `n=${verifiedCount} verified`;

  cards.innerHTML = `
    <div class="card">
      <div class="lbl-row">
        <span class="label">Brier (multiclass)</span>
        <span class="pill ${brier.cls}">${brier.hint}</span>
      </div>
      <div class="value">${fmtNum(metrics.brier_multiclass, 3)}</div>
      <div class="desc">越低越好；随机猜≈0.667；理想 0。${rangeText}</div>
    </div>
    <div class="card">
      <div class="lbl-row">
        <span class="label">Log loss</span>
        <span class="pill ${ll.cls}">${ll.hint}</span>
      </div>
      <div class="value">${fmtNum(metrics.log_loss, 3)}</div>
      <div class="desc">3 类对数损失，越低越好。${rangeText}</div>
    </div>
    <div class="card">
      <div class="lbl-row">
        <span class="label">ECE</span>
        <span class="pill ${ece.cls}">${ece.hint}</span>
      </div>
      <div class="value">${fmtNum(metrics.ece, 3)}</div>
      <div class="desc">期望校准误差；目标 ≤ 0.10。${rangeText}</div>
    </div>
  `;

  renderRegimeTable(root, metrics);
  renderReliabilityChart(root, metrics);
}

function renderRegimeTable(root: HTMLElement, metrics: AccuracyMetricsV2) {
  const tbody = root.querySelector<HTMLTableSectionElement>("#regime-table tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  const allKeys = new Set<string>();
  for (const k of Object.keys(metrics.accuracy_by_regime || {})) allKeys.add(k);
  for (const k of Object.keys(metrics.brier_by_regime || {})) allKeys.add(k);
  if (allKeys.size === 0) {
    tbody.innerHTML = `<tr><td colspan="4" style="text-align:center;color:var(--c-text-mute);padding:18px;">尚无 regime 分层数据</td></tr>`;
    return;
  }
  // Order: bull, transition, choppy, bear, unknown, unlabeled, then others
  const order = ["bull", "transition", "choppy", "bear", "unknown", "unlabeled"];
  const sortedKeys = Array.from(allKeys).sort((a, b) => {
    const ai = order.indexOf(a);
    const bi = order.indexOf(b);
    if (ai === -1 && bi === -1) return a.localeCompare(b);
    if (ai === -1) return 1;
    if (bi === -1) return -1;
    return ai - bi;
  });
  for (const key of sortedKeys) {
    const acc = metrics.accuracy_by_regime[key];
    const brier = metrics.brier_by_regime[key];
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><span class="regime-tag ${escapeHtml(key)}">${escapeHtml(key)}</span></td>
      <td class="num">—</td>
      <td class="num">${acc === undefined ? "—" : formatPercent(acc)}</td>
      <td class="num">${brier === undefined ? "—" : fmtNum(brier, 3)}</td>
    `;
    tbody.appendChild(tr);
  }
}

function renderReliabilityChart(root: HTMLElement, metrics: AccuracyMetricsV2) {
  const el = root.querySelector<HTMLElement>("#reliability-chart");
  if (!el) return;
  const bins = metrics.reliability_diagram || [];
  if (bins.length === 0) {
    el.innerHTML = `<div class="empty">样本不足，等更多 v2 数据累积</div>`;
    return;
  }
  // Re-init container in case previously had empty placeholder
  el.innerHTML = "";
  const muted = readVar("--c-text-mute", "#7e7a76");
  const surface = readVar("--c-surface", "#ffffff");
  const border = readVar("--c-border", "#e7e5e4");
  const text = readVar("--c-text", "#0a0a0a");
  const accent = readVar("--c-accent", "#b8860b");

  const chart = echarts.getInstanceByDom(el) || echarts.init(el, undefined, { renderer: "canvas" });
  const points = bins.map((b) => ({
    value: [b.avg_confidence, b.hit_rate],
    sample_size: b.sample_size,
  }));
  chart.setOption(
    {
      grid: { left: 56, right: 24, top: 18, bottom: 36 },
      animationDuration: 600,
      animationEasing: "cubicOut",
      tooltip: {
        trigger: "item",
        backgroundColor: surface,
        borderColor: border,
        borderWidth: 1,
        textStyle: { color: text, fontSize: 12 },
        padding: [8, 12],
        formatter: (params: any) => {
          const data = params.data;
          if (!data) return "";
          const [conf, hit] = data.value;
          return `<div style="font-family: var(--font-mono);">
            <div style="color:${muted}; font-size:10px; text-transform:uppercase;">置信桶</div>
            <div>avg conf <strong>${(conf as number).toFixed(2)}</strong></div>
            <div>hit rate <strong>${(hit as number).toFixed(2)}</strong></div>
            <div style="color:${muted}; font-size:11px;">n=${data.sample_size}</div>
          </div>`;
        },
      },
      xAxis: {
        type: "value", min: 0, max: 1,
        name: "avg confidence", nameGap: 22, nameLocation: "middle",
        nameTextStyle: { color: muted, fontSize: 11 },
        axisLine: { lineStyle: { color: border } },
        axisLabel: { color: muted, fontSize: 11 },
        splitLine: { lineStyle: { color: border, type: "dashed" } },
      },
      yAxis: {
        type: "value", min: 0, max: 1,
        name: "hit rate", nameGap: 32, nameLocation: "middle", nameRotate: 90,
        nameTextStyle: { color: muted, fontSize: 11 },
        axisLine: { lineStyle: { color: border } },
        axisLabel: { color: muted, fontSize: 11 },
        splitLine: { lineStyle: { color: border, type: "dashed" } },
      },
      series: [
        {
          name: "perfect calibration",
          type: "line",
          data: [[0, 0], [1, 1]],
          showSymbol: false,
          lineStyle: { color: muted, type: "dashed", width: 1 },
          tooltip: { show: false },
          z: 1,
        },
        {
          name: "buckets",
          type: "scatter",
          data: points,
          symbolSize: (d: any) => Math.max(8, Math.min(28, Math.sqrt(d?.sample_size || 1) * 6)),
          itemStyle: { color: accent, borderColor: surface, borderWidth: 1.5 },
          z: 2,
        },
      ],
    },
    true,
  );
}

function renderPhase2Empty(root: HTMLElement, message: string) {
  const cards = root.querySelector<HTMLElement>("#phase2-cards");
  if (cards) {
    cards.innerHTML = `<div class="card" style="grid-column: 1 / -1; text-align: center; padding: 24px; color: var(--c-text-mute);">${escapeHtml(message)}</div>`;
  }
}

function renderRawVsCalibrated(root: HTMLElement, metrics: AccuracyMetricsV2) {
  const wrap = root.querySelector<HTMLElement>("#raw-vs-cal");
  const body = root.querySelector<HTMLTableSectionElement>("#rvs-body");
  if (!wrap || !body) return;
  const raw = metrics.raw_summary;
  if (!raw || raw.sample_size === 0) {
    wrap.hidden = true;
    return;
  }
  wrap.hidden = false;

  type Row = {
    label: string;
    raw: number | null;
    cal: number | null;
    lowerIsBetter: boolean;
    fmt: (v: number | null) => string;
  };
  const rows: Row[] = [
    {
      label: "Brier (multiclass)",
      raw: raw.brier_multiclass,
      cal: metrics.brier_multiclass,
      lowerIsBetter: true,
      fmt: (v) => fmtNum(v, 3),
    },
    {
      label: "Log loss",
      raw: raw.log_loss,
      cal: metrics.log_loss,
      lowerIsBetter: true,
      fmt: (v) => fmtNum(v, 3),
    },
    {
      label: "ECE",
      raw: raw.ece,
      cal: metrics.ece,
      lowerIsBetter: true,
      fmt: (v) => fmtNum(v, 3),
    },
    {
      label: "命中率",
      raw: raw.accuracy,
      cal: metrics.overall_accuracy,
      lowerIsBetter: false,
      fmt: (v) => (v === null ? "—" : `${(v * 100).toFixed(1)}%`),
    },
  ];

  body.innerHTML = rows
    .map((row) => {
      const rawTxt = row.fmt(row.raw);
      const calTxt = row.fmt(row.cal);
      let deltaTxt = "—";
      let deltaCls = "neutral";
      if (row.raw !== null && row.cal !== null && Number.isFinite(row.raw) && Number.isFinite(row.cal)) {
        const delta = row.cal - row.raw;
        // Δ display: keep raw sign; tone depends on direction of improvement.
        const isBetter = row.lowerIsBetter ? delta < 0 : delta > 0;
        const isWorse = row.lowerIsBetter ? delta > 0 : delta < 0;
        if (Math.abs(delta) < 1e-6) {
          deltaTxt = "0";
          deltaCls = "neutral";
        } else {
          if (row.label === "命中率") {
            deltaTxt = `${delta >= 0 ? "+" : ""}${(delta * 100).toFixed(1)}pp`;
          } else {
            deltaTxt = `${delta >= 0 ? "+" : ""}${delta.toFixed(3)}`;
          }
          deltaCls = isBetter ? "better" : isWorse ? "worse" : "neutral";
        }
      }
      return `
        <tr>
          <td>${escapeHtml(row.label)}</td>
          <td class="num">${rawTxt}</td>
          <td class="num">${calTxt}</td>
          <td class="num delta ${deltaCls}">${deltaTxt}</td>
        </tr>
      `;
    })
    .join("");
}

function readVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function renderSkillAudit(root: HTMLElement, audit: SkillAuditSummary) {
  const stat = root.querySelector<HTMLElement>("#skill-status");
  const recent = root.querySelector<HTMLElement>("#skill-recent");
  if (!stat || !recent) return;

  let lastChangeTxt: string;
  let lastChangeDesc: string;
  let lastChangeCls: "live" | "cold";
  if (audit.last_change_date && audit.days_since_last_change !== null) {
    if (audit.days_since_last_change === 0) {
      lastChangeTxt = "今天";
      lastChangeDesc = `于 ${audit.last_change_date}`;
    } else {
      lastChangeTxt = `${audit.days_since_last_change} 天前`;
      lastChangeDesc = `最近一次：${audit.last_change_date}`;
    }
    lastChangeCls = audit.days_since_last_change <= 14 ? "live" : "cold";
  } else if (audit.audits_in_window === 0) {
    lastChangeTxt = "—";
    lastChangeDesc = "等待 04:00 cron 首次落盘";
    lastChangeCls = "cold";
  } else {
    lastChangeTxt = "未演化";
    lastChangeDesc = `已审计 ${audit.audits_in_window} 天，无修改`;
    lastChangeCls = "cold";
  }

  const hintCls = audit.hint_count > 0 ? "live" : "cold";
  const hintDesc = audit.hint_count > 0
    ? "Hermes 已写入经验提示，会注入下次预测 prompt"
    : "Hermes 尚未生成 hint（周日反思后才会出现）";

  const nonemptyCls = audit.nonempty_in_window > 0 ? "live" : "cold";

  stat.innerHTML = `
    <div class="stat ${lastChangeCls}">
      <div class="lbl">最近修改</div>
      <div class="val">${escapeHtml(lastChangeTxt)}</div>
      <div class="desc">${escapeHtml(lastChangeDesc)}</div>
    </div>
    <div class="stat ${nonemptyCls}">
      <div class="lbl">30 天内有变更</div>
      <div class="val">${audit.nonempty_in_window} / ${audit.audits_in_window}</div>
      <div class="desc">非空 diff 数 / 审计天数</div>
    </div>
    <div class="stat ${hintCls}">
      <div class="lbl">Hint 文件</div>
      <div class="val">${audit.hint_count}</div>
      <div class="desc">${escapeHtml(hintDesc)}</div>
    </div>
  `;

  recent.innerHTML = "";
  if (audit.most_recent.length === 0) {
    recent.innerHTML = `<span class="day">尚无审计记录</span>`;
    return;
  }
  for (const entry of audit.most_recent) {
    const cls = entry.has_change ? "day changed" : "day";
    const title = entry.has_change
      ? (typeof entry.bytes === "number" ? `${entry.bytes} bytes 变更` : "有变更")
      : "无变更";
    recent.innerHTML += `<span class="${cls}" title="${escapeHtml(title)}">${escapeHtml(entry.date)}</span>`;
  }
}

function renderSkillAuditEmpty(root: HTMLElement, msg: string) {
  const stat = root.querySelector<HTMLElement>("#skill-status");
  if (stat) stat.innerHTML = `<div class="stat" style="grid-column: 1 / -1; text-align:center; padding:18px; color:var(--c-text-mute);">${escapeHtml(msg)}</div>`;
}

const VS_BASELINE_MIN_N = 30;

function renderVsBaseline(root: HTMLElement, accuracy: AccuracySnapshot) {
  const row = root.querySelector<HTMLElement>("#vs-baseline-row");
  const note = root.querySelector<HTMLElement>("#vs-baseline-note");
  if (!row || !note) return;
  const n = accuracy.baseline_verified_count ?? 0;
  const isShort = n < VS_BASELINE_MIN_N;

  if (isShort) {
    note.textContent = `样本不足 (n=${n} / ${VS_BASELINE_MIN_N})`;
    note.classList.add("short");
  } else {
    note.textContent = `n=${n} verified`;
    note.classList.remove("short");
  }

  type Cell = {
    who: string;
    pct: number | null;
    base?: number | null;
    isAurumers?: boolean;
  };
  const cells: Cell[] = [
    { who: "Aurumers", pct: accuracy.overall_accuracy ?? null, isAurumers: true },
    { who: "Persistence", pct: accuracy.baseline_persistence_accuracy, base: accuracy.overall_accuracy ?? null },
    { who: "MA(5)", pct: accuracy.baseline_ma_accuracy, base: accuracy.overall_accuracy ?? null },
  ];

  row.innerHTML = cells.map((c) => {
    const cls = ["vs-cell"];
    if (c.isAurumers) cls.push("aurumers");
    if (isShort) cls.push("short");

    const pctTxt = c.pct === null || c.pct === undefined ? "—" : `${(c.pct * 100).toFixed(1)}%`;

    let deltaHtml = "";
    if (!c.isAurumers && !isShort && c.pct !== null && c.pct !== undefined && c.base !== null && c.base !== undefined) {
      // delta = Aurumers - baseline; positive = Aurumers better
      const delta = c.base - c.pct;
      const sign = delta > 0 ? "↑" : delta < 0 ? "↓" : "·";
      const cls2 = delta > 0.005 ? "up" : delta < -0.005 ? "down" : "";
      const pp = Math.abs(delta * 100).toFixed(1);
      deltaHtml = `<div class="delta ${cls2}">Aurumers ${sign}${pp}pp</div>`;
    } else if (!c.isAurumers && (c.pct === null || c.pct === undefined)) {
      deltaHtml = `<div class="delta">基线尚无样本</div>`;
    } else if (c.isAurumers) {
      deltaHtml = `<div class="delta">模型整体命中率</div>`;
    }

    return `
      <div class="${cls.join(" ")}">
        <div class="who">${escapeHtml(c.who)}</div>
        <div class="pct">${pctTxt}</div>
        ${deltaHtml}
      </div>
    `;
  }).join("");
}

function renderCards(root: HTMLElement, accuracy: AccuracySnapshot) {
  (root.querySelector<HTMLElement>("#ins-accuracy") as HTMLElement).textContent = formatPercent(accuracy.overall_accuracy);
  (root.querySelector<HTMLElement>("#ins-accuracy-desc") as HTMLElement).textContent = `${accuracy.correct_predictions} 命中 / ${accuracy.verified_predictions} 已验证`;
  (root.querySelector<HTMLElement>("#ins-verified") as HTMLElement).textContent = `${accuracy.verified_predictions} / ${accuracy.total_predictions}`;
  (root.querySelector<HTMLElement>("#ins-verified-desc") as HTMLElement).textContent = accuracy.last_updated ? `最近 ${accuracy.last_updated.slice(0, 10)} 更新` : "等待样本";
  (root.querySelector<HTMLElement>("#ins-streak") as HTMLElement).textContent = `${accuracy.current_streak} / ${accuracy.longest_streak}`;
  (root.querySelector<HTMLElement>("#ins-streak-desc") as HTMLElement).textContent = "当前连续命中 / 历史最长连胜";
}

function renderDirections(root: HTMLElement, accuracy: AccuracySnapshot) {
  const host = root.querySelector<HTMLElement>("#ins-directions");
  if (!host) return;
  host.innerHTML = "";
  const map: Record<string, string> = { 上涨: "上涨", 下跌: "下跌", 震荡: "震荡" };
  for (const key of Object.keys(map)) {
    const value = accuracy.accuracy_by_direction?.[key];
    const div = document.createElement("div");
    div.className = "direction";
    div.innerHTML = `
      <div class="lbl">预测 ${escapeHtml(key)}</div>
      <div class="val">${value === undefined ? "—" : formatPercent(value)}</div>
    `;
    host.appendChild(div);
  }
}

function renderTimeline(root: HTMLElement, items: DailyPrediction[], accuracy: AccuracySnapshot) {
  const misses = root.querySelector<HTMLElement>("#ins-misses");
  if (misses) misses.textContent = accuracy.recent_miss_pattern || "暂未识别明显失误模式";
  const host = root.querySelector<HTMLElement>("#ins-timeline");
  if (!host) return;
  host.innerHTML = "";
  if (!items.length) {
    host.innerHTML = `<div class="muted" style="padding: 20px; text-align: center;">暂无预测记录</div>`;
    return;
  }
  for (const item of items.slice(0, 20)) {
    const cls = item.verified_correct === null ? "pending" : item.verified_correct ? "correct" : "wrong";
    const status = item.verified_correct === null ? "未验证" : item.verified_correct ? "命中" : "未中";
    const div = document.createElement("div");
    div.className = `row ${cls}`;
    div.innerHTML = `
      <div class="date">${escapeHtml(item.prediction_date)}</div>
      <div class="summary">${escapeHtml(item.reasoning_summary || item.tomorrow_advice || "—")}</div>
      <div><aurumers-chip label="${escapeHtml(item.tomorrow_direction)}"></aurumers-chip><span class="muted" style="margin-left:8px;">${status}</span></div>
    `;
    host.appendChild(div);
  }
}
