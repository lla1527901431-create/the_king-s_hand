// ============================================================================
// API 封装层
//
// 会话用的是 HttpOnly cookie：JavaScript **读不到** access_token，
// 所以前端完全不需要（也无法）自己管理 token。只需要做两件事：
//
//   1. 每个请求带 credentials: "same-origin"，让浏览器自动带上 cookie
//   2. 写操作带上 X-CSRF-Token 头（值从非 HttpOnly 的 kh_csrf cookie 读）
//
// access_token 过期时后端返回 401 + auth_code=token_expired，
// 这里自动调一次 /session/refresh 再重试原请求 —— 用户完全无感。
// ============================================================================

const AUTH_CODES = {
  NO_SESSION: "no_session",
  INVALID_TOKEN: "invalid_token",
  TOKEN_EXPIRED: "token_expired",
  CSRF_FAILED: "csrf_failed",
};

function getCookie(name) {
  const target = name + "=";
  for (const part of document.cookie.split(";")) {
    const item = part.trim();
    if (item.startsWith(target)) {
      return decodeURIComponent(item.slice(target.length));
    }
  }
  return "";
}

function getCsrfToken() {
  return getCookie("kh_csrf");
}

/** 把错误统一成 Error 对象，附带状态码与 auth_code，方便上层判断。 */
async function readError(resp) {
  let detail = "";
  let code = "";
  try {
    const data = await resp.json();
    detail = data.detail || data.message || "";
    code = data.auth_code || "";
  } catch (e) {
    detail = await resp.text().catch(() => "");
  }
  const err = new Error(detail || `请求失败（HTTP ${resp.status}）`);
  err.status = resp.status;
  err.authCode = code;
  return err;
}

let _refreshing = null;

/** 续期。并发请求只会触发一次真正的续期。 */
async function refreshSession() {
  if (_refreshing) return _refreshing;
  _refreshing = (async () => {
    try {
      const resp = await fetch("/session/refresh", {
        method: "POST",
        credentials: "same-origin",
      });
      if (!resp.ok) return false;
      await resp.json().catch(() => ({}));
      return true;
    } catch (e) {
      return false;
    } finally {
      // 留一点时间让并发的其它请求读到结果
      setTimeout(() => {
        _refreshing = null;
      }, 0);
    }
  })();
  return _refreshing;
}

/**
 * 统一的请求函数。
 * @param {string} path   例如 "/events"
 * @param {object} opts   { method, body, retry }
 */
async function api(path, opts = {}) {
  const method = (opts.method || "GET").toUpperCase();
  const headers = {};
  const isWrite = !["GET", "HEAD", "OPTIONS"].includes(method);

  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (isWrite) {
    const csrf = getCsrfToken();
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }

  const doFetch = () =>
    fetch(path, {
      method,
      headers,
      credentials: "same-origin",
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    });

  let resp = await doFetch();

  // access_token 过期或凭证无效 -> 尝试续期一次
  if (resp.status === 401) {
    let code = "";
    try {
      const clone = resp.clone();
      const data = await clone.json();
      code = data.auth_code || "";
    } catch (e) {
      /* 忽略 */
    }
    const canRetry = opts.retry !== false && (code === AUTH_CODES.TOKEN_EXPIRED || code === AUTH_CODES.INVALID_TOKEN);
    if (canRetry) {
      const ok = await refreshSession();
      if (ok) {
        resp = await doFetch();
      } else if (typeof onSessionLost === "function") {
        onSessionLost();
      }
    } else if (code === AUTH_CODES.NO_SESSION && typeof onSessionLost === "function") {
      onSessionLost();
    }
  } else if (resp.status === 403) {
    let code = "";
    try {
      const data = await resp.clone().json();
      code = data.auth_code || "";
    } catch (e) {
      /* 忽略 */
    }
    // CSRF 值失效（例如 cookie 被清）时，刷一次续期能拿到新的 csrf
    if (code === AUTH_CODES.CSRF_FAILED && opts.retry !== false) {
      const ok = await refreshSession();
      if (ok) {
        const csrf = getCsrfToken();
        if (csrf) headers["X-CSRF-Token"] = csrf;
        resp = await doFetch();
      }
    }
  }

  if (!resp.ok) throw await readError(resp);
  if (resp.status === 204) return null;
  const text = await resp.text();
  return text ? JSON.parse(text) : null;
}

// ---------------------------------------------------------------------------
// 会话相关
// ---------------------------------------------------------------------------
const SessionApi = {
  login: (email, password) => api("/session/login", { method: "POST", body: { email, password } }),
  register: (email, password) => api("/session/register", { method: "POST", body: { email, password } }),
  resend: (email) => api("/session/resend", { method: "POST", body: { email } }),
  info: () => api("/session", { retry: false }),
  logout: () => api("/session/logout", { method: "POST" }),
  me: () => api("/me"),
};

const CredentialsApi = {
  get: () => api("/credentials"),
  save: (payload) => api("/credentials", { method: "POST", body: payload }),
  clear: () => api("/credentials", { method: "DELETE" }),
};

const MemoryApi = {
  get: () => api("/memory"),
  update: (payload) => api("/memory/update", { method: "POST", body: payload }),
  clear: () => api("/memory/clear", { method: "POST" }),
};
