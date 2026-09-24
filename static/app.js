// ==================== DOM 引用 ====================
const chatHistory = document.getElementById("chat-history");
const chatInput = document.getElementById("chat-input");
const sendBtn = document.getElementById("send-btn");
const showSteps = document.getElementById("show-steps");
const resetBtn = document.getElementById("reset-btn");
const exportIcsBtn = document.getElementById("export-ics-btn");
const exportEmailBtn = document.getElementById("export-email-btn");
const taskList = document.getElementById("task-list");
const confirmAllBtn = document.getElementById("confirm-all-btn");
const tabButtons = document.querySelectorAll(".tab-btn");
const calendarDays = document.querySelector(".calendar-days");
const calendarBody = document.getElementById("calendar-body");
const rightPanel = document.querySelector(".right-panel");

// Next Week
const bottomHandle = document.getElementById("bottom-handle");
const nextWeekOverlay = document.getElementById("next-week-overlay");
const overlayTitle = document.getElementById("overlay-title");
const overlayClose = document.getElementById("overlay-close");
const overlayDaysHeader = document.getElementById("overlay-days-header");
const overlayBody = document.getElementById("overlay-body");

// Modal
const eventModal = document.getElementById("event-modal");
const modalDetails = document.getElementById("modal-details");
const modalAlter = document.getElementById("modal-alter");

const viewTitle = document.getElementById("view-title");
const viewTime = document.getElementById("view-time");
const viewLocation = document.getElementById("view-location");
const viewNote = document.getElementById("view-note");

const editTitle = document.getElementById("edit-title");
const editStart = document.getElementById("edit-start");
const editEnd = document.getElementById("edit-end");
const editLocation = document.getElementById("edit-location");
const editNote = document.getElementById("edit-note");

const modalSaveBtn = document.getElementById("modal-save");
const modalDeleteBtn = document.getElementById("modal-delete");
const modalEditBtn = document.getElementById("modal-edit-btn");
const modalCloseBtn = document.getElementById("modal-close");
const modalCancelBtn = document.getElementById("modal-cancel");

// ==================== 状态 ====================
let pendingData = { confirmed: [], planned: [] };
let activeTab = "confirmed";
let confirmedEvents = [];
let editingEventId = null;

const EVENT_COLORS = [
  "var(--event-1)",
  "var(--event-2)",
  "var(--event-3)",
  "var(--event-4)",
  "var(--event-5)",
];

const HOUR_HEIGHT = parseFloat(
  getComputedStyle(document.documentElement).getPropertyValue("--hour-height")
);

// ==================== 工具函数 ====================
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function getMonday(date) {
  const d = new Date(date);
  const day = d.getDay();
  const diff = day === 0 ? -6 : 1 - day;
  d.setDate(d.getDate() + diff);
  d.setHours(0, 0, 0, 0);
  return d;
}

function parseDateTime(str) {
  if (!str) return null;
  const m = String(str).match(/^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})$/);
  if (!m) return null;
  return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
}

function formatDateTime(d) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function formatDateOnly(d) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

// ==================== 聊天 ====================
function appendMessage(role, text) {
  const div = document.createElement("div");
  div.className = "msg " + role;
  div.textContent = text;
  chatHistory.appendChild(div);
  chatHistory.scrollTop = chatHistory.scrollHeight;
}

function appendSteps(steps) {
  if (!showSteps.checked) return;
  if (!steps || steps.length === 0) return;
  const div = document.createElement("div");
  div.className = "steps";
  div.textContent = steps
    .map((s) => `↳ 调用 ${s.tool}，参数 ${JSON.stringify(s.args)}`)
    .join("\n");
  chatHistory.appendChild(div);
  chatHistory.scrollTop = chatHistory.scrollHeight;
}

async function send() {
  const text = chatInput.value.trim();
  if (!text) return;

  appendMessage("user", text);
  chatInput.value = "";

  const loading = document.createElement("div");
  loading.className = "msg assistant";
  loading.textContent = "思考中...";
  chatHistory.appendChild(loading);
  chatHistory.scrollTop = chatHistory.scrollHeight;

  try {
    const resp = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    });
    const data = await resp.json();
    loading.remove();
    appendSteps(data.steps);
    appendMessage("assistant", data.output);
    if (data.tasks && data.tasks.length > 0) {
      await addTasks(data.tasks);
    }
  } catch (e) {
    loading.textContent = "出错了：" + e.message;
  }
}

// ==================== 任务列表 ====================
function currentTasks() {
  return activeTab === "confirmed" ? pendingData.confirmed : pendingData.planned;
}

