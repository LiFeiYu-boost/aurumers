import { LitElement, css, html } from "lit";
import { customElement, property } from "lit/decorators.js";

interface RangeOption {
  key: string;
  label: string;
}

@customElement("aurumers-range-toggle")
export class RangeToggle extends LitElement {
  static styles = css`
    :host { display: inline-flex; }
    .group {
      display: inline-flex;
      background: var(--c-surface);
      border: 1px solid var(--c-border);
      border-radius: 8px;
      padding: 2px;
      gap: 0;
    }
    button {
      padding: 6px 12px;
      font-size: 12px;
      color: var(--c-text-mute);
      border-radius: 6px;
      transition: background var(--dur-fast) var(--ease-out),
                  color var(--dur-fast) var(--ease-out);
      font-variant-numeric: tabular-nums;
      line-height: 1.2;
    }
    button:hover { color: var(--c-text); }
    button.active {
      background: var(--c-segmented-active-bg);
      color: var(--c-segmented-active-fg);
    }
  `;

  @property({ type: Array }) options: RangeOption[] = [];
  @property() value = "";
  @property() label = "";

  private _select(key: string) {
    this.value = key;
    this.dispatchEvent(new CustomEvent("range-change", {
      detail: { value: key },
      bubbles: true,
      composed: true,
    }));
  }

  render() {
    return html`
      <div class="group" role="group" aria-label="${this.label}">
        ${this.options.map((opt) => html`
          <button
            class="${opt.key === this.value ? "active" : ""}"
            aria-pressed="${opt.key === this.value ? "true" : "false"}"
            @click=${() => this._select(opt.key)}
          >${opt.label}</button>
        `)}
      </div>
    `;
  }
}
