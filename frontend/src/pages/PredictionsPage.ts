import { api } from "../api/client";
import { renderCalibrationScatter } from "../charts/calibrationScatter";
import { renderPredictionCalendar } from "../charts/predictionCalendar";
import { renderSparkline } from "../charts/sparkline";
import type { SignalTone } from "../components/SignalBadge";
import { toast } from "../components/Toast";
import { chunkText, escapeHtml, formatNumber, formatPercent, setButtonState } from "../utils";
import type { AccuracySnapshot, DailyPrediction } from "../api/schemas";

const CSS = `
.pred { padding: 28px 0; }
.hero {
  display: grid;
  grid-template-columns: 1.6fr 1fr;
  gap: 28px;
  margin-bottom: 28px;
}
.hero .panel {
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  padding: 28px 28px 30px;
  position: relative;
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}
.hero .panel.headline {
  background:
    radial-gradient(420px 220px at 100% 0%, color-mix(in srgb, var(--c-accent) 14%, transparent), transparent 70%),
    var(--c-surface);
}
.hero h1 { margin: 4px 0 6px; font-size: clamp(22px, 2.4vw, 28px); font-weight: 600; letter-spacing: -0.02em; }
.hero .arrow {
  display: inline-flex;
  align-items: baseline;
  gap: 14px;
  margin: 8px 0 12px;
}
.hero .arrow .dir {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: clamp(48px, 6vw, 72px);
  font-weight: 600;
  letter-spacing: -0.04em;
  line-height: 1;
}
.hero .arrow .conf {
  display: flex;
  flex-direction: column;
  font-size: 12px;
  color: var(--c-text-mute);
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.hero .arrow .conf strong {
  color: var(--c-text);
  font-family: var(--font-mono);
  font-size: 26px;
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}
.hero .meta-row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
.hero .reasoning {
  margin-top: 18px;
  font-size: 14px;
  color: var(--c-text-soft);
  line-height: 1.7;
}
.hero .calibration {
  margin-top: 16px;
  padding: 14px 16px;
  background: var(--c-bg-soft);
  border-left: 2px solid var(--c-accent);
  border-radius: 8px;
  font-size: 13px;
  color: var(--c-text-soft);
  line-height: 1.6;
}
.hero .closes {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.close-card {
  border: 1px solid var(--c-border);
  border-radius: 10px;
  padding: 14px;
}
.close-card .lbl {
  font-size: 11px;
  color: var(--c-text-mute);
  text-transform: uppercase;
  letter-spacing: 0.1em;
}
.close-card .val {
  margin-top: 6px;
  font-size: 24px;
  font-weight: 600;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
}
.spread-bar {
  margin-top: 14px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  color: var(--c-text-mute);
}

.section { margin-top: 28px; }
.row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}
.panel {
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  padding: 22px 24px;
  box-shadow: var(--shadow-sm);
}
.scatter, .calendar {
  width: 100%;
  min-height: 260px;
}

.history table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.history th {
  text-align: left;
  font-weight: 500;
  color: var(--c-text-mute);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  padding: 10px 8px;
  border-bottom: 1px solid var(--c-border);
}
.history td {
  padding: 12px 8px;
  border-bottom: 1px solid var(--c-border);
  vertical-align: middle;
}
.history tr:last-child td { border-bottom: 0; }
.history .num { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }

.signal-radar {
  display: grid;
  gap: 18px;
}
.signal-radar .badges {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
}
.signal-radar .sparkline-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}
.signal-radar .sparkline-cell {
  background: var(--c-bg-soft);
  border: 1px solid var(--c-border);
  border-radius: 8px;
  padding: 10px 12px 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.signal-radar .sparkline-cell .head {
  display: flex; align-items: baseline; justify-content: space-between; gap: 8px;
}
.signal-radar .sparkline-cell .head .lbl {
  font-size: 10px; color: var(--c-text-mute); letter-spacing: 0.08em; text-transform: uppercase;
}
.signal-radar .sparkline-cell .head .val {
  font-size: 13px; font-family: var(--font-mono); font-variant-numeric: tabular-nums; color: var(--c-text);
}
.signal-radar .sparkline-cell .spark { width: 100%; height: 60px; }
.signal-radar .empty-hint {
  color: var(--c-text-mute);
  font-size: 12px;
  padding: 14px;
  text-align: center;
  border: 1px dashed var(--c-border);
  border-radius: 8px;
}

@media (max-width: 960px) {
  .hero { grid-template-columns: 1fr; }
  .row { grid-template-columns: 1fr; }
  .signal-radar .badges { grid-template-columns: repeat(2, 1fr); }
  .signal-radar .sparkline-strip { grid-template-columns: 1fr; }
}
`;

