import { LitElement, css, html } from "lit";
import { customElement, property } from "lit/decorators.js";
import type { ChatGreeting } from "../api/schemas";

@customElement("aurumers-chat-greeting-card")
export class ChatGreetingCard extends LitElement {
  static styles = css`
    :host {
      display: block;
      margin-bottom: 16px;
    }
    .card {
      background: var(--c-surface);
      border: 1px solid var(--c-border);
      border-left: 3px solid var(--c-accent);
      border-radius: var(--r-md);
      padding: 20px 22px;
      box-shadow: var(--shadow-sm);
    }
    .greet {
      font-size: 15px;
      line-height: 1.7;
      color: var(--c-text);
      white-space: pre-wrap;
    }
    .suggestions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 14px;
    }
    .suggestion {
      padding: 8px 14px;
      border-radius: 999px;
      background: var(--c-surface-2);
      border: 1px solid var(--c-border);
      font-size: 13px;
      color: var(--c-text);
      cursor: pointer;
      transition: background var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out), transform var(--dur-fast) var(--ease-out);
    }
    .suggestion:hover {
      background: var(--c-accent-soft);
      border-color: var(--c-accent-line);
      transform: translateY(-1px);
    }
  `;

  @property({ attribute: false }) greeting: ChatGreeting | null = null;

  private _select(question: string) {
    this.dispatchEvent(new CustomEvent("suggestion-select", {
      detail: { question },
      bubbles: true,
      composed: true,
    }));
  }

  render() {
    if (!this.greeting) {
      return html`<div class="card"><div class="greet">Hermes 正在准备你今天的金价摘要…</div></div>`;
    }
    return html`
      <div class="card">
        <div class="greet">${this.greeting.opening_message}</div>
        <div class="suggestions">
          ${(this.greeting.suggested_questions || []).map((q) => html`
            <button class="suggestion" @click=${() => this._select(q)}>${q}</button>
          `)}
        </div>
      </div>
    `;
  }
}
