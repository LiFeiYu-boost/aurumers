import { api } from "../api/client";
import { router } from "../router";
import { toast } from "../components/Toast";

const CSS = `
.account { padding: 28px 0; max-width: 560px; }
.account h1 { margin: 0 0 4px; font-size: clamp(24px,2.8vw,32px); font-weight: 600; letter-spacing: -0.02em; }
.account p.lead { margin: 0 0 20px; color: var(--c-text-soft); font-size: 14px; }
.account .panel { background: var(--c-surface); border: 1px solid var(--c-border); border-radius: var(--r-md); padding: 22px 24px; box-shadow: var(--shadow-sm); margin-top: 16px; }
.account .label { font-weight: 600; font-size: 15px; color: var(--c-text); }
.account .desc { font-size: 13px; color: var(--c-text-mute); margin-top: 4px; line-height: 1.6; }
.account .form { display: flex; flex-direction: column; gap: 10px; margin-top: 14px; }
.account input { width: 100%; padding: 11px 14px; font-size: 14px; border: 1px solid var(--c-border); border-radius: 10px; background: var(--c-bg); color: var(--c-text); }
.account input:focus { outline: none; border-color: var(--c-text-soft); box-shadow: 0 0 0 3px color-mix(in srgb, var(--c-up-soft) 55%, transparent); }
.account .actions { display: flex; justify-content: flex-end; margin-top: 4px; }
.account .panel.danger { border-color: color-mix(in srgb, var(--c-down) 40%, var(--c-border)); }
.account .danger .label { color: var(--c-down); }
.account .danger-btn { margin-top: 14px; color: var(--c-down); border: 1px solid color-mix(in srgb, var(--c-down) 45%, transparent); }
.account .danger-btn:hover { background: color-mix(in srgb, var(--c-down) 12%, transparent); }
`;

export function renderAccount(): HTMLElement {
  const root = document.createElement("div");
  root.dataset.title = "账号";
  root.innerHTML = `
    <style>${CSS}</style>
    <aurumers-shell>
      <div class="account shell">
        <h1>账号设置</h1>
        <p class="lead" id="whoami">…</p>
        <div class="panel">
          <div class="label">修改密码</div>
          <div class="form">
            <input id="oldpw" type="password" placeholder="当前密码" autocomplete="current-password" />
            <input id="newpw" type="password" placeholder="新密码(至少 6 位)" autocomplete="new-password" />
            <div class="actions"><button id="changepw" class="btn btn-primary">保存新密码</button></div>
          </div>
        </div>
        <div class="panel danger">
          <div class="label">注销账号</div>
          <div class="desc">注销后账号将被停用、无法再登录,且所有会话立即失效。此操作不可撤销。</div>
          <button id="delacct" class="btn btn-ghost danger-btn">注销我的账号</button>
        </div>
      </div>
      <aurumers-toast-stack></aurumers-toast-stack>
    </aurumers-shell>
  `;

  api.auth.me().then((u) => {
    const el = root.querySelector("#whoami");
    if (el) el.textContent = `当前登录:${u.username}${u.role === "admin" ? "(管理员)" : ""}`;
  }).catch(() => {});

  root.querySelector("#changepw")?.addEventListener("click", async () => {
    const oldEl = root.querySelector<HTMLInputElement>("#oldpw");
    const newEl = root.querySelector<HTMLInputElement>("#newpw");
    const oldp = oldEl?.value ?? "";
    const newp = newEl?.value ?? "";
    if (!oldp || newp.length < 6) { toast("请填当前密码,新密码至少 6 位", "error"); return; }
    try {
      await api.auth.changePassword(oldp, newp);
      toast("密码已修改", "success");
      if (oldEl) oldEl.value = "";
      if (newEl) newEl.value = "";
    } catch (e: any) {
      toast(e?.message || "修改失败", "error");
    }
  });

  root.querySelector("#delacct")?.addEventListener("click", async () => {
    if (!confirm("确定注销账号?注销后无法再登录,此操作不可撤销。")) return;
    try {
      await api.auth.deleteAccount();
      toast("账号已注销", "info");
      router.navigate("/auth/login");
    } catch (e: any) {
      toast(e?.message || "注销失败", "error");
    }
  });

  return root;
}
