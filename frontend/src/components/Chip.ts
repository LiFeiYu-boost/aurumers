import { LitElement, css, html } from "lit";
import { customElement, property } from "lit/decorators.js";

interface StyleEntry { cls: string; display?: string }

// Maps raw label values (Chinese trends + English statuses from the API) to
// chip color class + an optional Chinese display override. Lets pages pass
// `label="success"` and have the chip render "成功" with the right color.
const STYLE_MAP: Record<string, StyleEntry> = {
  上涨: { cls: "chip-up" },
  下跌: { cls: "chip-down" },
  震荡: { cls: "chip-flat" },
  未知: { cls: "chip-unknown" },
  success: { cls: "chip-up", display: "成功" },
  partial: { cls: "chip-flat", display: "部分" },
  failed: { cls: "chip-down", display: "失败" },
};

@customElement("aurumers-chip")
export class Chip extends LitElement {
  static styles = css`
    :host { display: inline-flex; }
    .chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 10px;
      border-radius: 6px;
      font-size: 12px;
      font-weight: 500;
      border: 1px solid transparent;
      letter-spacing: 0.01em;
      line-height: 1.2;
    }
    .chip::before {
      content: "";
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: currentColor;
      opacity: 0.85;
    }
    .chip-up      { color: var(--c-up);      background: var(--c-up-soft);      border-color: var(--c-up-soft); }
    .chip-down    { color: var(--c-down);    background: var(--c-down-soft);    border-color: var(--c-down-soft); }
    .chip-flat    { color: var(--c-flat);    background: var(--c-flat-soft);    border-color: var(--c-flat-soft); }
    .chip-unknown { color: var(--c-unknown); background: var(--c-unknown-soft); border-color: var(--c-unknown-soft); }
    .chip-accent  { color: var(--c-accent);  background: var(--c-accent-soft);  border-color: var(--c-accent-line); }
    .chip-strong  { color: var(--c-surface); background: var(--c-text); border-color: var(--c-text); }
  `;

  @property() label = "";
  @property() variant = "";

  render() {
    const entry = STYLE_MAP[this.label];
    const cls = entry?.cls || (this.variant ? `chip-${this.variant}` : "chip-unknown");
    const text = entry?.display || this.label || "—";
    return html`<span class="chip ${cls}">${text}</span>`;
  }
}
