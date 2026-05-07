const STORAGE_KEY = "qq-helper-activities";
const CATEGORY_LIST = ["五育", "必做", "休闲活动"];

const aiForm = document.getElementById("ai-form");
const clearExpiredBtn = document.getElementById("clear-expired-btn");
const categoryFilter = document.getElementById("category-filter");
const activityList = document.getElementById("activity-list");
const emptyState = document.getElementById("empty-state");
const itemTemplate = document.getElementById("item-template");
let activeCategory = "全部";

function loadActivities() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch (error) {
    console.error("读取活动数据失败:", error);
    return [];
  }
}

function saveActivities(activities) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(activities));
}

function normalizeText(value, fallback = "无") {
  const text = String(value || "").trim();
  return text || fallback;
}

function normalizeDateTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toISOString();
}

function detectCategoryByContent(item) {
  const directCategory = String(item.category || "").trim();
  const textPool = [
    item.name,
    item.summary,
    item.location,
    item.chatText,
    item.sourceText,
    directCategory,
  ]
    .filter(Boolean)
    .join(" ");

  if (textPool.includes("五育")) return "五育";
  if (/讲座|工坊|分享/.test(textPool)) return "休闲活动";
  if (CATEGORY_LIST.includes(directCategory)) return directCategory;
  return "必做";
}

function normalizeActivity(raw) {
  const name = normalizeText(raw.name || raw.title, "");
  const summary = normalizeText(raw.summary || raw.description, "");
  const eventTime = normalizeDateTime(raw.eventTime);
  const ddl = normalizeDateTime(raw.ddl);
  if (!name || !summary || (!eventTime && !ddl)) return null;

  return {
    name,
    summary,
    location: normalizeText(raw.location),
    signupLink: normalizeText(raw.signupLink),
    category: detectCategoryByContent(raw),
    eventTime,
    ddl,
  };
}

function normalizeCategory(value) {
  return CATEGORY_LIST.includes(value) ? value : "必做";
}

function getActivityFingerprint(activity) {
  return normalizeText(activity.name, "").replace(/\s+/g, "").toLowerCase();
}

function isSameActivity(a, b) {
  return getActivityFingerprint(a) === getActivityFingerprint(b);
}

function hasActivityChanged(oldItem, nextItem) {
  return (
    oldItem.summary !== nextItem.summary ||
    oldItem.location !== nextItem.location ||
    oldItem.signupLink !== nextItem.signupLink ||
    oldItem.category !== nextItem.category ||
    oldItem.eventTime !== nextItem.eventTime ||
    oldItem.ddl !== nextItem.ddl
  );
}

function formatDateTime(value) {
  if (!value) return "未设置";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "未设置";
  return date.toLocaleString("zh-CN", { hour12: false });
}

function isExpired(activity, now = Date.now()) {
  const eventTime = activity.eventTime ? new Date(activity.eventTime).getTime() : null;
  const ddl = activity.ddl ? new Date(activity.ddl).getTime() : null;
  const expiredByEvent = eventTime && !Number.isNaN(eventTime) && now > eventTime;
  const expiredByDDL = ddl && !Number.isNaN(ddl) && now > ddl;
  return expiredByEvent || expiredByDDL;
}

function cleanExpiredActivities() {
  const activities = loadActivities();
  const valid = activities.filter((item) => !isExpired(item));
  if (valid.length !== activities.length) {
    saveActivities(valid);
  }
  renderActivities();
}

