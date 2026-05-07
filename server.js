const http = require("http");
const fs = require("fs");
const path = require("path");
const { URL } = require("url");

const PORT = Number(process.env.PORT || 8000);
const AI_API_KEY = process.env.AI_API_KEY || "";
const AI_BASE_URL = process.env.AI_BASE_URL || "https://api.deepseek.com/v1";
const AI_MODEL = process.env.AI_MODEL || "deepseek-chat";
const BACKFILL_DAYS = Number(process.env.BACKFILL_DAYS || 7);
const BACKFILL_MAX_MESSAGES = Number(process.env.BACKFILL_MAX_MESSAGES || 80);
const ROOT = __dirname;
const DATA_DIR = path.join(ROOT, "data");
const ACTIVITIES_FILE = path.join(DATA_DIR, "activities.json");
const MESSAGE_LOG_FILE = path.join(DATA_DIR, "message_log.json");

const MIME_TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".ico": "image/x-icon",
};

function sendJson(res, statusCode, payload) {
  res.writeHead(statusCode, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(payload));
}

function ensureDataFile() {
  if (!fs.existsSync(DATA_DIR)) {
    fs.mkdirSync(DATA_DIR, { recursive: true });
  }
  if (!fs.existsSync(ACTIVITIES_FILE)) {
    fs.writeFileSync(ACTIVITIES_FILE, "[]", "utf-8");
  }
  if (!fs.existsSync(MESSAGE_LOG_FILE)) {
    fs.writeFileSync(MESSAGE_LOG_FILE, "[]", "utf-8");
  }
}

function readJsonArray(filePath) {
  try {
    const raw = fs.readFileSync(filePath, "utf-8");
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (error) {
    return [];
  }
}

function writeJsonArray(filePath, data) {
  fs.writeFileSync(filePath, JSON.stringify(data, null, 2), "utf-8");
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
  const pool = [
    item.name,
    item.summary,
    item.location,
    item.rawMessage,
    item.sourceText,
    directCategory,
  ]
    .filter(Boolean)
    .join(" ");

  if (pool.includes("五育")) return "五育";
  if (/讲座|工坊|分享/.test(pool)) return "休闲活动";
  if (["五育", "必做", "休闲活动"].includes(directCategory)) return directCategory;
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

function getFingerprint(activity) {
  return normalizeText(activity.name, "").replace(/\s+/g, "").toLowerCase();
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

function mergeActivities(stored, incoming) {
  const merged = [...stored];
  incoming.forEach((item) => {
    const idx = merged.findIndex((x) => getFingerprint(x) === getFingerprint(item));
    if (idx === -1) {
      merged.push(item);
      return;
    }
    if (hasActivityChanged(merged[idx], item)) {
      merged[idx] = { ...merged[idx], ...item };
    }
  });
  return merged;
}

function extractJsonArray(content) {
  const text = String(content || "").trim();
  const first = text.indexOf("[");
  const last = text.lastIndexOf("]");
  if (first === -1 || last === -1 || last <= first) return [];
  try {
    const parsed = JSON.parse(text.slice(first, last + 1));
    return Array.isArray(parsed) ? parsed : [];
  } catch (error) {
    return [];
  }
}

async function extractActivitiesByAI(rawMessage) {
  const systemPrompt = process.env.SYSTEM_PROMPT || `你是QQ群活动提取助手。请从消息中提取活动信息并只返回 JSON 数组，不要解释。
每个对象格式：
[
  {
    "name": "活动名称",
    "summary": "活动概况",
    "location": "活动地点，没有填无",
    "signupLink": "报名链接，没有填无",
    "category": "五育|必做|休闲活动",
    "eventTime": "ISO时间或空字符串",
    "ddl": "ISO时间或空字符串"
  }
]
规则：
1) name、summary 必填；
2) eventTime 和 ddl 至少一个有值；
3) 信息中出现“五育”则分类为“五育”；
4) 出现“讲座”“工坊”“分享”则分类为“休闲活动”；
5) 其他分类为“必做”。
如果没有有效活动，返回空数组 []。`;

  const resp = await fetch(`${AI_BASE_URL.replace(/\/$/, "")}/chat/completions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${AI_API_KEY}`,
    },
    body: JSON.stringify({
      model: AI_MODEL,
      temperature: 0.1,
      messages: [
        { role: "system", content: systemPrompt },
        { role: "user", content: rawMessage },
      ],
    }),
  });

  if (!resp.ok) {
    const t = await resp.text();
    throw new Error(`AI request failed: ${resp.status} ${t}`);
  }
  const data = await resp.json();
  const content = data?.choices?.[0]?.message?.content || "[]";
  return extractJsonArray(content).map(normalizeActivity).filter(Boolean);
}

async function backfillFromRecentMessages() {
  if (!AI_API_KEY) return { activities: [], touched: false };

  const now = Date.now();
  const windowStart = now - BACKFILL_DAYS * 24 * 60 * 60 * 1000;
  const messageLog = readJsonArray(MESSAGE_LOG_FILE)
    .filter((m) => new Date(m.time || 0).getTime() >= windowStart)
    .slice(-BACKFILL_MAX_MESSAGES);

  const dedupMessages = [];
  const seen = new Set();
  for (const msg of messageLog) {
    const key = `${msg.group_id || ""}:${msg.user_id || ""}:${String(msg.raw_message || "").trim()}`;
    if (!key || seen.has(key)) continue;
    seen.add(key);
    dedupMessages.push(msg);
  }

  let extracted = [];
  for (const msg of dedupMessages) {
    const items = await extractActivitiesByAI(String(msg.raw_message || ""));
    extracted = extracted.concat(items);
  }

  const uniqueExtracted = mergeActivities([], extracted);
  if (uniqueExtracted.length === 0) return { activities: [], touched: false };

  const stored = readJsonArray(ACTIVITIES_FILE);
  const merged = mergeActivities(stored, uniqueExtracted);
  writeJsonArray(ACTIVITIES_FILE, merged);
  return { activities: merged, touched: true };
}

async function handleApi(req, res) {
  ensureDataFile();
  let activities = readJsonArray(ACTIVITIES_FILE);
  let backfilled = false;

  if (activities.length === 0) {
    const result = await backfillFromRecentMessages();
    activities = result.activities;
    backfilled = result.touched;
  }

  sendJson(res, 200, { activities, backfilled });
}

function handleStatic(req, res) {
  const urlObj = new URL(req.url, `http://${req.headers.host}`);
  let filePath = urlObj.pathname === "/" ? "/index.html" : urlObj.pathname;
  filePath = path.normalize(filePath).replace(/^(\.\.[/\\])+/, "");
  const fullPath = path.join(ROOT, filePath);

  if (!fullPath.startsWith(ROOT)) {
    res.writeHead(403);
    res.end("Forbidden");
    return;
  }

  fs.readFile(fullPath, (err, data) => {
    if (err) {
      res.writeHead(404);
      res.end("Not Found");
      return;
    }
    const ext = path.extname(fullPath).toLowerCase();
    res.writeHead(200, { "Content-Type": MIME_TYPES[ext] || "application/octet-stream" });
    res.end(data);
  });
}

const server = http.createServer(async (req, res) => {
  try {
    if (req.method === "POST" && req.url === "/api/activities/extract") {
      await handleApi(req, res);
      return;
    }
    handleStatic(req, res);
  } catch (error) {
    console.error(error);
    sendJson(res, 500, { error: "Internal server error", detail: String(error.message || error) });
  }
});

server.listen(PORT, () => {
  ensureDataFile();
  console.log(`NJU QQ helper server running at http://localhost:${PORT}`);
});
