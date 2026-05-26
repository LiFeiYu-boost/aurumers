import * as echarts from "echarts/core";
import { PieChart } from "echarts/charts";
import { TooltipComponent, LegendComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([PieChart, TooltipComponent, LegendComponent, CanvasRenderer]);

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

export function renderTrendDonut(el: HTMLElement, counts: Record<string, number>): echarts.ECharts {
  const chart = echarts.getInstanceByDom(el) || echarts.init(el, undefined, { renderer: "canvas" });
  const data = ["上涨", "震荡", "下跌", "未知"]
    .map((name) => ({ name, value: counts?.[name] ?? 0, itemStyle: { color: TREND_COLORS[name] } }))
    .filter((item) => item.value > 0);

  const text = readVar("--c-text", "#0a0a0a");
  const muted = readVar("--c-text-mute", "#7e7a76");
  const surface = readVar("--c-surface", "#fff");
  const border = readVar("--c-border", "#e7e5e4");

  if (data.length === 0) {
    chart.clear();
    chart.setOption({
      graphic: {
        type: "text",
        left: "center",
        top: "middle",
        style: { text: "暂无数据", fill: muted, font: '13px -apple-system' },
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
      borderColor: border,
      borderWidth: 1,
      padding: 10,
      textStyle: { color: text, fontSize: 12 },
      formatter: (item: any) => `${item.name}<br/><span style="font-feature-settings:'tnum';font-weight:600">${item.value}</span> 条 (${item.percent}%)`,
    },
    legend: {
      orient: "horizontal",
      bottom: 4,
      icon: "circle",
      itemWidth: 8,
      itemHeight: 8,
      textStyle: { color: muted, fontSize: 12 },
      itemGap: 16,
    },
    series: [{
      name: "trend",
      type: "pie",
      radius: ["54%", "78%"],
      center: ["50%", "44%"],
      avoidLabelOverlap: true,
      label: { show: false },
      itemStyle: { borderColor: surface, borderWidth: 2, borderRadius: 2 },
      emphasis: {
        scale: true,
        scaleSize: 6,
        label: { show: true, formatter: "{b}\n{d}%", color: text, fontSize: 13, fontWeight: 600 },
      },
      data,
    }],
  }, true);
  return chart;
}
