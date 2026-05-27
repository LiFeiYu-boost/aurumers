import { api, type HoldingsAdvice, type OutlookItem } from "../api/client";
import { toast } from "../components/Toast";

const CSS = `
.holdings { padding: 28px 0; }
.holdings h1 { margin: 0 0 4px; font-size: clamp(26px,3vw,34px); font-weight: 600; letter-spacing: -0.02em; }
.holdings p.lead { margin: 0 0 22px; color: var(--c-text-soft); max-width: 640px; line-height: 1.6; }
.holdings .panel { background: var(--c-surface); border: 1px solid var(--c-border); border-radius: var(--r-md); padding: 22px 24px; box-shadow: var(--shadow-sm); margin-top: 16px; }
.holdings .seg { display: inline-flex; border: 1px solid var(--c-border); border-radius: 8px; overflow: hidden; margin-bottom: 16px; }
.holdings .seg button { padding: 8px 16px; font-size: 14px; background: var(--c-bg); color: var(--c-text-soft); border: none; cursor: pointer; }
.holdings .seg button.on { background: var(--c-accent-soft); color: var(--c-text); font-weight: 600; }
.holdings .field { margin-bottom: 12px; }
.holdings .field label { display: block; font-size: 13px; color: var(--c-text-soft); margin-bottom: 5px; }
.holdings input { width: 100%; padding: 10px 14px; font-size: 15px; border: 1px solid var(--c-border); border-radius: 8px; background: var(--c-bg); color: var(--c-text); box-sizing: border-box; }
.holdings .row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.holdings .btn-go { width: 100%; margin-top: 8px; }
.card-head { display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; gap: 8px; }
.dir { font-size: 22px; font-weight: 700; letter-spacing: -0.01em; }
.dir.up { color: #16a34a; } .dir.down { color: #dc2626; } .dir.flat { color: var(--c-text-soft); }
.chips { display: flex; gap: 8px; flex-wrap: wrap; margin: 12px 0; }
.chip { font-size: 12px; padding: 4px 10px; border-radius: 999px; background: var(--c-accent-soft); color: var(--c-text); border: 1px solid var(--c-border); }
.chip.warn { background: #fef3c7; color: #92400e; border-color: #fde68a; }
.kv { display: grid; grid-template-columns: auto 1fr; gap: 4px 16px; font-size: 14px; margin-top: 8px; }
.kv .k { color: var(--c-text-mute); } .kv .v { text-align: right; font-variant-numeric: tabular-nums; }
.pnl-pos { color: #16a34a; } .pnl-neg { color: #dc2626; }
.headline { font-size: 16px; line-height: 1.6; margin: 14px 0 6px; }
.risk { font-size: 13px; color: var(--c-text-soft); line-height: 1.6; }
.detail-toggle { margin-top: 12px; font-size: 14px; color: var(--c-accent, #b8860b); background: none; border: none; cursor: pointer; padding: 0; text-decoration: underline; }
.detail-box { margin-top: 10px; padding: 12px 14px; background: var(--c-bg); border: 1px dashed var(--c-border); border-radius: 8px; font-size: 14px; line-height: 1.7; }
.disclaimer { margin-top: 18px; font-size: 12px; color: var(--c-text-mute); line-height: 1.7; border-top: 1px solid var(--c-border); padding-top: 12px; }
.outlook { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 6px; }
@media (max-width: 640px) { .outlook { grid-template-columns: 1fr; } }
.ocard { background: var(--c-surface); border: 1px solid var(--c-border); border-radius: var(--r-md); padding: 16px 18px; box-shadow: var(--shadow-sm); }
.ocard .olabel { font-size: 13px; color: var(--c-text-soft); }
.ocard .odir { font-size: 20px; font-weight: 700; margin: 6px 0 2px; }
.ocard .odir.up { color: #16a34a; } .ocard .odir.down { color: #dc2626; }
.ocard .ometric { font-size: 13px; color: var(--c-text-mute); line-height: 1.7; }
.ocard .acc { font-weight: 600; color: var(--c-text); }
.section-h { font-size: 15px; font-weight: 600; margin: 22px 0 4px; }
.section-sub { font-size: 12px; color: var(--c-text-mute); margin-bottom: 4px; }
`;

