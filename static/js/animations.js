// Lightweight animation helpers — count-up, observer reveal, toast.

export function safeUrl(value) {
    const text = String(value || "").trim();
    if (!text) return "#";
    if (/^(https?:|mailto:)/i.test(text)) return text;
    if (text.startsWith("//")) return `https:${text}`;
    if (text.startsWith("/") || text.startsWith("#")) return text;
    return "#";
}

export function countUp(element, target, { duration = 720, decimals = 0, prefix = "", suffix = "" } = {}) {
    if (element == null) return;
    const numericTarget = Number(target);
    if (!Number.isFinite(numericTarget)) {
        element.textContent = `${prefix}${target ?? "—"}${suffix}`;
        return;
    }
    const start = performance.now();
    const initial = Number(element.dataset.cuValue ?? 0);
    const ease = (t) => 1 - Math.pow(1 - t, 3);
    function frame(now) {
        const t = Math.min(1, (now - start) / duration);
        const value = initial + (numericTarget - initial) * ease(t);
        element.textContent = `${prefix}${value.toFixed(decimals)}${suffix}`;
        if (t < 1) {
            requestAnimationFrame(frame);
        } else {
            element.dataset.cuValue = String(numericTarget);
        }
    }
    requestAnimationFrame(frame);
}

export function showToast(message, { duration = 1800 } = {}) {
    const toast = document.getElementById("toast");
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add("show");
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => toast.classList.remove("show"), duration);
}

export function observeReveal(selector = "[data-reveal]") {
    if (!("IntersectionObserver" in window)) {
        document.querySelectorAll(selector).forEach((node) => node.classList.add("revealed"));
        return;
    }
    const observer = new IntersectionObserver(
        (entries) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting) {
                    entry.target.classList.add("revealed");
                    observer.unobserve(entry.target);
                }
            });
        },
        { threshold: 0.1, rootMargin: "0px 0px -40px 0px" },
    );
    document.querySelectorAll(selector).forEach((node) => observer.observe(node));
}