export function renderPredictions(): HTMLElement {
  const root = document.createElement("div");
  root.dataset.title = "预测中心";
  root.innerHTML = `
    <style>${CSS}</style>
    <aurumers-shell>
      <div class="pred shell">
        <section class="hero" data-anim="0">
          <div class="panel headline" id="hero-panel">
            <span class="section-eyebrow" id="hero-eyebrow">明日预测</span>
            <h1 id="hero-title">等待数据…</h1>
            <div class="arrow">
              <span class="dir" id="hero-dir">—</span>
              <span class="conf">
                <span>把握程度</span>
                <strong id="hero-conf">—</strong>
              </span>
            </div>
            <div class="meta-row" id="hero-meta"></div>
            <div class="reasoning" id="hero-reason">—</div>
            <div class="calibration" id="hero-calibration"></div>
          </div>
          <div class="panel">
            <span class="section-eyebrow">今日收盘价</span>
            <div class="closes" style="margin-top: 14px;">
              <div class="close-card">
                <div class="lbl">上海金 · 元/克</div>
                <div class="val" id="close-sge">—</div>
              </div>
              <div class="close-card">
                <div class="lbl">国际金 · 美元/盎司</div>
                <div class="val" id="close-comex">—</div>
              </div>
            </div>
            <div class="spread-bar" id="spread-row">数据来源 —</div>
            <div style="margin-top: 18px;">
              <aurumers-countdown></aurumers-countdown>
            </div>
            <div style="margin-top: 18px; display: flex; gap: 10px;">
              <button id="rerun-btn" class="btn btn-primary"><span data-label>立即重跑预测</span></button>
              <button id="verify-btn" class="btn btn-ghost"><span data-label>核对昨日</span></button>
            </div>
          </div>
        </section>

        <section class="section" data-anim="1">
          <div class="panel">
            <aurumers-section-header
              eyebrow="影响金价的因素"
              titleText="本次判断的主要依据"
              desc="AI 主要参考以下客观指标；下方折线为近 30 天市场背景。"
            ></aurumers-section-header>
            <div class="signal-radar" id="signal-radar"></div>
          </div>
        </section>

        <section class="section row" data-anim="2">
          <div class="panel">
            <aurumers-section-header eyebrow="把握 vs 实际" titleText="把握程度是否可信" desc="点越贴近对角线，标示的把握程度越接近实际命中率。"></aurumers-section-header>
            <div class="scatter" id="scatter"></div>
          </div>
          <div class="panel">
            <aurumers-section-header eyebrow="近 5 周" titleText="每日命中情况"></aurumers-section-header>
            <div class="calendar" id="calendar"></div>
          </div>
        </section>

        <section class="section history" data-anim="4">
          <div class="panel">
            <aurumers-section-header eyebrow="预测历史" titleText="近 30 条"></aurumers-section-header>
            <table>
              <thead>
                <tr>
                  <th>日期</th>
                  <th>上海金 元/克</th>
                  <th>国际金 美元/盎司</th>
                  <th>今日情况</th>
                  <th>明日预测</th>
                  <th>把握</th>
                  <th>结果</th>
                  <th>次日实际</th>
                </tr>
              </thead>
              <tbody id="history-body"></tbody>
            </table>
          </div>
        </section>
      </div>
      <aurumers-toast-stack></aurumers-toast-stack>
    </aurumers-shell>
  `;

  void load(root);
  setupActions(root);
  return root;
}

