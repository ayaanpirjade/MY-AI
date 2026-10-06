const state = {
  user: null,
  demoAvailable: false,
  chats: [],
  chatId: null,
  messages: [],
  busy: false,
  loading: true,
  sidebar: false,
  settings: false,
  search: "",
  theme: localStorage.getItem("my-ai-theme") || "system",
  authMode: "login", // login | register
};

const app = document.querySelector("#app");
const apiBase = (window.MY_AI_API_BASE || "").replace(/\/$/, "");

async function api(path, options = {}) {
  const response = await fetch(`${apiBase}${path}`, {
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
    ...options,
  });
  const text = await response.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { error: text || "Invalid server response" };
  }
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

function toast(message, kind = "info") {
  const node = document.createElement("div");
  node.className = `toast ${kind}`;
  node.textContent = message;
  document.body.append(node);
  setTimeout(() => node.remove(), 3200);
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char])
  );
}

function markdown(value) {
  let html = esc(value);
  html = html.replace(
    /```([\w+-]*)\n?([\s\S]*?)```/g,
    (_, lang, code) =>
      `<pre><span class="code-label">${esc(lang || "code")}</span><code>${code.trim()}</code><button class="copy-code" data-copy="${encodeURIComponent(code.trim())}">Copy</button></pre>`
  );
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html
    .replace(/^### (.*)$/gm, "<h4>$1</h4>")
    .replace(/^## (.*)$/gm, "<h3>$1</h3>")
    .replace(/^# (.*)$/gm, "<h2>$1</h2>");
  html = html.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>").replace(/\*(.*?)\*/g, "<em>$1</em>");
  html = html.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noreferrer">$1</a>'
  );
  html = html
    .split(/\n\n+/)
    .map((block) => (/^<h[234]|^<pre>/.test(block) ? block : `<p>${block.replace(/\n/g, "<br>")}</p>`))
    .join("");
  return html;
}

function initials(user) {
  return (user?.name || user?.email || "You")
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}
function greeting() {
  const hour = new Date().getHours();
  return hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
}
function dateLabel(value) {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  const now = new Date();
  const diff = (now - d) / 86400000;
  if (diff < 1 && now.getDate() === d.getDate()) return "Today";
  if (diff < 2) return "Yesterday";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
function themeValue() {
  if (state.theme === "system") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return state.theme;
}
function applyTheme() {
  document.documentElement.dataset.theme = themeValue();
  localStorage.setItem("my-ai-theme", state.theme);
}

function renderAuth() {
  const isLogin = state.authMode === "login";
  app.innerHTML = `<main class="auth-screen"><div class="orbit one"></div><div class="orbit two"></div><section class="auth-card"><div class="brand"><span class="mark">✦</span><b>My AI</b></div><p class="eyebrow">Your intelligent workbench</p><h1>A clearer way to think with AI.</h1><p class="auth-copy">Ideas, learning, coding, and everyday work — in one calm place built for momentum.</p><div class="tabs"><button class="${isLogin ? "active" : ""}" id="tab-login">Sign in</button><button class="${!isLogin ? "active" : ""}" id="tab-register">Create account</button></div>
<form class="auth-form" id="auth-form">
  ${!isLogin ? `<label class="field"><span>Name</span><input name="name" type="text" placeholder="Your name" autocomplete="name" /></label>` : ""}
  <label class="field"><span>Email</span><input name="email" type="email" required placeholder="you@example.com" autocomplete="email" /></label>
  <label class="field"><span>Password</span><input name="password" type="password" required placeholder="${isLogin ? "Your password" : "Min 4 characters"}" autocomplete="${isLogin ? "current-password" : "new-password"}" /></label>
  <button class="primary" type="submit" id="auth-submit">${isLogin ? "↗ Sign in" : "✦ Create account"}</button>
</form>
${state.demoAvailable ? `<div class="divider"><span>or</span></div><button class="demo" id="demo">✦ Try the demo workspace</button><small class="demo-note">Preview-only demo mode. No account or password required.</small>` : ""}
<small class="auth-note">Your account is stored locally on this server. Sign out anytime from Settings.</small></section><p class="tagline">A focused space for the next useful step.</p></main>`;

  document.querySelector("#tab-login").onclick = () => {
    state.authMode = "login";
    renderAuth();
  };
  document.querySelector("#tab-register").onclick = () => {
    state.authMode = "register";
    renderAuth();
  };
  document.querySelector("#auth-form").onsubmit = async (event) => {
    event.preventDefault();
    const fd = new FormData(event.currentTarget);
    const email = String(fd.get("email") || "").trim();
    const password = String(fd.get("password") || "");
    const name = String(fd.get("name") || "").trim();
    const btn = document.querySelector("#auth-submit");
    btn.disabled = true;
    try {
      if (state.authMode === "register") {
        await api("/api/auth/register", {
          method: "POST",
          body: JSON.stringify({ email, password, name }),
        });
        toast("Account created", "success");
      } else {
        await api("/api/auth/login", {
          method: "POST",
          body: JSON.stringify({ email, password }),
        });
        toast("Signed in", "success");
      }
      await loadSession();
    } catch (error) {
      toast(error.message, "error");
      btn.disabled = false;
    }
  };
  document.querySelector("#demo")?.addEventListener("click", demoLogin);
}

async function demoLogin() {
  try {
    await api("/api/auth/demo-login", { method: "POST" });
    await loadSession();
    toast("Demo workspace ready", "success");
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderShell() {
  const filtered = state.chats.filter((chat) =>
    chat.title.toLowerCase().includes(state.search.toLowerCase())
  );
  app.innerHTML = `<div class="shell ${state.sidebar ? "drawer-open" : ""}"><div class="overlay"></div><aside class="sidebar"><div class="side-head"><div class="brand"><span class="mark small">✦</span><b>My AI</b></div><button class="close-drawer" aria-label="Close sidebar">×</button><button class="new-chat">＋ New chat <kbd>⌘ K</kbd></button><label class="search">⌕<input placeholder="Search chats" value="${esc(state.search)}" /></label><div class="history-title">History <span>${filtered.length}</span></div></div><div class="history">${
    filtered.length
      ? filtered
          .map(
            (chat) =>
              `<div class="history-item ${chat.id === state.chatId ? "active" : ""}" data-chat="${esc(chat.id)}"><span>◌</span><b>${esc(chat.title)}</b><small>${dateLabel(chat.updatedAt)}</small><button data-delete="${esc(chat.id)}" aria-label="Delete chat">×</button></div>`
          )
          .join("")
      : `<div class="empty-history">◫<p>${state.search ? "No matching chats" : "No conversations yet"}</p></div>`
  }</div><div class="side-foot"><button class="settings-open">⚙ Settings</button><button class="account"><span class="avatar">${initials(state.user)}</span><span><b>${esc(state.user?.name || "Demo User")}</b><small>${esc(state.user?.email || "demo@myai.local")}</small></span></button><button class="clear-history">Clear history</button></div></aside><main class="main"><header class="topbar"><button class="menu">☰</button><span class="top-title">${esc(state.chatId ? state.chats.find((chat) => chat.id === state.chatId)?.title || "Conversation" : "New conversation")}</span><div><button class="theme-toggle" title="Toggle theme">◐</button><span class="status"></span></div></header><section class="scroll"><div class="content">${state.messages.length ? renderMessages() : renderEmpty()}${
    state.busy
      ? `<div class="thinking"><span class="mark small">✦</span><span>My AI is thinking <i></i><i></i><i></i></span></div>`
      : ""
  }<div id="bottom"></div></div></section><footer class="composer-wrap"><form class="composer"><textarea rows="1" placeholder="Ask My AI anything…"></textarea><button type="submit" class="send">➤</button></form><small>My AI can make mistakes. Check important information.</small></footer></main>${state.settings ? renderSettings() : ""}</div>`;
  bindShell();
}

function renderEmpty() {
  return `<section class="empty"><div class="presence"><span class="mark">✦</span></div><p class="eyebrow">${greeting()}</p><h1>What can I help with?</h1><p class="lede">Ask anything — coding, writing, learning, planning, or just thinking out loud.</p><div class="suggestions">
    <button class="suggestion" data-prompt="${encodeURIComponent("Explain a complex topic simply")}"><span>✦</span><b>Explain simply</b><small>Break down a hard idea</small></button>
    <button class="suggestion" data-prompt="${encodeURIComponent("Write a clean Python function that…")}"><span>⌘</span><b>Write code</b><small>Functions, scripts, fixes</small></button>
    <button class="suggestion" data-prompt="${encodeURIComponent("Help me plan my week productively")}"><span>◈</span><b>Plan my week</b><small>Priorities & schedule</small></button>
    <button class="suggestion" data-prompt="${encodeURIComponent("Summarize this concept and give examples")}"><span>◎</span><b>Summarize</b><small>Key points + examples</small></button>
    <button class="suggestion" data-prompt="${encodeURIComponent("Brainstorm creative ideas for…")}"><span>◇</span><b>Brainstorm</b><small>Ideas & angles</small></button>
    <button class="suggestion" data-prompt="${encodeURIComponent("Review this text and improve the writing")}"><span>✎</span><b>Improve writing</b><small>Clarity & style</small></button>
  </div></section>`;
}

function renderMessages() {
  return state.messages
    .map((message) => {
      const isUser = message.role === "user";
      return `<article class="message ${isUser ? "user" : "assistant"}"><div class="message-avatar">${isUser ? initials(state.user) : "✦"}</div><div class="message-body"><div class="message-content">${isUser ? esc(message.content).replace(/\n/g, "<br>") : markdown(message.content)}</div>${
        !isUser
          ? `<div class="message-actions"><button data-copy="${encodeURIComponent(message.content)}">Copy</button><button data-share="${encodeURIComponent(message.content)}">Share</button><button data-regenerate>Regenerate</button></div>`
          : ""
      }</div></article>`;
    })
    .join("");
}

function renderSettings() {
  return `<div class="settings-panel"><div class="settings-card"><header><b>Settings</b><button class="settings-close" aria-label="Close">×</button></header><label class="setting">Theme<select id="theme"><option value="system" ${state.theme === "system" ? "selected" : ""}>System</option><option value="light" ${state.theme === "light" ? "selected" : ""}>Light</option><option value="dark" ${state.theme === "dark" ? "selected" : ""}>Dark</option></select></label><div class="setting-note">Account: ${esc(state.user?.email || "—")}<br>Powered by Groq. Conversations stay on this server.</div><button class="logout">Sign out</button></div></div>`;
}

function bindShell() {
  document.querySelector(".overlay").onclick = () => {
    state.sidebar = false;
    renderShell();
  };
  document.querySelector(".menu").onclick = () => {
    state.sidebar = true;
    renderShell();
  };
  document.querySelector(".close-drawer").onclick = () => {
    state.sidebar = false;
    renderShell();
  };
  document.querySelector(".new-chat").onclick = () => {
    state.chatId = null;
    state.messages = [];
    state.sidebar = false;
    renderShell();
  };
  document.querySelector(".search input").oninput = (event) => {
    state.search = event.target.value;
    renderShell();
    const input = document.querySelector(".search input");
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  };
  document.querySelectorAll("[data-chat]").forEach(
    (node) => (node.onclick = () => openChat(node.dataset.chat))
  );
  document.querySelectorAll("[data-delete]").forEach(
    (node) =>
      (node.onclick = (event) => {
        event.stopPropagation();
        deleteChat(node.dataset.delete);
      })
  );
  document.querySelector(".clear-history").onclick = clearHistory;
  document.querySelector(".settings-open").onclick = () => {
    state.settings = true;
    renderShell();
  };
  document.querySelector(".account").onclick = () => {
    state.settings = true;
    renderShell();
  };
  document.querySelector(".theme-toggle").onclick = () => {
    state.theme = state.theme === "dark" ? "light" : "dark";
    applyTheme();
    renderShell();
  };
  document.querySelectorAll(".suggestion").forEach(
    (node) => (node.onclick = () => sendMessage(decodeURIComponent(node.dataset.prompt)))
  );
  document.querySelectorAll("[data-copy]").forEach(
    (node) => (node.onclick = () => copy(decodeURIComponent(node.dataset.copy)))
  );
  document.querySelectorAll("[data-share]").forEach(
    (node) => (node.onclick = () => share(decodeURIComponent(node.dataset.share)))
  );
  document.querySelectorAll("[data-regenerate]").forEach((node) => (node.onclick = regenerate));
  document.querySelector(".composer").onsubmit = (event) => {
    event.preventDefault();
    const input = event.currentTarget.querySelector("textarea");
    sendMessage(input.value);
  };
  const textarea = document.querySelector("textarea");
  textarea.oninput = () => {
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`;
  };
  textarea.onkeydown = (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form.requestSubmit();
    }
  };
  document.querySelector(".settings-close")?.addEventListener("click", () => {
    state.settings = false;
    renderShell();
  });
  document.querySelector("#theme")?.addEventListener("change", (event) => {
    state.theme = event.target.value;
    applyTheme();
    renderShell();
  });
  document.querySelector(".logout")?.addEventListener("click", logout);
}

async function loadSession() {
  const data = await api("/api/auth/me");
  state.user = data.user;
  state.demoAvailable = Boolean(data.demoAvailable);
  state.loading = false;
  if (state.user) {
    await loadChats();
    renderShell();
  } else renderAuth();
}

async function loadChats() {
  const data = await api("/api/chats");
  state.chats = data.chats || [];
}

async function openChat(id) {
  try {
    const data = await api(`/api/chats/${encodeURIComponent(id)}`);
    state.chatId = id;
    state.messages = data.messages || [];
    state.sidebar = false;
    renderShell();
    scrollBottom();
  } catch (error) {
    toast(error.message, "error");
  }
}

async function deleteChat(id) {
  try {
    await api(`/api/chats/${encodeURIComponent(id)}`, { method: "DELETE" });
    state.chats = state.chats.filter((chat) => chat.id !== id);
    if (state.chatId === id) {
      state.chatId = null;
      state.messages = [];
    }
    renderShell();
    toast("Chat deleted", "success");
  } catch (error) {
    toast(error.message, "error");
  }
}

async function clearHistory() {
  if (!confirm("Clear all conversation history?")) return;
  try {
    await api("/api/chats", { method: "DELETE" });
    state.chats = [];
    state.chatId = null;
    state.messages = [];
    renderShell();
    toast("History cleared", "success");
  } catch (error) {
    toast(error.message, "error");
  }
}

async function sendMessage(value) {
  const text = String(value || "").trim();
  if (!text || state.busy) return;
  state.busy = true;
  if (!state.chatId) {
    try {
      const data = await api("/api/chats", {
        method: "POST",
        body: JSON.stringify({ title: text.slice(0, 56) }),
      });
      state.chatId = data.chat.id;
      state.chats.unshift(data.chat);
    } catch (error) {
      state.busy = false;
      toast(error.message, "error");
      return;
    }
  }
  const optimistic = {
    id: `local-${Date.now()}`,
    role: "user",
    content: text,
    createdAt: new Date().toISOString(),
  };
  state.messages.push(optimistic);
  renderShell();
  scrollBottom();
  try {
    const data = await api("/chat", {
      method: "POST",
      body: JSON.stringify({ chat_id: state.chatId, message: text }),
    });
    state.messages = state.messages.filter((item) => item.id !== optimistic.id);
    state.messages.push(optimistic, data.message);
    state.chats = [data.chat, ...state.chats.filter((chat) => chat.id !== data.chat.id)];
  } catch (error) {
    state.messages = state.messages.filter((item) => item.id !== optimistic.id);
    toast(error.message, "error");
  } finally {
    state.busy = false;
    renderShell();
    scrollBottom();
  }
}

async function regenerate() {
  const lastUser = [...state.messages].reverse().find((message) => message.role === "user");
  if (!lastUser || state.busy) return;
  state.busy = true;
  state.messages = state.messages.filter(
    (message) => message.role !== "assistant" || message !== state.messages[state.messages.length - 1]
  );
  renderShell();
  try {
    const data = await api("/chat", {
      method: "POST",
      body: JSON.stringify({ chat_id: state.chatId, regenerate: true }),
    });
    state.messages.push(data.message);
  } catch (error) {
    toast(error.message, "error");
  } finally {
    state.busy = false;
    renderShell();
    scrollBottom();
  }
}

async function logout() {
  await api("/api/auth/logout", { method: "POST" });
  state.user = null;
  state.chats = [];
  state.messages = [];
  state.chatId = null;
  state.settings = false;
  renderAuth();
  toast("Signed out", "success");
}

async function copy(value) {
  try {
    await navigator.clipboard.writeText(value);
    toast("Copied", "success");
  } catch {
    toast("Copy failed", "error");
  }
}

async function share(value) {
  if (navigator.share) {
    try {
      await navigator.share({ title: "My AI response", text: value });
    } catch {}
  } else copy(value);
}

function scrollBottom() {
  requestAnimationFrame(() => document.querySelector("#bottom")?.scrollIntoView({ behavior: "smooth" }));
}

applyTheme();
loadSession().catch((error) => {
  state.loading = false;
  state.demoAvailable = true;
  renderAuth();
  toast(`API connection failed: ${error.message}`, "error");
});
