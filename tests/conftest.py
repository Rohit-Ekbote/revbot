from __future__ import annotations

import json
from pathlib import Path

import pytest

from config import Settings

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        github_token="ghp_test_token",
        github_repo="testorg/testrepo",
        slack_bot_token="xoxb-test-token",
        slack_signing_secret="test_signing_secret",
        slack_channel="C01234567",
        webhook_secret="test_webhook_secret",
        review_mode="manual",
        allowed_slack_users=["U01234567"],
    )


@pytest.fixture
def sample_review_text() -> str:
    return (FIXTURES_DIR / "sample_review.txt").read_text()


@pytest.fixture
def sample_slack_event() -> dict:
    return json.loads((FIXTURES_DIR / "sample_slack_event.json").read_text())
