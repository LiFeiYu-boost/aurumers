import { ApiError, api, getOrCreateClientId } from "../api/client";
import { toast } from "../components/Toast";
import type { ChatBubble } from "../components/ChatBubble";
import type { ChatGreeting, ChatMessage, ChatSession } from "../api/schemas";

const CSS = `
.chat-shell {
  width: min(1280px, calc(100% - 32px));
  margin: 0 auto;
  padding: 18px 0 8px;
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 20px;
  height: calc(100vh - 100px);
}
.sidebar {
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  padding: 18px;
  height: 100%;
  display: flex;
  flex-direction: column;
}
.main {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  padding: 18px 22px 0;
  position: relative;
  overflow: hidden;
}
.chat-topbar {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--c-border);
}
.chat-topbar h1 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  letter-spacing: -0.01em;
}
.banner {
  margin: 12px 0 4px;
  padding: 10px 14px;
  background: var(--c-bg-soft);
  border-left: 2px solid var(--c-accent);
  border-radius: 8px;
  font-size: 12px;
  color: var(--c-text-soft);
  line-height: 1.6;
}
.thread {
  flex: 1;
  overflow-y: auto;
  padding: 16px 0;
  display: flex;
  flex-direction: column;
}
.sidebar-backdrop {
  display: none;
}
.mobile-toggle {
  display: none;
}
@media (max-width: 960px) {
  .chat-shell {
    grid-template-columns: 1fr;
    height: calc(100vh - 100px);
    width: calc(100% - 16px);
  }
  .sidebar {
    position: fixed;
    inset: 0 30% 0 0;
    z-index: 60;
    transform: translateX(-100%);
    transition: transform 280ms var(--ease-spring);
    border-radius: 0 14px 14px 0;
    box-shadow: var(--shadow-lg);
  }
  .chat-shell[data-mobile-open="true"] .sidebar {
    transform: translateX(0);
  }
  .mobile-toggle {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 10px;
    border-radius: 8px;
    background: var(--c-surface-2);
    color: var(--c-text);
    font-size: 12px;
    cursor: pointer;
  }
  .sidebar-backdrop {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(15, 12, 8, 0.34);
    z-index: 55;
    backdrop-filter: blur(2px);
  }
  .chat-shell[data-mobile-open="true"] .sidebar-backdrop {
    display: block;
  }
}
`;

interface State {
  clientId: string;
  sessions: ChatSession[];
  activeId: string;
  messages: ChatMessage[];
  greeting: ChatGreeting | null;
  streaming: boolean;
}

export function renderChat(): HTMLElement {
  const root = document.createElement("div");
  root.dataset.title = "Hermes 对话";
  root.innerHTML = `
    <style>${CSS}</style>
    <aurumers-shell>
      <div class="chat-shell" data-mobile-open="false">
        <div class="sidebar-backdrop"></div>
        <aside class="sidebar">
          <aurumers-chat-session-list id="session-list"></aurumers-chat-session-list>
        </aside>
        <section class="main">
          <div class="chat-topbar">
            <h1 id="chat-title">Hermes 对话</h1>
            <button class="mobile-toggle" id="mobile-toggle">📋 历史</button>
          </div>
          <div class="banner">
            ✨ Hermes 是 Aurumers 的对话助手，只聊黄金行情和网站使用；不会触碰代码 / 部署 / 服务器，也无法执行任何操作。
          </div>
          <div class="thread" id="thread"></div>
          <aurumers-chat-input id="chat-input"></aurumers-chat-input>
        </section>
      </div>
      <aurumers-toast-stack></aurumers-toast-stack>
    </aurumers-shell>
  `;

  const state: State = {
    clientId: getOrCreateClientId(),
    sessions: [],
    activeId: "",
    messages: [],
    greeting: null,
    streaming: false,
  };

  setupMobile(root);
  setupSidebarHandlers(root, state);
  setupInput(root, state);
  void boot(root, state);
  return root;
}

