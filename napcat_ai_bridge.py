import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp
from openai import AsyncOpenAI


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
ACTIVITIES_FILE = DATA_DIR / "activities.json"
MESSAGE_LOG_FILE = DATA_DIR / "message_log.json"

NAPCAT_HTTP_URL = os.getenv("NAPCAT_HTTP_URL", "http://host.docker.internal:3002").strip()
NAPCAT_HISTORY_PATH = os.getenv("NAPCAT_HISTORY_PATH", "/get_group_msg_history").strip()
NAPCAT_POLL_INTERVAL_SEC = float(os.getenv("NAPCAT_POLL_INTERVAL_SEC", "5"))
NAPCAT_POLL_LIMIT = int(os.getenv("NAPCAT_POLL_LIMIT", "30"))

TARGET_GROUP_ID = os.getenv("TARGET_GROUP_ID", "").strip()
TARGET_USERS = {u.strip() for u in os.getenv("TARGET_USERS", "").split(",") if u.strip()}

AI_API_KEY = os.getenv("AI_API_KEY", "").strip()
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.deepseek.com/v1").strip()
AI_MODEL = os.getenv("AI_MODEL", "deepseek-chat").strip()

SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    """你是QQ群活动提取助手。请从消息中提取活动信息并只返回 JSON 数组，不要解释。
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
如果没有有效活动，返回空数组 []。""",
).strip()

if not AI_API_KEY:
    raise RuntimeError("AI_API_KEY 未配置，请在环境变量中设置。")
if not TARGET_GROUP_ID:
    raise RuntimeError("TARGET_GROUP_ID 未配置，请在环境变量中设置。")


client = AsyncOpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL)
lock = asyncio.Lock()
seen_message_ids: set[str] = set()


def ensure_store() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not ACTIVITIES_FILE.exists():
        ACTIVITIES_FILE.write_text("[]", encoding="utf-8")
    if not MESSAGE_LOG_FILE.exists():
        MESSAGE_LOG_FILE.write_text("[]", encoding="utf-8")


def normalize_text(value: Any, fallback: str = "无") -> str:
    text = str(value or "").strip()
    return text if text else fallback


def normalize_datetime(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        if "T" in raw:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(raw, "%Y-%m-%d %H:%M")
        return dt.isoformat()
    except ValueError:
        return ""


def detect_category(item: dict[str, Any]) -> str:
    direct = str(item.get("category", "")).strip()
    pool = " ".join(
        [
            str(item.get("name", "")),
            str(item.get("summary", "")),
            str(item.get("location", "")),
            str(item.get("sourceText", "")),
            direct,
        ]
    )
    if "五育" in pool:
        return "五育"
    if re.search(r"讲座|工坊|分享", pool):
        return "休闲活动"
    if direct in {"五育", "必做", "休闲活动"}:
        return direct
    return "必做"


def normalize_activity(item: dict[str, Any]) -> dict[str, Any] | None:
    name = normalize_text(item.get("name") or item.get("title"), "")
    summary = normalize_text(item.get("summary") or item.get("description"), "")
    event_time = normalize_datetime(item.get("eventTime"))
    ddl = normalize_datetime(item.get("ddl"))
    if not name or not summary or (not event_time and not ddl):
        return None
    return {
        "name": name,
        "summary": summary,
        "location": normalize_text(item.get("location")),
        "signupLink": normalize_text(item.get("signupLink")),
        "category": detect_category(item),
        "eventTime": event_time,
        "ddl": ddl,
    }


def fingerprint(item: dict[str, Any]) -> str:
    return normalize_text(item.get("name"), "").replace(" ", "").lower()


def changed(old: dict[str, Any], new: dict[str, Any]) -> bool:
    keys = ("summary", "location", "signupLink", "category", "eventTime", "ddl")
    return any(old.get(k) != new.get(k) for k in keys)


def parse_json_array(text: str) -> list[dict[str, Any]]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.replace("json", "", 1).strip()
    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        data = json.loads(raw[start : end + 1])
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def extract_messages(resp_json: dict[str, Any]) -> list[dict[str, Any]]:
    data = resp_json.get("data")
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("messages", "message", "list"):
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


async def extract_activities(message: str) -> list[dict[str, Any]]:
    response = await client.chat.completions.create(
        model=AI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message},
        ],
        temperature=0.1,
    )
    content = response.choices[0].message.content or "[]"
    raw_items = parse_json_array(content)
    return [item for item in (normalize_activity(x) for x in raw_items) if item is not None]


