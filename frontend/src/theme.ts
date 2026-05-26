const STORAGE_KEY = "aurumers.theme";

export type ThemeMode = "auto" | "light" | "dark";

function applyMode(mode: ThemeMode) {
  if (mode === "auto") {
    document.documentElement.removeAttribute("data-theme");
  } else {
    document.documentElement.setAttribute("data-theme", mode);
  }
}

export function initTheme() {
  let saved: ThemeMode = "auto";
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    if (value === "light" || value === "dark" || value === "auto") {
      saved = value;
    }
  } catch {
    // ignore
  }
  applyMode(saved);
}

export function setTheme(mode: ThemeMode) {
  try {
    localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    // ignore
  }
  applyMode(mode);
}

export function getTheme(): ThemeMode {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    if (value === "light" || value === "dark" || value === "auto") return value;
  } catch {
    // ignore
  }
  return "auto";
}
