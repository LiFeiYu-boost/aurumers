import { api } from "../api/client";
import { toast } from "../components/Toast";
import { chunkText, escapeHtml, formatNumber, formatSource, safeUrl, statusCssClass, trendCssClass } from "../utils";
import type { AnalysisRecord } from "../api/schemas";

const CSS = `
.rec { padding: 28px 0; }
.rec h1 { margin: 0 0 4px; font-size: clamp(28px, 3.4vw, 36px); font-weight: 600; letter-spacing: -0.022em; }
.rec p.lead { margin: 0 0 22px; color: var(--c-text-soft); max-width: 60ch; }
.filters { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; margin-bottom: 18px; }
.search {
  flex: 1 1 240px;
  display: flex; gap: 8px; align-items: center;
  background: var(--c-surface); border: 1px solid var(--c-border);
  border-radius: 8px; padding: 8px 12px;
  transition: border-color var(--dur-fast) var(--ease-out);
}
.search:focus-within { border-color: var(--c-accent-line); }
.search input { flex: 1; border: 0; outline: 0; background: transparent; color: var(--c-text); font: inherit; font-size: 14px; }
.search svg { color: var(--c-text-mute); }

.records-list {
  display: flex; flex-direction: column; gap: 1px;
  background: var(--c-border);
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  overflow: hidden;
}
.row {
  background: var(--c-surface);
  padding: 14px 18px;
  display: grid;
  grid-template-columns: 110px 1fr auto auto;
  gap: 16px;
  align-items: center;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out);
}
.row:hover { background: var(--c-surface-2); }
.time {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--c-text-mute);
  font-variant-numeric: tabular-nums;
  line-height: 1.3;
}
.time strong { display: block; color: var(--c-text); font-size: 13px; font-weight: 500; }
.summary { font-size: 14px; color: var(--c-text); line-height: 1.5; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.row .meta { font-size: 12px; color: var(--c-text-mute); margin-top: 2px; display: flex; gap: 10px; flex-wrap: wrap; }
.row .meta .num { color: var(--c-text-soft); font-family: var(--font-mono); font-variant-numeric: tabular-nums; }

.empty { padding: 32px; text-align: center; color: var(--c-text-mute); border: 1px dashed var(--c-border); border-radius: 12px; }

.detail-section { margin-top: 22px; }
.detail-section h3 { font-size: 12px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--c-text-mute); margin: 0 0 10px; font-weight: 500; }
.detail-section ul { display: flex; flex-direction: column; gap: 8px; }
.detail-section ul li { padding-left: 14px; position: relative; color: var(--c-text-soft); line-height: 1.6; }
.detail-section ul li::before { content: ""; position: absolute; left: 0; top: 0.7em; width: 4px; height: 4px; border-radius: 50%; background: var(--c-text-faint); }
.detail-section pre.raw {
  margin: 0;
  padding: 12px 14px;
  background: var(--c-bg-soft);
  border: 1px solid var(--c-border);
  border-radius: 8px;
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--c-text-soft);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 280px;
  overflow: auto;
}

@media (max-width: 760px) {
  .row { grid-template-columns: 1fr; }
}
`;

interface State {
  records: AnalysisRecord[];
  filtered: AnalysisRecord[];
  range: string;
  trend: string;
  status: string;
  keyword: string;
}

export function renderRecords(): HTMLElement {
  const root = document.createElement("div");
  root.dataset.title = "历史记录";
  root.innerHTML = `
    <style>${CSS}</style>
    <aurumers-shell>
      <div class="rec shell">
        <span class="section-eyebrow" data-anim="0">分析记录</span>
        <h1 data-anim="0">历史分析记录</h1>
        <p class="lead" data-anim="1">每一次金价分析都保存在这里，点开任意一行可以看到完整结论和当时引用的新闻。</p>

        <div class="filters" data-anim="2">
          <label class="search">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            <input id="search-input" type="text" placeholder="搜索摘要、新闻、建议、来源…" autocomplete="off" />
          </label>
          <aurumers-range-toggle id="range-toggle" label="时间范围"></aurumers-range-toggle>
          <aurumers-range-toggle id="trend-toggle" label="趋势"></aurumers-range-toggle>
          <aurumers-range-toggle id="status-toggle" label="状态"></aurumers-range-toggle>
        </div>

        <div id="empty" class="empty" style="display:none;">没有匹配的记录。试试放宽筛选条件。</div>
        <div id="list" class="records-list"></div>

        <aurumers-drawer id="drawer">
          <div slot="title">
            <span class="section-eyebrow">分析详情</span>
            <h2 id="drawer-title" class="num" style="margin: 4px 0 6px; font-size: 22px; font-weight: 600;">—</h2>
            <div id="drawer-meta" style="font-size: 13px; color: var(--c-text-mute);">—</div>
            <div style="display: flex; gap: 8px; margin-top: 10px;">
              <aurumers-chip id="drawer-trend" label="未知"></aurumers-chip>
              <aurumers-chip id="drawer-status" label="—"></aurumers-chip>
            </div>
          </div>
          <div class="detail-section">
            <h3>摘要</h3>
            <p id="drawer-summary" style="margin:0;color:var(--c-text);line-height:1.7;">—</p>
          </div>
          <div class="detail-section">
            <h3>原因</h3>
            <ul id="drawer-reasons"></ul>
          </div>
          <div class="detail-section">
            <h3>操作建议</h3>
            <p id="drawer-advice" style="margin:0;color:var(--c-text);line-height:1.7;">—</p>
          </div>
          <div class="detail-section">
            <h3>相关新闻</h3>
            <ul id="drawer-news"></ul>
          </div>
          <div class="detail-section">
            <h3>原始模型输出</h3>
            <pre class="raw" id="drawer-raw">—</pre>
          </div>
          <div class="detail-section" style="display: flex; justify-content: flex-end;">
            <button id="drawer-delete" class="btn btn-ghost" style="color: var(--c-down); border-color: var(--c-down-soft);">删除该记录</button>
          </div>
        </aurumers-drawer>
      </div>
      <aurumers-toast-stack></aurumers-toast-stack>
    </aurumers-shell>
  `;

  const state: State = {
    records: [],
    filtered: [],
    range: "24h",
    trend: "all",
    status: "all",
    keyword: "",
  };

  setupToggles(root, state);
  setupSearch(root, state);
  setupDrawer(root);
  void load(root, state);
  return root;
}

