import json
import os
import urllib.request
from pathlib import Path

ENV_FILE = Path("~/.config/mini-deploy/env").expanduser()
PUSH_URL = "https://api.line.me/v2/bot/message/push"


def _credentials() -> tuple[str | None, str | None]:
    values = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and not key.startswith("#"):
                values[key.strip()] = value.strip().strip('"').strip("'")
    get = lambda k: os.environ.get(k) or values.get(k)
    return get("LINE_CHANNEL_ACCESS_TOKEN"), get("LINE_USER_ID")


def send(text: str) -> bool:
    """沒設權杖就回 False、不出錯；呼叫失敗會丟例外，由呼叫端決定怎麼記。"""
    token, user = _credentials()
    if not token or not user:
        return False
    req = urllib.request.Request(
        PUSH_URL,
        data=json.dumps({"to": user, "messages": [{"type": "text", "text": text}]}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()
    return True
