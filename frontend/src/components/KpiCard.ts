import { LitElement, css, html } from "lit";
import { customElement, property } from "lit/decorators.js";

@customElement("aurumers-kpi")
export class KpiCard extends LitElement {
  static styles = css`
    :host {
      display: block;
    }
    .card {
      background: var(--c-surface);
      border: 1px solid var(--c-border);
      border-radius: var(--r-md);
      padding: 18px 20px;
      box-shadow: var(--shadow-sm);
      transition: transform var(--dur-base) var(--ease-spring),
                  box-shadow var(--dur-base) var(--ease-out),
                  border-color var(--dur-fast) var(--ease-out);
      position: relative;
      overflow: hidden;
    }
    .card:hover {
      transform: translateY(-2px);
      box-shadow: var(--shadow-md);
      border-color: var(--c-border-strong);
    }
    .label {
      font-size: 11px;
      color: var(--c-text-mute);
      letter-spacing: 0.08em;
      text-transform: uppercase;
      font-weight: 500;
    }
    .value {
      margin-top: 10px;
      font-size: 30px;
      font-weight: 600;
      letter-spacing: -0.03em;
      line-height: 1.05;
      color: var(--c-text);
      font-family: var(--font-mono);
      font-variant-numeric: tabular-nums;
    }
    .suffix {
      margin-left: 4px;
      font-size: 16px;
      color: var(--c-text-mute);
      font-weight: 500;
    }
    .foot {
      margin-top: 12px;
      font-size: 12px;
      color: var(--c-text-mute);
      display: flex;
      gap: 6px;
      align-items: center;
      min-height: 14px;
    }
    .delta {
      font-family: var(--font-mono);
      font-variant-numeric: tabular-nums;
      font-size: 11px;
      padding: 2px 6px;
      border-radius: 4px;
    }
    .delta-up { color: var(--c-up); background: var(--c-up-soft); }
    .delta-down { color: var(--c-down); background: var(--c-down-soft); }
    .delta-flat { color: var(--c-text-mute); background: var(--c-bg-soft); }
  `;

  @property() label = "";
  @property() value: string | number = "—";
  @property() suffix = "";
  @property() foot = "";
  @property({ type: Number }) delta = NaN;
  @property() deltaUnit = "";

  private get deltaDisplay(): { class: string; text: string } | null {
    if (!Number.isFinite(this.delta)) return null;
    if (this.delta > 0) return { class: "delta-up", text: `+${this.delta.toFixed(2)}${this.deltaUnit}` };
    if (this.delta < 0) return { class: "delta-down", text: `${this.delta.toFixed(2)}${this.deltaUnit}` };
    return { class: "delta-flat", text: `±0${this.deltaUnit}` };
  }

  render() {
    const delta = this.deltaDisplay;
    return html`
      <div class="card">
        <div class="label">${this.label}</div>
        <div class="value">
          ${this.value}<span class="suffix">${this.suffix}</span>
        </div>
        <div class="foot">
          ${delta ? html`<span class="delta ${delta.class}">${delta.text}</span>` : null}
          <span>${this.foot}</span>
        </div>
      </div>
    `;
  }
}