export function renderHoldings(): HTMLElement {
  const root = document.createElement("div");
  root.dataset.title = "持仓助手";
  root.innerHTML = `
    <style>${CSS}</style>
    <aurumers-shell>
      <div class="holdings shell">
        <h1>持仓助手</h1>
        <p class="lead">基于多周期趋势模型,给出未来 1–3 个月的方向展望与持仓参考。
          本工具<strong>仅供参考、非投资建议</strong>。</p>
        <div class="section-h">多周期趋势展望</div>
        <div class="section-sub">周期越长方向越可判断;括号内为该周期的历史样本外命中率(2010–2026)。</div>
        <div class="outlook" id="outlook"><div class="ocard"><div class="ometric">加载中…</div></div></div>
        <div class="section-h">持仓建议</div>
        <div class="panel">
          <div class="seg">
            <button data-mode="cost" class="on">成本价 × 克数</button>
            <button data-mode="value">总价值(元)</button>
          </div>
          <div id="form-cost">
            <div class="row2">
              <div class="field"><label>成本价(元/克)</label><input id="cost" type="number" inputmode="decimal" placeholder="如 880" /></div>
              <div class="field"><label>持有克数(克)</label><input id="grams" type="number" inputmode="decimal" placeholder="如 50" /></div>
            </div>
          </div>
          <div id="form-value" style="display:none">
            <div class="field"><label>持仓总价值(元)</label><input id="value" type="number" inputmode="decimal" placeholder="如 50000" /></div>
          </div>
          <button id="go" class="btn btn-primary btn-go">获取持仓建议</button>
        </div>
        <div id="result"></div>
      </div>
      <aurumers-toast-stack></aurumers-toast-stack>
    </aurumers-shell>
  `;

  let mode: "cost" | "value" = "cost";
  root.querySelectorAll<HTMLButtonElement>(".seg button").forEach((b) => {
    b.addEventListener("click", () => {
      mode = b.dataset.mode as "cost" | "value";
      root.querySelectorAll(".seg button").forEach((x) => x.classList.toggle("on", x === b));
      (root.querySelector("#form-cost") as HTMLElement).style.display = mode === "cost" ? "" : "none";
      (root.querySelector("#form-value") as HTMLElement).style.display = mode === "value" ? "" : "none";
    });
  });

  const num = (id: string) => {
    const v = parseFloat(root.querySelector<HTMLInputElement>(id)?.value ?? "");
    return Number.isFinite(v) ? v : undefined;
  };
  const fmt = (n: number) => n.toLocaleString("zh-CN", { maximumFractionDigits: 2 });

  root.querySelector("#go")?.addEventListener("click", async () => {
    let body: { grams?: number; cost_per_g?: number; value_cny?: number };
    if (mode === "cost") {
      const grams = num("#grams");
      if (!grams) { toast("请输入持有克数", "error"); return; }
      body = { grams, cost_per_g: num("#cost") };
    } else {
      const value_cny = num("#value");
      if (!value_cny) { toast("请输入持仓总价值", "error"); return; }
      body = { value_cny };
    }
    const btn = root.querySelector<HTMLButtonElement>("#go")!;
    btn.disabled = true; btn.textContent = "计算中…";
    try {
      const r = await api.signal.advice(body);
      renderResult(root.querySelector("#result")!, r, fmt);
    } catch (e: any) {
      toast(e?.message || "获取失败", "error");
    } finally {
      btn.disabled = false; btn.textContent = "获取持仓建议";
    }
  });

  // 多周期展望(进页面即加载)
  api.signal.outlook()
    .then((r) => renderOutlook(root.querySelector("#outlook")!, r.outlook))
    .catch(() => {
      const el = root.querySelector("#outlook");
      if (el) el.innerHTML = `<div class="ocard"><div class="ometric">展望暂不可用</div></div>`;
    });

  return root;
}

