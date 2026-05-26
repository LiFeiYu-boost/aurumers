import * as d3 from "d3";
import type { DailyPrediction } from "../api/schemas";

function readVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export function renderPredictionCalendar(el: HTMLElement, predictions: DailyPrediction[]) {
  el.innerHTML = "";
  const rect = el.getBoundingClientRect();
  const width = Math.max(280, rect.width || 360);
  const cellSize = Math.max(14, Math.floor((width - 36) / 7) - 4);
  const cellPadding = 4;
  const columns = 7;

  const muted = readVar("--c-text-mute", "#7e7a76");
  const border = readVar("--c-border", "#e7e5e4");
  const surface = readVar("--c-surface", "#fff");

  const today = new Date();
  const days = 35; // 5 weeks
  const start = new Date(today);
  start.setDate(today.getDate() - days + 1);

  const map = new Map(predictions.map((p) => [p.prediction_date, p]));

  const rows = Math.ceil(days / columns);
  const height = rows * (cellSize + cellPadding) + 28;

  const svg = d3.select(el).append("svg")
    .attr("width", width)
    .attr("height", height)
    .attr("viewBox", `0 0 ${width} ${height}`);

  const root = svg.append("g").attr("transform", `translate(18, 22)`);

  // weekday labels
  const weekdays = ["日", "一", "二", "三", "四", "五", "六"];
  root.selectAll("text.weekday")
    .data(weekdays)
    .enter()
    .append("text")
    .attr("class", "weekday")
    .attr("x", (_, i) => i * (cellSize + cellPadding) + cellSize / 2)
    .attr("y", -8)
    .attr("text-anchor", "middle")
    .attr("font-size", 10)
    .attr("fill", muted)
    .text((d) => d);

  for (let i = 0; i < days; i += 1) {
    const day = new Date(start);
    day.setDate(start.getDate() + i);
    const iso = day.toISOString().slice(0, 10);
    const col = i % columns;
    const row = Math.floor(i / columns);
    const x = col * (cellSize + cellPadding);
    const y = row * (cellSize + cellPadding);
    const prediction = map.get(iso);
    let fill = surface;
    let stroke = border;
    let label = "";
    if (prediction) {
      if (prediction.verified_correct === true) { fill = "rgba(21, 128, 61, 0.10)"; stroke = "rgba(21, 128, 61, 0.42)"; label = "✓"; }
      else if (prediction.verified_correct === false) { fill = "rgba(185, 28, 28, 0.10)"; stroke = "rgba(185, 28, 28, 0.42)"; label = "✗"; }
      else { fill = "rgba(184, 134, 11, 0.08)"; stroke = "rgba(184, 134, 11, 0.38)"; label = "·"; }
    }
    const cell = root.append("g").attr("transform", `translate(${x}, ${y})`);
    cell.append("rect")
      .attr("width", cellSize)
      .attr("height", cellSize)
      .attr("rx", 3)
      .attr("fill", fill)
      .attr("stroke", stroke)
      .attr("stroke-width", 0.7);
    cell.append("text")
      .attr("x", 4)
      .attr("y", 11)
      .attr("font-size", 9)
      .attr("font-family", "ui-monospace, SF Mono, monospace")
      .attr("fill", muted)
      .text(day.getDate().toString());
    if (label) {
      cell.append("text")
        .attr("x", cellSize / 2)
        .attr("y", cellSize - 6)
        .attr("text-anchor", "middle")
        .attr("font-size", 11)
        .attr("font-weight", 600)
        .attr("fill", stroke)
        .text(label);
    }
    cell.append("title")
      .text(prediction
        ? `${iso} · 预测 ${prediction.tomorrow_direction}（置信 ${prediction.tomorrow_confidence ?? 0}）${prediction.verified_correct === null ? '· 未验证' : prediction.verified_correct ? '· 命中' : '· 未中'}`
        : `${iso} · 暂无记录`);
  }
}
