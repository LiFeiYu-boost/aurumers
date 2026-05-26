import { LitElement, css, html } from "lit";
import { customElement, property } from "lit/decorators.js";

@customElement("aurumers-skeleton")
export class Skeleton extends LitElement {
  static styles = css`
    :host { display: block; }
    .bar {
      width: 100%;
      height: var(--h, 16px);
      border-radius: 6px;
      background: linear-gradient(
        110deg,
        var(--c-bg-soft) 35%,
        color-mix(in srgb, var(--c-bg-soft) 70%, var(--c-text-faint) 30%) 50%,
        var(--c-bg-soft) 65%
      );
      background-size: 220% 100%;
      animation: shimmer 1.6s ease-in-out infinite;
    }
    @keyframes shimmer {
      0% { background-position: -120% 0; }
      100% { background-position: 220% 0; }
    }
  `;

  @property() h = "16px";

  render() {
    return html`<div class="bar" style="--h:${this.h}"></div>`;
  }
}
