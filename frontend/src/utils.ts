export function escapeHtml(text: unknown): string {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c] as string));
}

export function safeUrl(value: unknown): string {
  const text = String(value || "").trim();
  if (!text) return "#";
  if (/^(https?:|mailto:)/i.test(text)) return text;
  if (text.startsWith("//")) return `https:${text}`;
  if (text.startsWith("/") || text.startsWith("#")) return text;
  return "#";
}

export function formatNumber(value: number | null | undefined, decimals = 2, fallback = "—"): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return fallback;
  return value.toFixed(decimals);
}

export function formatPercent(value: number | null | undefined, decimals = 0, fallback = "—"): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return fallback;
  return `${(value * 100).toFixed(decimals)}%`;
}

export function trendCssClass(trend: string | null | undefined): string {
  if (trend === "上涨") return "chip-up";
  if (trend === "下跌") return "chip-down";
  if (trend === "震荡") return "chip-flat";
  return "chip-unknown";
}

export function statusCssClass(status: string | null | undefined): string {
  if (status === "success") return "chip-up";
  if (status === "partial") return "chip-flat";
  if (status === "failed") return "chip-down";
  return "chip-unknown";
}

// Translate raw API source identifier to a Chinese label for plain-text rendering.
// Chip-rendered statuses (success/partial/failed) are translated by the Chip component itself.
const SOURCE_LABEL: Record<string, string> = {
  manual: "手动",
  scheduler: "调度",
  cron: "调度",
  hermes: "Hermes",
  api: "API",
};
export function formatSource(source: string | null | undefined): string {
  if (!source) return "手动";
  return SOURCE_LABEL[source] || source;
}

export function chunkText(text: string, max = 160): string {
  if (!text) return "";
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1)}…`;
}

/**
 * Set a button's data-state and inner [data-label] safely.
 * No-op if the elements have been re-rendered out from under us.
 */
export function setButtonState(button: HTMLButtonElement | null, state: "" | "loading", labelText?: string) {
  if (!button) return;
  button.dataset.state = state;
  if (typeof labelText === "string") {
    const label = button.querySelector<HTMLSpanElement>('[data-label]');
    if (label) label.textContent = labelText;
  }
}
