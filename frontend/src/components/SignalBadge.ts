import { LitElement, css, html } from "lit";
import { customElement, property } from "lit/decorators.js";

export type SignalTone = "up" | "down" | "neutral" | "overbought" | "oversold";

@customElement("aurumers-signal-badge")
export class SignalBadge extends LitElement {
  static styles = css`
    :host {
      display: block;
    }
    .badge {
      background: var(--c-surface);
      border: 1px solid var(--c-border);
      border-radius: var(--r-md);
      padding: 12px 14px;
      box-shadow: var(--shadow-sm);
      display: flex;
      flex-direction: column;
      gap: 4px;
      transition: border-color var(--dur-fast) var(--ease-out);
      min-height: 76px;
    }
    .badge:hover { border-color: var(--c-border-strong); }
    .label {
      font-size: 10px;
      color: var(--c-text-mute);
      letter-spacing: 0.08em;
      text-transform: uppercase;
      font-weight: 500;
    }
    .value-row {
      display: flex;
      align-items: baseline;
      gap: 8px;
      flex-wrap: wrap;
    }
    .value {
      font-size: 20px;
      font-weight: 600;
      letter-spacing: -0.02em;
      font-family: var(--font-mono);
      font-variant-numeric: tabular-nums;
      line-height: 1.1;
      color: var(--c-text);
    }
    .delta {
      font-family: var(--font-mono);
      font-variant-numeric: tabular-nums;
      font-size: 11px;
      padding: 2px 6px;
      border-radius: 4px;
    }
    .hint {
      font-size: 10px;
      color: var(--c-text-mute);
      margin-top: auto;
    }
    /* tone color rails */
    :host([tone="up"]) .badge,
    :host([tone="oversold"]) .badge { border-left: 2px solid var(--c-up); }
    :host([tone="down"]) .badge,
    :host([tone="overbought"]) .badge { border-left: 2px solid var(--c-down); }
    :host([tone="neutral"]) .badge { border-left: 2px solid var(--c-accent); }

    :host([tone="up"]) .delta,
    :host([tone="oversold"]) .delta { color: var(--c-up); background: var(--c-up-soft); }
    :host([tone="down"]) .delta,
    :host([tone="overbought"]) .delta { color: var(--c-down); background: var(--c-down-soft); }
    :host([tone="neutral"]) .delta { color: var(--c-text-mute); background: var(--c-bg-soft); }
  `;

  @property() label = "";
  @property() value: string | number = "—";
  @property() delta = "";
  @property({ reflect: true }) tone: SignalTone = "neutral";
  @property() hint = "";

  render() {
    return html`
      <div class="badge">
        <div class="label">${this.label}</div>
        <div class="value-row">
          <span class="value">${this.value}</span>
          ${this.delta ? html`<span class="delta">${this.delta}</span>` : null}
        </div>
        ${this.hint ? html`<div class="hint">${this.hint}</div>` : null}
      </div>
    `;
  }
}