async def upsert_activities(items: list[dict[str, Any]]) -> None:
    if not items:
        return
    async with lock:
        ensure_store()
        stored = json.loads(ACTIVITIES_FILE.read_text(encoding="utf-8"))
        if not isinstance(stored, list):
            stored = []

        merged = list(stored)
        for item in items:
            idx = next((i for i, it in enumerate(merged) if fingerprint(it) == fingerprint(item)), -1)
            if idx == -1:
                merged.append(item)
            elif changed(merged[idx], item):
                merged[idx] = {**merged[idx], **item}

        ACTIVITIES_FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")


async def append_message_log(*, message_id: str, group_id: str, user_id: str, raw_message: str) -> None:
    async with lock:
        ensure_store()
        stored = json.loads(MESSAGE_LOG_FILE.read_text(encoding="utf-8"))
        if not isinstance(stored, list):
            stored = []

        existing = {str(x.get("message_id", "")) for x in stored}
        if message_id and message_id in existing:
            return

        stored.append(
            {
                "message_id": message_id,
                "group_id": group_id,
                "user_id": user_id,
                "raw_message": raw_message,
                "time": datetime.now().isoformat(),
            }
        )
        MESSAGE_LOG_FILE.write_text(json.dumps(stored[-5000:], ensure_ascii=False, indent=2), encoding="utf-8")


async def process_message(raw_message: str, group_id: str, user_id: str) -> None:
    try:
        items = await extract_activities(raw_message)
        await upsert_activities(items)
        if items:
            print(f"✅ 已写入/更新 {len(items)} 条活动，group={group_id}, user={user_id}")
    except Exception as exc:
        print(f"❌ 处理消息失败: {exc}")


async def handle_message(msg: dict[str, Any]) -> None:
    group_id = str(msg.get("group_id", ""))
    user_id = str(msg.get("user_id", ""))
    message_id = str(msg.get("message_id", "") or msg.get("id", ""))
    raw_message = str(msg.get("raw_message", "") or msg.get("message", "")).strip()
    if not raw_message or group_id != TARGET_GROUP_ID:
        return
    if TARGET_USERS and user_id not in TARGET_USERS:
        return
    if message_id and message_id in seen_message_ids:
        return
    if message_id:
        seen_message_ids.add(message_id)
        if len(seen_message_ids) > 10000:
            seen_message_ids.clear()

    print(f"📩 group={group_id} user={user_id}: {raw_message[:100]}")
    await append_message_log(
        message_id=message_id,
        group_id=group_id,
        user_id=user_id,
        raw_message=raw_message,
    )
    asyncio.create_task(process_message(raw_message, group_id, user_id))


async def poll_message_loop() -> None:
    base = NAPCAT_HTTP_URL.rstrip("/")
    path = NAPCAT_HISTORY_PATH if NAPCAT_HISTORY_PATH.startswith("/") else f"/{NAPCAT_HISTORY_PATH}"
    url = f"{base}{path}"
    print(f"🔁 轮询 NapCat HTTP: {url}, interval={NAPCAT_POLL_INTERVAL_SEC}s")
    timeout = aiohttp.ClientTimeout(total=12)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        while True:
            try:
                params = {"group_id": int(TARGET_GROUP_ID), "count": NAPCAT_POLL_LIMIT}
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        print(f"❌ NapCat HTTP异常 {resp.status}: {text[:200]}")
                    else:
                        body = await resp.json(content_type=None)
                        messages = extract_messages(body if isinstance(body, dict) else {})
                        for msg in messages:
                            await handle_message(msg)
            except Exception as exc:
                print(f"❌ 轮询失败: {exc}")
            await asyncio.sleep(NAPCAT_POLL_INTERVAL_SEC)


if __name__ == "__main__":
    ensure_store()
    asyncio.run(poll_message_loop())
