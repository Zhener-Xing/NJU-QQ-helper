import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import websockets
from openai import AsyncOpenAI


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
ACTIVITIES_FILE = DATA_DIR / "activities.json"
MESSAGE_LOG_FILE = DATA_DIR / "message_log.json"

# client: bridge 主动连 NapCat（正向 WS）
# server: bridge 监听端口，NapCat 反向连过来（反向 WS）
BRIDGE_WS_MODE = os.getenv("BRIDGE_WS_MODE", "client").strip().lower()
NAPCAT_WS_URL = os.getenv("NAPCAT_WS_URL", "ws://127.0.0.1:3001")
BRIDGE_WS_HOST = os.getenv("BRIDGE_WS_HOST", "0.0.0.0").strip()
BRIDGE_WS_PORT = int(os.getenv("BRIDGE_WS_PORT", "8765"))
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
            fp = fingerprint(item)
            idx = next((i for i, it in enumerate(merged) if fingerprint(it) == fp), -1)
            if idx == -1:
                merged.append(item)
            elif changed(merged[idx], item):
                merged[idx] = {**merged[idx], **item}

        ACTIVITIES_FILE.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
        )


async def append_message_log(
    *, message_id: str, group_id: str, user_id: str, raw_message: str
) -> None:
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
        # 只保留最近 14 天日志，避免无限增长
        recent = stored[-5000:]
        MESSAGE_LOG_FILE.write_text(
            json.dumps(recent, ensure_ascii=False, indent=2), encoding="utf-8"
        )


async def process_message(raw_message: str, group_id: str, user_id: str) -> None:
    try:
        items = await extract_activities(raw_message)
        await upsert_activities(items)
        if items:
            print(f"✅ 已写入/更新 {len(items)} 条活动，group={group_id}, user={user_id}")
    except Exception as exc:
        print(f"❌ 处理消息失败: {exc}")


async def handle_napcat_payload(payload: str) -> None:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return

    if data.get("post_type") != "message" or data.get("message_type") != "group":
        return

    group_id = str(data.get("group_id", ""))
    user_id = str(data.get("user_id", ""))
    message_id = str(data.get("message_id", ""))
    raw_message = str(data.get("raw_message", "")).strip()
    if not raw_message:
        return

    if group_id != TARGET_GROUP_ID:
        return
    if TARGET_USERS and user_id not in TARGET_USERS:
        return

    print(f"📩 group={group_id} user={user_id}: {raw_message[:100]}")
    await append_message_log(
        message_id=message_id,
        group_id=group_id,
        user_id=user_id,
        raw_message=raw_message,
    )
    asyncio.create_task(process_message(raw_message, group_id, user_id))


async def client_message_loop() -> None:
    while True:
        try:
            async with websockets.connect(NAPCAT_WS_URL) as ws:
                print(f"🤖 已连接 NapCat（正向）: {NAPCAT_WS_URL}")
                async for payload in ws:
                    await handle_napcat_payload(payload)
        except Exception as exc:
            print(f"❌ NapCat 连接异常: {exc}，5秒后重连")
            await asyncio.sleep(5)


async def reverse_ws_handler(websocket: Any) -> None:
    addr = getattr(websocket, "remote_address", None)
    print(f"📎 NapCat 已连接（反向 WS）: {addr}")
    try:
        async for payload in websocket:
            await handle_napcat_payload(payload)
    finally:
        print(f"📴 NapCat 断开: {addr}")


async def server_message_loop() -> None:
    async with websockets.serve(
        reverse_ws_handler,
        BRIDGE_WS_HOST,
        BRIDGE_WS_PORT,
    ):
        print(
            f"🛰️ 反向 WebSocket 已监听 ws://{BRIDGE_WS_HOST}:{BRIDGE_WS_PORT}/ "
            f"（请在 NapCat 里把上报地址指到这里）"
        )
        await asyncio.Future()


if __name__ == "__main__":
    ensure_store()
    if BRIDGE_WS_MODE == "server":
        asyncio.run(server_message_loop())
    else:
        asyncio.run(client_message_loop())