function setupMobile(root: HTMLElement) {
  const shell = root.querySelector<HTMLDivElement>(".chat-shell");
  const toggle = root.querySelector<HTMLButtonElement>("#mobile-toggle");
  const backdrop = root.querySelector<HTMLDivElement>(".sidebar-backdrop");
  if (!shell || !toggle) return;
  toggle.addEventListener("click", () => {
    shell.dataset.mobileOpen = shell.dataset.mobileOpen === "true" ? "false" : "true";
  });
  backdrop?.addEventListener("click", () => { shell.dataset.mobileOpen = "false"; });
}

function setupSidebarHandlers(root: HTMLElement, state: State) {
  const list = root.querySelector<HTMLElement>("#session-list") as any;
  if (!list) return;
  list.addEventListener("session-create", () => void createSession(root, state));
  list.addEventListener("session-select", (event: Event) => {
    const id = (event as CustomEvent<{ id: string }>).detail.id;
    void switchSession(root, state, id);
  });
  list.addEventListener("session-delete", (event: Event) => {
    const id = (event as CustomEvent<{ id: string }>).detail.id;
    void deleteSession(root, state, id);
  });
}

function setupInput(root: HTMLElement, state: State) {
  const input = root.querySelector<HTMLElement>("#chat-input") as any;
  if (!input) return;
  input.addEventListener("send", async (event: Event) => {
    const content = (event as CustomEvent<{ content: string }>).detail.content;
    await sendMessage(root, state, content);
  });
}

async function boot(root: HTMLElement, state: State) {
  try {
    const [greeting, sessions] = await Promise.all([
      api.chat.greeting(),
      api.chat.listSessions(state.clientId),
    ]);
    state.greeting = greeting;
    state.sessions = sessions;
    refreshSessionList(root, state);

    if (sessions.length > 0) {
      await switchSession(root, state, sessions[0].id);
    } else {
      await createSession(root, state);
    }
  } catch (err: any) {
    if (err instanceof ApiError) {
      toast(err.message || "聊天初始化失败", "error");
    } else {
      toast("聊天初始化失败", "error");
    }
  }
}

function refreshSessionList(root: HTMLElement, state: State) {
  const list = root.querySelector<HTMLElement>("#session-list") as any;
  if (!list) return;
  list.sessions = state.sessions;
  list.activeId = state.activeId;
}

async function createSession(root: HTMLElement, state: State) {
  try {
    const session = await api.chat.createSession(state.clientId);
    state.sessions = [session, ...state.sessions];
    state.activeId = session.id;
    state.messages = [];
    refreshSessionList(root, state);
    renderThread(root, state);
    setTitle(root, session.title);
  } catch (err: any) {
    toast(err?.message || "新建对话失败", "error");
  }
}

async function switchSession(root: HTMLElement, state: State, id: string) {
  try {
    state.activeId = id;
    refreshSessionList(root, state);
    state.messages = await api.chat.listMessages(id, state.clientId);
    const matched = state.sessions.find((s) => s.id === id);
    setTitle(root, matched?.title || "Hermes 对话");
    renderThread(root, state);
  } catch (err: any) {
    toast(err?.message || "加载会话失败", "error");
  }
}

async function deleteSession(root: HTMLElement, state: State, id: string) {
  if (!confirm("删除这个对话？历史消息会被归档但不再显示。")) return;
  try {
    await api.chat.deleteSession(id, state.clientId);
    state.sessions = state.sessions.filter((s) => s.id !== id);
    if (state.activeId === id) {
      if (state.sessions.length > 0) {
        await switchSession(root, state, state.sessions[0].id);
      } else {
        await createSession(root, state);
      }
    } else {
      refreshSessionList(root, state);
    }
    toast("对话已删除", "info");
  } catch (err: any) {
    toast(err?.message || "删除失败", "error");
  }
}

function setTitle(root: HTMLElement, title: string) {
  const titleEl = root.querySelector<HTMLElement>("#chat-title");
  if (titleEl) titleEl.textContent = title || "Hermes 对话";
}

