// ============================================================================
// 凭据面板（DeepSeek Key / QQ 邮箱）与长期记忆面板
// ============================================================================

// ---------------------------------------------------------------------------
// 凭据
// ---------------------------------------------------------------------------
async function loadCredentialsStatus() {
  try {
    const r = await CredentialsApi.get();
    credentialsStatus = r.credentials || credentialsStatus;
  } catch (e) {
    /* 读不到就沿用已有状态 */
  }
  return credentialsStatus;
}

function renderCredentialsStatus() {
  const s = credentialsStatus || {};
  const keyInput = el("cred-key");
  const userInput = el("cred-user");
  const passInput = el("cred-pass");

  keyInput.placeholder = s.has_deepseek_key ? "已配置（留空表示不修改）" : "sk-...";
  userInput.placeholder = s.smtp_user ? "已配置：" + s.smtp_user : "你的QQ邮箱@qq.com";
  passInput.placeholder = s.has_smtp_pass ? "已配置（留空表示不修改）" : "16 位授权码";

  const state = el("cred-state");
  const parts = [];
  parts.push(s.has_deepseek_key ? "DeepSeek Key：已配置 ✓" : "DeepSeek Key：未配置");
  if (s.smtp_user || s.has_smtp_pass) {
    parts.push(`邮箱：${s.smtp_user || "已配置"}${s.has_smtp_pass ? "（授权码已存）" : ""}`);
  }
  if (s.updated_at) parts.push("更新于 " + s.updated_at);
  state.textContent = parts.join(" · ");
}

async function openCredentials(force) {
  el("cred-key").value = "";
  el("cred-user").value = "";
  el("cred-pass").value = "";
  await loadCredentialsStatus();
  renderCredentialsStatus();
  el("credentials-modal").classList.remove("hidden");
  el("cred-key").focus();
}

function closeCredentials() {
  el("credentials-modal").classList.add("hidden");
}

async function saveCredentials() {
  const payload = {
    deepseek_key: el("cred-key").value.trim(),
    smtp_user: el("cred-user").value.trim(),
    smtp_pass: el("cred-pass").value.trim(),
  };
  if (!payload.deepseek_key && !payload.smtp_user && !payload.smtp_pass) {
    toast("没有填写任何内容。", "error");
    return;
  }
  try {
    const r = await CredentialsApi.save(payload);
    credentialsStatus = r.credentials || credentialsStatus;
    renderCredentialsStatus();
    el("cred-key").value = "";
    el("cred-pass").value = "";
    toast("已加密保存在你的账号下，只有你能看到。", "ok");
    closeCredentials();
  } catch (e) {
    toast("保存失败：" + e.message, "error", 6000);
  }
}

async function clearCredentials() {
  if (!confirm("确定清空已保存的 API Key 和邮箱授权码？清空后需要重新填写。")) return;
  try {
    const r = await CredentialsApi.clear();
    credentialsStatus = r.credentials || { has_deepseek_key: false, smtp_user: "", has_smtp_pass: false };
    renderCredentialsStatus();
    toast("已清空。", "ok");
  } catch (e) {
    toast("清空失败：" + e.message, "error");
  }
}

// ---------------------------------------------------------------------------
// 长期记忆
// ---------------------------------------------------------------------------
let memoryData = { facts: [], observations: [], preferences: [], last_updated: "" };

async function openMemoryPanel() {
  el("memory-modal").classList.remove("hidden");
  el("memory-body").innerHTML = "<div class='muted'>加载中…</div>";
  try {
    const r = await MemoryApi.get();
    memoryData = r.memory || memoryData;
    renderMemory();
  } catch (e) {
    el("memory-body").innerHTML = `<div class="muted">加载失败：${esc(e.message)}</div>`;
  }
}

function closeMemoryPanel() {
  el("memory-modal").classList.add("hidden");
}