function createActivityItem(activity, index) {
  const node = itemTemplate.content.cloneNode(true);
  const titleEl = node.querySelector(".item-title");
  const metaEl = node.querySelector(".item-meta");
  const editBtn = node.querySelector(".edit-btn");
  const deleteBtn = node.querySelector(".delete-btn");

  titleEl.textContent = activity.name;
  metaEl.textContent = `概况：${activity.summary}
地点：${activity.location}
报名链接：${activity.signupLink}
活动时间：${formatDateTime(activity.eventTime)}
DDL：${formatDateTime(activity.ddl)}`;

  editBtn.addEventListener("click", () => {
    const nextName = prompt("活动名称（必填）", activity.name);
    if (nextName === null) return;
    const nextSummary = prompt("活动概况（必填）", activity.summary);
    if (nextSummary === null) return;
    const nextLocation = prompt("活动地点（无则填写无）", activity.location);
    if (nextLocation === null) return;
    const nextSignupLink = prompt("活动报名链接（无则填写无）", activity.signupLink);
    if (nextSignupLink === null) return;
    const nextEventTime = prompt(
      "活动时间（可空，推荐 ISO 或 2026-05-08 19:00）",
      activity.eventTime ? activity.eventTime.slice(0, 16) : ""
    );
    if (nextEventTime === null) return;
    const nextDDL = prompt(
      "DDL（可空，推荐 ISO 或 2026-05-08 19:00）",
      activity.ddl ? activity.ddl.slice(0, 16) : ""
    );
    if (nextDDL === null) return;

    const edited = normalizeActivity({
      name: nextName,
      summary: nextSummary,
      location: nextLocation,
      signupLink: nextSignupLink,
      category: activity.category,
      eventTime: nextEventTime,
      ddl: nextDDL,
    });

    if (!edited) {
      alert("保存失败：活动名称、活动概况必填，且 DDL 与活动时间至少填写一个。");
      return;
    }

    const activities = loadActivities();
    activities[index] = edited;
    saveActivities(activities);
    cleanExpiredActivities();
  });

  deleteBtn.addEventListener("click", () => {
    const activities = loadActivities();
    activities.splice(index, 1);
    saveActivities(activities);
    renderActivities();
  });

  return node;
}

function renderActivities() {
  const activities = loadActivities();
  activityList.innerHTML = "";
  const filtered = activities.filter((activity) => {
    if (activeCategory === "全部") return true;
    return normalizeCategory(activity.category) === activeCategory;
  });

  filtered.forEach((activity) => {
    const index = activities.findIndex((stored) => isSameActivity(stored, activity));
    activityList.appendChild(createActivityItem(activity, index));
  });

  emptyState.style.display = filtered.length === 0 ? "block" : "none";
}

function addActivities(items) {
  const current = loadActivities();
  const parsedItems = items.map(normalizeActivity).filter(Boolean);
  const merged = [...current];

  parsedItems.forEach((item) => {
    const existingIndex = merged.findIndex((stored) => isSameActivity(stored, item));
    if (existingIndex === -1) {
      merged.push(item);
      return;
    }
    if (hasActivityChanged(merged[existingIndex], item)) {
      merged[existingIndex] = { ...merged[existingIndex], ...item };
    }
  });

  saveActivities(merged);
  cleanExpiredActivities();
}

async function requestAI() {
  // TODO: 将 URL 换成你自己的后端接口
  const response = await fetch("/api/activities/extract", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });

  if (!response.ok) {
    throw new Error(`AI 接口请求失败: ${response.status}`);
  }

  const data = await response.json();
  if (!Array.isArray(data.activities)) {
    throw new Error("AI 返回格式错误，缺少 activities 数组");
  }
  return data;
}

aiForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const button = aiForm.querySelector("button[type='submit']");
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "处理中...";

  try {
    const result = await requestAI();
    addActivities(result.activities);

    if (result.activities.length === 0) {
      const debug = result.debug || {};
      alert(
        `同步到 0 条活动。\n` +
          `消息日志条数: ${debug.messageLogCount ?? 0}\n` +
          `回溯扫描消息数: ${debug.scannedMessages ?? 0}\n` +
          `AI密钥已配置: ${debug.hasApiKey ? "是" : "否"}\n` +
          `最近消息时间: ${debug.lastMessageTime || "无"}`
      );
    } else {
      alert(`成功同步 ${result.activities.length} 条活动`);
    }
  } catch (error) {
    console.error(error);
    alert("活动同步失败，请检查后端接口或返回数据格式。");
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
});

clearExpiredBtn.addEventListener("click", cleanExpiredActivities);
categoryFilter.addEventListener("change", () => {
  activeCategory = categoryFilter.value;
  renderActivities();
});

// 页面加载时清理一次，并每分钟自动清理一次
cleanExpiredActivities();
setInterval(cleanExpiredActivities, 60 * 1000);
