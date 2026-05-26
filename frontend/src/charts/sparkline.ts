import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer]);

function readVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export interface SparklinePoint {
  date: string;        // YYYY-MM-DD
  value: number | null;
}

export interface SparklineOptions {
  color?: string;          // line color; defaults to --c-accent
  unit?: string;           // tooltip suffix, e.g. "%" or " CNY/g"
  decimals?: number;       // tooltip rounding, default 2
  emptyHint?: string;      // shown when no valid points
  showArea?: boolean;      // light area fill, default true
}

/**
 * Render a minimal time-series sparkline (no axis labels / no grid lines).
 * Idempotent: re-rendering on the same `el` reuses the ECharts instance.
 *
 * Used for the macro/technical signal strip on PredictionsPage where multiple
 * compact lines stack vertically. Tooltip on hover surfaces date + value.
 */
export function renderSparkline(
  el: HTMLElement,
  points: SparklinePoint[],
  options: SparklineOptions = {},
): echarts.ECharts {
  const chart = echarts.getInstanceByDom(el) || echarts.init(el, undefined, { renderer: "canvas" });
  const valid = points.filter((p) => Number.isFinite(p.value as number));

  const color = options.color || readVar("--c-accent", "#b8860b");
  const muted = readVar("--c-text-mute", "#7e7a76");
  const surface = readVar("--c-surface", "#ffffff");
  const border = readVar("--c-border", "#e7e5e4");
  const text = readVar("--c-text", "#0a0a0a");
  const decimals = options.decimals ?? 2;
  const unit = options.unit || "";
  const showArea = options.showArea ?? true;

  if (valid.length < 2) {
    chart.clear();
    chart.setOption({
      graphic: {
        type: "text",
        left: "center",
        top: "middle",
        style: {
          text: options.emptyHint || "样本不足",
          fill: muted,
          font: '11px -apple-system',
        },
      },
    });
    return chart;
  }

  const dates = valid.map((p) => p.date);
  const values = valid.map((p) => p.value as number);

  chart.setOption(
    {
      grid: { left: 4, right: 4, top: 6, bottom: 4, containLabel: false },
      animationDuration: 500,
      animationEasing: "cubicOut",
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "line", lineStyle: { color: border, width: 1, type: "solid" } },
        backgroundColor: surface,
        borderColor: border,
        borderWidth: 1,
        textStyle: { color: text, fontSize: 11 },
        padding: [6, 10],
        formatter: (params: any) => {
          const item = Array.isArray(params) ? params[0] : params;
          if (!item) return "";
          const v = (item.value as number).toFixed(decimals);
          return `<div style="font-family: var(--font-mono);">
            <div style="color: ${muted}; font-size: 10px;">${item.axisValueLabel || item.name}</div>
            <div style="margin-top: 2px;">${v}${unit}</div>
          </div>`;
        },
      },
      xAxis: {
        type: "category",
        data: dates,
        show: false,
        boundaryGap: false,
      },
      yAxis: { type: "value", show: false, scale: true },
      series: [
        {
          type: "line",
          data: values,
          showSymbol: false,
          smooth: true,
          lineStyle: { color, width: 1.6 },
          areaStyle: showArea
            ? {
                color: {
                  type: "linear",
                  x: 0, y: 0, x2: 0, y2: 1,
                  colorStops: [
                    { offset: 0, color: `${color}30` },
                    { offset: 1, color: `${color}00` },
                  ],
                },
              }
            : undefined,
        },
      ],
    },
    true,
  );
  return chart;
}
