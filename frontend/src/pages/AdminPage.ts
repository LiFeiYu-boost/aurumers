import { api } from "../api/client";
import type { AuthUser } from "../api/client";
import { toast } from "../components/Toast";

const CSS = `
.admin { padding: 28px 0; }
.admin h1 { margin: 0 0 16px; font-size: clamp(24px,2.6vw,30px); font-weight: 600; }
.admin .panel { background: var(--c-surface); border: 1px solid var(--c-border); border-radius: var(--r-md); padding: 20px 22px; box-shadow: var(--shadow-sm); margin-top: 16px; }
.admin table { width: 100%; border-collapse: collapse; font-size: 13px; }
.admin th, .admin td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--c-border); }
.admin th { color: var(--c-text-mute); font-weight: 500; }
.admin .gen-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 12px; }
.admin input { padding: 8px 12px; border: 1px solid var(--c-border); border-radius: 8px; background: var(--c-bg); color: var(--c-text); width: 120px; }
.admin .codes { margin-top: 12px; font-family: var(--font-mono); font-size: 12px; color: var(--c-text-soft); word-break: break-all; }
.admin button.mini { padding: 4px 10px; font-size: 12px; border: 1px solid var(--c-border); border-radius: 6px; }
`;

export function renderAdmin(): HTMLElement {
  const root = document.createElement("div");
  root.dataset.title = "管理后台";
  root.innerHTML = `
    <style>${CSS}</style>
    <aurumers-shell>
      <div class="admin shell">
        <h1>管理后台</h1>
        <div class="panel">
          <div style="font-weight:500;">用户</div>
          <div id="users"><div style="color:var(--c-text-mute);font-size:13px;margin-top:8px;">加载中…</div></div>
        </div>
        <div class="panel">
          <div style="font-weight:500;">生成兑换码</div>
          <div class="gen-row">
            <input id="cents" type="number" placeholder="金额(分)" value="1000" />
            <input id="count" type="number" placeholder="数量" value="1" />
            <button id="gen" class="btn btn-primary">生成</button>
          </div>
          <div class="codes" id="codes"></div>
        </div>
      </div>
      <aurumers-toast-stack></aurumers-toast-stack>
    </aurumers-shell>
  `;

  const yuan = (c: number) => (c / 100).toFixed(2);

  async function loadUsers() {
    const box = root.querySelector("#users");
    try {
      const users = await api.admin.users();
      if (!box) return;
      const rows = users
        .map(
          (u: AuthUser) => `
        <tr>
          <td>${u.username}</td>
          <td>${u.role}</td>
          <td>${u.status}</td>
          <td>¥${yuan(u.balance_cents)}</td>
          <td>${u.daily_free_cents === null ? "默认" : "¥" + yuan(u.daily_free_cents)}</td>
          <td><button class="mini" data-edit="${u.id}">改额度</button></td>
        </tr>`,
        )
        .join("");
      box.innerHTML = `<table>
        <tr><th>用户名</th><th>角色</th><th>状态</th><th>余额</th><th>每日免费</th><th></th></tr>
        ${rows}</table>`;
      box.querySelectorAll<HTMLButtonElement>("[data-edit]").forEach((b) =>
        b.addEventListener("click", async () => {
          const id = b.dataset.edit!;
          const v = prompt("设置该用户每日免费额度(分);留空=恢复默认");
          if (v === null) return;
          const fields = v.trim() === "" ? { daily_free_cents: null } : { daily_free_cents: parseInt(v, 10) };
          try {
            await api.admin.updateUser(id, fields);
            toast("已更新", "success");
            void loadUsers();
          } catch (e: any) {
            toast(e?.message || "更新失败", "error");
          }
        }),
      );
    } catch (e: any) {
      if (box) box.innerHTML = `<div style="color:var(--c-down);font-size:13px;margin-top:8px;">${e?.message || "加载失败(需管理员登录)"}</div>`;
    }
  }

  root.querySelector("#gen")?.addEventListener("click", async () => {
    const cents = parseInt(root.querySelector<HTMLInputElement>("#cents")?.value || "0", 10);
    const count = parseInt(root.querySelector<HTMLInputElement>("#count")?.value || "1", 10);
    try {
      const r = await api.admin.createCodes(cents, count);
      const box = root.querySelector("#codes");
      if (box) box.innerHTML = `面额 ¥${yuan(r.cents)} 共 ${r.codes.length} 个:<br>${r.codes.join("<br>")}`;
      toast("已生成", "success");
    } catch (e: any) {
      toast(e?.message || "生成失败", "error");
    }
  });

  void loadUsers();
  return root;
}
