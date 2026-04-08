from __future__ import annotations

import hashlib
import hmac
import time

import pytest
import httpx
import respx

from slack import SlackClient, verify_slack_signature


@pytest.fixture
def slack_client(settings) -> SlackClient:
    return SlackClient(
        bot_token=settings.slack_bot_token,
        channel=settings.slack_channel,
    )


class TestVerifySlackSignature:
    def test_valid_signature(self, settings: object):
        body = b'{"event": "test"}'
        timestamp = str(int(time.time()))
        base = f"v0:{timestamp}:{body.decode()}"
        sig = "v0=" + hmac.new(
            settings.slack_signing_secret.encode(), base.encode(), hashlib.sha256
        ).hexdigest()
        assert verify_slack_signature(
            body=body,
            timestamp=timestamp,
            signature=sig,
            signing_secret=settings.slack_signing_secret,
        ) is True

    def test_invalid_signature(self, settings: object):
        assert verify_slack_signature(
            body=b"test",
            timestamp=str(int(time.time())),
            signature="v0=invalid",
            signing_secret=settings.slack_signing_secret,
        ) is False

    def test_stale_timestamp(self, settings: object):
        old_ts = str(int(time.time()) - 600)  # 10 minutes old
        body = b"test"
        base = f"v0:{old_ts}:{body.decode()}"
        sig = "v0=" + hmac.new(
            settings.slack_signing_secret.encode(), base.encode(), hashlib.sha256
        ).hexdigest()
        assert verify_slack_signature(
            body=body,
            timestamp=old_ts,
            signature=sig,
            signing_secret=settings.slack_signing_secret,
        ) is False


class TestSlackClient:
    @respx.mock
    @pytest.mark.asyncio
    async def test_post_message(self, slack_client: SlackClient):
        route = respx.post("https://slack.com/api/chat.postMessage").mock(
            return_value=httpx.Response(200, json={"ok": True, "ts": "1234.5678"})
        )
        ts = await slack_client.post_message(blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": "hi"}}])
        assert ts == "1234.5678"
        assert route.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_post_thread_reply(self, slack_client: SlackClient):
        route = respx.post("https://slack.com/api/chat.postMessage").mock(
            return_value=httpx.Response(200, json={"ok": True, "ts": "1234.9999"})
        )
        ts = await slack_client.post_thread_reply(thread_ts="1234.5678", text="Applied!")
        assert ts == "1234.9999"
        payload = route.calls[0].request.content
        assert b"thread_ts" in payload or b"1234.5678" in payload

    @respx.mock
    @pytest.mark.asyncio
    async def test_post_message_api_error(self, slack_client: SlackClient):
        respx.post("https://slack.com/api/chat.postMessage").mock(
            return_value=httpx.Response(200, json={"ok": False, "error": "channel_not_found"})
        )
        with pytest.raises(RuntimeError, match="channel_not_found"):
            await slack_client.post_message(blocks=[])
