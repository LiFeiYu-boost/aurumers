import { LitElement, css, html } from "lit";
import { customElement, property, state } from "lit/decorators.js";

function pad(n: number): string {
  return n.toString().padStart(2, "0");
}

/**
 * Calculates the next moment at hour:minute Asia/Shanghai wall clock.
 * DST-safe by using Intl.DateTimeFormat to read the current Beijing wall time
 * regardless of the user's local timezone.
 */
function nextBeijingFire(hour: number, minute: number): Date {
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
  const parts = fmt.formatToParts(new Date());
  const find = (type: string) => Number(parts.find((p) => p.type === type)?.value ?? "0");
  const y = find("year");
  const mo = find("month");
  const d = find("day");
  const h = find("hour");
  const mi = find("minute");
  const s = find("second");

  // Beijing is UTC+8 (no DST). Construct the target as a UTC instant.
  const targetUtcMs = Date.UTC(y, mo - 1, d, hour - 8, minute, 0);
  // Compare against current Beijing-as-UTC instant.
  const nowBeijingUtcMs = Date.UTC(y, mo - 1, d, h - 8, mi, s);
  let next = targetUtcMs;
  if (next <= nowBeijingUtcMs) {
    next += 24 * 60 * 60 * 1000;
  }
  return new Date(next);
}

@customElement("aurumers-countdown")
export class CountdownTimer extends LitElement {
  static styles = css`
    :host {
      display: inline-flex;
      flex-direction: column;
      gap: 4px;
    }
    .label {
      font-size: 11px;
      color: var(--c-text-mute);
      letter-spacing: 0.08em;
      text-transform: uppercase;
      font-weight: 500;
    }
    .display {
      display: inline-flex;
      align-items: baseline;
      gap: 6px;
      font-family: var(--font-mono);
      font-variant-numeric: tabular-nums;
      font-size: 28px;
      font-weight: 600;
      letter-spacing: -0.02em;
      color: var(--c-text);
    }
    .unit { font-size: 13px; color: var(--c-text-mute); font-weight: 400; }
  `;

  @property({ type: Number }) hour = 2;
  @property({ type: Number }) minute = 50;
  @property() label = "距下一次 02:50 北京时间预测";
  @state() private remainingMs = 0;
  private _timer = 0;

  connectedCallback(): void {
    super.connectedCallback();
    this._tick();
    this._timer = window.setInterval(() => this._tick(), 1000);
  }
  disconnectedCallback(): void {
    super.disconnectedCallback();
    if (this._timer) clearInterval(this._timer);
  }
  private _tick() {
    const target = nextBeijingFire(this.hour, this.minute);
    this.remainingMs = Math.max(0, target.getTime() - Date.now());
  }

  render() {
    const total = Math.floor(this.remainingMs / 1000);
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    return html`
      <span class="label">${this.label}</span>
      <span class="display">
        <span>${pad(h)}</span><span class="unit">h</span>
        <span>${pad(m)}</span><span class="unit">m</span>
        <span>${pad(s)}</span><span class="unit">s</span>
      </span>
    `;
  }
}
