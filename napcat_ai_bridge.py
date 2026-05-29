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
POLL_STATE_FILE = DATA_DIR / "napcat_poll_state.json"


def resolve_napcat_http_url() -> str:
    explicit = os.getenv("NAPCAT_HTTP_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    default_host = "host.docker.internal" if Path("/.dockerenv").exists() else "127.0.0.1"
    port = os.getenv("NAPCAT_HTTP_PORT", "3002").strip() or "3002"
    return f"http://{default_host}:{port}"


NAPCAT_HTTP_URL = resolve_napcat_http_url()
NAPCAT_HISTORY_PATH = os.getenv("NAPCAT_HISTORY_PATH", "/get_group_msg_history").strip()
NAPCAT_POLL_INTERVAL = float(os.getenv("NAPCAT_POLL_INTERVAL", "10"))
NAPCAT_POLL_COUNT = int(os.getenv("NAPCAT_POLL_COUNT", "20"))
NAPCAT_ACCESS_TOKEN = os.getenv("NAPCAT_ACCESS_TOKEN", "").strip()
TARGET_GROUP_ID = os.getenv("TARGET_GROUP_ID", "").strip()
TARGET_USERS = {
    u.strip()
    for u in os.getenv("TARGET_USERS", "").split(",")
    if u.strip()
}
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


def ensure_store() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not ACTIVITIES_FILE.exists():
        ACTIVITIES_FILE.write_text("[]", encoding="utf-8")


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
    if not name or not summary:
        return None
    if not event_time and not ddl:
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
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


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
    return [item for item in (normalize_activity(x) for x in raw_items) if item]


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
            fp = fingerprint(item)
            idx = next(
                (i for i, it in enumerate(merged) if fingerprint(it) == fp),
                -1,
            )
            if idx == -1:
                merged.append(item)
            elif changed(merged[idx], item):
                merged[idx] = {**merged[idx], **item}
        ACTIVITIES_FILE.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


async def process_message(raw_message: str, group_id: str, user_id: str) -> None:
    try:
        items = await extract_activities(raw_message)
        await upsert_activities(items)
        if items:
            print(f"✅ 已写入/更新 {len(items)} 条活动，group={group_id}, user={user_id}")
    except Exception as exc:
        print(f"❌ 处理消息失败: {exc}")


def napcat_api_url(path: str) -> str:
    path = path if path.startswith("/") else f"/{path}"
    return f"{NAPCAT_HTTP_URL}{path}"


def napcat_request_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if NAPCAT_ACCESS_TOKEN:
        headers["Authorization"] = f"Bearer {NAPCAT_ACCESS_TOKEN}"
    return headers


def load_poll_state() -> dict[str, str]:
    try:
        data = json.loads(POLL_STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_poll_state(state: dict[str, str]) -> None:
    ensure_store()
    POLL_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _message_id(msg: dict[str, Any]) -> str:
    for key in ("message_id", "message_seq", "real_id"):
        value = msg.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _message_id_gt(left: str, right: str) -> bool:
    if not right:
        return True
    if left.isdigit() and right.isdigit():
        return int(left) > int(right)
    return left > right


def _raw_message_text(msg: dict[str, Any]) -> str:
    raw = msg.get("raw_message")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    segments = msg.get("message")
    if not isinstance(segments, list):
        return ""
    parts: list[str] = []
    for seg in segments:
        if not isinstance(seg, dict) or seg.get("type") != "text":
            continue
        data = seg.get("data")
        if isinstance(data, dict):
            parts.append(str(data.get("text", "")))
        elif isinstance(data, str):
            parts.append(data)
    return "".join(parts).strip()


def extract_history_messages(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, dict):
        messages = data.get("messages")
        if isinstance(messages, list):
            return [m for m in messages if isinstance(m, dict)]
    if isinstance(data, list):
        return [m for m in data if isinstance(m, dict)]
    messages = payload.get("messages")
    if isinstance(messages, list):
        return [m for m in messages if isinstance(m, dict)]
    return []


async def fetch_group_history(session: aiohttp.ClientSession) -> list[dict[str, Any]]:
    group_id: int | str = int(TARGET_GROUP_ID) if TARGET_GROUP_ID.isdigit() else TARGET_GROUP_ID
    body = {"group_id": group_id, "count": NAPCAT_POLL_COUNT}
    url = napcat_api_url(NAPCAT_HISTORY_PATH)
    async with session.post(url, json=body, headers=napcat_request_headers()) as resp:
        text = await resp.text()
        if resp.status >= 400:
            raise RuntimeError(f"HTTP {resp.status}: {text[:300]}")
        payload = json.loads(text)
    retcode = payload.get("retcode", 0)
    if payload.get("status") == "failed" or (isinstance(retcode, int) and retcode != 0):
        raise RuntimeError(f"NapCat API 错误: {payload}")
    return extract_history_messages(payload)


async def poll_loop() -> None:
    state = load_poll_state()
    state_key = f"group:{TARGET_GROUP_ID}"
    last_seen = state.get(state_key, "")
    first_sync = not last_seen

    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        print(
            f"🤖 NapCat HTTP 轮询: {napcat_api_url(NAPCAT_HISTORY_PATH)} "
            f"群={TARGET_GROUP_ID} 间隔={NAPCAT_POLL_INTERVAL}s"
        )
        while True:
            try:
                messages = await fetch_group_history(session)
                messages.sort(
                    key=lambda m: int(_message_id(m) or "0")
                    if (_message_id(m) or "").isdigit()
                    else 0
                )
                newest = last_seen
                for msg in messages:
                    mid = _message_id(msg)
                    if not mid:
                        continue
                    if not _message_id_gt(mid, last_seen):
                        continue
                    newest = mid if _message_id_gt(mid, newest) else newest
                    if first_sync:
                        continue
                    user_id = str(msg.get("user_id", ""))
                    if TARGET_USERS and user_id not in TARGET_USERS:
                        continue
                    raw_message = _raw_message_text(msg)
                    if not raw_message:
                        continue
                    print(f"📩 message_id={mid} user={user_id}: {raw_message[:100]}")
                    await process_message(raw_message, TARGET_GROUP_ID, user_id)

                if first_sync:
                    if newest:
                        print(f"⏭ 首次对齐 message_id={newest}（跳过历史，只处理之后的新消息）")
                    first_sync = False

                if newest and newest != last_seen:
                    last_seen = newest
                    state[state_key] = last_seen
                    save_poll_state(state)
            except Exception as exc:
                print(f"❌ NapCat HTTP 请求失败: {exc}，{NAPCAT_POLL_INTERVAL}秒后重试")
            await asyncio.sleep(NAPCAT_POLL_INTERVAL)


if __name__ == "__main__":
    ensure_store()
    asyncio.run(poll_loop())
