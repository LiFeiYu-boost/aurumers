import { LitElement, css, html } from "lit";
import { customElement, state } from "lit/decorators.js";
import { api } from "../api/client";

@customElement("aurumers-live-ticker")
export class LiveTicker extends LitElement {
  static styles = css`
    :host {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 8px 14px;
      border-radius: 999px;
      background: var(--c-surface);
      border: 1px solid var(--c-border);
      box-shadow: var(--shadow-sm);
      font-size: 13px;
      color: var(--c-text-soft);
    }
    .pulse {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--c-up);
      box-shadow: 0 0 0 0 rgba(21, 128, 61, 0.42);
      animation: pulse 1.6s ease-out infinite;
    }
    .pulse.closed {
      background: var(--c-text-mute);
      animation: none;
      box-shadow: none;
    }
    @keyframes pulse {
      0%   { box-shadow: 0 0 0 0 rgba(21, 128, 61, 0.45); }
      80%  { box-shadow: 0 0 0 10px rgba(21, 128, 61, 0); }
      100% { box-shadow: 0 0 0 0 rgba(21, 128, 61, 0); }
    }
    .num {
      font-family: var(--font-mono);
      font-variant-numeric: tabular-nums;
      color: var(--c-text);
      font-weight: 600;
      letter-spacing: -0.01em;
    }
    .delta {
      font-family: var(--font-mono);
      font-size: 12px;
      padding: 2px 6px;
      border-radius: 4px;
    }
    .delta-up { color: var(--c-up); background: var(--c-up-soft); }
    .delta-down { color: var(--c-down); background: var(--c-down-soft); }
    .label-meta {
      font-size: 11px;
      color: var(--c-text-mute);
      letter-spacing: 0.04em;
    }
  `;

  @state() private price = "—";
  @state() private delta: number | null = null;
  @state() private label = "实时金价";
  @state() private comexOpen: boolean | null = null;
  @state() private dataTime: string | null = null;
  private _timer = 0;
  private _previous: number | null = null;

  connectedCallback(): void {
    super.connectedCallback();
    void this._poll();
    this._timer = window.setInterval(() => void this._poll(), 15000);
  }
  disconnectedCallback(): void {
    super.disconnectedCallback();
    if (this._timer) clearInterval(this._timer);
  }

  private async _poll() {
    try {
      const data = await api.price();
      const value = typeof data.price_value === "number" ? data.price_value : null;
      if (value !== null) {
        this.price = value.toFixed(2);
        if (this._previous !== null) {
          this.delta = Number((value - this._previous).toFixed(2));
        }
        this._previous = value;
      } else {
        this.price = data.price_raw || "—";
      }
      this.comexOpen = data.comex_open;
      this.dataTime = data.data_timestamp || null;
      if (data.comex_open === false) {
        this.label = "周末/休市";
      } else if (data.comex_open === true) {
        this.label = "实时金价";
      } else {
        this.label = data.data_label || "金价";
      }
    } catch {
      // silent
    }
  }

  render() {
    let deltaCls = "";
    let deltaText = "";
    if (this.comexOpen !== false && this.delta !== null && Math.abs(this.delta) > 0.001) {
      deltaCls = this.delta > 0 ? "delta-up" : "delta-down";
      deltaText = `${this.delta > 0 ? "+" : ""}${this.delta}`;
    }
    const closedTag = this.comexOpen === false && this.dataTime
      ? html`<span class="label-meta">截至 ${this.dataTime}</span>`
      : null;
    return html`
      <span class="pulse ${this.comexOpen === false ? "closed" : ""}" aria-hidden="true"></span>
      <span>${this.label}</span>
      <span class="num">${this.price}</span>
      ${deltaText ? html`<span class="delta ${deltaCls}">${deltaText}</span>` : null}
      ${closedTag}
    `;
  }
}
