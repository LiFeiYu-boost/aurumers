import { api } from "../api/client";
import { router } from "../router";
import { toast } from "../components/Toast";

const ICON_USER = `<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 4-6.5 8-6.5s8 2.5 8 6.5"/></svg>`;
const ICON_LOCK = `<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>`;

const CSS = `
.auth-wrap {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background:
    radial-gradient(820px 420px at 50% -8%, color-mix(in srgb, var(--c-up-soft) 50%, transparent), transparent),
    radial-gradient(560px 560px at 88% 112%, color-mix(in srgb, #d4af37 13%, transparent), transparent),
    var(--c-bg);
}
.auth-card {
  position: relative;
  overflow: hidden;
  width: 100%;
  max-width: 400px;
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: 18px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04), 0 18px 44px -22px rgba(0,0,0,0.30);
  padding: 38px 32px 30px;
}
.auth-card::before {
  content: "";
  position: absolute; top: 0; left: 0; right: 0; height: 3px;
  background: linear-gradient(90deg, transparent, color-mix(in srgb, #d4af37 75%, transparent), transparent);
}
.auth-head { text-align: center; margin-bottom: 24px; }
.auth-head .mark {
  width: 52px; height: 52px;
  border-radius: 15px;
  background: var(--gradient-mark);
  display: inline-flex; align-items: center; justify-content: center;
  color: #fff; font-weight: 700; font-size: 19px;
  box-shadow: 0 6px 16px -6px color-mix(in srgb, #d4af37 70%, transparent), inset 0 1px 0 rgba(255,255,255,0.22);
  margin-bottom: 15px;
}
.auth-head .brand { font-size: 23px; font-weight: 600; letter-spacing: -0.02em; color: var(--c-text); }
.auth-head .sub { font-size: 13px; color: var(--c-text-mute); margin-top: 5px; }
.auth-card .tabs {
  display: flex; gap: 4px; margin: 0 0 18px;
  background: var(--c-bg-soft); border-radius: 10px; padding: 3px;
}
.auth-card .tabs button {
  flex: 1; padding: 9px 0; font-size: 14px; font-weight: 500;
  color: var(--c-text-mute); border-radius: 8px; transition: all var(--dur-fast) var(--ease-out);
}
.auth-card .tabs button.active { background: var(--c-surface); color: var(--c-text); box-shadow: var(--shadow-sm); }
.auth-card form { display: flex; flex-direction: column; gap: 12px; }
.auth-card .field { position: relative; }
.auth-card .field .ic {
  position: absolute; left: 13px; top: 50%; transform: translateY(-50%);
  width: 16px; height: 16px; color: var(--c-text-mute); pointer-events: none;
  transition: color var(--dur-fast) var(--ease-out);
}
.auth-card .field:focus-within .ic { color: var(--c-text-soft); }
.auth-card input {
  width: 100%; padding: 12px 14px 12px 40px; font-size: 14px;
  border: 1px solid var(--c-border); border-radius: 10px;
  background: var(--c-bg); color: var(--c-text);
  transition: border-color var(--dur-fast) var(--ease-out), box-shadow var(--dur-fast) var(--ease-out);
}
.auth-card input::placeholder { color: var(--c-text-mute); }
.auth-card input:focus {
  outline: none;
  border-color: var(--c-text-soft);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--c-up-soft) 55%, transparent);
}
.auth-card .submit { margin-top: 6px; padding: 12px 0; font-size: 15px; font-weight: 600; border-radius: 10px; width: 100%; }
.auth-card .hint { font-size: 12px; color: var(--c-text-mute); margin-top: 2px; line-height: 1.5; text-align: center; }
.auth-card .back { display: block; text-align: center; margin-top: 20px; font-size: 13px; color: var(--c-text-mute); }
.auth-card .back:hover { color: var(--c-text); }
`;

export function renderAuth({ path }: { path: string }): HTMLElement {
  const isRegister = path.startsWith("/auth/register");
  const root = document.createElement("div");
  root.dataset.title = isRegister ? "注册" : "登录";
  root.innerHTML = `
    <style>${CSS}</style>
    <div class="auth-wrap">
      <div class="auth-card">
        <div class="auth-head">
          <span class="mark">Au</span>
          <div class="brand">Aurumers</div>
          <div class="sub">黄金市场结构化预测</div>
        </div>
        <div class="tabs">
          <button type="button" data-tab="login" class="${!isRegister ? "active" : ""}">登录</button>
          <button type="button" data-tab="register" class="${isRegister ? "active" : ""}">注册</button>
        </div>
        <form id="auth-form" novalidate>
          <div class="field">
            ${ICON_USER}
            <input id="username" name="username" placeholder="用户名" autocomplete="username" />
          </div>
          <div class="field">
            ${ICON_LOCK}
            <input id="password" name="password" type="password" placeholder="密码"
                   autocomplete="${isRegister ? "new-password" : "current-password"}" />
          </div>
          <button type="submit" class="btn btn-primary submit">${isRegister ? "注册并登录" : "登录"}</button>
          ${isRegister ? '<div class="hint">用户名 3-32 位字母/数字/下划线,密码至少 6 位。</div>' : ""}
        </form>
        <a class="back" href="/" data-route>← 返回首页</a>
      </div>
    </div>
  `;

  root.querySelectorAll<HTMLButtonElement>("[data-tab]").forEach((b) =>
    b.addEventListener("click", () =>
      router.navigate(b.dataset.tab === "register" ? "/auth/register" : "/auth/login"),
    ),
  );

  const form = root.querySelector<HTMLFormElement>("#auth-form");
  form?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const username = root.querySelector<HTMLInputElement>("#username")?.value.trim() ?? "";
    const password = root.querySelector<HTMLInputElement>("#password")?.value ?? "";
    if (!username || !password) {
      toast("请输入用户名和密码", "error");
      return;
    }
    const btn = root.querySelector<HTMLButtonElement>(".submit");
    if (btn) btn.disabled = true;
    try {
      if (isRegister) await api.auth.register(username, password);
      else await api.auth.login(username, password);
      toast(isRegister ? "注册成功" : "登录成功", "success");
      router.navigate("/app");
    } catch (err: any) {
      toast(err?.message || "操作失败,请重试", "error");
      if (btn) btn.disabled = false;
    }
  });

  return root;
}