function renderTasks() {
  taskList.innerHTML = "";

  confirmAllBtn.style.display = activeTab === "confirmed" ? "" : "none";

  const tasks = currentTasks();
  if (tasks.length === 0) {
    const empty = document.createElement("div");
    empty.style.color = "var(--text-dim)";
    empty.style.fontSize = "12px";
    empty.textContent = activeTab === "confirmed" ? "暂无待确认任务" : "暂无待计划任务";
    taskList.appendChild(empty);
    return;
  }

  tasks.forEach((task) => {
    const card = document.createElement("div");
    card.className = "task-card";
    const timeText = task.start
      ? `${task.start}${task.end ? " ~ " + task.end : ""}`
      : "待计划";

    const actionsHtml = activeTab === "confirmed"
      ? `<button class="confirm">确认</button>
         <button class="modify">修改</button>
         <button class="delete">删除</button>`
      : `<button class="modify">修改</button>
         <button class="delete">删除</button>`;

    const locHtml = task.location
      ? `<div class="task-location">${escapeHtml(task.location)}</div>`
      : "";

    const noteHtml = task.note
      ? `<div class="task-note">${escapeHtml(task.note)}</div>`
      : "";

    card.innerHTML = `
      <div class="task-title">${escapeHtml(task.title)}</div>
      <div class="task-time">${escapeHtml(timeText)}</div>
      ${locHtml}
      ${noteHtml}
      <div class="task-actions">${actionsHtml}</div>
    `;

    const confirmBtn = card.querySelector(".confirm");
    if (confirmBtn) confirmBtn.addEventListener("click", () => confirmTask(task.id));
    card.querySelector(".modify").addEventListener("click", () => modifyTask(task.id));
    card.querySelector(".delete").addEventListener("click", () => deleteTask(task.id));

    taskList.appendChild(card);
  });
}

async function addTasks(tasks) {
  for (const t of tasks) {
    if (!t.id) t.id = "task-" + Math.random().toString(36).slice(2, 8);
    await fetch("/pending/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(t),
    });
  }
  await loadPending();
}

async function deleteTask(id) {
  await fetch("/pending/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id }),
  });
  await loadPending();
}

async function modifyTask(id) {
  const task =
    pendingData.confirmed.find((t) => t.id === id) ||
    pendingData.planned.find((t) => t.id === id);
  if (!task) return;

  const newTitle = prompt("修改任务标题：", task.title);
  if (newTitle === null) return;
  task.title = newTitle.trim() || task.title;

  const newStart = prompt("修改开始时间（YYYY-MM-DD HH:MM，留空表示待计划）：", task.start || "");
  if (newStart === null) return;
  task.start = newStart.trim() || null;

  const newEnd = prompt("修改结束时间（YYYY-MM-DD HH:MM）：", task.end || "");
  if (newEnd === null) return;
  task.end = newEnd.trim() || null;

  const newLocation = prompt("修改地点（留空表示无）：", task.location || "");
  if (newLocation === null) return;
  task.location = newLocation.trim() || "";

  const newNote = prompt("修改备注（留空表示无）：", task.note || "");
  if (newNote === null) return;
  task.note = newNote.trim() || "";

  await fetch("/pending/update", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id: task.id,
      title: task.title,
      start: task.start,
      end: task.end,
      location: task.location,
      note: task.note,
    }),
  });
  await loadPending();
}

async function confirmTask(id) {
  const task =
    pendingData.confirmed.find((t) => t.id === id) ||
    pendingData.planned.find((t) => t.id === id);
  if (!task) return;

  if (task.start && !task.end) {
    const start = parseDateTime(task.start);
    if (start) {
      const end = new Date(start.getTime() + 60 * 60 * 1000);
      task.end = formatDateTime(end);
    }
  }

  await fetch("/pending/update", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id: task.id,
      title: task.title,
      start: task.start,
      end: task.end,
      location: task.location,
      note: task.note,
    }),
  });

  const resp = await fetch("/pending/confirm", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id }),
  });
  if (!resp.ok) return;

  await loadPending();
  await loadEvents();
}

async function confirmAll() {
  const ids = pendingData.confirmed.map((t) => t.id);
  for (const id of ids) {
    await confirmTask(id);
  }
}

// ==================== 数据加载 ====================
async function loadPending() {
  try {
    const resp = await fetch("/pending");
    const data = await resp.json();
    pendingData = data;
    renderTasks();
  } catch (e) {
    console.error("加载待办失败：", e);
  }
}

async function loadEvents() {
  try {
    const resp = await fetch("/events");
    const data = await resp.json();
    confirmedEvents = data.events || [];
    renderCalendar();
    renderNextWeekOverlay();
  } catch (e) {
    console.error("加载事件失败：", e);
  }
}

