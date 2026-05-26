import * as echarts from "echarts/core";
import { LineChart, ScatterChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  MarkLineComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { TimeSeriesPoint } from "../api/schemas";

echarts.use([
  LineChart,
  ScatterChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  MarkLineComponent,
  CanvasRenderer,
]);

const TREND_COLORS: Record<string, string> = {
  上涨: "#15803d",
  下跌: "#b91c1c",
  震荡: "#a16207",
  未知: "#6b7280",
};

function readVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function escapeHtml(text: unknown): string {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c] as string));
}

export function renderPriceChart(el: HTMLElement, points: TimeSeriesPoint[]): echarts.ECharts {
  const chart = echarts.getInstanceByDom(el) || echarts.init(el, undefined, { renderer: "canvas" });
  const valid = points.filter((p) => Number.isFinite(p.price));

  const accent = readVar("--c-accent", "#b8860b");
  const text = readVar("--c-text", "#0a0a0a");
  const muted = readVar("--c-text-mute", "#7e7a76");
  const surface = readVar("--c-surface", "#fff");
  const border = readVar("--c-border", "#e7e5e4");

  if (valid.length === 0) {
    chart.clear();
    chart.setOption({
      graphic: {
        type: "text",
        left: "center",
        top: "middle",
        style: { text: "暂无数据 · 等待首次分析", fill: muted, font: '13px -apple-system' },
      },
    });
    return chart;
  }

  const times = valid.map((p) => p.time);
  const prices = valid.map((p) => p.price as number);
  const movingAvg = computeMovingAverage(prices, 7);

  const trendScatter = valid.map((p) => ({
    value: [p.time, p.price],
    itemStyle: { color: TREND_COLORS[p.trend] || "#6b7280" },
    meta: p,
  }));

  chart.setOption({
    grid: { left: 56, right: 24, top: 28, bottom: 36 },
    animationDuration: 720,
    animationEasing: "cubicOut",
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "line", lineStyle: { color: border } },
      backgroundColor: surface,
      borderColor: border,
      borderWidth: 1,
      padding: 12,
      textStyle: { color: text, fontSize: 12 },
      formatter: (items: any) => {
        const list = Array.isArray(items) ? items : [items];
        if (list.length === 0) return "";
        const lineEntry = list.find((it: any) => it.seriesName === "price") || list[0];
        const scatter = list.find((it: any) => it.seriesName === "trend-points");
        const meta = scatter?.data?.meta;
        const time = lineEntry.axisValueLabel || lineEntry.axisValue || meta?.time || "";
        let price: number | null = null;
        if (Array.isArray(lineEntry.value)) price = lineEntry.value[1];
        else if (typeof lineEntry.value === "number") price = lineEntry.value;
        const priceText = typeof price === "number" && Number.isFinite(price) ? price.toFixed(2) : "—";
        const trend = meta?.trend || "";
        const status = meta?.status || "";
        const summary = meta?.summary || "";
        const trendColor = TREND_COLORS[trend] || muted;
        return `
          <div style="font-family:-apple-system,sans-serif;color:${text}">
            <div style="font-size:11px;color:${muted};letter-spacing:.04em;text-transform:uppercase;margin-bottom:6px">${escapeHtml(time)}</div>
            <div style="font-size:22px;font-weight:600;letter-spacing:-.02em;font-feature-settings:'tnum'">${priceText}</div>
            <div style="margin-top:4px;font-size:12px;color:${muted}">
              <span style="color:${trendColor}">●</span> ${escapeHtml(trend || "—")} · ${escapeHtml(status || "—")}
            </div>
            ${summary ? `<div style="margin-top:8px;max-width:280px;font-size:12px;line-height:1.5;color:${text}">${escapeHtml(summary)}</div>` : ""}
          </div>`;
      },
    },
    xAxis: {
      type: "category",
      data: times,
      boundaryGap: false,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: muted, fontSize: 11, hideOverlap: true,
        formatter: (v: string) => v.slice(11, 16) },
    },
    yAxis: {
      type: "value",
      scale: true,
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: border, type: "dashed" } },
      axisLabel: { color: muted, fontSize: 11, fontFamily: "ui-monospace, SF Mono", formatter: (v: number) => v.toFixed(0) },
    },
    series: [
      {
        name: "price",
        type: "line",
        data: prices,
        smooth: 0.3,
        showSymbol: false,
        lineStyle: { width: 1.5, color: accent },
        areaStyle: {
          color: {
            type: "linear", x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: "rgba(184, 134, 11, 0.20)" },
              { offset: 1, color: "rgba(184, 134, 11, 0)" },
            ],
          },
        },
        z: 1,
      },
      {
        name: "ma7",
        type: "line",
        data: movingAvg,
        smooth: 0.3,
        showSymbol: false,
        lineStyle: { width: 1, color: muted, type: "dashed", opacity: 0.6 },
        z: 2,
      },
      {
        name: "trend-points",
        type: "scatter",
        data: trendScatter,
        symbolSize: 6,
        z: 3,
        emphasis: { scale: 1.6, itemStyle: { borderColor: surface, borderWidth: 2 } },
      },
    ],
  }, true);

  return chart;
}

function computeMovingAverage(values: number[], window: number): (number | null)[] {
  const out: (number | null)[] = [];
  for (let i = 0; i < values.length; i += 1) {
    if (i < window - 1) {
      out.push(null);
      continue;
    }
    const slice = values.slice(i - window + 1, i + 1);
    out.push(slice.reduce((a, b) => a + b, 0) / slice.length);
  }
  return out;
}
