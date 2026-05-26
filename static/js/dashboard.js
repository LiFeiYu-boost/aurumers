import { countUp, showToast, safeUrl } from "./animations.js";
import { renderPriceChart, renderTrendDonut, renderHourlyStatus } from "./charts.js";

const TREND_LABEL = { "上涨": "chip-up", "下跌": "chip-down", "震荡": "chip-flat", "未知": "chip-unknown" };

const state = {
    range: "24h",
    priceChart: null,
    donutChart: null,
    hourlyChart: null,
};

function unwrap(payload) {
    if (!payload || payload.success === false) {
        throw new Error((payload && payload.error) || "请求失败");
    }
    return payload.data;
}

async function fetchJson(url) {
    const response = await fetch(url);
    return unwrap(await response.json());
}

function formatPrice(value, fallback = "—") {
    if (!Number.isFinite(value)) return fallback;
    return value.toFixed(2);
}

function setText(id, text) {
    const node = document.getElementById(id);
    if (node) node.textContent = text;
}

function setChip(id, trend) {
    const node = document.getElementById(id);
    if (!node) return;
    const cls = TREND_LABEL[trend] || "chip-unknown";
    node.className = `chip ${cls}`;
    node.textContent = trend || "未知";
}

function setStatusChip(id, status) {
    const node = document.getElementById(id);
    if (!node) return;
    const map = { success: "chip-up", partial: "chip-flat", failed: "chip-down" };
    node.className = `chip ${map[status] || "chip-unknown"}`;
    node.textContent = ({ success: "成功", partial: "部分成功", failed: "失败" }[status]) || status || "未知";
}

function renderLatest(record) {
    if (!record) return;
    setText("hero-price", formatPrice(record.price_value, record.price_raw || "—"));
    setText("hero-time", record.time || "—");
    setChip("hero-trend", record.trend);

    setText("latest-summary", record.summary || "暂无总结");
    setText("latest-advice", record.advice || "暂无建议");
    setText("latest-meta",
        `${record.time || "—"} · 模型 ${record.model_name || "—"} · 来源 ${record.source || "—"}`);
    setChip("latest-trend", record.trend);
    setStatusChip("latest-status", record.status);

    const reasonsHost = document.getElementById("latest-reasons");
    if (reasonsHost) {
        reasonsHost.innerHTML = "";
        const items = (record.reasons || []).filter(Boolean);
        if (items.length === 0) {
            const li = document.createElement("li");
            li.textContent = "暂无原因分析";
            reasonsHost.appendChild(li);
        } else {
            items.forEach((reason) => {
                const li = document.createElement("li");
                li.textContent = reason;
                reasonsHost.appendChild(li);
            });
        }
    }

    const newsHost = document.getElementById("latest-news");
    if (newsHost) {
        newsHost.innerHTML = "";
        const news = record.news || [];
        if (news.length === 0) {
            const li = document.createElement("li");
            li.className = "empty";
            li.textContent = "暂无相关新闻";
            newsHost.appendChild(li);
        } else {
            news.forEach((item, index) => {
                const li = document.createElement("li");
                const a = document.createElement("a");
                a.target = "_blank";
                a.rel = "noopener noreferrer";
                a.href = safeUrl(item.link);
                const indexNode = document.createElement("span");
                indexNode.className = "num";
                indexNode.textContent = String(index + 1).padStart(2, "0");
                const titleNode = document.createElement("span");
                titleNode.textContent = item.title || "(无标题)";
                a.append(indexNode, titleNode);
                li.appendChild(a);
                newsHost.appendChild(li);
            });
        }
    }
}

