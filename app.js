const STORAGE_KEY = "qq-helper-activities";
const FAVORITES_STORAGE_KEY = "qq-helper-favorite-fingerprints";
const MIN_ACTIVITY_TEXT_LEN = 50;
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

function loadFavoriteFingerprints() {
  try {
    const raw = localStorage.getItem(FAVORITES_STORAGE_KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw);
    return new Set(Array.isArray(arr) ? arr.filter((x) => typeof x === "string") : []);
  } catch (error) {
    console.error("读取收藏失败:", error);
    return new Set();
  }
}

function saveFavoriteFingerprints(set) {
  localStorage.setItem(FAVORITES_STORAGE_KEY, JSON.stringify([...set]));
}

function toggleFavoriteFingerprint(fp) {
  const set = loadFavoriteFingerprints();
  if (set.has(fp)) {
    set.delete(fp);
  } else {
    set.add(fp);
  }
  saveFavoriteFingerprints(set);
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

  if (textPool.includes("五育") || /智育|德育|体育|美育|劳育/.test(textPool)) return "五育";
  if (/讲座|工坊|分享/.test(textPool)) return "休闲活动";
  if (CATEGORY_LIST.includes(directCategory)) return directCategory;
  return "必做";
}

function normalizeActivity(raw) {
  if (!raw || typeof raw !== "object") return null;
  const name = normalizeText(raw.name || raw.title, "");
  const summary = normalizeText(raw.summary || raw.description, "");
  const eventTime = normalizeDateTime(raw.eventTime);
  const ddl = normalizeDateTime(raw.ddl);
  if (!name || !summary) return null;
  if (name.trim().length + summary.trim().length < MIN_ACTIVITY_TEXT_LEN) return null;

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

/** 仅允许 http(s)，用于可点击报名链接；无法解析则返回 null */
function toSafeHttpHref(value) {
  const raw = String(value || "").trim();
  if (!raw || raw === "无") return null;
  const candidate = /^https?:\/\//i.test(raw) ? raw : `https://${raw.replace(/^\/+/, "")}`;
  try {
    const u = new URL(candidate);
    if (u.protocol !== "http:" && u.protocol !== "https:") return null;
    return u.href;
  } catch {
    return null;
  }
}

function appendMetaLine(container, label, valueText) {
  const line = document.createElement("p");
  line.className = "meta-line";
  line.appendChild(document.createTextNode(`${label}${valueText}`));
  container.appendChild(line);
}

function appendSignupMetaLine(container, signupLink) {
  const line = document.createElement("p");
  line.className = "meta-line";
  line.appendChild(document.createTextNode("报名链接："));
  const href = toSafeHttpHref(signupLink);
  if (href) {
    const a = document.createElement("a");
    a.href = href;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.textContent = signupLink.trim();
    line.appendChild(a);
  } else {
    line.appendChild(document.createTextNode(signupLink));
  }
  container.appendChild(line);
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

function createActivityItem(activity, index, favoriteSet) {
  const node = itemTemplate.content.cloneNode(true);
  const titleEl = node.querySelector(".item-title");
  const metaEl = node.querySelector(".item-meta");
  const favoriteBtn = node.querySelector(".favorite-btn");
  const editBtn = node.querySelector(".edit-btn");
  const deleteBtn = node.querySelector(".delete-btn");

  const fp = getActivityFingerprint(activity);
  const favorited = favoriteSet.has(fp);

  titleEl.textContent = activity.name;
  metaEl.replaceChildren();
  appendMetaLine(metaEl, "概况：", activity.summary);
  appendMetaLine(metaEl, "地点：", activity.location);
  appendSignupMetaLine(metaEl, activity.signupLink);
  appendMetaLine(metaEl, "活动时间：", formatDateTime(activity.eventTime));
  appendMetaLine(metaEl, "DDL：", formatDateTime(activity.ddl));

  favoriteBtn.textContent = favorited ? "已收藏" : "收藏";
  favoriteBtn.classList.toggle("favorite-on", favorited);
  favoriteBtn.setAttribute("aria-pressed", favorited ? "true" : "false");

  favoriteBtn.addEventListener("click", () => {
    toggleFavoriteFingerprint(fp);
    renderActivities();
  });

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

    const oldFp = getActivityFingerprint(activity);

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
      alert(`保存失败：活动名称与概况必填，且名称与概况合计不少于 ${MIN_ACTIVITY_TEXT_LEN} 个字符。`);
      return;
    }

    const newFp = getActivityFingerprint(edited);
    if (oldFp !== newFp) {
      const favs = loadFavoriteFingerprints();
      if (favs.has(oldFp)) {
        favs.delete(oldFp);
        favs.add(newFp);
        saveFavoriteFingerprints(favs);
      }
    }

    const activities = loadActivities();
    activities[index] = edited;
    saveActivities(activities);
    cleanExpiredActivities();
  });

  deleteBtn.addEventListener("click", () => {
    const fpRemove = getActivityFingerprint(activity);
    const favs = loadFavoriteFingerprints();
    if (favs.has(fpRemove)) {
      favs.delete(fpRemove);
      saveFavoriteFingerprints(favs);
    }
    const activities = loadActivities();
    activities.splice(index, 1);
    saveActivities(activities);
    renderActivities();
  });

  return node;
}

function renderActivities() {
  const activities = loadActivities();
  const favoriteSet = loadFavoriteFingerprints();
  activityList.innerHTML = "";
  const filtered = activities.filter((activity) => {
    if (activeCategory === "我的收藏") {
      return favoriteSet.has(getActivityFingerprint(activity));
    }
    if (activeCategory === "全部") return true;
    return normalizeCategory(activity.category) === activeCategory;
  });

  filtered.forEach((activity) => {
    const index = activities.findIndex((stored) => isSameActivity(stored, activity));
    activityList.appendChild(createActivityItem(activity, index, favoriteSet));
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
  const response = await fetch("/api/activities/extract", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });

  const text = await response.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    throw new Error(
      `接口返回不是 JSON（HTTP ${response.status}）。请用「npm start」或 Docker 里的 web 服务地址打开页面（例如 http://localhost:8000），不要直接用浏览器打开本地 index.html 文件。响应开头：${text.slice(0, 120)}`
    );
  }

  if (!response.ok) {
    const detail = [data.error, data.detail].filter(Boolean).join(" — ");
    throw new Error(detail || `请求失败 HTTP ${response.status}`);
  }

  if (!Array.isArray(data.activities)) {
    throw new Error("返回 JSON 中缺少 activities 数组，请确认请求的是本项目的 node 服务 /api/activities/extract");
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
    alert(`活动同步失败：${error.message || String(error)}`);
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