function setupActions(root: HTMLElement) {
  const rerun = root.querySelector<HTMLButtonElement>("#rerun-btn");
  const verify = root.querySelector<HTMLButtonElement>("#verify-btn");
  rerun?.addEventListener("click", async () => {
    rerun.disabled = true;
    setButtonState(rerun, "", "调用中…");
    try {
      await api.runDaily();
      toast("已重跑今日预测", "success");
      void load(root);
    } catch (err: any) {
      toast(err?.message || "重跑失败", "error");
    } finally {
      rerun.disabled = false;
      setButtonState(rerun, "", "立即重跑预测");
    }
  });
  verify?.addEventListener("click", async () => {
    verify.disabled = true;
    setButtonState(verify, "", "校验中…");
    try {
      const yesterday = new Date(Date.now() - 86400 * 1000).toISOString().slice(0, 10);
      const res = await api.verifyDaily(yesterday);
      toast(res.verified ? "已校验昨日预测" : "昨日预测尚不可校验", res.verified ? "success" : "info");
      void load(root);
    } catch (err: any) {
      toast(err?.message || "校验失败", "error");
    } finally {
      verify.disabled = false;
      setButtonState(verify, "", "校验昨日");
    }
  });
}

async function load(root: HTMLElement) {
  try {
    const [today, list, accuracy, calibration] = await Promise.all([
      api.todayPrediction(),
      api.dailyPredictions("30d"),
      api.accuracy("30d"),
      api.calibration("30d", 5),
    ]);
    renderHero(root, today, accuracy);
    const items = list.items || [];
    renderHistory(root, items);
    renderPredictionCalendar(root.querySelector<HTMLElement>("#calendar")!, items);
    renderCalibrationScatter(root.querySelector<HTMLElement>("#scatter")!, calibration);
    renderSignalRadar(root, today, items);
  } catch (err: any) {
    toast(err?.message || "数据加载失败", "error");
  }
}

function renderHero(root: HTMLElement, prediction: DailyPrediction | null, accuracy: AccuracySnapshot) {
  const eyebrow = root.querySelector<HTMLElement>("#hero-eyebrow");
  const title = root.querySelector<HTMLElement>("#hero-title");
  const dir = root.querySelector<HTMLElement>("#hero-dir");
  const conf = root.querySelector<HTMLElement>("#hero-conf");
  const meta = root.querySelector<HTMLElement>("#hero-meta");
  const reason = root.querySelector<HTMLElement>("#hero-reason");
  const calib = root.querySelector<HTMLElement>("#hero-calibration");
  const sgeEl = root.querySelector<HTMLElement>("#close-sge");
  const comexEl = root.querySelector<HTMLElement>("#close-comex");
  const spreadEl = root.querySelector<HTMLElement>("#spread-row");

  if (!prediction) {
    if (title) title.textContent = "尚无预测";
    if (eyebrow) eyebrow.textContent = "等待今早更新";
    if (dir) dir.textContent = "—";
    if (conf) conf.textContent = "—";
    if (meta) meta.innerHTML = "";
    if (reason) reason.textContent = "正在采集数据，每日凌晨自动生成。";
    if (calib) calib.textContent = "暂无说明";
    return;
  }
  if (eyebrow) eyebrow.textContent = `${prediction.prediction_date} · 明日预测`;
  if (title) title.textContent = `今日 ${prediction.today_direction}`;
  if (dir) dir.textContent = prediction.tomorrow_direction;
  if (conf) conf.textContent = formatPercent(prediction.tomorrow_confidence);
  if (meta) {
    meta.innerHTML = `
      ${prediction.verified_correct === null
        ? `<aurumers-chip label="未验证"></aurumers-chip>`
        : prediction.verified_correct
          ? `<aurumers-chip label="命中" variant="up"></aurumers-chip>`
          : `<aurumers-chip label="未中" variant="down"></aurumers-chip>`}
      <span class="muted">模型 ${escapeHtml(prediction.model_name || "—")}</span>
      <span class="muted">近 30 天准确率 ${formatPercent(accuracy.overall_accuracy)}</span>
      <span class="muted">连续命中 ${accuracy.current_streak}</span>
    `;
  }
  if (reason) reason.textContent = prediction.reasoning_summary || "—";
  if (calib) calib.textContent = chunkText(prediction.calibration_note, 360) || "暂无说明";

  if (sgeEl) sgeEl.textContent = formatNumber(prediction.today_close_sge);
  if (comexEl) comexEl.textContent = formatNumber(prediction.today_close_comex);
  if (spreadEl) {
    const tag = ({
      both: "双源齐备",
      sge_only: "仅上海金可用",
      comex_only: "仅国际金可用",
      neither: "暂缺",
    } as Record<string, string>)[prediction.today_close_source] || prediction.today_close_source;
    spreadEl.textContent = `数据来源 · ${tag}（两者单位不同，不可直接相减）`;
  }
}

