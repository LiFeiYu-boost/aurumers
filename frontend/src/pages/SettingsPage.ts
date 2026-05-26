import { api } from "../api/client";
import { toast } from "../components/Toast";
import { getTheme, setTheme, type ThemeMode } from "../theme";
import type { ChannelStatus } from "../api/schemas";

const CSS = `
.settings { padding: 28px 0; }
.settings h1 { margin: 0 0 4px; font-size: clamp(28px, 3.4vw, 36px); font-weight: 600; letter-spacing: -0.022em; }
.settings p.lead { margin: 0 0 24px; color: var(--c-text-soft); max-width: 60ch; }

.section { margin-top: 24px; }
.panel {
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  padding: 22px 24px;
  box-shadow: var(--shadow-sm);
}
.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 0;
  border-bottom: 1px solid var(--c-border);
}
.row:last-child { border-bottom: 0; }
.row .label { font-weight: 500; color: var(--c-text); font-size: 14px; }
.row .desc { font-size: 12px; color: var(--c-text-mute); margin-top: 4px; }

.theme-toggle {
  display: inline-flex;
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: 8px;
  padding: 2px;
}
.theme-toggle button {
  padding: 6px 14px;
  font-size: 12px;
  color: var(--c-text-mute);
  border-radius: 6px;
  transition: all var(--dur-fast) var(--ease-out);
}
.theme-toggle button.active {
  background: var(--c-text);
  color: var(--c-bg);
}

.channels {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 18px;
}
.channel {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border: 1px solid var(--c-border);
  border-radius: 10px;
  gap: 16px;
}
.channel.configured { border-color: var(--c-up-soft); background: color-mix(in srgb, var(--c-up-soft) 60%, transparent); }
.channel-name { font-weight: 500; font-size: 14px; }
.channel-meta { font-size: 12px; color: var(--c-text-mute); margin-top: 2px; }
.channel-status {
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 6px;
  background: var(--c-bg-soft);
  color: var(--c-text-mute);
}
.channel.configured .channel-status {
  background: var(--c-up-soft);
  color: var(--c-up);
}

.notice {
  margin-top: 18px;
  font-size: 13px;
  color: var(--c-text-soft);
  background: var(--c-bg-soft);
  border: 1px dashed var(--c-border);
  border-radius: 10px;
  padding: 14px 16px;
}
.notice code {
  font-family: var(--font-mono);
  font-size: 12px;
  background: var(--c-surface);
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid var(--c-border);
}
`;

const CHANNEL_META: Record<string, { label: string; key: string; help: string }> = {
  webhook: { label: "Webhook", key: "WEBHOOK_URLS", help: "POST 到任意你给的 URL（多条逗号分隔）" },
  telegram: { label: "Telegram", key: "TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID", help: "BotFather 创建机器人后填 token 与 chat id" },
  feishu: { label: "飞书 Lark", key: "FEISHU_WEBHOOK_URL", help: "群机器人 webhook 地址" },
  wecom: { label: "企业微信", key: "WECOM_KEY", help: "群机器人 key（webhook URL 末段 key 参数）" },
  email: { label: "邮件 SMTP", key: "EMAIL_SMTP_*", help: "host / port / user / pass / from / to 五件套" },
};