function setupToggles(root: HTMLElement, state: State) {
  const range = root.querySelector<HTMLElement>("#range-toggle") as any;
  if (range) {
    range.options = [
      { key: "24h", label: "24h" },
      { key: "7d", label: "7d" },
      { key: "30d", label: "30d" },
      { key: "all", label: "全部" },
    ];
    range.value = "24h";
    range.addEventListener("range-change", (event: Event) => {
      state.range = (event as CustomEvent<{ value: string }>).detail.value;
      applyFilters(root, state);
    });
  }
  const trend = root.querySelector<HTMLElement>("#trend-toggle") as any;
  if (trend) {
    trend.options = [
      { key: "all", label: "全部" },
      { key: "上涨", label: "上涨" },
      { key: "下跌", label: "下跌" },
      { key: "震荡", label: "震荡" },
    ];
    trend.value = "all";
    trend.addEventListener("range-change", (event: Event) => {
      state.trend = (event as CustomEvent<{ value: string }>).detail.value;
      applyFilters(root, state);
    });
  }
  const statusToggle = root.querySelector<HTMLElement>("#status-toggle") as any;
  if (statusToggle) {
    statusToggle.options = [
      { key: "all", label: "全部" },
      { key: "success", label: "成功" },
      { key: "partial", label: "部分" },
      { key: "failed", label: "失败" },
    ];
    statusToggle.value = "all";
    statusToggle.addEventListener("range-change", (event: Event) => {
      state.status = (event as CustomEvent<{ value: string }>).detail.value;
      applyFilters(root, state);
    });
  }
}

function setupSearch(root: HTMLElement, state: State) {
  const input = root.querySelector<HTMLInputElement>("#search-input");
  input?.addEventListener("input", () => {
    state.keyword = input.value;
    applyFilters(root, state);
  });
}

function setupDrawer(root: HTMLElement) {
  const drawer = root.querySelector<HTMLElement>("#drawer") as any;
  const deleteBtn = root.querySelector<HTMLButtonElement>("#drawer-delete");
  deleteBtn?.addEventListener("click", async () => {
    const id = deleteBtn.dataset.id;
    if (!id) return;
    if (!confirm("确定删除这条记录？")) return;
    try {
      await api.deleteRecord(id);
      drawer.open = false;
      toast("已删除", "success");
      const event = new CustomEvent("records-refresh", { bubbles: true, composed: true });
      root.dispatchEvent(event);
    } catch (err: any) {
      toast(err?.message || "删除失败", "error");
    }
  });
  root.addEventListener("records-refresh", () => void loadAndKeepFilters(root));
}

async function loadAndKeepFilters(root: HTMLElement) {
  const range = (root.querySelector<HTMLElement>("#range-toggle") as any)?.value || "24h";
  const trend = (root.querySelector<HTMLElement>("#trend-toggle") as any)?.value || "all";
  const statusVal = (root.querySelector<HTMLElement>("#status-toggle") as any)?.value || "all";
  const keyword = (root.querySelector<HTMLInputElement>("#search-input")?.value || "");
  await load(root, { records: [], filtered: [], range, trend, status: statusVal, keyword } as State);
}

async function load(root: HTMLElement, state: State) {
  try {
    const records = await api.recordsLatest(200);
    state.records = records;
    applyFilters(root, state);
  } catch (err: any) {
    toast(err?.message || "记录加载失败", "error");
  }
}

