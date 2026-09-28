// ============================================================================
// 会话 UI：登录 / 注册 / 登出 / 应用启动
// ============================================================================

let currentUser = null;
let credentialsStatus = { has_deepseek_key: false, smtp_user: "", has_smtp_pass: false };
let appBooted = false;

function el(id) {
  return document.getElementById(id);
}

function esc(s) {
  if (typeof escapeHtml === "function") return escapeHtml(s);
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function toast(message, kind = "info", ms = 4200) {
  const box = el("toast");
  if (!box) return alert(message);
  const div = document.createElement("div");
  div.className = "toast-item " + kind;
  div.textContent = message;
  box.appendChild(div);
  setTimeout(() => div.remove(), ms);
}

// ---------------------------------------------------------------------------
// 视图切换
// ---------------------------------------------------------------------------
function showLoginView() {
  const screen = el("login-screen");
  if (screen) screen.classList.remove("hidden");
  const appRoot = el("app-root");
  if (appRoot) appRoot.classList.add("hidden");
  const chip = el("user-chip");
  if (chip) chip.textContent = "";
  appBooted = false;
  document.querySelectorAll(".modal-overlay").forEach((m) => m.classList.add("hidden"));
}

function showAppView() {
  const screen = el("login-screen");
  if (screen) screen.classList.add("hidden");
  const appRoot = el("app-root");
  if (appRoot) appRoot.classList.remove("hidden");
}

function setLoginMode(mode) {
  const isRegister = mode === "register";
  el("login-tab-login").classList.toggle("active", !isRegister);
  el("login-tab-register").classList.toggle("active", isRegister);
  el("login-submit").textContent = isRegister ? "注册" : "登录";
  el("login-hint").textContent = isRegister
    ? "注册后需要到邮箱点确认链接，然后回来登录。"
    : "用你的邮箱和密码登录。";
  el("login-error").classList.add("hidden");
}

function showLoginError(message) {
  const box = el("login-error");
  box.textContent = message;
  box.classList.remove("hidden");
}

// ---------------------------------------------------------------------------
// 登录 / 注册
// ---------------------------------------------------------------------------
let loginMode = "login";

async function submitLogin(event) {
  if (event) event.preventDefault();
  const email = el("login-email").value.trim();
  const password = el("login-password").value;
  const btn = el("login-submit");

  if (!email || !password) {
    showLoginError("请填写邮箱和密码。");
    return;
  }

  btn.disabled = true;
  btn.textContent = loginMode === "register" ? "注册中…" : "登录中…";
  el("login-error").classList.add("hidden");

  try {
    const result =
      loginMode === "register"
        ? await SessionApi.register(email, password)
        : await SessionApi.login(email, password);

    if (result && result.status === "needs_confirmation") {
      showLoginError(result.message || "请到邮箱点确认链接后再登录。");
      el("login-resend").classList.remove("hidden");
      return;
    }

    el("login-password").value = "";
    await startApp();
  } catch (e) {
    showLoginError(e.message);
  } finally {
    btn.disabled = false;
    setLoginMode(loginMode);
  }
}

async function resendConfirmation() {
  const email = el("login-email").value.trim();
  if (!email) {
    showLoginError("请先填邮箱。");
    return;
  }
  try {
    const r = await SessionApi.resend(email);
    toast(r.message || "已重发，请查收（注意垃圾邮件）", "info", 6000);
  } catch (e) {
    showLoginError(e.message);
  }
}

// ---------------------------------------------------------------------------
// 应用启动 / 结束
// ---------------------------------------------------------------------------
async function startApp() {
  let me = null;
  try {
    me = await SessionApi.me();
  } catch (e) {
    if (e.status === 401) {
      showLoginView();
      return;
    }
    toast("加载账号信息失败：" + e.message, "error");
  }

  currentUser = me;
  credentialsStatus = (me && me.credentials) || credentialsStatus;

  const chip = el("user-chip");
  if (chip) chip.textContent = (me && me.email) || "";

  showAppView();
  appBooted = true;

  // 让既有的 app.js 逻辑开始工作（它原来在脚本末尾直接调用这两个函数）
  try {
    if (typeof loadPending === "function") await loadPending();
    if (typeof loadEvents === "function") await loadEvents();
  } catch (e) {
    toast("加载数据失败：" + e.message, "error");
  }

  if (!credentialsStatus.has_deepseek_key) {
    // 第一次用：引导配置 API Key
    openCredentials(true);
  }
}

function onSessionLost() {
  if (!appBooted && el("login-screen").classList.contains("hidden") === false) return;
  currentUser = null;
  appBooted = false;
  showLoginView();
  toast("登录状态已失效，请重新登录。", "error");
}

async function doLogout() {
  try {
    await SessionApi.logout();
  } catch (e) {
    /* 本地照样清干净 */
  }
  const history = el("chat-history");
  if (history) history.innerHTML = "";
  currentUser = null;
  credentialsStatus = { has_deepseek_key: false, smtp_user: "", has_smtp_pass: false };
  showLoginView();
  setLoginMode("login");
  el("login-password").value = "";
}

// ---------------------------------------------------------------------------
// 初始化
// ---------------------------------------------------------------------------
async function initSession() {
  el("login-tab-login").addEventListener("click", () => {
    loginMode = "login";
    setLoginMode("login");
  });
  el("login-tab-register").addEventListener("click", () => {
    loginMode = "register";
    setLoginMode("register");
  });
  el("login-form").addEventListener("submit", submitLogin);
  el("login-resend").addEventListener("click", resendConfirmation);
  el("logout-btn").addEventListener("click", doLogout);
  el("settings-btn").addEventListener("click", () => openCredentials(false));
  el("user-chip").addEventListener("click", () => openCredentials(false));

  // 任何请求发现会话没了，都会走这里
  window.onSessionLost = onSessionLost;

  setLoginMode("login");

  try {
    const info = await SessionApi.info();
    if (info && info.authenticated) {
      await startApp();
      return;
    }
  } catch (e) {
    /* 未登录是正常情况 */
  }
  showLoginView();
}

document.addEventListener("DOMContentLoaded", initSession);
