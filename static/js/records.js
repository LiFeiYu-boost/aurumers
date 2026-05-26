import { showToast, safeUrl } from "./animations.js";

const TREND_CHIP = { "上涨": "chip-up", "下跌": "chip-down", "震荡": "chip-flat", "未知": "chip-unknown" };
const STATUS_CHIP = { success: "chip-up", partial: "chip-flat", failed: "chip-down" };
const STATUS_LABEL = { success: "成功", partial: "部分成功", failed: "失败" };

const state = {
    records: [],
    filtered: [],
    range: "24h",
    keyword: "",
    trend: "all",
    status: "all",
};

function unwrap(payload) {
    if (!payload || payload.success === false) {
        throw new Error((payload && payload.error) || "请求失败");
    }
    return payload.data;
}

function escapeHtml(text) {
    return String(text || "").replace(/[&<>"']/g, (c) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
}

function inRange(timeStr) {
    if (state.range === "all") return true;
    const now = new Date();
    const map = { "24h": 24, "7d": 24 * 7, "30d": 24 * 30 };
    const hours = map[state.range] ?? 24;
    const cutoff = now.getTime() - hours * 3600 * 1000;
    const t = Date.parse(timeStr.replace(" ", "T"));
    return Number.isFinite(t) ? t >= cutoff : true;
}

function applyFilters() {
    const keyword = state.keyword.trim().toLowerCase();
    state.filtered = state.records.filter((record) => {
        if (!inRange(record.time || "")) return false;
        if (state.trend !== "all" && record.trend !== state.trend) return false;
        if (state.status !== "all" && record.status !== state.status) return false;
        if (keyword) {
            const blob = [
                record.summary,
                record.advice,
                record.source,
                record.model_name,
                record.trend,
                record.status,
                record.price_raw,
                (record.reasons || []).join(" "),
                (record.news || []).map((n) => `${n.title || ""} ${n.source || ""}`).join(" "),
            ].join(" ").toLowerCase();
            if (!blob.includes(keyword)) return false;
        }
        return true;
    });
    renderList();
}

function renderList() {
    const container = document.getElementById("records-host");
    const empty = document.getElementById("records-empty");
    if (!container || !empty) return;

    if (state.filtered.length === 0) {
        container.innerHTML = "";
        empty.style.display = "";
        return;
    }
    empty.style.display = "none";
    container.innerHTML = state.filtered.map((record, index) => `
        <div class="record-row" data-index="${index}">
            <div class="record-time">
                <strong>${escapeHtml((record.time || "").slice(11, 16))}</strong>
                <span class="num">${escapeHtml((record.time || "").slice(0, 10))}</span>
            </div>
            <div>
                <div class="record-summary">${escapeHtml(record.summary || "暂无总结")}</div>
                <div class="record-meta">
                    <span class="num">${escapeHtml(record.price_raw || "—")}</span>
                    <span>${escapeHtml(record.source || "manual")}</span>
                    <span>${(record.news || []).length} 条新闻</span>
                </div>
            </div>
            <span class="chip ${TREND_CHIP[record.trend] || "chip-unknown"}">${escapeHtml(record.trend || "未知")}</span>
            <span class="chip ${STATUS_CHIP[record.status] || "chip-unknown"}">${escapeHtml(STATUS_LABEL[record.status] || record.status || "—")}</span>
        </div>
    `).join("");

    container.querySelectorAll(".record-row").forEach((row) => {
        row.addEventListener("click", () => {
            const idx = Number(row.getAttribute("data-index"));
            openDrawer(state.filtered[idx]);
        });
    });
}

function openDrawer(record) {
    if (!record) return;
    const drawer = document.getElementById("drawer");
    const backdrop = document.getElementById("drawer-backdrop");
    if (!drawer || !backdrop) return;

    document.getElementById("drawer-title").textContent = `金价 ${record.price_raw || "—"}`;
    document.getElementById("drawer-meta").textContent =
        `${record.time || "—"} · ${record.source || "manual"} · ${record.model_name || "—"}`;

    const trendNode = document.getElementById("drawer-trend");
    trendNode.className = `chip ${TREND_CHIP[record.trend] || "chip-unknown"}`;
    trendNode.textContent = record.trend || "未知";

    const statusNode = document.getElementById("drawer-status");
    statusNode.className = `chip ${STATUS_CHIP[record.status] || "chip-unknown"}`;
    statusNode.textContent = STATUS_LABEL[record.status] || record.status || "—";

    document.getElementById("drawer-summary").textContent = record.summary || "暂无总结";
    document.getElementById("drawer-advice").textContent = record.advice || "暂无建议";
    document.getElementById("drawer-error").textContent = record.error || "无";
    document.getElementById("drawer-confidence").textContent =
        Number.isFinite(record.confidence) ? `${(record.confidence * 100).toFixed(0)}%` : "—";

    const reasonHost = document.getElementById("drawer-reasons");
    reasonHost.innerHTML = "";
    const reasons = (record.reasons || []).filter(Boolean);
    if (reasons.length === 0) {
        const li = document.createElement("li");
        li.textContent = "暂无原因分析";
        reasonHost.appendChild(li);
    } else {
        reasons.forEach((r) => {
            const li = document.createElement("li");
            li.textContent = r;
            reasonHost.appendChild(li);
        });
    }

    const newsHost = document.getElementById("drawer-news");
    newsHost.innerHTML = "";
    (record.news || []).forEach((item, index) => {
        const li = document.createElement("li");
        const a = document.createElement("a");
        a.href = safeUrl(item.link);
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        const num = document.createElement("span");
        num.className = "num";
        num.textContent = String(index + 1).padStart(2, "0");
        const title = document.createElement("span");
        title.textContent = item.title || "(无标题)";
        a.append(num, title);
        li.appendChild(a);
        newsHost.appendChild(li);
    });
    if ((record.news || []).length === 0) {
        const li = document.createElement("li");
        li.className = "empty";
        li.textContent = "暂无相关新闻";
        newsHost.appendChild(li);
    }

    document.getElementById("drawer-raw").textContent = record.raw_output || "（无）";

    const deleteBtn = document.getElementById("drawer-delete");
    deleteBtn.dataset.id = record.id;

    drawer.classList.add("open");
    backdrop.classList.add("open");
}

function closeDrawer() {
    document.getElementById("drawer")?.classList.remove("open");
    document.getElementById("drawer-backdrop")?.classList.remove("open");
}

async function loadRecords() {
    try {
        const data = await fetch("/api/records/latest?n=200").then((r) => r.json());
        state.records = unwrap(data) || [];
        applyFilters();
    } catch (error) {
        showToast(error.message || "记录加载失败");
    }
}

async function deleteCurrent() {
    const button = document.getElementById("drawer-delete");
    const id = button?.dataset.id;
    if (!id) return;
    if (!confirm("确定删除这条记录？")) return;
    try {
        const response = await fetch(`/api/records/${id}`, { method: "DELETE" });
        const result = await response.json();
        if (!result.success) throw new Error(result.error || "删除失败");
        showToast("已删除");
        closeDrawer();
        await loadRecords();
    } catch (error) {
        showToast(error.message || "删除失败");
    }
}

function bindFilters() {
    function makeGroup(attr, stateKey) {
        document.querySelectorAll(`[${attr}]`).forEach((node) => {
            node.addEventListener("click", () => {
                state[stateKey] = node.getAttribute(attr);
                document.querySelectorAll(`[${attr}]`).forEach((n) => {
                    const active = n === node;
                    n.classList.toggle("active", active);
                    n.setAttribute("aria-pressed", active ? "true" : "false");
                });
                applyFilters();
            });
        });
    }
    makeGroup("data-range", "range");
    makeGroup("data-trend", "trend");
    makeGroup("data-status-filter", "status");
    const search = document.getElementById("search-input");
    if (search) {
        search.addEventListener("input", () => {
            state.keyword = search.value;
            applyFilters();
        });
    }
}

function bindDrawer() {
    document.getElementById("drawer-close")?.addEventListener("click", closeDrawer);
    document.getElementById("drawer-backdrop")?.addEventListener("click", closeDrawer);
    document.getElementById("drawer-delete")?.addEventListener("click", deleteCurrent);
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") closeDrawer();
    });
}

function init() {
    bindFilters();
    bindDrawer();
    loadRecords();
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
} else {
    init();
}