function inRange(record: AnalysisRecord, range: string): boolean {
  if (range === "all") return true;
  const map: Record<string, number> = { "24h": 24, "7d": 24 * 7, "30d": 24 * 30 };
  const hours = map[range] ?? 24;
  const t = Date.parse((record.time || "").replace(" ", "T"));
  if (!Number.isFinite(t)) return true;
  return t >= Date.now() - hours * 3600 * 1000;
}

function applyFilters(root: HTMLElement, state: State) {
  const keyword = state.keyword.trim().toLowerCase();
  state.filtered = state.records.filter((record) => {
    if (!inRange(record, state.range)) return false;
    if (state.trend !== "all" && record.trend !== state.trend) return false;
    if (state.status !== "all" && record.status !== state.status) return false;
    if (keyword) {
      const blob = [
        record.summary, record.advice, record.source, record.model_name,
        record.trend, record.status, record.price_raw,
        (record.reasons || []).join(" "),
        (record.news || []).map((n) => `${n.title} ${n.source}`).join(" "),
      ].join(" ").toLowerCase();
      if (!blob.includes(keyword)) return false;
    }
    return true;
  });
  renderList(root, state);
}

function renderList(root: HTMLElement, state: State) {
  const empty = root.querySelector<HTMLDivElement>("#empty");
  const list = root.querySelector<HTMLDivElement>("#list");
  if (!empty || !list) return;
  if (state.filtered.length === 0) {
    list.innerHTML = "";
    empty.style.display = "";
    return;
  }
  empty.style.display = "none";
  list.innerHTML = "";
  state.filtered.forEach((record) => {
    const row = document.createElement("div");
    row.className = "row";
    row.innerHTML = `
      <div class="time">
        <strong>${escapeHtml((record.time || "").slice(11, 16))}</strong>
        <span class="num">${escapeHtml((record.time || "").slice(0, 10))}</span>
      </div>
      <div>
        <div class="summary">${escapeHtml(record.summary || "暂无总结")}</div>
        <div class="meta">
          <span class="num">${escapeHtml(record.price_raw || "—")}</span>
          <span>${escapeHtml(formatSource(record.source))}</span>
          <span>${(record.news || []).length} 条新闻</span>
        </div>
      </div>
      <aurumers-chip label="${escapeHtml(record.trend)}"></aurumers-chip>
      <aurumers-chip label="${escapeHtml(record.status)}"></aurumers-chip>
    `;
    row.addEventListener("click", () => openDrawer(root, record));
    list.appendChild(row);
  });
}

function openDrawer(root: HTMLElement, record: AnalysisRecord) {
  const drawer = root.querySelector<HTMLElement>("#drawer") as any;
  if (!drawer) return;
  drawer.titleText = `金价 ${record.price_raw}`;
  (root.querySelector<HTMLElement>("#drawer-title") as HTMLElement).textContent = `金价 ${record.price_raw || "—"}`;
  (root.querySelector<HTMLElement>("#drawer-meta") as HTMLElement).textContent = `${record.time} · ${formatSource(record.source)} · 模型 ${record.model_name || "—"}`;
  const trendChip = root.querySelector<HTMLElement>("#drawer-trend") as any;
  if (trendChip) trendChip.label = record.trend;
  const statusChip = root.querySelector<HTMLElement>("#drawer-status") as any;
  if (statusChip) statusChip.label = record.status;
  (root.querySelector<HTMLElement>("#drawer-summary") as HTMLElement).textContent = record.summary || "暂无总结";
  (root.querySelector<HTMLElement>("#drawer-advice") as HTMLElement).textContent = record.advice || "暂无建议";
  const reasons = root.querySelector<HTMLUListElement>("#drawer-reasons");
  if (reasons) {
    reasons.innerHTML = "";
    (record.reasons.length ? record.reasons : ["暂无原因"]).forEach((r) => {
      const li = document.createElement("li");
      li.textContent = r;
      reasons.appendChild(li);
    });
  }
  const news = root.querySelector<HTMLUListElement>("#drawer-news");
  if (news) {
    news.innerHTML = "";
    if (!record.news.length) {
      const li = document.createElement("li");
      li.textContent = "暂无相关新闻";
      news.appendChild(li);
    } else {
      record.news.forEach((item, idx) => {
        const li = document.createElement("li");
        const a = document.createElement("a");
        a.href = safeUrl(item.link);
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        const num = document.createElement("span");
        num.textContent = String(idx + 1).padStart(2, "0");
        num.style.cssText = "color: var(--c-text-faint); margin-right: 8px; font-family: var(--font-mono);";
        const title = document.createElement("span");
        title.textContent = item.title || "(无标题)";
        a.append(num, title);
        li.appendChild(a);
        news.appendChild(li);
      });
    }
  }
  (root.querySelector<HTMLElement>("#drawer-raw") as HTMLElement).textContent = record.raw_output || "—";
  const deleteBtn = root.querySelector<HTMLButtonElement>("#drawer-delete");
  if (deleteBtn) deleteBtn.dataset.id = record.id;
  drawer.open = true;
}