function fmtSigned(value: number | null, decimals = 2, suffix = ""): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(decimals)}${suffix}`;
}

function fmtRaw(value: number | null, decimals = 2, suffix = ""): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${value.toFixed(decimals)}${suffix}`;
}

// Gold has historic NEGATIVE correlation with USD index and US real yield,
// POSITIVE correlation with realized vol (ATR proxy). Tone reflects the
// implication for gold price (up = bullish).
function dxyTone(change5d: number | null): SignalTone {
  if (change5d === null) return "neutral";
  if (change5d <= -0.3) return "up";   // USD weakens → gold up
  if (change5d >= 0.3) return "down";  // USD strengthens → gold down
  return "neutral";
}

function us10yTone(change5d: number | null): SignalTone {
  if (change5d === null) return "neutral";
  if (change5d <= -0.5) return "up";
  if (change5d >= 0.5) return "down";
  return "neutral";
}

function rsiTone(rsi: number | null): SignalTone {
  if (rsi === null) return "neutral";
  if (rsi >= 70) return "overbought";  // gold momentum hot
  if (rsi <= 30) return "oversold";    // gold oversold
  return "neutral";
}

function renderSignalRadar(
  root: HTMLElement,
  today: DailyPrediction | null,
  history: DailyPrediction[],
) {
  const host = root.querySelector<HTMLElement>("#signal-radar");
  if (!host) return;

  if (!today) {
    host.innerHTML = `<div class="empty-hint">今日预测尚未生成 — 02:50 北京时间自动产出后再来</div>`;
    return;
  }

  const dxy = today.dxy_value;
  const dxy5d = today.dxy_5d_change_pct;
  const us10y = today.us10y_real_yield;
  const us10y5d = today.us10y_5d_change_pct;
  const atr = today.atr14;
  const rsi = today.rsi14;
  const z = today.dist_ma20_z;

  const allMissing = dxy === null && us10y === null && atr === null && rsi === null && z === null;
  if (allMissing) {
    host.innerHTML = `<div class="empty-hint">这条旧预测没有附带这些指标。</div>`;
    return;
  }

  host.innerHTML = `
    <div class="badges">
      <aurumers-signal-badge
        label="美元强弱"
        value="${fmtRaw(dxy, 2)}"
        delta="${fmtSigned(dxy5d, 2, "%")} 近5天"
        tone="${dxyTone(dxy5d)}"
        hint="美元越强，金价通常越受压"
      ></aurumers-signal-badge>
      <aurumers-signal-badge
        label="美债实际利率"
        value="${fmtRaw(us10y, 2, "%")}"
        delta="${fmtSigned(us10y5d, 2, "%")} 近5天"
        tone="${us10yTone(us10y5d)}"
        hint="利率越高，持有黄金越不划算（金价偏空）"
      ></aurumers-signal-badge>
      <aurumers-signal-badge
        label="近期波动幅度"
        value="${fmtRaw(atr, 2)}"
        tone="neutral"
        hint="金价最近每天大约波动多少"
      ></aurumers-signal-badge>
      <aurumers-signal-badge
        label="买卖力度"
        value="${fmtRaw(rsi, 1)}"
        tone="${rsiTone(rsi)}"
        hint="${rsi !== null && rsi >= 70 ? "涨过头，警惕回调" : rsi !== null && rsi <= 30 ? "跌过头，可能反弹" : "处于正常区间"}"
      ></aurumers-signal-badge>
      <aurumers-signal-badge
        label="偏离近期均价"
        value="${z === null ? "—" : `${z.toFixed(2)}σ`}"
        tone="neutral"
        hint="当前价比近 20 天平均价高还是低"
      ></aurumers-signal-badge>
    </div>
    <div class="sparkline-strip">
      <div class="sparkline-cell">
        <div class="head"><span class="lbl">美元强弱 · 近30天</span><span class="val">${fmtRaw(dxy, 2)}</span></div>
        <div class="spark" id="spark-dxy"></div>
      </div>
      <div class="sparkline-cell">
        <div class="head"><span class="lbl">美债实际利率 · 近30天</span><span class="val">${fmtRaw(us10y, 2, "%")}</span></div>
        <div class="spark" id="spark-us10y"></div>
      </div>
      <div class="sparkline-cell">
        <div class="head"><span class="lbl">买卖力度 · 近30天</span><span class="val">${fmtRaw(rsi, 1)}</span></div>
        <div class="spark" id="spark-rsi"></div>
      </div>
    </div>
  `;

  // Sparkline data — history is DESC by date; reverse to ASC for time series.
  const ordered = [...history].reverse();
  const dxyPoints = ordered.map((p) => ({ date: p.prediction_date, value: p.dxy_value }));
  const us10yPoints = ordered.map((p) => ({ date: p.prediction_date, value: p.us10y_real_yield }));
  const rsiPoints = ordered.map((p) => ({ date: p.prediction_date, value: p.rsi14 }));

  // Defer to next frame so the elements have measured dimensions before ECharts init.
  requestAnimationFrame(() => {
    const dxyEl = host.querySelector<HTMLElement>("#spark-dxy");
    const us10yEl = host.querySelector<HTMLElement>("#spark-us10y");
    const rsiEl = host.querySelector<HTMLElement>("#spark-rsi");
    if (dxyEl) renderSparkline(dxyEl, dxyPoints, { unit: "", decimals: 2 });
    if (us10yEl) renderSparkline(us10yEl, us10yPoints, { unit: "%", decimals: 2 });
    if (rsiEl) renderSparkline(rsiEl, rsiPoints, { unit: "", decimals: 1 });
  });
}

