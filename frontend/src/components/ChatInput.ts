import { LitElement, css, html } from "lit";
import { customElement, property, state } from "lit/decorators.js";

@customElement("aurumers-chat-input")
export class ChatInput extends LitElement {
  static styles = css`
    :host {
      display: block;
      position: sticky;
      bottom: 0;
      background: linear-gradient(to top, var(--c-bg) 70%, transparent);
      padding: 12px 8px 16px;
    }
    .wrap {
      display: flex;
      gap: 10px;
      align-items: flex-end;
      border: 1px solid var(--c-border);
      background: var(--c-surface);
      border-radius: var(--r-md);
      padding: 8px 10px 8px 14px;
      box-shadow: var(--shadow-sm);
      transition: border-color var(--dur-fast) var(--ease-out), box-shadow var(--dur-fast) var(--ease-out);
    }
    .wrap:focus-within {
      border-color: var(--c-accent-line);
      box-shadow: var(--shadow-md);
    }
    textarea {
      flex: 1;
      resize: none;
      outline: none;
      border: 0;
      background: transparent;
      color: var(--c-text);
      font: inherit;
      font-size: 15px;
      line-height: 1.55;
      max-height: 220px;
      min-height: 24px;
      padding: 6px 0;
      font-family: var(--font-sans);
    }
    button.send {
      align-self: flex-end;
      background: var(--c-text);
      color: var(--c-bg);
      border-radius: 12px;
      width: 40px;
      height: 40px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      transition: opacity var(--dur-fast) var(--ease-out), transform var(--dur-fast) var(--ease-out);
    }
    button.send[disabled] { opacity: 0.4; cursor: not-allowed; }
    button.send:hover:not([disabled]) { transform: translateY(-1px); }
    .meta {
      display: flex;
      justify-content: space-between;
      font-size: 11px;
      color: var(--c-text-mute);
      margin-top: 6px;
      padding: 0 4px;
    }
    .meta .warn { color: var(--c-down); }
  `;

  @property({ type: Boolean }) disabled = false;
  @state() private value = "";

  private get charCount(): number {
    return this.value.length;
  }

  private _onInput(event: Event) {
    const target = event.target as HTMLTextAreaElement;
    this.value = target.value;
    target.style.height = "auto";
    target.style.height = `${Math.min(target.scrollHeight, 220)}px`;
  }

  private _onKeyDown(event: KeyboardEvent) {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      this._submit();
    }
  }

  private _submit() {
    const trimmed = this.value.trim();
    if (!trimmed || this.disabled) return;
    if (trimmed.length > 4000) return;
    this.dispatchEvent(new CustomEvent("send", {
      detail: { content: trimmed },
      bubbles: true,
      composed: true,
    }));
    this.value = "";
    const ta = this.renderRoot.querySelector("textarea");
    if (ta) ta.style.height = "auto";
  }

  render() {
    const overflowed = this.charCount > 4000;
    return html`
      <div class="wrap">
        <textarea
          rows="1"
          placeholder="问问 Hermes 关于黄金行情或网站使用… (Enter 发送 / Shift+Enter 换行)"
          .value=${this.value}
          @input=${this._onInput}
          @keydown=${this._onKeyDown}
          ?disabled=${this.disabled}
        ></textarea>
        <button class="send" @click=${this._submit} ?disabled=${this.disabled || !this.value.trim() || overflowed} aria-label="发送">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="22" y1="2" x2="11" y2="13"></line>
            <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
          </svg>
        </button>
      </div>
      <div class="meta">
        <span>Hermes 仅解答黄金行情与本站使用相关问题</span>
        <span class=${overflowed ? "warn" : ""}>${this.charCount} / 4000</span>
      </div>
    `;
  }
}
