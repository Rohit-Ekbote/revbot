from __future__ import annotations

import hashlib
import hmac
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
        "WEBHOOK_SECRET": "test_webhook_secret",
        "REVIEW_MODE": "manual",
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
        assert "tracked_prs" in data


class TestReviewComplete:
    def test_rejects_missing_hmac(self, client: TestClient):
        resp = client.post("/review-complete", json={"pr_number": 1})
        assert resp.status_code == 401

    def test_rejects_bad_hmac(self, client: TestClient):
        resp = client.post(
            "/review-complete",
            json={"pr_number": 1},
            headers={"X-Webhook-Secret": "wrong"},
        )
        assert resp.status_code == 401

    def test_accepts_valid_hmac(self, client: TestClient):
        payload = {
            "pr_number": 42,
            "pr_title": "Test PR",
            "pr_url": "https://github.com/org/repo/pull/42",
            "pr_author": "dev",
            "stacks": "go",
            "run_id": "123",
            "raw_review": "FINDING_START\nID: 1\nSEVERITY: NIT\nFILE: GENERAL\nLINE: 0\nTITLE: Test\nBODY: Body\nFINDING_END\n\nSUMMARY_START\nOK\nSUMMARY_END",
            "repo": "org/repo",
        }
        body = json.dumps(payload).encode()
        sig = hmac.new(b"test_webhook_secret", body, hashlib.sha256).hexdigest()
        resp = client.post(
            "/review-complete",
            content=body,
            headers={
                "X-Webhook-Secret": sig,
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200


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
