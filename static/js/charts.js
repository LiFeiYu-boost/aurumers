// ECharts wrappers — Apple/Stripe-grade financial visuals.

const TREND_COLORS = {
    "上涨": "#15803d",
    "下跌": "#b91c1c",
    "震荡": "#a16207",
    "未知": "#9ca3af",
};

const STATUS_COLORS = {
    success: "#15803d",
    partial: "#a16207",
    failed:  "#b91c1c",
};

function readVar(name, fallback) {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
}

function escapeHtml(text) {
    return String(text == null ? "" : text).replace(/[&<>"']/g, (c) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
}

function tooltipShell(content) {
    return `<div style="font-family:-apple-system,sans-serif;color:${readVar("--c-text", "#0a0a0a")};">${content}</div>`;
}

export function renderPriceChart(domEl, points) {
    if (!domEl || typeof echarts === "undefined") return null;
    const chart = echarts.getInstanceByDom(domEl) || echarts.init(domEl, null, { renderer: "canvas" });
    const valid = (points || []).filter((p) => Number.isFinite(p.price));

    if (valid.length === 0) {
        chart.clear();
        chart.setOption({
            graphic: {
                type: "text",
                left: "center",
                top: "middle",
                style: {
                    text: "暂无数据 · 等待首次分析",
                    fill: readVar("--c-text-mute", "#8a8682"),
                    font: '13px -apple-system, sans-serif',
                },
            },
        });
        return chart;
    }

    const times = valid.map((p) => p.time);
    const prices = valid.map((p) => p.price);

    const trendScatter = valid.map((p) => ({
        value: [p.time, p.price],
        itemStyle: { color: TREND_COLORS[p.trend] || "#9ca3af" },
        meta: p,
    }));

    const accent = readVar("--c-accent", "#b8860b");
    const textColor = readVar("--c-text", "#0a0a0a");
    const mutedColor = readVar("--c-text-mute", "#8a8682");
    const borderColor = readVar("--c-border", "#e7e5e4");

    chart.setOption({
        grid: { left: 56, right: 24, top: 24, bottom: 36, containLabel: false },
        animationDuration: 720,
        animationEasing: "cubicOut",
        tooltip: {
            trigger: "axis",
            axisPointer: { type: "line", lineStyle: { color: borderColor } },
            backgroundColor: readVar("--c-surface", "#ffffff"),
            borderColor,
            borderWidth: 1,
            padding: 12,
            textStyle: { color: textColor, fontSize: 12 },
            formatter: (items) => {
                const list = Array.isArray(items) ? items : (items ? [items] : []);
                if (list.length === 0) return "";
                const lineEntry = list.find((it) => it.seriesName === "price") || list[0];
                const scatterEntry = list.find((it) => it.seriesName === "trend-points");
                const meta = scatterEntry && scatterEntry.data && scatterEntry.data.meta
                    ? scatterEntry.data.meta
                    : null;

                const rawTime = lineEntry.axisValueLabel || lineEntry.axisValue || (meta && meta.time) || "";
                let price = null;
                if (Array.isArray(lineEntry.value)) {
                    price = lineEntry.value[1];
                } else if (typeof lineEntry.value === "number") {
                    price = lineEntry.value;
                } else if (scatterEntry && Array.isArray(scatterEntry.value)) {
                    price = scatterEntry.value[1];
                }
                const priceText = typeof price === "number" && Number.isFinite(price)
                    ? price.toFixed(2)
                    : "—";

                const trend = meta ? meta.trend : "";
                const status = meta ? meta.status : "";
                const summary = meta && meta.summary ? meta.summary : "";
                const trendColor = TREND_COLORS[trend] || mutedColor;
                return tooltipShell(`
                    <div style="font-size:11px;color:${mutedColor};letter-spacing:.04em;text-transform:uppercase;margin-bottom:6px;">${escapeHtml(rawTime)}</div>
                    <div style="font-size:20px;font-weight:600;letter-spacing:-.02em;font-feature-settings:'tnum';">${priceText}</div>
                    <div style="margin-top:4px;font-size:12px;color:${mutedColor};">
                        <span style="color:${trendColor}">●</span>
                        ${escapeHtml(trend || "—")} · ${escapeHtml(status || "—")}
                    </div>
                    ${summary ? `<div style="margin-top:8px;max-width:280px;font-size:12px;color:${textColor};line-height:1.5;">${escapeHtml(summary)}</div>` : ""}
                `);
            },
        },
        xAxis: {
            type: "category",
            data: times,
            axisLine: { show: false },
            axisTick: { show: false },
            axisLabel: {
                color: mutedColor,
                fontSize: 11,
                hideOverlap: true,
                formatter: (value) => (value || "").slice(11, 16),
            },
            boundaryGap: false,
        },
        yAxis: {
            type: "value",
            scale: true,
            axisLine: { show: false },
            axisTick: { show: false },
            splitLine: { lineStyle: { color: borderColor, type: "dashed" } },
            axisLabel: {
                color: mutedColor,
                fontSize: 11,
                fontFamily: readVar("--font-mono", "ui-monospace"),
                formatter: (value) => Number(value).toFixed(0),
            },
        },
        series: [
            {
                name: "price",
                type: "line",
                data: prices,
                smooth: 0.32,
                showSymbol: false,
                lineStyle: { width: 1.5, color: accent },
                areaStyle: {
                    color: {
                        type: "linear",
                        x: 0, y: 0, x2: 0, y2: 1,
                        colorStops: [
                            { offset: 0, color: "rgba(184, 134, 11, 0.18)" },
                            { offset: 1, color: "rgba(184, 134, 11, 0)" },
                        ],
                    },
                },
                emphasis: { focus: "series" },
                z: 1,
            },
            {
                name: "trend-points",
                type: "scatter",
                data: trendScatter,
                symbolSize: 6,
                z: 2,
                emphasis: {
                    scale: 1.6,
                    itemStyle: { borderColor: readVar("--c-surface", "#fff"), borderWidth: 2 },
                },
            },
        ],
    }, true);

    return chart;
}

export function renderTrendDonut(domEl, counts) {
    if (!domEl || typeof echarts === "undefined") return null;
    const chart = echarts.getInstanceByDom(domEl) || echarts.init(domEl, null, { renderer: "canvas" });
    const data = ["上涨", "震荡", "下跌", "未知"]
        .map((name) => ({ name, value: counts?.[name] ?? 0, itemStyle: { color: TREND_COLORS[name] } }))
        .filter((item) => item.value > 0);

    const textColor = readVar("--c-text", "#0a0a0a");
    const mutedColor = readVar("--c-text-mute", "#8a8682");
    const surface = readVar("--c-surface", "#ffffff");

    if (data.length === 0) {
        chart.clear();
        chart.setOption({
            graphic: {
                type: "text",
                left: "center",
                top: "middle",
                style: { text: "暂无数据", fill: mutedColor, font: '13px -apple-system, sans-serif' },
            },
        });
        return chart;
    }

    chart.setOption({
        animationDuration: 720,
        animationEasing: "cubicOut",
        tooltip: {
            trigger: "item",
            backgroundColor: surface,
            borderColor: readVar("--c-border", "#e7e5e4"),
            borderWidth: 1,
            padding: 10,
            textStyle: { color: textColor, fontSize: 12 },
            formatter: (item) => `${item.name}<br/><span style="font-feature-settings:'tnum';font-weight:600;">${item.value}</span> 条 (${item.percent}%)`,
        },
        legend: {
            orient: "horizontal",
            bottom: 4,
            icon: "circle",
            itemWidth: 8,
            itemHeight: 8,
            textStyle: { color: mutedColor, fontSize: 12 },
            itemGap: 16,
        },
        series: [
            {
                name: "trend",
                type: "pie",
                radius: ["52%", "78%"],
                center: ["50%", "44%"],
                avoidLabelOverlap: true,
                label: { show: false },
                itemStyle: {
                    borderColor: surface,
                    borderWidth: 2,
                    borderRadius: 2,
                },
                emphasis: {
                    scale: true,
                    scaleSize: 6,
                    label: {
                        show: true,
                        formatter: "{b}\n{d}%",
                        color: textColor,
                        fontSize: 13,
                        fontWeight: 600,
                    },
                },
                data,
            },
        ],
    }, true);

    return chart;
}

export function renderHourlyStatus(domEl, hourly) {
    if (!domEl || typeof echarts === "undefined") return null;
    const chart = echarts.getInstanceByDom(domEl) || echarts.init(domEl, null, { renderer: "canvas" });

    const data = hourly || [];
    const buckets = data.map((row) => row.bucket || "");
    const series = ["success", "partial", "failed"].map((status) => ({
        name: status,
        type: "bar",
        stack: "status",
        emphasis: { focus: "series" },
        itemStyle: { color: STATUS_COLORS[status], borderRadius: [2, 2, 0, 0] },
        data: data.map((row) => row[status] || 0),
        barMaxWidth: 14,
    }));

    const textColor = readVar("--c-text", "#0a0a0a");
    const mutedColor = readVar("--c-text-mute", "#8a8682");
    const surface = readVar("--c-surface", "#ffffff");
    const borderColor = readVar("--c-border", "#e7e5e4");

    if (data.length === 0) {
        chart.clear();
        chart.setOption({
            graphic: {
                type: "text",
                left: "center",
                top: "middle",
                style: { text: "暂无数据", fill: mutedColor, font: '13px -apple-system, sans-serif' },
            },
        });
        return chart;
    }

    chart.setOption({
        animationDuration: 720,
        animationEasing: "cubicOut",
        grid: { left: 36, right: 16, top: 24, bottom: 28 },
        tooltip: {
            trigger: "axis",
            axisPointer: { type: "shadow" },
            backgroundColor: surface,
            borderColor,
            borderWidth: 1,
            padding: 10,
            textStyle: { color: textColor, fontSize: 12 },
        },
        legend: {
            data: ["success", "partial", "failed"],
            icon: "circle",
            itemWidth: 8,
            itemHeight: 8,
            top: 0,
            right: 0,
            textStyle: { color: mutedColor, fontSize: 12 },
        },
        xAxis: {
            type: "category",
            data: buckets,
            axisLine: { show: false },
            axisTick: { show: false },
            axisLabel: {
                color: mutedColor,
                fontSize: 11,
                hideOverlap: true,
                formatter: (value) => (value || "").slice(11),
            },
        },
        yAxis: {
            type: "value",
            axisLine: { show: false },
            axisTick: { show: false },
            splitLine: { lineStyle: { color: borderColor, type: "dashed" } },
            minInterval: 1,
            axisLabel: { color: mutedColor, fontSize: 11 },
        },
        series,
    }, true);

    return chart;
}

export function bindResize(...charts) {
    const list = charts.filter(Boolean);
    if (list.length === 0) return;
    const handler = () => list.forEach((chart) => chart && chart.resize());
    window.addEventListener("resize", handler);
    return () => window.removeEventListener("resize", handler);
}
