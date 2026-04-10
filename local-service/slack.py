from __future__ import annotations

import hashlib
import hmac
import time

import httpx

SLACK_API = "https://slack.com/api"
MAX_TIMESTAMP_AGE = 300  # 5 minutes


def verify_slack_signature(
    *,
    body: bytes,
    timestamp: str,
    signature: str,
    signing_secret: str,
) -> bool:
    """Verify Slack request signature (HMAC-SHA256)."""
    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        return False
    if abs(time.time() - ts) > MAX_TIMESTAMP_AGE:
        return False
    try:
        body_str = body.decode("utf-8")
    except UnicodeDecodeError:
        return False
    base = f"v0:{timestamp}:{body_str}"
    expected = "v0=" + hmac.new(
        signing_secret.encode(), base.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


class SlackClient:
    def __init__(self, *, bot_token: str, channel: str) -> None:
        self._token = bot_token
        self._channel = channel
        self._http = httpx.AsyncClient(
            base_url=SLACK_API,
            headers={"Authorization": f"Bearer {bot_token}"},
            timeout=10.0,
        )

    async def post_message(self, *, blocks: list[dict], text: str = "") -> str:
        """Post a message to the configured channel. Returns the message ts."""
        resp = await self._http.post(
            "/chat.postMessage",
            json={
                "channel": self._channel,
                "blocks": blocks,
                "text": text or "New PR review",
            },
        )
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack API error: {data.get('error')}")
        return data["ts"]

    async def post_thread_reply(self, *, thread_ts: str, text: str) -> str:
        """Post a reply in a thread. Returns the reply ts."""
        resp = await self._http.post(
            "/chat.postMessage",
            json={
                "channel": self._channel,
                "thread_ts": thread_ts,
                "text": text,
            },
        )
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack API error: {data.get('error')}")
        return data["ts"]

    async def read_thread_replies(self, *, thread_ts: str) -> list[dict]:
        """Read all replies in a thread. Returns list of message dicts."""
        resp = await self._http.get(
            "/conversations.replies",
            params={
                "channel": self._channel,
                "ts": thread_ts,
                "limit": 100,
            },
        )
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack API error: {data.get('error')}")
        return data.get("messages", [])

    async def close(self) -> None:
        await self._http.aclose()
