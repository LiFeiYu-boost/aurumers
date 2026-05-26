import { api } from "../api/client";
import { escapeHtml, formatNumber, formatPercent } from "../utils";

const HERO_CSS = `
.landing { position: relative; }
.hero {
  position: relative;
  padding: 80px 0 64px;
  isolation: isolate;
}
.hero-inner {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: 48px;
  align-items: center;
}
.hero h1 {
  margin: 0 0 18px;
  font-size: clamp(48px, 6.4vw, 78px);
  font-weight: 600;
  line-height: 1.04;
  letter-spacing: -0.025em;
  background: linear-gradient(180deg, var(--c-text) 0%, color-mix(in srgb, var(--c-text) 70%, var(--c-bg-soft)) 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.hero h1 .gold {
  background: var(--gradient-mark);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.hero p.lead {
  margin: 0 0 30px;
  color: var(--c-text-soft);
  font-size: 17px;
  line-height: 1.65;
  max-width: 56ch;
}
.hero-cta { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
.hero-side {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.hero-card {
  background: color-mix(in srgb, var(--c-surface) 88%, transparent);
  backdrop-filter: blur(12px);
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  padding: 22px 24px;
  box-shadow: var(--shadow-md);
}
.hero-card .label {
  font-size: 11px;
  color: var(--c-text-mute);
  letter-spacing: 0.12em;
  text-transform: uppercase;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.hero-card .pred-direction {
  font-size: 56px;
  font-weight: 600;
  letter-spacing: -0.04em;
  font-family: var(--font-mono);
  color: var(--c-text);
  line-height: 1.05;
  margin-bottom: 6px;
}
.hero-card .pred-meta {
  color: var(--c-text-mute);
  font-size: 13px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}
.hero-card .pred-summary {
  margin-top: 14px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--c-text-soft);
}
.hero-pill { padding: 4px 10px; border-radius: 999px; font-size: 12px; }

.value-row {
  margin-top: 64px;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 20px;
}
.value-row .vc {
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  padding: 24px;
  transition: transform var(--dur-base) var(--ease-spring), box-shadow var(--dur-base);
}
.value-row .vc:hover { transform: translateY(-3px); box-shadow: var(--shadow-md); }
.value-row .icon {
  width: 36px; height: 36px;
  border-radius: 10px;
  background: var(--c-accent-soft);
  color: var(--c-accent);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 14px;
}
.value-row h3 { margin: 0 0 8px; font-size: 16px; font-weight: 600; letter-spacing: -0.01em; }
.value-row p { margin: 0; color: var(--c-text-mute); font-size: 14px; line-height: 1.6; }

.flow {
  margin-top: 96px;
  text-align: left;
  position: relative;
}
.flow .grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  margin-top: 24px;
}
.flow .step {
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: 12px;
  padding: 22px 22px 24px;
  position: relative;
}
.flow .step::before {
  content: counter(step);
  counter-increment: step;
  position: absolute;
  top: 18px; right: 20px;
  font-family: var(--font-mono);
  color: var(--c-accent);
  font-size: 12px;
  letter-spacing: 0.04em;
}
.flow .grid { counter-reset: step; }
.flow .step h4 { margin: 0 0 8px; font-size: 15px; font-weight: 600; }
.flow .step p { margin: 0; font-size: 13px; color: var(--c-text-mute); line-height: 1.6; }

.cta-band {
  margin-top: 96px;
  padding: 56px 48px;
  border-radius: var(--r-md);
  background:
    radial-gradient(800px 360px at 80% 0%, rgba(212, 165, 45, 0.32), transparent 60%),
    var(--c-text);
  color: var(--c-bg);
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 32px;
  box-shadow: var(--shadow-lg);
}
.cta-band h2 {
  margin: 0;
  font-size: clamp(22px, 2.4vw, 30px);
  font-weight: 600;
  letter-spacing: -0.02em;
  max-width: 30ch;
}
.cta-band a {
  background: var(--c-bg);
  color: var(--c-text);
  padding: 12px 22px;
  border-radius: 10px;
  font-weight: 500;
  font-size: 14px;
  transition: transform var(--dur-fast) var(--ease-out);
}
.cta-band a:hover { transform: translateY(-1px); }

@media (max-width: 960px) {
  .hero { padding: 56px 0 32px; }
  .hero-inner { grid-template-columns: 1fr; gap: 28px; }
  .value-row { grid-template-columns: 1fr; }
  .flow .grid { grid-template-columns: 1fr 1fr; }
  .cta-band { padding: 32px 24px; flex-direction: column; align-items: flex-start; }
}
@media (max-width: 760px) {
  .flow .grid { grid-template-columns: 1fr; }
}
`;