function renderMemory() {
  const body = el("memory-body");
  const blocks = [
    {
      key: "facts",
      title: "事实",
      hint: "你明确说过的稳定信息。",
      removable: true,
    },
    {
      key: "preferences",
      title: "偏好",
      hint: "带「据多次观察归纳」标记的是 AI 自己总结的，不是你直接说的 —— 不对就直接删掉。",
      removable: true,
    },
    {
      key: "observations",
      title: "观察台账",
      hint: "每次行为的原始记录，AI 靠它攒够多次才归纳出偏好。",
      removable: true,
    },
  ];

  let html = `<div class="memory-updated">最后更新：${esc(memoryData.last_updated || "（暂无）")}</div>`;

  for (const block of blocks) {
    const items = memoryData[block.key] || [];
    html += `<section class="memory-block">`;
    html += `<header><h4>${block.title}<span class="count">${items.length}</span></h4>`;
    html += `<button class="ghost" data-add="${block.key}">+ 添加</button></header>`;
    html += `<p class="hint">${esc(block.hint)}</p>`;
    if (!items.length) {
      html += `<div class="muted">（空）</div>`;
    } else {
      html += `<ul class="memory-list">`;
      items.forEach((item, index) => {
        const inferred = block.key === "preferences" && /归纳|观察/.test(item);
        html += `<li class="${inferred ? "inferred" : ""}">`;
        html += `<span class="text">${esc(item)}</span>`;
        html += `<button class="del" data-del="${block.key}" data-index="${index}" title="删除">×</button>`;
        html += `</li>`;
      });
      html += `</ul>`;
    }
    html += `</section>`;
  }

  html += `<div class="memory-footer"><button class="danger" id="memory-clear-all">清空全部记忆</button></div>`;
  body.innerHTML = html;

  body.querySelectorAll("[data-del]").forEach((btn) => {
    btn.addEventListener("click", () => deleteMemoryItem(btn.dataset.del, Number(btn.dataset.index)));
  });
  body.querySelectorAll("[data-add]").forEach((btn) => {
    btn.addEventListener("click", () => addMemoryItem(btn.dataset.add));
  });
  const clearAll = el("memory-clear-all");
  if (clearAll) clearAll.addEventListener("click", clearAllMemory);
}

async function deleteMemoryItem(key, index) {
  const items = (memoryData[key] || []).slice();
  items.splice(index, 1);
  await saveMemoryBlock(key, items);
}

async function addMemoryItem(key) {
  const label = { facts: "事实", preferences: "偏好", observations: "观察记录" }[key] || key;
  const value = prompt(`添加一条${label}：`);
  if (!value || !value.trim()) return;
  const items = (memoryData[key] || []).slice();
  items.push(value.trim());
  await saveMemoryBlock(key, items);
}

async function saveMemoryBlock(key, items) {
  try {
    const payload = {};
    payload[key] = items;
    const r = await MemoryApi.update(payload);
    memoryData = r.memory || memoryData;
    renderMemory();
    toast("已更新。", "ok", 2200);
  } catch (e) {
    toast("更新失败：" + e.message, "error", 6000);
  }
}

async function clearAllMemory() {
  if (!confirm("确定清空全部长期记忆？AI 会忘记关于你的一切。")) return;
  try {
    const r = await MemoryApi.clear();
    memoryData = r.memory || { facts: [], observations: [], preferences: [], last_updated: "" };
    renderMemory();
    toast("已清空全部记忆。", "ok");
  } catch (e) {
    toast("清空失败：" + e.message, "error");
  }
}

// ---------------------------------------------------------------------------
// 绑定
// ---------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  el("cred-save").addEventListener("click", saveCredentials);
  el("cred-clear").addEventListener("click", clearCredentials);
  el("cred-close").addEventListener("click", closeCredentials);
  el("credentials-modal").addEventListener("click", (e) => {
    if (e.target === el("credentials-modal")) closeCredentials();
  });

  el("memory-btn").addEventListener("click", openMemoryPanel);
  el("memory-close").addEventListener("click", closeMemoryPanel);
  el("memory-modal").addEventListener("click", (e) => {
    if (e.target === el("memory-modal")) closeMemoryPanel();
  });
});