// ==================== 日历渲染 ====================
function renderCalendar() {
  const monday = getMonday(new Date());

  calendarDays.innerHTML = "<div></div>";
  const wdNames = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  for (let i = 0; i < 7; i++) {
    const d = new Date(monday);
    d.setDate(monday.getDate() + i);
    const div = document.createElement("div");
    div.textContent = `${wdNames[i]} ${d.getMonth() + 1}/${d.getDate()}`;
    calendarDays.appendChild(div);
  }

  calendarBody.innerHTML = "";

  const timeCol = document.createElement("div");
  timeCol.className = "time-col";
  for (let h = 0; h < 24; h++) {
    const slot = document.createElement("div");
    slot.className = "time-slot";
    slot.textContent = String(h).padStart(2, "0") + ":00";
    timeCol.appendChild(slot);
  }
  calendarBody.appendChild(timeCol);

  const dayCols = [];
  for (let i = 0; i < 7; i++) {
    const col = document.createElement("div");
    col.className = "day-col";
    for (let h = 0; h < 24; h++) {
      const slot = document.createElement("div");
      slot.className = "hour-slot";
      col.appendChild(slot);
    }
    calendarBody.appendChild(col);
    dayCols.push(col);
  }

  confirmedEvents.forEach((evt, idx) => {
    const start = parseDateTime(evt.start);
    const end = parseDateTime(evt.end);
    if (!start || !end) return;

    const dayIndex = Math.floor((start - monday) / (1000 * 60 * 60 * 24));
    if (dayIndex < 0 || dayIndex > 6) return;

    const startMin = start.getHours() * 60 + start.getMinutes();
    const endMin = end.getHours() * 60 + end.getMinutes();
    const top = (startMin / 60) * HOUR_HEIGHT;
    const height = Math.max(((endMin - startMin) / 60) * HOUR_HEIGHT, 20);

    const card = document.createElement("div");
    card.className = "event-card";
    card.style.top = top + "px";
    card.style.height = height + "px";
    card.style.background = EVENT_COLORS[idx % EVENT_COLORS.length];
    card.style.cursor = "pointer";
    card.textContent = evt.location
      ? `${evt.title} · ${evt.location}`
      : evt.title;
    card.addEventListener("click", (e) => {
      e.stopPropagation();
      openEventModal(evt.id);
    });
    dayCols[dayIndex].appendChild(card);
  });

  calendarBody.scrollTop = 7 * HOUR_HEIGHT;
}

// ==================== Next Week 覆盖层 ====================
function renderNextWeekOverlay() {
  const monday = getMonday(new Date());
  const nextMonday = new Date(monday);
  nextMonday.setDate(monday.getDate() + 7);
  const nextSunday = new Date(nextMonday);
  nextSunday.setDate(nextMonday.getDate() + 6);

  overlayTitle.textContent = `Next Week (${nextMonday.getMonth() + 1}/${nextMonday.getDate()} - ${nextSunday.getMonth() + 1}/${nextSunday.getDate()})`;

  const wdNames = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

  // 表头
  overlayDaysHeader.innerHTML = "<div class='overlay-spacer'></div>";
  for (let i = 0; i < 7; i++) {
    const d = new Date(nextMonday);
    d.setDate(nextMonday.getDate() + i);
    const div = document.createElement("div");
    div.textContent = `${wdNames[i]} ${d.getMonth() + 1}/${d.getDate()}`;
    overlayDaysHeader.appendChild(div);
  }

  // 主体
  overlayBody.innerHTML = "<div class='overlay-spacer'></div>";
  for (let i = 0; i < 7; i++) {
    const dayDate = new Date(nextMonday);
    dayDate.setDate(nextMonday.getDate() + i);
    const dayStr = formatDateOnly(dayDate);

    const col = document.createElement("div");
    col.className = "overlay-day-col";

    // 筛选当天事件
    const dayEvents = confirmedEvents.filter(
      (e) => e.start && e.start.startsWith(dayStr)
    );
    dayEvents.sort((a, b) => (a.start || "").localeCompare(b.start || ""));

    const morning = [];
    const afternoon = [];
    for (const e of dayEvents) {
      const hour = parseInt(e.start.slice(11, 13), 10);
      if (hour < 12) morning.push(e);
      else afternoon.push(e);
    }

    if (morning.length > 0) {
      const title = document.createElement("div");
      title.className = "overlay-section-title";
      title.textContent = "上午";
      col.appendChild(title);
      morning.forEach((e) => col.appendChild(makeOverlayCard(e, "morning")));
    }

    if (afternoon.length > 0) {
      const title = document.createElement("div");
      title.className = "overlay-section-title";
      title.textContent = "下午";
      col.appendChild(title);
      afternoon.forEach((e) => col.appendChild(makeOverlayCard(e, "afternoon")));
    }

    overlayBody.appendChild(col);
  }
}

