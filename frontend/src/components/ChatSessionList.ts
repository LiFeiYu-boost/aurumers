import { LitElement, css, html } from "lit";
import { customElement, property } from "lit/decorators.js";
import type { ChatSession } from "../api/schemas";

@customElement("aurumers-chat-session-list")
export class ChatSessionList extends LitElement {
  static styles = css`
    :host {
      display: block;
      width: 100%;
    }
    .head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 0 4px 10px;
    }
    .head h3 {
      margin: 0;
      font-size: 11px;
      font-weight: 500;
      color: var(--c-text-mute);
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }
    button.new-btn {
      padding: 6px 12px;
      font-size: 12px;
      font-weight: 500;
      color: var(--c-bg);
      background: var(--c-text);
      border-radius: 8px;
      transition: opacity var(--dur-fast) var(--ease-out);
    }
    button.new-btn:hover { opacity: 0.85; }
    .list {
      display: flex;
      flex-direction: column;
      gap: 2px;
      max-height: calc(100vh - 220px);
      overflow-y: auto;
    }
    .item {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 10px 10px;
      border-radius: 8px;
      cursor: pointer;
      transition: background var(--dur-fast) var(--ease-out);
    }
    .item:hover { background: var(--c-surface-2); }
    .item.active {
      background: var(--c-accent-soft);
      border: 1px solid var(--c-accent-line);
    }
    .text {
      flex: 1;
      min-width: 0;
      display: flex;
      flex-direction: column;
      gap: 2px;
    }
    .title {
      font-size: 13px;
      color: var(--c-text);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .meta {
      font-size: 11px;
      color: var(--c-text-mute);
    }
    button.del-btn {
      width: 26px;
      height: 26px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: 6px;
      color: var(--c-text-mute);
      opacity: 0;
      transition: opacity var(--dur-fast) var(--ease-out), background var(--dur-fast) var(--ease-out);
    }
    .item:hover button.del-btn,
    .item.active button.del-btn { opacity: 1; }
    button.del-btn:hover { color: var(--c-down); background: var(--c-down-soft); }
    .empty {
      color: var(--c-text-mute);
      font-size: 13px;
      padding: 12px;
      text-align: center;
    }
  `;

  @property({ type: Array }) sessions: ChatSession[] = [];
  @property() activeId = "";

  private _select(id: string) {
    this.dispatchEvent(new CustomEvent("session-select", { detail: { id }, bubbles: true, composed: true }));
  }
  private _delete(event: Event, id: string) {
    event.stopPropagation();
    this.dispatchEvent(new CustomEvent("session-delete", { detail: { id }, bubbles: true, composed: true }));
  }
  private _newSession() {
    this.dispatchEvent(new CustomEvent("session-create", { bubbles: true, composed: true }));
  }

  private _formatRelative(iso: string): string {
    if (!iso) return "";
    const stamp = Date.parse(iso.replace(" ", "T"));
    if (!Number.isFinite(stamp)) return iso.slice(5, 16);
    const diff = (Date.now() - stamp) / 1000;
    if (diff < 60) return "刚刚";
    if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
    if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} 天前`;
    return iso.slice(5, 10);
  }

  render() {
    return html`
      <div class="head">
        <h3>历史对话</h3>
        <button class="new-btn" @click=${this._newSession}>+ 新对话</button>
      </div>
      <div class="list">
        ${this.sessions.length === 0
          ? html`<div class="empty">还没有任何对话<br/>点上方「+ 新对话」开始</div>`
          : this.sessions.map((s) => html`
            <div class="item ${s.id === this.activeId ? "active" : ""}" @click=${() => this._select(s.id)}>
              <div class="text">
                <div class="title">${s.title || "新对话"}</div>
                <div class="meta">${s.message_count} 条消息 · ${this._formatRelative(s.updated_at)}</div>
              </div>
              <button class="del-btn" @click=${(e: Event) => this._delete(e, s.id)} aria-label="删除">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="3 6 5 6 21 6"></polyline>
                  <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path>
                  <path d="M10 11v6"></path>
                  <path d="M14 11v6"></path>
                </svg>
              </button>
            </div>
          `)}
      </div>
    `;
  }
}