export function renderLanding(): HTMLElement {
  const root = document.createElement("div");
  root.dataset.title = "封面";
  root.innerHTML = `
    <style>${HERO_CSS}</style>
    <aurumers-shell>
      <div class="landing shell">
        <section class="hero">
          <aurumers-orb></aurumers-orb>
          <div class="hero-inner">
            <div data-anim="0">
              <h1>把行情、新闻、历史预测，<br/>翻译成一份<span class="gold">可校准</span>的判断。</h1>
              <p class="lead">Aurumers 每日 02:50 北京时间自动产出今日金价定性与次日方向预测，过去命中率与置信度校准全程留痕，新闻面 + 多源行情双轨输入，模型输出可追溯、可比对、可订正。</p>
              <div class="hero-cta">
                <a href="/app" class="btn btn-primary" data-route>进入应用</a>
                <a href="/app/chat" class="btn btn-ghost" data-route>和 Hermes 聊聊金价</a>
                <a href="/app/predictions" class="btn btn-ghost" data-route>明日预测</a>
                <aurumers-live-ticker></aurumers-live-ticker>
              </div>
            </div>
            <div class="hero-side" data-anim="2">
              <div class="hero-card">
                <div class="label">下一份预测</div>
                <div class="pred-direction" id="hero-pred">—</div>
                <div class="pred-meta" id="hero-meta">等待 02:50 调度</div>
                <div class="pred-summary" id="hero-summary">系统初始化中…</div>
              </div>
              <aurumers-countdown></aurumers-countdown>
            </div>
          </div>
        </section>

        <section class="value-row">
          <div class="vc" data-anim="3">
            <div class="icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
            </div>
            <h3>双源收盘交叉验证</h3>
            <p>SGE 上海黄金交易所夜场收盘 + COMEX 国际黄金期货收盘，双轨拉取互为校验，单源失效自动降级。</p>
          </div>
          <div class="vc" data-anim="4">
            <div class="icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            </div>
            <h3>02:50 北京时间自动定调</h3>
            <p>每日固定时点产出今日定性 + 次日方向，调度由 Hermes 框架托管，挂钟触发不漂移、Cron 重试不重复。</p>
          </div>
          <div class="vc" data-anim="5">
            <div class="icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20v-6"/><path d="M6 20V10"/><path d="M18 20V4"/></svg>
            </div>
            <h3>历史命中率与基线对照</h3>
            <p>每条预测次日自动比对实际收盘，命中/未中持久化；同时与持续性 / MA(5) 两条朴素基线并行记录，是否真的优于基线，留给数据回答。</p>
          </div>
        </section>

        <section class="flow">
          <span class="section-eyebrow">运转节奏</span>
          <h2 class="h-display h-display-md">从抓数到推送，全自动闭环。</h2>
          <div class="grid">
            <div class="step" data-anim="3">
              <h4>采集</h4>
              <p>30 分钟轮询金价/新闻 + SGE 夜场 + COMEX 日 K，多源去抖。</p>
            </div>
            <div class="step" data-anim="4">
              <h4>分析</h4>
              <p>LangChain 编排 LLM，输出结构化趋势、置信度、原因 3 条、操作建议。</p>
            </div>
            <div class="step" data-anim="5">
              <h4>校准</h4>
              <p>每日 03:10 用次日实际收盘比对，回填命中率与失误模式。</p>
            </div>
            <div class="step" data-anim="6">
              <h4>推送</h4>
              <p>Webhook / Telegram / 飞书 / 企业微信 / 邮件全通道留接口，配齐即用。</p>
            </div>
          </div>
        </section>

        <section class="cta-band" data-anim="6">
          <h2>把模型的每次判断都留痕、可比、可订正。</h2>
          <a href="/app" data-route>进入看板 →</a>
        </section>
      </div>
      <aurumers-toast-stack></aurumers-toast-stack>
    </aurumers-shell>
  `;

  void hydrateHero(root);
  return root;
}

async function hydrateHero(root: HTMLElement) {
  try {
    const prediction = await api.todayPrediction();
    const directionEl = root.querySelector<HTMLDivElement>("#hero-pred");
    const metaEl = root.querySelector<HTMLDivElement>("#hero-meta");
    const summaryEl = root.querySelector<HTMLDivElement>("#hero-summary");
    if (!directionEl || !metaEl || !summaryEl) return;
    if (!prediction) {
      directionEl.textContent = "—";
      metaEl.textContent = "等待首次 02:50 触发";
      summaryEl.textContent = "服务正在持续抓取数据中。";
      return;
    }
    directionEl.textContent = prediction.tomorrow_direction;
    const isToday = prediction.is_today !== false;
    const dateLabel = isToday
      ? `${prediction.prediction_date} 预测次日`
      : `${prediction.prediction_date} 旧版预测（待今日 02:50 刷新）`;
    metaEl.innerHTML = `
      <span class="hero-pill chip-accent">${escapeHtml(dateLabel)}</span>
      <span>置信 ${formatPercent(prediction.tomorrow_confidence)}</span>
      <span>近 30 天准确率 ${formatPercent(prediction.accuracy_window_30d)}</span>
    `;
    summaryEl.textContent = prediction.tomorrow_advice || prediction.reasoning_summary || "—";
  } catch {
    /* silent */
  }
}