function escapeHtml(text) {
    return String(text || "").replace(/[&<>"']/g, (c) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
}

function renderKpis(kpi) {
    const priceEl = document.getElementById("kpi-price");
    const avgEl = document.getElementById("kpi-avg");
    const volEl = document.getElementById("kpi-vol");
    const successEl = document.getElementById("kpi-success");

    countUp(priceEl, kpi.latest_price ?? kpi.avg_price ?? 0, { decimals: 2 });
    countUp(avgEl, kpi.avg_price ?? 0, { decimals: 2 });
    countUp(volEl, kpi.volatility ?? 0, { decimals: 2 });
    countUp(successEl, (kpi.success_rate ?? 0) * 100, { decimals: 0, suffix: "%" });

    setText("kpi-foot-runs", `${kpi.total_runs ?? 0} 次分析 · 平均 ${(kpi.avg_latency_ms ?? 0).toFixed(0)}ms`);
    setText("kpi-foot-range", `近 ${labelForRange(state.range)} 数据`);
    setText("kpi-foot-update", kpi.last_updated ? `最近更新 ${kpi.last_updated.slice(11, 16)}` : "等待首次分析");

    if (Number.isFinite(kpi.min_price) && Number.isFinite(kpi.max_price)) {
        setText("kpi-foot-band", `区间 ${kpi.min_price.toFixed(2)} – ${kpi.max_price.toFixed(2)}`);
    } else {
        setText("kpi-foot-band", "—");
    }
}

function labelForRange(range) {
    return ({ "24h": "24 小时", "7d": "7 天", "30d": "30 天", "all": "全部" })[range] || range;
}

async function loadAll() {
    try {
        const [series, kpi, distribution, summary] = await Promise.all([
            fetchJson(`/api/analytics/timeseries?range=${state.range}`),
            fetchJson(`/api/analytics/kpis?range=${state.range}`),
            fetchJson(`/api/analytics/distribution?range=${state.range}`),
            fetchJson("/api/dashboard/summary?limit=1"),
        ]);

        renderKpis(kpi);
        if (summary && summary.latest) renderLatest(summary.latest);
        state.priceChart = renderPriceChart(document.getElementById("chart-price"), series.points || []);
        state.donutChart = renderTrendDonut(document.getElementById("chart-trend"), distribution.trend_counts);
        state.hourlyChart = renderHourlyStatus(document.getElementById("chart-status"), distribution.hourly_status);
    } catch (error) {
        showToast(error.message || "数据加载失败");
    }
}

async function refreshLivePrice() {
    try {
        const data = await fetchJson("/api/price");
        if (data && Number.isFinite(data.price_value)) {
            const heroEl = document.getElementById("hero-price");
            if (heroEl && !heroEl.dataset.locked) {
                countUp(heroEl, data.price_value, { decimals: 2 });
            }
        }
    } catch (_) {
        /* silent */
    }
}

function bindRangeToggle() {
    document.querySelectorAll("[data-range]").forEach((node) => {
        node.addEventListener("click", () => {
            const range = node.getAttribute("data-range");
            if (!range || range === state.range) return;
            state.range = range;
            document.querySelectorAll("[data-range]").forEach((n) => {
                const active = n === node;
                n.classList.toggle("active", active);
                n.setAttribute("aria-pressed", active ? "true" : "false");
            });
            loadAll();
        });
    });
}

function bindRunButton() {
    const button = document.getElementById("btn-run");
    if (!button) return;
    button.addEventListener("click", async () => {
        if (button.dataset.state === "loading") return;
        button.dataset.state = "loading";
        button.querySelector("[data-label]").textContent = "正在分析";
        try {
            const response = await fetch("/api/analysis/run", { method: "POST" });
            const record = unwrap(await response.json());
            renderLatest(record);
            await loadAll();
            showToast("分析完成");
        } catch (error) {
            showToast(error.message || "分析请求失败");
        } finally {
            button.dataset.state = "";
            button.querySelector("[data-label]").textContent = "执行新一次分析";
        }
    });
}

function init() {
    bindRangeToggle();
    bindRunButton();
    loadAll();
    refreshLivePrice();
    setInterval(refreshLivePrice, 15000);
    setInterval(loadAll, 60000);
    window.addEventListener("resize", () => {
        [state.priceChart, state.donutChart, state.hourlyChart].forEach((chart) => {
            if (chart && typeof chart.resize === "function") chart.resize();
        });
    });
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
} else {
    init();
}