export function renderSettings(): HTMLElement {
  const root = document.createElement("div");
  root.dataset.title = "设置";
  root.innerHTML = `
    <style>${CSS}</style>
    <aurumers-shell>
      <div class="settings shell">
        <span class="section-eyebrow" data-anim="0">设置</span>
        <h1 data-anim="0">个性化与推送</h1>
        <p class="lead" data-anim="1">主题切换即时生效，推送通道由后端 .env 控制；UI 显示哪些通道已配置，未配置时给出占位与对应的环境变量名。</p>

        <section class="section" data-anim="2">
          <div class="panel">
            <aurumers-section-header eyebrow="外观" titleText="主题"></aurumers-section-header>
            <div class="row">
              <div>
                <div class="label">主题模式</div>
                <div class="desc">auto 跟随系统；手动选择 light / dark 后会持久化在浏览器。</div>
              </div>
              <div class="theme-toggle" id="theme-toggle">
                <button data-mode="auto">系统</button>
                <button data-mode="light">浅色</button>
                <button data-mode="dark">深色</button>
              </div>
            </div>
          </div>
        </section>

        <section class="section" data-anim="3">
          <div class="panel">
            <aurumers-section-header eyebrow="管理员" titleText="管理员令牌" desc="保留一些敏感操作（如删除记录）需要服务端配置 ADMIN_TOKEN，这里填入后浏览器会随每次请求自动附带。仅保存在本机 localStorage。"></aurumers-section-header>
            <div class="row" style="flex-direction: column; align-items: stretch; gap: 12px;">
              <input id="admin-token" type="password" placeholder="未配置 / 填写后保存" autocomplete="off"
                     style="width: 100%; padding: 10px 14px; border: 1px solid var(--c-border); border-radius: 8px; background: var(--c-surface); color: var(--c-text); font-family: var(--font-mono); font-size: 13px;" />
              <div style="display: flex; gap: 8px; justify-content: flex-end;">
                <button id="admin-clear" class="btn btn-ghost">清除</button>
                <button id="admin-save" class="btn btn-primary">保存</button>
              </div>
            </div>
          </div>
        </section>

        <section class="section" data-anim="4">
          <div class="panel">
            <aurumers-section-header eyebrow="消息推送" titleText="通道接入状态" desc="未配置即灰，配置完成且后端读取后变绿。"></aurumers-section-header>
            <div class="channels" id="channels"></div>
            <div class="notice">
              <strong>如何启用：</strong>把对应的环境变量写入服务器 <code>/opt/aurumers/.env</code>，重启 <code>systemctl restart aurumers</code> 即可生效；测试推送需要将 <code>ALLOW_TEST_NOTIFY=1</code> 与 <code>ADMIN_TOKEN=...</code> 同时配上。
            </div>
          </div>
        </section>
      </div>
      <aurumers-toast-stack></aurumers-toast-stack>
    </aurumers-shell>
  `;

  setupThemeToggle(root);
  setupAdminToken(root);
  void loadChannels(root);
  return root;
}

function setupAdminToken(root: HTMLElement) {
  const input = root.querySelector<HTMLInputElement>("#admin-token");
  const save = root.querySelector<HTMLButtonElement>("#admin-save");
  const clear = root.querySelector<HTMLButtonElement>("#admin-clear");
  if (!input || !save || !clear) return;
  try {
    const existing = localStorage.getItem("aurumers.adminToken");
    if (existing) input.value = existing;
  } catch {
    // ignore
  }
  save.addEventListener("click", () => {
    try {
      const value = input.value.trim();
      if (value) {
        localStorage.setItem("aurumers.adminToken", value);
        toast("已保存管理员令牌", "success");
      } else {
        localStorage.removeItem("aurumers.adminToken");
        toast("已清除管理员令牌", "info");
      }
    } catch (err: any) {
      toast(err?.message || "无法访问 localStorage", "error");
    }
  });
  clear.addEventListener("click", () => {
    input.value = "";
    try { localStorage.removeItem("aurumers.adminToken"); } catch { /* ignore */ }
    toast("已清除管理员令牌", "info");
  });
}

function setupThemeToggle(root: HTMLElement) {
  const current: ThemeMode = getTheme();
  const buttons = root.querySelectorAll<HTMLButtonElement>("#theme-toggle button");
  buttons.forEach((btn) => {
    if (btn.dataset.mode === current) btn.classList.add("active");
    btn.addEventListener("click", () => {
      const mode = btn.dataset.mode as ThemeMode;
      setTheme(mode);
      buttons.forEach((b) => b.classList.toggle("active", b === btn));
      toast(`主题已切换：${mode}`, "info");
    });
  });
}

async function loadChannels(root: HTMLElement) {
  try {
    const channels: ChannelStatus = await api.channels();
    const host = root.querySelector<HTMLDivElement>("#channels");
    if (!host) return;
    host.innerHTML = "";
    const configured = new Set(channels.configured);
    for (const name of channels.available) {
      const meta = CHANNEL_META[name] || { label: name, key: name.toUpperCase(), help: "" };
      const isOn = configured.has(name);
      const div = document.createElement("div");
      div.className = `channel ${isOn ? "configured" : ""}`;
      div.innerHTML = `
        <div>
          <div class="channel-name">${meta.label}</div>
          <div class="channel-meta">${meta.help} · 环境变量：<code style="font-family:var(--font-mono);font-size:11px;">${meta.key}</code></div>
        </div>
        <span class="channel-status">${isOn ? "已配置" : "未配置"}</span>
      `;
      host.appendChild(div);
    }
  } catch (err: any) {
    toast(err?.message || "通道状态加载失败", "error");
  }
}