function renderThread(root: HTMLElement, state: State) {
  const thread = root.querySelector<HTMLDivElement>("#thread");
  if (!thread) return;
  thread.innerHTML = "";

  if (state.messages.length === 0 && state.greeting) {
    const card = document.createElement("aurumers-chat-greeting-card") as any;
    card.greeting = state.greeting;
    card.addEventListener("suggestion-select", (event: Event) => {
      const question = (event as CustomEvent<{ question: string }>).detail.question;
      void sendMessage(root, state, question);
    });
    thread.appendChild(card);
  }

  for (const msg of state.messages) {
    appendBubble(thread, msg.role === "user" ? "user" : "assistant", msg.content);
  }
  scrollToBottom(thread);
}

function appendBubble(thread: HTMLElement, variant: "user" | "assistant", content: string, typing = false): ChatBubble {
  const bubble = document.createElement("aurumers-chat-bubble") as any;
  bubble.variant = variant;
  bubble.content = content;
  bubble.typing = typing;
  thread.appendChild(bubble);
  return bubble;
}

function scrollToBottom(el: HTMLElement) {
  requestAnimationFrame(() => { el.scrollTop = el.scrollHeight; });
}

async function sendMessage(root: HTMLElement, state: State, content: string) {
  if (!state.activeId || state.streaming) return;
  const trimmed = content.trim();
  if (!trimmed) return;
  if (trimmed.length > 4000) {
    toast("消息超过 4000 字符上限", "warn");
    return;
  }

  state.streaming = true;
  const inputEl = root.querySelector<HTMLElement>("#chat-input") as any;
  if (inputEl) inputEl.disabled = true;

  const thread = root.querySelector<HTMLDivElement>("#thread");
  if (!thread) {
    state.streaming = false;
    if (inputEl) inputEl.disabled = false;
    return;
  }
  // Drop the greeting card once user sends the first message.
  if (state.messages.length === 0) {
    const card = thread.querySelector("aurumers-chat-greeting-card");
    if (card) card.remove();
  }

  appendBubble(thread, "user", trimmed);
  scrollToBottom(thread);

  const assistantBubble = appendBubble(thread, "assistant", "", true);
  let buffer = "";
  let frame: number | null = null;
  let everReceived = false;
  let succeeded = false;

  const flush = () => {
    if (assistantBubble) {
      assistantBubble.content = buffer || "（暂无回复）";
    }
    scrollToBottom(thread);
    frame = null;
  };

  try {
    for await (const chunk of api.chat.streamMessage(state.activeId, state.clientId, trimmed)) {
      buffer += chunk;
      everReceived = true;
      if (frame === null) frame = requestAnimationFrame(flush);
    }
    if (frame === null) {
      assistantBubble.content = buffer || "（暂无回复）";
    }
    assistantBubble.typing = false;
    if (!everReceived) assistantBubble.content = "（模型未返回内容，请稍后重试）";
    succeeded = everReceived;

    // Optimistic: refresh sessions to pick up the auto-summarized title (only for first message).
    setTimeout(() => { void refreshSessions(root, state); }, 1500);
  } catch (err: any) {
    assistantBubble.typing = false;
    assistantBubble.content = `（出错了：${err?.message || "请求失败"}）`;
    toast(err?.message || "发送失败", "error");
    // On failure, drop both bubbles from the rendered thread to keep UI honest.
    setTimeout(() => {
      assistantBubble.remove();
      // Remove the user bubble we just rendered, too — last child of class user.
      const userBubbles = thread.querySelectorAll('aurumers-chat-bubble[variant="user"]');
      const last = userBubbles[userBubbles.length - 1];
      if (last) last.remove();
    }, 2400);
  } finally {
    state.streaming = false;
    if (inputEl) inputEl.disabled = false;
    if (succeeded) {
      state.messages = [
        ...state.messages,
        { id: `tmp-u-${Date.now()}`, session_id: state.activeId, role: "user", content: trimmed, created_at: new Date().toISOString() },
        { id: `tmp-a-${Date.now()}`, session_id: state.activeId, role: "assistant", content: assistantBubble.content, created_at: new Date().toISOString() },
      ];
    }
  }
}

async function refreshSessions(root: HTMLElement, state: State) {
  try {
    const fresh = await api.chat.listSessions(state.clientId);
    state.sessions = fresh;
    refreshSessionList(root, state);
    const active = fresh.find((s) => s.id === state.activeId);
    if (active) setTitle(root, active.title);
  } catch {
    /* silent */
  }
}
