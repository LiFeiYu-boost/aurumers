import { LitElement, css, html } from "lit";
import { customElement, state } from "lit/decorators.js";

interface ToastEntry {
  id: number;
  message: string;
  variant: "info" | "success" | "warn" | "error";
}

@customElement("aurumers-toast-stack")
export class ToastStack extends LitElement {
  static styles = css`
    :host {
      position: fixed;
      bottom: 24px;
      left: 50%;
      transform: translateX(-50%);
      display: flex;
      flex-direction: column;
      gap: 10px;
      z-index: 200;
      pointer-events: none;
    }
    .toast {
      pointer-events: auto;
      background: var(--c-text);
      color: var(--c-bg);
      padding: 10px 18px;
      border-radius: 8px;
      font-size: 13px;
      box-shadow: var(--shadow-lg);
      opacity: 0;
      transform: translateY(8px);
      animation: enter 360ms var(--ease-spring) forwards,
                 leave 280ms var(--ease-out) forwards 1.6s;
      max-width: min(560px, calc(100vw - 24px));
      display: inline-flex;
      align-items: center;
      gap: 10px;
    }
    @keyframes enter {
      to { opacity: 1; transform: translateY(0); }
    }
    @keyframes leave {
      to { opacity: 0; transform: translateY(-6px); }
    }
    .dot {
      width: 8px; height: 8px; border-radius: 50%;
      background: var(--c-accent-bright);
    }
    .toast.info .dot     { background: var(--c-accent-bright); }
    .toast.success .dot  { background: var(--c-up); }
    .toast.warn .dot     { background: var(--c-flat); }
    .toast.error .dot    { background: var(--c-down); }
  `;

  @state() private entries: ToastEntry[] = [];
  private nextId = 1;

  connectedCallback(): void {
    super.connectedCallback();
    window.addEventListener("aurumers:toast" as any, this._onToast as EventListener);
  }
  disconnectedCallback(): void {
    super.disconnectedCallback();
    window.removeEventListener("aurumers:toast" as any, this._onToast as EventListener);
  }
  private _onToast = (event: CustomEvent<{ message: string; variant?: ToastEntry["variant"] }>) => {
    const id = this.nextId++;
    const entry: ToastEntry = {
      id,
      message: event.detail.message,
      variant: event.detail.variant || "info",
    };
    this.entries = [...this.entries, entry];
    setTimeout(() => {
      this.entries = this.entries.filter((e) => e.id !== id);
    }, 2400);
  };

  render() {
    return html`
      ${this.entries.map((entry) => html`
        <div class="toast ${entry.variant}" role="status">
          <span class="dot"></span><span>${entry.message}</span>
        </div>
      `)}
    `;
  }
}

export function toast(message: string, variant: ToastEntry["variant"] = "info") {
  window.dispatchEvent(new CustomEvent("aurumers:toast", { detail: { message, variant } }));
}
