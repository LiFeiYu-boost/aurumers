import { api } from "../api/client";
import { toast } from "../components/Toast";

const CSS = `
.wallet { padding: 28px 0; }
.wallet h1 { margin: 0 0 4px; font-size: clamp(26px,3vw,34px); font-weight: 600; letter-spacing: -0.02em; }
.wallet p.lead { margin: 0 0 22px; color: var(--c-text-soft); }
.wallet .panel { background: var(--c-surface); border: 1px solid var(--c-border); border-radius: var(--r-md); padding: 22px 24px; box-shadow: var(--shadow-sm); margin-top: 16px; }
.wallet .label { font-weight: 500; font-size: 14px; color: var(--c-text); }
.wallet .bal { font-size: 34px; font-weight: 600; letter-spacing: -0.02em; margin-top: 6px; }
.wallet .desc { margin-top: 10px; font-size: 13px; color: var(--c-text-mute); line-height: 1.6; }
.wallet .redeem-row { display: flex; gap: 8px; margin-top: 12px; }
.wallet input { flex: 1; padding: 10px 14px; font-size: 14px; border: 1px solid var(--c-border); border-radius: 8px; background: var(--c-bg); color: var(--c-text); }
`;

export function renderWallet(): HTMLElement {
  const root = document.createElement("div");
  root.dataset.title = "钱包";
  root.innerHTML = `
    <style>${CSS}</style>
    <aurumers-shell>
      <div class="wallet shell">
        <h1>我的钱包</h1>
        <p class="lead">免费用户每日享有固定额度,超出后从钱包余额扣费。用兑换码充值。</p>
        <div class="panel" id="bal"><div class="desc">加载中…</div></div>
        <div class="panel">
          <div class="label">兑换码充值</div>
          <div class="redeem-row">
            <input id="code" placeholder="输入兑换码,如 AUR-XXXXXXXXXXXX" autocomplete="off" />
            <button id="redeem" class="btn btn-primary">兑换</button>
          </div>
        </div>
      </div>
      <aurumers-toast-stack></aurumers-toast-stack>
    </aurumers-shell>
  `;

  const yuan = (c: number) => (c / 100).toFixed(2);

  async function refresh() {
    try {
      const w = await api.wallet.info();
      const el = root.querySelector("#bal");
      if (el) {
        el.innerHTML = `
          <div class="label">钱包余额</div>
          <div class="bal">¥${yuan(w.balance_cents)}</div>
          <div class="desc">今日已用 ¥${(w.today_cost_cents / 100).toFixed(3)} ·
            每日免费额度 ¥${yuan(w.daily_free_limit_cents)} ·
            今日剩余免费 ¥${(w.free_remaining_cents / 100).toFixed(3)}</div>`;
      }
    } catch (e: any) {
      toast(e?.message || "加载失败", "error");
    }
  }

  root.querySelector("#redeem")?.addEventListener("click", async () => {
    const input = root.querySelector<HTMLInputElement>("#code");
    const code = input?.value.trim() ?? "";
    if (!code) {
      toast("请输入兑换码", "error");
      return;
    }
    try {
      const r = await api.wallet.redeem(code);
      toast(`充值成功 +¥${yuan(r.added_cents)}`, "success");
      if (input) input.value = "";
      void refresh();
    } catch (e: any) {
      toast(e?.message || "兑换失败", "error");
    }
  });

  void refresh();
  return root;
}
