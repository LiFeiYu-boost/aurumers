import { LitElement, css, html } from "lit";
import { customElement, property } from "lit/decorators.js";

@customElement("aurumers-drawer")
export class Drawer extends LitElement {
  static styles = css`
    :host { display: contents; }
    .backdrop {
      position: fixed; inset: 0;
      background: rgba(15, 12, 8, 0.34);
      opacity: 0;
      pointer-events: none;
      transition: opacity var(--dur-base) var(--ease-out);
      z-index: 90;
      backdrop-filter: blur(2px);
    }
    .panel {
      position: fixed;
      top: 0; right: 0; bottom: 0;
      width: min(620px, 100%);
      background: var(--c-bg);
      border-left: 1px solid var(--c-border);
      box-shadow: var(--shadow-lg);
      transform: translateX(100%);
      transition: transform var(--dur-slow) var(--ease-spring);
      z-index: 100;
      overflow-y: auto;
      padding: 24px 28px 64px;
    }
    :host([open]) .panel { transform: translateX(0); }
    :host([open]) .backdrop { opacity: 1; pointer-events: auto; }
    .head {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 16px;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--c-border);
    }
    .close-btn {
      width: 32px; height: 32px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      color: var(--c-text-mute);
      border-radius: 6px;
      transition: background var(--dur-fast) var(--ease-out),
                  color var(--dur-fast) var(--ease-out);
    }
    .close-btn:hover { color: var(--c-text); background: var(--c-surface); }
    @media (max-width: 540px) {
      .panel { padding: 18px 16px 36px; }
    }
  `;

  @property({ type: Boolean, reflect: true }) open = false;
  @property() titleText = "";

  connectedCallback(): void {
    super.connectedCallback();
    document.addEventListener("keydown", this._onKey);
  }
  disconnectedCallback(): void {
    super.disconnectedCallback();
    document.removeEventListener("keydown", this._onKey);
  }
  private _onKey = (event: KeyboardEvent) => {
    if (event.key === "Escape" && this.open) this._close();
  };
  private _close = () => {
    this.open = false;
    this.dispatchEvent(new CustomEvent("close", { bubbles: true, composed: true }));
  };

  render() {
    return html`
      <div class="backdrop" @click=${this._close}></div>
      <aside class="panel" role="dialog" aria-hidden=${!this.open}>
        <div class="head">
          <slot name="title">${this.titleText}</slot>
          <button class="close-btn" @click=${this._close} aria-label="关闭">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>
        <slot></slot>
      </aside>
    `;
  }
}