function renderOutlook(el: Element, items: OutlookItem[]) {
  el.innerHTML = items.map((o) => {
    const up = o.direction === "看多";
    const acc = o.accuracy != null ? `${(o.accuracy * 100).toFixed(0)}%` : "—";
    return `
      <div class="ocard">
        <div class="olabel">${o.label}</div>
        <div class="odir ${up ? "up" : "down"}">${o.direction}</div>
        <div class="ometric">上涨概率 ${(o.prob_up * 100).toFixed(0)}%</div>
        <div class="ometric">历史命中 <span class="acc">${acc}</span></div>
        ${o.skill_pp != null ? `<div class="ometric" style="font-size:12px;">较“始终看涨”基准高 ${o.skill_pp} 个百分点</div>` : ""}
      </div>`;
  }).join("");
}

function renderResult(el: Element, r: HoldingsAdvice, fmt: (n: number) => string) {
  const s = r.signal;
  const dirClass = s.direction === "看多" ? "up" : s.direction === "看空" ? "down" : "flat";
  const pnl = r.holdings.pnl;
  const pnlHtml = pnl
    ? `<div class="k">成本</div><div class="v">¥${fmt(pnl.cost_basis)}</div>
       <div class="k">浮动盈亏</div><div class="v ${pnl.pnl >= 0 ? "pnl-pos" : "pnl-neg"}">${pnl.pnl >= 0 ? "+" : ""}¥${fmt(pnl.pnl)}（${pnl.pnl_pct >= 0 ? "+" : ""}${pnl.pnl_pct}%）</div>`
    : "";
  const d = r.advice.detail;
  const detailHtml = d.type === "reduce" && d.sell_grams_range
    ? `<button class="detail-toggle" id="dt">▸ 查看具体调整区间</button>
       <div class="detail-box" id="db" style="display:none">
         参考减持区间:约 <strong>${d.sell_grams_range[0]}–${d.sell_grams_range[1]} 克</strong>
         （约 ¥${fmt(d.sell_value_range![0])}–¥${fmt(d.sell_value_range![1])}）。
         <br>这是把黄金仓位降到信号建议水平的参考量,不是精确指令,请结合自身情况分批操作。
       </div>`
    : `<div class="detail-box">当前信号不建议减仓。${s.direction === "看多" ? "如计划加仓,需在你的黄金配置上限内顺势进行。" : "建议持有观望,等趋势转明确。"}</div>`;

  const crowd = s.crowding === "偏高" ? `<span class="chip warn">投机持仓拥挤</span>`
    : s.crowding === "偏低" ? `<span class="chip">持仓不拥挤</span>` : "";

  el.innerHTML = `
    <div class="panel">
      <div class="card-head">
        <span class="dir ${dirClass}">趋势${s.direction}</span>
        <span style="color:var(--c-text-mute);font-size:13px">截至 ${s.asof} · ${s.horizon}</span>
      </div>
      <div class="chips">
        <span class="chip">把握 ${s.confidence}</span>
        <span class="chip">上涨概率 ${(s.prob_up * 100).toFixed(0)}%</span>
        <span class="chip">${s.horizon_agreement}/3 看多一致</span>
        ${crowd}
      </div>
      <div class="kv">
        <div class="k">当前金价</div><div class="v">¥${fmt(r.holdings.price_per_g)}/克</div>
        <div class="k">你的持仓</div><div class="v">${fmt(r.holdings.grams)} 克 · ¥${fmt(r.holdings.current_value)}</div>
        ${pnlHtml}
      </div>
      <div class="headline">${r.advice.headline}</div>
      <div class="risk">${r.advice.risk_note}</div>
      ${detailHtml}
      <div class="disclaimer">⚠ ${r.disclaimer}</div>
    </div>
  `;
  const dt = el.querySelector("#dt");
  dt?.addEventListener("click", () => {
    const db = el.querySelector<HTMLElement>("#db")!;
    const open = db.style.display !== "none";
    db.style.display = open ? "none" : "";
    dt.textContent = (open ? "▸" : "▾") + " 查看具体调整区间";
  });
}
