import { LitElement, css, html } from "lit";
import { customElement, property } from "lit/decorators.js";

@customElement("aurumers-section-header")
export class SectionHeader extends LitElement {
  static styles = css`
    :host {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 16px;
    }
    .left {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .eyebrow {
      font-size: 11px;
      color: var(--c-text-mute);
      letter-spacing: 0.12em;
      text-transform: uppercase;
      font-weight: 500;
    }
    .title {
      font-size: 18px;
      font-weight: 600;
      letter-spacing: -0.01em;
      color: var(--c-text);
    }
    .desc {
      font-size: 13px;
      color: var(--c-text-mute);
    }
  `;

  @property() eyebrow = "";
  @property() titleText = "";
  @property() desc = "";

  render() {
    return html`
      <div class="left">
        ${this.eyebrow ? html`<span class="eyebrow">${this.eyebrow}</span>` : null}
        <span class="title">${this.titleText}</span>
        ${this.desc ? html`<span class="desc">${this.desc}</span>` : null}
      </div>
      <div class="right">
        <slot></slot>
      </div>
    `;
  }
}
