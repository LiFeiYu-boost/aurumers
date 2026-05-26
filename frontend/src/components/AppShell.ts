import { LitElement, css, html, type PropertyValues } from "lit";
import { customElement, property, state } from "lit/decorators.js";
import { api } from "../api/client";
import { router } from "../router";

const NAV = [
  { href: "/app", label: "看板" },
  { href: "/app/predictions", label: "预测中心" },
  { href: "/app/chat", label: "Hermes" },
  { href: "/app/records", label: "历史记录" },
  { href: "/app/insights", label: "洞察" },
  { href: "/app/wallet", label: "钱包" },
  { href: "/app/account", label: "账号" },
  { href: "/app/settings", label: "设置" },
];

@customElement("aurumers-shell")
export class AppShell extends LitElement {
  static styles = css`
    :host {
      display: block;
      min-height: 100vh;
    }
    .topbar {
      position: sticky;
      top: 0;
      z-index: 30;
      background: color-mix(in srgb, var(--c-bg) 86%, transparent);
      backdrop-filter: saturate(160%) blur(14px);
      -webkit-backdrop-filter: saturate(160%) blur(14px);
      border-bottom: 1px solid var(--c-border);
    }
    .inner {
      width: min(1240px, calc(100% - 48px));
      margin: 0 auto;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 14px 0;
      gap: 16px;
    }
    a.brand {
      display: inline-flex;
      align-items: center;
      gap: 12px;
      color: inherit;
      font-weight: 600;
      letter-spacing: -0.01em;
    }
    .mark {
      width: 32px;
      height: 32px;
      border-radius: 9px;
      background: var(--gradient-mark);
      box-shadow: var(--shadow-xs), inset 0 1px 0 rgba(255, 255, 255, 0.18);
      position: relative;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      color: #fff;
      font-family: var(--font-sans);
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0;
    }
    .mark::after {
      content: "";
      position: absolute;
      inset: 6px;
      border-radius: 5px;
      border: 1px solid rgba(255, 255, 255, 0.34);
      border-bottom-color: transparent;
      border-left-color: transparent;
      pointer-events: none;
    }
    .brand-name { font-size: 15px; }
    .brand-tag {
      font-size: 12px;
      color: var(--c-text-mute);
      letter-spacing: 0.04em;
    }
    nav {
      display: flex;
      gap: 4px;
    }
    nav a {
      padding: 8px 12px;
      font-size: 14px;
      color: var(--c-text-soft);
      border-radius: 6px;
      transition: background var(--dur-fast) var(--ease-out),
                  color var(--dur-fast) var(--ease-out);
    }
    nav a:hover { color: var(--c-text); background: var(--c-accent-soft); }
    nav a.active { color: var(--c-text); background: var(--c-accent-soft); }
    .right {
      display: flex;
      gap: 8px;
      align-items: center;
    }
    .icon-btn {
      width: 34px; height: 34px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: 8px;
      color: var(--c-text-soft);
      border: 1px solid transparent;
      transition: background var(--dur-fast) var(--ease-out),
                  border-color var(--dur-fast) var(--ease-out),
                  color var(--dur-fast) var(--ease-out);
      background: transparent;
      cursor: pointer;
    }
    .icon-btn:hover {
      color: var(--c-text);
      background: var(--c-surface);
      border-color: var(--c-border);
    }
    .hamburger { display: none; }
    .backdrop { display: none; }
    @media (max-width: 760px) {
      .inner { padding: 10px 0; }
      .brand-tag { display: none; }
      .hamburger { display: inline-flex; }
      nav {
        position: fixed;
        top: 0;
        right: 0;
        height: 100vh;
        width: min(280px, 78vw);
        flex-direction: column;
        gap: 4px;
        padding: 72px 16px 24px;
        background: var(--c-surface);
        border-left: 1px solid var(--c-border);
        box-shadow: var(--shadow-lg);
        z-index: 60;
        transform: translateX(100%);
        transition: transform var(--dur-base) var(--ease-spring);
      }
      nav a {
        padding: 12px 14px;
        font-size: 15px;
      }
      :host([menuopen]) nav { transform: translateX(0); }
      .backdrop {
        display: block;
        position: fixed;
        inset: 0;
        background: rgba(0, 0, 0, 0.36);
        backdrop-filter: blur(2px);
        z-index: 55;
        opacity: 0;
        pointer-events: none;
        transition: opacity var(--dur-base) var(--ease-out);
      }
      :host([menuopen]) .backdrop { opacity: 1; pointer-events: auto; }
    }
  `;

  @property() current = "/";
  @property({ type: Boolean, reflect: true }) menuopen = false;
  @state() private theme = "auto";
  @state() private isAdmin = false;

  connectedCallback(): void {
    super.connectedCallback();
    this.theme = document.documentElement.getAttribute("data-theme") || "auto";
    window.addEventListener("popstate", this._onNav);
    this.current = window.location.pathname || "/";
    api.auth.me().then((u) => { this.isAdmin = u.role === "admin"; }).catch(() => { this.isAdmin = false; });
  }
  disconnectedCallback(): void {
    super.disconnectedCallback();
    window.removeEventListener("popstate", this._onNav);
  }
  protected updated(_props: PropertyValues): void {
    this.current = window.location.pathname || "/";
  }
  private _onNav = () => { this.current = window.location.pathname || "/"; this.menuopen = false; };
  private _toggleMenu = () => { this.menuopen = !this.menuopen; };
  private _closeMenu = () => { this.menuopen = false; };
  private _logout = async () => {
    try { await api.auth.logout(); } catch { /* noop */ }
    router.navigate("/auth/login");
  };
  private _toggleTheme = () => {
    const next = this.theme === "dark" ? "light" : this.theme === "light" ? "auto" : "dark";
    this.theme = next;
    if (next === "auto") {
      document.documentElement.removeAttribute("data-theme");
    } else {
      document.documentElement.setAttribute("data-theme", next);
    }
    try { localStorage.setItem("aurumers.theme", next); } catch { /* noop */ }
    this.dispatchEvent(new CustomEvent("theme-change", { bubbles: true, composed: true, detail: { theme: next } }));
  };

  render() {
    const themeIcon = this.theme === "dark" ? "🌙" : this.theme === "light" ? "☀️" : "⚙️";
    return html`
      <header class="topbar">
        <div class="inner">
          <a class="brand" href="/" data-route>
            <span class="mark">Au</span>
            <span class="brand-name">Aurumers</span>
            <span class="brand-tag">· 黄金市场结构化预测</span>
          </a>
          <nav @click=${this._closeMenu}>
            ${NAV.map((item) => html`
              <a
                data-route
                href="${item.href}"
                class="${this.current === item.href || (item.href !== "/app" && this.current.startsWith(item.href)) ? "active" : ""}"
              >${item.label}</a>
            `)}
            ${this.isAdmin ? html`<a data-route href="/_ops" class="${this.current.startsWith("/_ops") ? "active" : ""}">管理</a>` : ""}
          </nav>
          <div class="backdrop" @click=${this._closeMenu}></div>
          <div class="right">
            <button class="icon-btn" @click=${this._toggleTheme} title="切换主题（auto / light / dark）">${themeIcon}</button>
            <button class="icon-btn" @click=${this._logout} title="登出">⏻</button>
            <button class="icon-btn hamburger" @click=${this._toggleMenu} aria-label="菜单" title="菜单">${this.menuopen ? "✕" : "☰"}</button>
          </div>
        </div>
      </header>
      <main>
        <slot></slot>
      </main>
    `;
  }
}