function renderHistory(root: HTMLElement, items: DailyPrediction[]) {
  const body = root.querySelector<HTMLTableSectionElement>("#history-body");
  if (!body) return;
  body.innerHTML = "";
  if (items.length === 0) {
    body.innerHTML = `<tr><td colspan="8" class="muted" style="text-align:center;padding:24px;">暂无历史预测记录</td></tr>`;
    return;
  }
  for (const item of items) {
    const status = item.verified_correct === null
      ? `<aurumers-chip label="未验证"></aurumers-chip>`
      : item.verified_correct
        ? `<aurumers-chip label="命中" variant="up"></aurumers-chip>`
        : `<aurumers-chip label="未中" variant="down"></aurumers-chip>`;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="num">${escapeHtml(item.prediction_date)}</td>
      <td class="num">${formatNumber(item.today_close_sge)}</td>
      <td class="num">${formatNumber(item.today_close_comex)}</td>
      <td><aurumers-chip label="${escapeHtml(item.today_direction)}"></aurumers-chip></td>
      <td><aurumers-chip label="${escapeHtml(item.tomorrow_direction)}"></aurumers-chip></td>
      <td class="num">${formatPercent(item.tomorrow_confidence)}</td>
      <td>${status}</td>
      <td class="num">${formatNumber(item.verified_actual_close)}</td>
    `;
    body.appendChild(tr);
  }
}
