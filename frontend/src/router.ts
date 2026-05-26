/**
 * Tiny history-API router with hash-based fallback.
 *
 * Routes are matched longest-prefix first. Catch-all "*" route is the fallback.
 */

export type RouteRender = (params: { path: string }) => HTMLElement;

interface RouteEntry {
  prefix: string;
  render: RouteRender;
}

class Router {
  private routes: RouteEntry[] = [];
  private fallback: RouteRender | null = null;
  private mount: HTMLElement | null = null;
  private currentEl: HTMLElement | null = null;

  on(prefix: string, render: RouteRender): this {
    this.routes.push({ prefix, render });
    this.routes.sort((a, b) => b.prefix.length - a.prefix.length);
    return this;
  }

  setFallback(render: RouteRender): this {
    this.fallback = render;
    return this;
  }

  bind(mount: HTMLElement): void {
    this.mount = mount;
    window.addEventListener("popstate", () => this.render());
    document.addEventListener("click", (event) => {
      const target = (event.target as HTMLElement | null)?.closest("a[data-route]");
      if (!target) return;
      const href = (target as HTMLAnchorElement).getAttribute("href");
      if (!href || href.startsWith("http")) return;
      event.preventDefault();
      this.navigate(href);
    });
    this.render();
  }

  navigate(path: string): void {
    if (window.location.pathname + window.location.search === path) return;
    history.pushState({}, "", path);
    this.render();
  }

  private render(): void {
    if (!this.mount) return;
    const path = window.location.pathname || "/";
    const match = this.routes.find((r) => path === r.prefix || path.startsWith(r.prefix === "/" ? "//never-match" : r.prefix));
    let render = match?.render;
    if (!render && path === "/") {
      const root = this.routes.find((r) => r.prefix === "/");
      render = root?.render;
    }
    if (!render) render = this.fallback || undefined;
    if (!render) return;
    const el = render({ path });
    el.dataset.routeMount = "true";
    if (this.currentEl && this.currentEl.parentElement === this.mount) {
      this.mount.replaceChild(el, this.currentEl);
    } else {
      this.mount.replaceChildren(el);
    }
    this.currentEl = el;
    window.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
    document.title = el.dataset.title ? `${el.dataset.title} · Aurumers` : "Aurumers · 黄金市场结构化预测";
  }
}

export const router = new Router();
