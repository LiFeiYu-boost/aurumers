import { LitElement, css, html } from "lit";
import { customElement } from "lit/decorators.js";

/**
 * Decorative animated background — large blurred gold orb with subtle
 * mouse-driven parallax + soft floating particles. Performance-friendly
 * (canvas, ≤80 particles, single rAF). Disables itself on
 * prefers-reduced-motion.
 */
@customElement("aurumers-orb")
export class MotionOrb extends LitElement {
  static styles = css`
    :host {
      position: absolute;
      inset: 0;
      pointer-events: none;
      overflow: hidden;
      z-index: 0;
    }
    .orb {
      position: absolute;
      width: 720px;
      height: 720px;
      top: -260px;
      right: -200px;
      border-radius: 50%;
      filter: blur(120px);
      background: radial-gradient(
        circle at 30% 30%,
        rgba(244, 203, 86, 0.55),
        rgba(184, 134, 11, 0.18) 40%,
        transparent 70%
      );
      will-change: transform;
      transition: transform 320ms var(--ease-out);
    }
    .orb-2 {
      position: absolute;
      width: 540px;
      height: 540px;
      bottom: -240px;
      left: -180px;
      border-radius: 50%;
      filter: blur(140px);
      background: radial-gradient(
        circle at 60% 40%,
        rgba(212, 165, 45, 0.30),
        transparent 70%
      );
      will-change: transform;
      transition: transform 480ms var(--ease-out);
    }
    canvas {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      mix-blend-mode: screen;
      opacity: 0.55;
    }
    @media (prefers-reduced-motion: reduce) {
      canvas { display: none; }
      .orb, .orb-2 { transition: none; }
    }
  `;

  private _raf = 0;
  private _onMove = (event: MouseEvent) => {
    const rect = this.getBoundingClientRect();
    const cx = (event.clientX - rect.left) / rect.width - 0.5;
    const cy = (event.clientY - rect.top) / rect.height - 0.5;
    const orb = this.renderRoot.querySelector(".orb") as HTMLElement | null;
    const orb2 = this.renderRoot.querySelector(".orb-2") as HTMLElement | null;
    if (orb) orb.style.transform = `translate(${cx * 32}px, ${cy * 24}px)`;
    if (orb2) orb2.style.transform = `translate(${cx * -22}px, ${cy * -18}px)`;
  };

  connectedCallback(): void {
    super.connectedCallback();
    window.addEventListener("mousemove", this._onMove);
  }
  disconnectedCallback(): void {
    super.disconnectedCallback();
    window.removeEventListener("mousemove", this._onMove);
    if (this._raf) cancelAnimationFrame(this._raf);
  }

  protected firstUpdated(): void {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const canvas = this.renderRoot.querySelector("canvas") as HTMLCanvasElement | null;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      canvas.width = Math.max(1, Math.floor(rect.width * dpr));
      canvas.height = Math.max(1, Math.floor(rect.height * dpr));
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);

    interface Particle { x: number; y: number; vy: number; vx: number; r: number; alpha: number; }
    const particles: Particle[] = [];
    const count = 70;
    const init = () => {
      particles.length = 0;
      for (let i = 0; i < count; i += 1) {
        particles.push({
          x: Math.random() * canvas.width,
          y: Math.random() * canvas.height,
          vx: (Math.random() - 0.5) * 0.18 * dpr,
          vy: -Math.random() * 0.30 * dpr - 0.05,
          r: (Math.random() * 1.6 + 0.4) * dpr,
          alpha: Math.random() * 0.5 + 0.2,
        });
      }
    };
    init();

    const tick = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      for (const p of particles) {
        p.x += p.vx;
        p.y += p.vy;
        if (p.y < -8 || p.x < -8 || p.x > canvas.width + 8) {
          p.x = Math.random() * canvas.width;
          p.y = canvas.height + Math.random() * 24;
          p.alpha = Math.random() * 0.5 + 0.2;
        }
        ctx.beginPath();
        const grd = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.r * 4);
        grd.addColorStop(0, `rgba(244, 203, 86, ${p.alpha})`);
        grd.addColorStop(1, "rgba(244, 203, 86, 0)");
        ctx.fillStyle = grd;
        ctx.arc(p.x, p.y, p.r * 4, 0, Math.PI * 2);
        ctx.fill();
      }
      this._raf = requestAnimationFrame(tick);
    };
    this._raf = requestAnimationFrame(tick);
  }

  render() {
    return html`
      <div class="orb"></div>
      <div class="orb-2"></div>
      <canvas></canvas>
    `;
  }
}
