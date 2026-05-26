import * as d3 from "d3";
import type { CalibrationBucket } from "../api/schemas";

function readVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export function renderCalibrationScatter(el: HTMLElement, buckets: CalibrationBucket[]) {
  el.innerHTML = "";
  const rect = el.getBoundingClientRect();
  const width = Math.max(280, rect.width || 320);
  const height = Math.max(220, rect.height || 240);
  const margin = { top: 14, right: 14, bottom: 32, left: 36 };

  const svg = d3.select(el).append("svg")
    .attr("width", width)
    .attr("height", height)
    .attr("viewBox", `0 0 ${width} ${height}`);

  const innerW = width - margin.left - margin.right;
  const innerH = height - margin.top - margin.bottom;

  const accent = readVar("--c-accent", "#b8860b");
  const muted = readVar("--c-text-mute", "#7e7a76");
  const text = readVar("--c-text", "#0a0a0a");
  const border = readVar("--c-border", "#e7e5e4");

  const root = svg.append("g").attr("transform", `translate(${margin.left}, ${margin.top})`);

  const x = d3.scaleLinear().domain([0, 1]).range([0, innerW]);
  const y = d3.scaleLinear().domain([0, 1]).range([innerH, 0]);

  // axes
  root.append("g")
    .attr("transform", `translate(0, ${innerH})`)
    .call(d3.axisBottom(x).ticks(5).tickFormat(d3.format(".0%")))
    .call((g) => g.selectAll(".domain").attr("stroke", border))
    .call((g) => g.selectAll("line").attr("stroke", border))
    .call((g) => g.selectAll("text").attr("fill", muted).attr("font-size", "11").attr("font-family", "ui-monospace, SF Mono, monospace"));

  root.append("g")
    .call(d3.axisLeft(y).ticks(5).tickFormat(d3.format(".0%")))
    .call((g) => g.selectAll(".domain").attr("stroke", border))
    .call((g) => g.selectAll("line").attr("stroke", border))
    .call((g) => g.selectAll("text").attr("fill", muted).attr("font-size", "11").attr("font-family", "ui-monospace, SF Mono, monospace"));

  // ideal diagonal
  root.append("line")
    .attr("x1", x(0)).attr("y1", y(0))
    .attr("x2", x(1)).attr("y2", y(1))
    .attr("stroke", border).attr("stroke-dasharray", "4 4").attr("stroke-width", 1);

  // axis labels
  root.append("text")
    .attr("x", innerW / 2)
    .attr("y", innerH + 26)
    .attr("text-anchor", "middle")
    .attr("fill", muted)
    .attr("font-size", "11")
    .text("预测置信度");
  root.append("text")
    .attr("x", -innerH / 2)
    .attr("y", -28)
    .attr("text-anchor", "middle")
    .attr("transform", "rotate(-90)")
    .attr("fill", muted)
    .attr("font-size", "11")
    .text("实际命中率");

  if (buckets.length === 0) {
    root.append("text")
      .attr("x", innerW / 2)
      .attr("y", innerH / 2)
      .attr("text-anchor", "middle")
      .attr("fill", muted)
      .attr("font-size", "12")
      .text("样本不足，等待历史预测累积");
    return;
  }

  const sizeScale = d3.scaleSqrt()
    .domain([1, d3.max(buckets, (b) => b.sample_size) || 1])
    .range([4, 14]);

  root.selectAll("circle")
    .data(buckets)
    .enter()
    .append("circle")
    .attr("cx", (d) => x((d.bucket_low + d.bucket_high) / 2))
    .attr("cy", (d) => y(d.hit_rate))
    .attr("r", (d) => sizeScale(d.sample_size))
    .attr("fill", accent)
    .attr("opacity", 0.85)
    .attr("stroke", text)
    .attr("stroke-width", 0.5)
    .append("title")
    .text((d) => `置信 ${(d.bucket_low * 100).toFixed(0)}-${(d.bucket_high * 100).toFixed(0)}% · 命中 ${(d.hit_rate * 100).toFixed(0)}% · 样本 ${d.sample_size}`);
}