function makeOverlayCard(evt, period) {
  const card = document.createElement("div");
  card.className = "overlay-card " + period;
  card.textContent = evt.title;
  card.title = evt.title;
  card.addEventListener("click", (e) => {
    e.stopPropagation();
    openEventModal(evt.id);
  });
  return card;
}

function openNextWeekOverlay() {
  renderNextWeekOverlay();
  nextWeekOverlay.classList.remove("hidden");
}

function closeNextWeekOverlay() {
  nextWeekOverlay.classList.add("hidden");
}

// ==================== Modal ====================
function openEventModal(eventId) {
  const evt = confirmedEvents.find((e) => e.id === eventId);
  if (!evt) return;

  editingEventId = eventId;

  viewTitle.textContent = evt.title || "(无标题)";
  const start = evt.start || "";
  const end = evt.end || "";
  viewTime.textContent = end ? `${start} ~ ${end}` : start;
  viewLocation.textContent = evt.location || "";
  viewNote.textContent = evt.note || "";

  switchToViewMode();
  eventModal.classList.remove("hidden");
}

function switchToViewMode() {
  modalDetails.classList.remove("hidden");
  modalAlter.classList.add("hidden");
}

function switchToEditMode() {
  const evt = confirmedEvents.find((e) => e.id === editingEventId);
  if (!evt) return;

  editTitle.value = evt.title || "";
  editStart.value = evt.start || "";
  editEnd.value = evt.end || "";
  editLocation.value = evt.location || "";
  editNote.value = evt.note || "";

  modalDetails.classList.add("hidden");
  modalAlter.classList.remove("hidden");
}

function closeEventModal() {
  eventModal.classList.add("hidden");
  editingEventId = null;
}

async function saveEventEdit() {
  if (!editingEventId) return;

  const body = {
    id: editingEventId,
    title: editTitle.value.trim(),
    start: editStart.value.trim(),
    end: editEnd.value.trim(),
    location: editLocation.value.trim(),
    note: editNote.value.trim(),
  };

  if (!body.title || !body.start) {
    alert("标题和开始时间不能为空");
    return;
  }

  const resp = await fetch("/event/update", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!resp.ok) {
    alert("保存失败");
    return;
  }

  await loadEvents();
  closeEventModal();
}

async function deleteEvent() {
  if (!editingEventId) return;
  if (!confirm("确定删除这个事件？")) return;

  const resp = await fetch("/event/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: editingEventId }),
  });

  if (!resp.ok) {
    alert("删除失败");
    return;
  }

  await loadEvents();
  closeEventModal();
}

// ==================== 事件绑定 ====================
sendBtn.addEventListener("click", send);
chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") send();
});

exportIcsBtn.addEventListener("click", () => {
  window.open("/export_ics", "_blank");
});

exportEmailBtn.addEventListener("click", async () => {
  const toEmail = prompt("收件邮箱：", "");
  if (!toEmail) return;

  try {
    const resp = await fetch("/export_email", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ to_email: toEmail.trim() }),
    });
    const data = await resp.json();
    alert(data.message || "已发送");
  } catch (e) {
    alert("发送失败：" + e.message);
  }
});

tabButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    activeTab = btn.dataset.tab;
    tabButtons.forEach((b) => b.classList.toggle("active", b === btn));
    renderTasks();
  });
});

confirmAllBtn.addEventListener("click", confirmAll);

resetBtn.addEventListener("click", async () => {
  await fetch("/reset", { method: "POST" });
  chatHistory.innerHTML = "";
  renderTasks();
});

// Next Week
bottomHandle.addEventListener("click", openNextWeekOverlay);
overlayClose.addEventListener("click", closeNextWeekOverlay);

// Modal
modalEditBtn.addEventListener("click", switchToEditMode);
modalCancelBtn.addEventListener("click", switchToViewMode);
modalCloseBtn.addEventListener("click", closeEventModal);
modalSaveBtn.addEventListener("click", saveEventEdit);
modalDeleteBtn.addEventListener("click", deleteEvent);

eventModal.addEventListener("click", (e) => {
  if (e.target === eventModal) {
    closeEventModal();
  }
});

// ==================== 初始化 ====================
loadPending();
loadEvents();