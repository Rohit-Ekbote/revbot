from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    """Import app after setting env vars to avoid config file requirement."""
    import os
    os.environ.update({
        "GITHUB_TOKEN": "ghp_test",
        "GITHUB_REPO": "testorg/testrepo",
        "SLACK_BOT_TOKEN": "xoxb-test",
        "SLACK_SIGNING_SECRET": "test_signing_secret",
        "SLACK_CHANNEL": "C01234567",
    })
    from main import app
    return app


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


class TestHealth:
    def test_health_returns_ok(self, client: TestClient):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


class TestSlackEvents:
    def test_url_verification_challenge(self, client: TestClient):
        payload = {"type": "url_verification", "challenge": "test_challenge_value"}
        resp = client.post("/slack/events", json=payload)
        assert resp.status_code == 200
        assert resp.json()["challenge"] == "test_challenge_value"

    def test_rejects_invalid_signature(self, client: TestClient):
        payload = {"type": "event_callback", "event": {"type": "message", "text": "hi"}}
        body = json.dumps(payload).encode()
        resp = client.post(
            "/slack/events",
            content=body,
            headers={
                "X-Slack-Request-Timestamp": str(int(time.time())),
                "X-Slack-Signature": "v0=invalid",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 401
