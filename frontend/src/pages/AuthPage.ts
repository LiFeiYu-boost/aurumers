import { api } from "../api/client";
import { router } from "../router";
import { toast } from "../components/Toast";

const CSS = `
.auth-wrap {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background:
    radial-gradient(900px 500px at 50% -5%, color-mix(in srgb, var(--c-up-soft) 35%, transparent), transparent),
    var(--c-bg);
}
.auth-card {
  width: 100%;
  max-width: 400px;
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: 16px;
  box-shadow: var(--shadow-md);
  padding: 36px 32px;
}
.auth-head { text-align: center; margin-bottom: 24px; }
.auth-head .mark {
  width: 48px; height: 48px;
  border-radius: 14px;
  background: var(--gradient-mark);
  display: inline-flex; align-items: center; justify-content: center;
  color: #fff; font-weight: 700; font-size: 18px; letter-spacing: 0;
  box-shadow: var(--shadow-sm), inset 0 1px 0 rgba(255, 255, 255, 0.18);
  margin-bottom: 14px;
}
.auth-head .brand { font-size: 22px; font-weight: 600; letter-spacing: -0.02em; color: var(--c-text); }
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
.auth-card input {
  width: 100%; padding: 12px 14px; font-size: 14px;
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
          <input id="username" name="username" placeholder="用户名" autocomplete="username" />
          <input id="password" name="password" type="password" placeholder="密码"
                 autocomplete="${isRegister ? "new-password" : "current-password"}" />
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
