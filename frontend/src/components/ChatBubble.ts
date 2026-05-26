import { LitElement, css, html } from "lit";
import { customElement, property } from "lit/decorators.js";

@customElement("aurumers-chat-bubble")
export class ChatBubble extends LitElement {
  static styles = css`
    :host {
      display: flex;
      width: 100%;
      margin-bottom: 14px;
    }
    :host([variant="user"]) {
      justify-content: flex-end;
    }
    :host([variant="assistant"]) {
      justify-content: flex-start;
    }
    .bubble {
      max-width: min(720px, 88%);
      padding: 12px 16px;
      border-radius: var(--r-md);
      line-height: 1.65;
      font-size: 15px;
      white-space: pre-wrap;
      word-break: break-word;
      box-shadow: var(--shadow-xs);
      border: 1px solid transparent;
    }
    :host([variant="user"]) .bubble {
      background: var(--c-bubble-user-bg);
      color: var(--c-bubble-user-fg);
      border-bottom-right-radius: 4px;
    }
    :host([variant="assistant"]) .bubble {
      background: var(--c-surface);
      color: var(--c-text);
      border-color: var(--c-border);
      border-bottom-left-radius: 4px;
    }
    .meta {
      font-size: 11px;
      color: var(--c-text-mute);
      margin-top: 6px;
      letter-spacing: 0.04em;
    }
    :host([variant="user"]) .meta { text-align: right; }
    .typing {
      display: inline-flex;
      gap: 4px;
      vertical-align: middle;
      margin-left: 2px;
    }
    .typing span {
      width: 4px;
      height: 4px;
      border-radius: 50%;
      background: currentColor;
      opacity: 0.5;
      animation: blink 1.2s infinite ease-in-out;
    }
    .typing span:nth-child(2) { animation-delay: 0.15s; }
    .typing span:nth-child(3) { animation-delay: 0.3s; }
    @keyframes blink {
      0%, 80%, 100% { opacity: 0.2; transform: translateY(0); }
      40% { opacity: 0.95; transform: translateY(-1px); }
    }
    .stack {
      display: flex;
      flex-direction: column;
      max-width: 100%;
    }
    /* Empty/failed assistant reply — visually marked so it doesn't look like UI broke */
    .bubble.placeholder {
      opacity: 0.62;
      font-style: italic;
      color: var(--c-text-mute);
      background: transparent;
      border-style: dashed;
      border-color: var(--c-border);
    }
    .bubble.placeholder::before {
      content: "⚠ ";
      font-style: normal;
      margin-right: 4px;
      color: var(--c-flat);
    }
  `;

  @property({ reflect: true }) variant: "user" | "assistant" = "assistant";
  @property() content = "";
  @property({ type: Boolean }) typing = false;
  @property() meta = "";

  // Persisted-empty markers from older sessions where the model never replied.
  // Detect them so the bubble renders as a visible "no-response" state, not raw text.
  private static readonly EMPTY_MARKERS = new Set([
    "（暂无回复）",
    "（模型未返回内容，请稍后重试）",
  ]);

  render() {
    const isPlaceholder = this.variant === "assistant"
      && !this.typing
      && (ChatBubble.EMPTY_MARKERS.has(this.content) || this.content.trim() === "");
    const text = isPlaceholder ? "未收到回复（可重新提问）" : this.content;
    return html`
      <div class="stack">
        <div class="bubble ${isPlaceholder ? "placeholder" : ""}">${text}${this.typing ? html`<span class="typing"><span></span><span></span><span></span></span>` : null}</div>
        ${this.meta ? html`<div class="meta">${this.meta}</div>` : null}
      </div>
    `;
  }
}
