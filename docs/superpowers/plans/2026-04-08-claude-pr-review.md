# Claude PR Review System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an automated PR review system where a GitHub Action invokes Claude to review PRs, posts findings to Slack, and a local FastAPI service lets the reviewer selectively apply findings back to GitHub.

**Architecture:** GitHub Action handles trigger detection, diff fetching, skill loading, and Claude invocation. It posts raw findings as a hidden PR comment and notifies a local FastAPI service via webhook. The local service formats findings into Slack Block Kit messages, handles Slack event callbacks (`apply N,M` / `review PR #N`), and writes selected findings back to GitHub as PR review comments. Cloudflared tunnel exposes the local service.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, httpx, structlog, pydantic-settings, PyYAML. GitHub Actions for CI. Slack Block Kit for messaging. pytest for testing.

---

## File Structure

```
revbot/
├── .github/
│   └── workflows/
│       └── claude-pr-review.yml          # GitHub Action: trigger, diff, Claude, notify
├── local-service/
│   ├── main.py                           # FastAPI app, routes, background tasks
│   ├── parser.py                         # Claude output parser + Slack Block Kit formatter
│   ├── github.py                         # GitHub API: read hidden findings, post comments, trigger dispatch
│   ├── slack.py                          # Slack API: post messages, verify signing secret
│   ├── config.py                         # pydantic-settings config from config.yml + env vars
│   ├── config.yml.example                # Example config (committed)
│   ├── requirements.txt                  # Production deps
│   └── requirements-dev.txt              # Test deps (pytest, pytest-asyncio, respx)
├── tests/
│   ├── conftest.py                       # Shared fixtures: mock config, httpx mocks
│   ├── test_parser.py                    # Parser + formatter unit tests
│   ├── test_github.py                    # GitHub API client tests (mocked httpx)
│   ├── test_slack.py                     # Slack client + signing verification tests
│   ├── test_routes.py                    # FastAPI route integration tests (TestClient)
│   └── fixtures/
│       ├── sample_review.txt             # Sample Claude output for parser tests
│       └── sample_slack_event.json       # Sample Slack event payload
├── .gitignore
└── README.md                             # Setup instructions
```

---

### Task 1: Project Scaffolding

**Files:**
- Create: `.gitignore`
- Create: `local-service/requirements.txt`
- Create: `local-service/requirements-dev.txt`
- Create: `local-service/config.yml.example`
- Create: `local-service/config.py`
- Create: `tests/conftest.py`
- Create: `tests/fixtures/sample_review.txt`
- Create: `tests/fixtures/sample_slack_event.json`

- [ ] **Step 1: Create .gitignore**

```gitignore
# Python
__pycache__/
*.pyc
.venv/

# Local config (contains secrets)
local-service/config.yml
local-service/.env

# IDE
.idea/
.vscode/
*.swp

# OS
.DS_Store
```

- [ ] **Step 2: Create requirements.txt**

```
fastapi>=0.111
uvicorn[standard]>=0.29
httpx>=0.27
structlog>=24.1
pydantic-settings>=2.2
pyyaml>=6.0
```

- [ ] **Step 3: Create requirements-dev.txt**

```
-r requirements.txt
pytest>=8.0
pytest-asyncio>=0.23
respx>=0.21
httpx>=0.27
```

- [ ] **Step 4: Create config.yml.example**

```yaml
# GitHub
github_token: "ghp_your_token_here"
github_repo: "org/repo"

# Slack
slack_bot_token: "xoxb-your-token-here"
slack_signing_secret: "your-signing-secret"
slack_channel: "C01234567"

# Security
webhook_secret: "your-webhook-secret"

# Review mode: manual | auto
review_mode: "manual"

# Slack user IDs allowed to use apply/review commands (empty = all users)
allowed_slack_users: []
```

- [ ] **Step 5: Create config.py**

```python
from __future__ import annotations

import yaml
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    github_token: str
    github_repo: str

    slack_bot_token: str
    slack_signing_secret: str
    slack_channel: str

    webhook_secret: str

    review_mode: str = "manual"
    allowed_slack_users: list[str] = Field(default_factory=list)

    model_config = {"env_prefix": "", "case_sensitive": False}


def load_settings(config_path: str | Path = "config.yml") -> Settings:
    """Load settings from YAML file, with env var overrides."""
    path = Path(config_path)
    file_values: dict = {}
    if path.exists():
        with open(path) as f:
            file_values = yaml.safe_load(f) or {}
    return Settings(**file_values)
```

- [ ] **Step 6: Create test fixtures — sample_review.txt**

```
FINDING_START
ID: 1
SEVERITY: BLOCKER
FILE: src/auth.py
LINE: 42
TITLE: SQL injection in login query
BODY: The `username` parameter is interpolated directly into the SQL query string without parameterization. Use parameterized queries to prevent SQL injection.
FINDING_END

FINDING_START
ID: 2
SEVERITY: WARNING
FILE: src/auth.py
LINE: 58
TITLE: Missing rate limiting on login endpoint
BODY: The login endpoint has no rate limiting, allowing brute-force attacks. Add rate limiting middleware or per-IP throttling.
FINDING_END

FINDING_START
ID: 3
SEVERITY: SUGGESTION
FILE: src/utils.py
LINE: 10
TITLE: Use pathlib instead of os.path
BODY: Modern Python prefers pathlib.Path over os.path for path manipulation. This improves readability and type safety.
FINDING_END

FINDING_START
ID: 4
SEVERITY: NIT
FILE: GENERAL
LINE: 0
TITLE: Inconsistent docstring style
BODY: Some functions use Google-style docstrings while others use NumPy-style. Pick one and apply consistently.
FINDING_END

SUMMARY_START
This PR introduces authentication middleware with a critical SQL injection vulnerability that must be fixed before merge. The overall approach is sound but needs security hardening and rate limiting before it is production-ready.
SUMMARY_END
```

- [ ] **Step 7: Create test fixtures — sample_slack_event.json**

```json
{
  "token": "verification_token",
  "team_id": "T01234567",
  "event": {
    "type": "message",
    "channel": "C01234567",
    "user": "U01234567",
    "text": "apply 1,3",
    "ts": "1712345678.000100",
    "thread_ts": "1712345600.000001"
  },
  "type": "event_callback",
  "event_id": "Ev01234567",
  "event_time": 1712345678
}
```

- [ ] **Step 8: Create tests/conftest.py with shared fixtures**

```python
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
```

- [ ] **Step 9: Set up virtualenv and verify imports**

Run:
```bash
cd local-service && python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cd .. && PYTHONPATH=local-service:tests python -c "from config import Settings, load_settings; print('OK')"
```
Expected: `OK`

- [ ] **Step 10: Commit scaffolding**

```bash
git add .gitignore local-service/requirements.txt local-service/requirements-dev.txt \
  local-service/config.yml.example local-service/config.py \
  tests/conftest.py tests/fixtures/sample_review.txt tests/fixtures/sample_slack_event.json
git commit -m "feat: project scaffolding — config, deps, test fixtures"
```

---

### Task 2: Claude Output Parser

**Files:**
- Create: `local-service/parser.py`
- Create: `tests/test_parser.py`

- [ ] **Step 1: Write failing tests for parser**

Create `tests/test_parser.py`:

```python
from __future__ import annotations

from parser import Finding, parse_review, format_slack_blocks


def test_parse_review_extracts_all_findings(sample_review_text: str):
    findings, summary = parse_review(sample_review_text)
    assert len(findings) == 4
    assert findings[0].id == 1
    assert findings[0].severity == "BLOCKER"
    assert findings[0].file == "src/auth.py"
    assert findings[0].line == 42
    assert findings[0].title == "SQL injection in login query"
    assert "parameterized queries" in findings[0].body


def test_parse_review_extracts_summary(sample_review_text: str):
    findings, summary = parse_review(sample_review_text)
    assert "SQL injection vulnerability" in summary


def test_parse_review_handles_general_file(sample_review_text: str):
    findings, summary = parse_review(sample_review_text)
    nit = findings[3]
    assert nit.file == "GENERAL"
    assert nit.line == 0


def test_parse_review_empty_input():
    findings, summary = parse_review("")
    assert findings == []
    assert summary == ""


def test_parse_review_no_summary():
    text = (
        "FINDING_START\n"
        "ID: 1\n"
        "SEVERITY: NIT\n"
        "FILE: GENERAL\n"
        "LINE: 0\n"
        "TITLE: Minor issue\n"
        "BODY: Details here.\n"
        "FINDING_END\n"
    )
    findings, summary = parse_review(text)
    assert len(findings) == 1
    assert summary == ""


def test_format_slack_blocks_contains_findings(sample_review_text: str):
    findings, summary = parse_review(sample_review_text)
    blocks = format_slack_blocks(
        findings=findings,
        summary=summary,
        pr_number=42,
        pr_title="Add auth middleware",
        pr_url="https://github.com/org/repo/pull/42",
        pr_author="dev-user",
        repo="org/repo",
        stacks="go fastapi",
    )
    # Must be a list of Block Kit blocks
    assert isinstance(blocks, list)
    assert len(blocks) > 0
    # Header block should mention PR number
    header_text = blocks[0]["text"]["text"]
    assert "#42" in header_text
    # Should contain all severity emojis present in findings
    all_text = str(blocks)
    assert "BLOCKER" in all_text or "\U0001f6a8" in all_text


def test_format_slack_blocks_includes_footer_instructions(sample_review_text: str):
    findings, summary = parse_review(sample_review_text)
    blocks = format_slack_blocks(
        findings=findings,
        summary=summary,
        pr_number=42,
        pr_title="Test",
        pr_url="https://github.com/org/repo/pull/42",
        pr_author="dev",
        repo="org/repo",
        stacks="go",
    )
    footer_text = str(blocks[-1])
    assert "apply" in footer_text.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/rohitekbote/emdash-projects/worktrees/first-draft-y71
PYTHONPATH=local-service:tests .venv/bin/python -m pytest tests/test_parser.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'parser'` (or `ImportError` for missing names)

- [ ] **Step 3: Implement parser.py**

Create `local-service/parser.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Finding:
    id: int
    severity: str  # BLOCKER | WARNING | SUGGESTION | NIT
    file: str      # relative path or "GENERAL"
    line: int      # 0 if not applicable
    title: str
    body: str


SEVERITY_EMOJI = {
    "BLOCKER": "\U0001f6a8",     # Red siren
    "WARNING": "\u26a0\ufe0f",   # Warning sign
    "SUGGESTION": "\U0001f4a1",  # Light bulb
    "NIT": "\U0001f50d",         # Magnifying glass
}

_FINDING_RE = re.compile(
    r"FINDING_START\s*\n"
    r"ID:\s*(?P<id>\d+)\s*\n"
    r"SEVERITY:\s*(?P<severity>\w+)\s*\n"
    r"FILE:\s*(?P<file>.+?)\s*\n"
    r"LINE:\s*(?P<line>\d+)\s*\n"
    r"TITLE:\s*(?P<title>.+?)\s*\n"
    r"BODY:\s*(?P<body>.*?)\s*\n"
    r"FINDING_END",
    re.DOTALL,
)

_SUMMARY_RE = re.compile(
    r"SUMMARY_START\s*\n(?P<summary>.*?)\s*\nSUMMARY_END",
    re.DOTALL,
)


def parse_review(raw: str) -> tuple[list[Finding], str]:
    """Parse Claude structured review output into findings and summary."""
    findings: list[Finding] = []
    for m in _FINDING_RE.finditer(raw):
        findings.append(
            Finding(
                id=int(m.group("id")),
                severity=m.group("severity").strip(),
                file=m.group("file").strip(),
                line=int(m.group("line")),
                title=m.group("title").strip(),
                body=m.group("body").strip(),
            )
        )
    summary_match = _SUMMARY_RE.search(raw)
    summary = summary_match.group("summary").strip() if summary_match else ""
    return findings, summary


def format_slack_blocks(
    *,
    findings: list[Finding],
    summary: str,
    pr_number: int,
    pr_title: str,
    pr_url: str,
    pr_author: str,
    repo: str,
    stacks: str,
) -> list[dict]:
    """Build Slack Block Kit blocks for a PR review message."""
    blocks: list[dict] = []

    # Header
    blocks.append({
        "type": "header",
        "text": {"type": "plain_text", "text": f"#{pr_number}: {pr_title}"[:150]},
    })

    # Metadata
    meta_lines = [
        f"*Repo:* {repo}  |  *Author:* {pr_author}  |  *Stacks:* {stacks}",
        f"<{pr_url}|View PR on GitHub>",
    ]
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": "\n".join(meta_lines)},
    })

    # Summary
    if summary:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Summary:* {summary}"},
        })

    # Stats bar
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    stats_parts = []
    for sev in ("BLOCKER", "WARNING", "SUGGESTION", "NIT"):
        if sev in counts:
            emoji = SEVERITY_EMOJI[sev]
            stats_parts.append(f"{emoji} {counts[sev]} {sev.lower()}")
    if stats_parts:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "  ".join(stats_parts)}],
        })

    blocks.append({"type": "divider"})

    # Individual findings
    for f in findings:
        emoji = SEVERITY_EMOJI.get(f.severity, "")
        location = f"`{f.file}:{f.line}`" if f.file != "GENERAL" and f.line > 0 else "_General_"
        text = f"*{emoji} #{f.id} [{f.severity}]* {f.title}\n{location}\n{f.body}"
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": text[:3000]},
        })

    blocks.append({"type": "divider"})

    # Footer with instructions
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": (
                    "Reply in this thread: `apply 1,3,5` to post selected findings to GitHub  |  "
                    "`apply all` for all findings  |  "
                    "In channel root: `review PR #N` to trigger a new review"
                ),
            }
        ],
    })

    return blocks
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
PYTHONPATH=local-service:tests .venv/bin/python -m pytest tests/test_parser.py -v
```
Expected: All 7 tests PASS

- [ ] **Step 5: Commit parser**

```bash
git add local-service/parser.py tests/test_parser.py
git commit -m "feat: Claude output parser and Slack Block Kit formatter"
```

---

### Task 3: Slack Client Module

**Files:**
- Create: `local-service/slack.py`
- Create: `tests/test_slack.py`

- [ ] **Step 1: Write failing tests for Slack client**

Create `tests/test_slack.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
PYTHONPATH=local-service:tests .venv/bin/python -m pytest tests/test_slack.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'slack'`

- [ ] **Step 3: Implement slack.py**

Create `local-service/slack.py`:

```python
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
    if abs(time.time() - int(timestamp)) > MAX_TIMESTAMP_AGE:
        return False
    base = f"v0:{timestamp}:{body.decode()}"
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

    async def close(self) -> None:
        await self._http.aclose()
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
PYTHONPATH=local-service:tests .venv/bin/python -m pytest tests/test_slack.py -v
```
Expected: All 6 tests PASS

- [ ] **Step 5: Commit Slack client**

```bash
git add local-service/slack.py tests/test_slack.py
git commit -m "feat: Slack client with signing verification and message posting"
```

---

### Task 4: GitHub Client Module

**Files:**
- Create: `local-service/github.py`
- Create: `tests/test_github.py`

- [ ] **Step 1: Write failing tests for GitHub client**

Create `tests/test_github.py`:

```python
from __future__ import annotations

import pytest
import httpx
import respx

from github import GitHubClient
from parser import Finding


@pytest.fixture
def gh_client(settings) -> GitHubClient:
    return GitHubClient(token=settings.github_token, repo=settings.github_repo)


class TestReadHiddenFindings:
    @respx.mock
    @pytest.mark.asyncio
    async def test_extracts_findings_from_hidden_comment(self, gh_client: GitHubClient):
        comments = [
            {"id": 1, "body": "Normal comment"},
            {
                "id": 2,
                "body": (
                    "<!-- claude-review-data\n"
                    '{"pr": 42, "run_id": "123", "raw": "FINDING_START\\nID: 1\\nSEVERITY: NIT\\nFILE: GENERAL\\nLINE: 0\\nTITLE: Test\\nBODY: Details\\nFINDING_END\\n\\nSUMMARY_START\\nOK\\nSUMMARY_END"}\n'
                    "-->"
                ),
            },
        ]
        respx.get(f"https://api.github.com/repos/testorg/testrepo/issues/42/comments").mock(
            return_value=httpx.Response(200, json=comments)
        )
        raw = await gh_client.read_hidden_findings(pr_number=42)
        assert "FINDING_START" in raw
        assert "Test" in raw

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_hidden_comment(self, gh_client: GitHubClient):
        respx.get(f"https://api.github.com/repos/testorg/testrepo/issues/42/comments").mock(
            return_value=httpx.Response(200, json=[{"id": 1, "body": "Normal comment"}])
        )
        raw = await gh_client.read_hidden_findings(pr_number=42)
        assert raw == ""


class TestPostReviewComment:
    @respx.mock
    @pytest.mark.asyncio
    async def test_posts_file_specific_comment(self, gh_client: GitHubClient):
        finding = Finding(id=1, severity="WARNING", file="src/auth.py", line=42, title="Issue", body="Details")
        # Need to get the diff to find the position — mock the diff endpoint
        respx.get(f"https://api.github.com/repos/testorg/testrepo/pulls/42").mock(
            return_value=httpx.Response(200, json={"head": {"sha": "abc123"}})
        )
        route = respx.post(f"https://api.github.com/repos/testorg/testrepo/pulls/42/comments").mock(
            return_value=httpx.Response(201, json={"id": 999})
        )
        await gh_client.post_review_comment(pr_number=42, finding=finding)
        assert route.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_posts_general_finding_as_issue_comment(self, gh_client: GitHubClient):
        finding = Finding(id=4, severity="NIT", file="GENERAL", line=0, title="Style", body="Be consistent")
        route = respx.post(f"https://api.github.com/repos/testorg/testrepo/issues/42/comments").mock(
            return_value=httpx.Response(201, json={"id": 888})
        )
        await gh_client.post_review_comment(pr_number=42, finding=finding)
        assert route.called
        body = route.calls[0].request.content.decode()
        assert "Style" in body


class TestTriggerWorkflowDispatch:
    @respx.mock
    @pytest.mark.asyncio
    async def test_dispatches_workflow(self, gh_client: GitHubClient):
        route = respx.post(
            f"https://api.github.com/repos/testorg/testrepo/actions/workflows/claude-pr-review.yml/dispatches"
        ).mock(return_value=httpx.Response(204))
        await gh_client.trigger_review(pr_number=142)
        assert route.called
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
PYTHONPATH=local-service:tests .venv/bin/python -m pytest tests/test_github.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'github'`

- [ ] **Step 3: Implement github.py**

Create `local-service/github.py`:

```python
from __future__ import annotations

import json
import re

import httpx

from parser import Finding

GITHUB_API = "https://api.github.com"
HIDDEN_COMMENT_RE = re.compile(r"<!-- claude-review-data\n(.*?)\n-->", re.DOTALL)
BOT_TAG = "<!-- claude-review-bot -->"


class GitHubClient:
    def __init__(self, *, token: str, repo: str) -> None:
        self._repo = repo
        self._http = httpx.AsyncClient(
            base_url=GITHUB_API,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=15.0,
        )

    async def read_hidden_findings(self, *, pr_number: int) -> str:
        """Read raw review text from the hidden HTML comment on the PR."""
        resp = await self._http.get(f"/repos/{self._repo}/issues/{pr_number}/comments")
        resp.raise_for_status()
        for comment in resp.json():
            match = HIDDEN_COMMENT_RE.search(comment.get("body", ""))
            if match:
                data = json.loads(match.group(1))
                return data.get("raw", "")
        return ""

    async def post_review_comment(self, *, pr_number: int, finding: Finding) -> None:
        """Post a finding as a PR review comment (file-specific) or issue comment (general)."""
        emoji = {"BLOCKER": "\U0001f6a8", "WARNING": "\u26a0\ufe0f", "SUGGESTION": "\U0001f4a1", "NIT": "\U0001f50d"}
        icon = emoji.get(finding.severity, "")
        body = f"{icon} **[{finding.severity}] {finding.title}**\n\n{finding.body}\n\n{BOT_TAG}"

        if finding.file == "GENERAL" or finding.line == 0:
            # Post as issue comment
            await self._http.post(
                f"/repos/{self._repo}/issues/{pr_number}/comments",
                json={"body": body},
            )
        else:
            # Post as PR review comment on the specific file/line
            pr_resp = await self._http.get(f"/repos/{self._repo}/pulls/{pr_number}")
            pr_resp.raise_for_status()
            head_sha = pr_resp.json()["head"]["sha"]

            await self._http.post(
                f"/repos/{self._repo}/pulls/{pr_number}/comments",
                json={
                    "body": body,
                    "commit_id": head_sha,
                    "path": finding.file,
                    "line": finding.line,
                },
            )

    async def trigger_review(self, *, pr_number: int) -> None:
        """Trigger the claude-pr-review workflow via workflow_dispatch."""
        await self._http.post(
            f"/repos/{self._repo}/actions/workflows/claude-pr-review.yml/dispatches",
            json={
                "ref": "main",
                "inputs": {"pr_number": str(pr_number)},
            },
        )

    async def close(self) -> None:
        await self._http.aclose()
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
PYTHONPATH=local-service:tests .venv/bin/python -m pytest tests/test_github.py -v
```
Expected: All 5 tests PASS

- [ ] **Step 5: Commit GitHub client**

```bash
git add local-service/github.py tests/test_github.py
git commit -m "feat: GitHub client — hidden findings reader, comment poster, workflow dispatch"
```

---

### Task 5: FastAPI Routes & Main App

**Files:**
- Create: `local-service/main.py`
- Create: `tests/test_routes.py`

- [ ] **Step 1: Write failing tests for routes**

Create `tests/test_routes.py`:

```python
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
        # 200 even though Slack post will fail (no real Slack) — the route accepts and queues
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
PYTHONPATH=local-service:tests .venv/bin/python -m pytest tests/test_routes.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'main'`

- [ ] **Step 3: Implement main.py**

Create `local-service/main.py`:

```python
from __future__ import annotations

import hashlib
import hmac
import json
import re

import structlog
from fastapi import BackgroundTasks, FastAPI, Request, Response

from config import load_settings
from github import GitHubClient
from parser import Finding, parse_review, format_slack_blocks
from slack import SlackClient, verify_slack_signature

logger = structlog.get_logger()

settings = load_settings()

app = FastAPI(title="Claude PR Review Service")

slack_client = SlackClient(bot_token=settings.slack_bot_token, channel=settings.slack_channel)
gh_client = GitHubClient(token=settings.github_token, repo=settings.github_repo)

# In-memory store: PR number -> (thread_ts, findings)
pr_store: dict[int, tuple[str, list[Finding]]] = {}

APPLY_RE = re.compile(r"^apply\s+(.+)$", re.IGNORECASE)
REVIEW_RE = re.compile(r"^review\s+pr\s*#?\s*(\d+)$", re.IGNORECASE)


@app.get("/health")
async def health():
    return {"status": "ok", "tracked_prs": list(pr_store.keys())}


@app.post("/review-complete")
async def review_complete(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()
    sig = request.headers.get("X-Webhook-Secret", "")
    expected = hmac.new(settings.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        logger.warning("review_complete_auth_failed")
        return Response(status_code=401, content="Unauthorized")

    payload = json.loads(body)
    logger.info("review_complete_received", pr=payload["pr_number"])

    findings, summary = parse_review(payload["raw_review"])

    if settings.review_mode == "auto":
        background_tasks.add_task(_auto_apply, payload, findings)
        return {"status": "queued", "mode": "auto"}

    background_tasks.add_task(_post_to_slack, payload, findings, summary)
    return {"status": "queued", "mode": "manual"}


async def _post_to_slack(payload: dict, findings: list[Finding], summary: str):
    try:
        blocks = format_slack_blocks(
            findings=findings,
            summary=summary,
            pr_number=payload["pr_number"],
            pr_title=payload["pr_title"],
            pr_url=payload["pr_url"],
            pr_author=payload["pr_author"],
            repo=payload["repo"],
            stacks=payload["stacks"],
        )
        thread_ts = await slack_client.post_message(blocks=blocks, text=f"Review: #{payload['pr_number']} {payload['pr_title']}")
        pr_store[payload["pr_number"]] = (thread_ts, findings)
        logger.info("slack_thread_created", pr=payload["pr_number"], thread_ts=thread_ts)
    except Exception:
        logger.exception("slack_post_failed", pr=payload["pr_number"])


async def _auto_apply(payload: dict, findings: list[Finding]):
    try:
        for finding in findings:
            await gh_client.post_review_comment(pr_number=payload["pr_number"], finding=finding)
        logger.info("auto_applied", pr=payload["pr_number"], count=len(findings))
    except Exception:
        logger.exception("auto_apply_failed", pr=payload["pr_number"])


@app.post("/slack/events")
async def slack_events(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()
    payload = json.loads(body)

    # URL verification challenge (no signature check needed)
    if payload.get("type") == "url_verification":
        return {"challenge": payload["challenge"]}

    # Verify Slack signature for all other events
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "0")
    signature = request.headers.get("X-Slack-Signature", "")
    if not verify_slack_signature(
        body=body,
        timestamp=timestamp,
        signature=signature,
        signing_secret=settings.slack_signing_secret,
    ):
        logger.warning("slack_signature_invalid")
        return Response(status_code=401, content="Invalid signature")

    event = payload.get("event", {})
    if event.get("type") != "message" or "bot_id" in event:
        return {"ok": True}

    user = event.get("user", "")
    if settings.allowed_slack_users and user not in settings.allowed_slack_users:
        logger.info("slack_user_not_allowed", user=user)
        return {"ok": True}

    text = event.get("text", "").strip()
    thread_ts = event.get("thread_ts")

    # "apply N,M" in a PR thread
    apply_match = APPLY_RE.match(text)
    if apply_match and thread_ts:
        background_tasks.add_task(_handle_apply, apply_match.group(1), thread_ts, user)
        return {"ok": True}

    # "review PR #N" in channel root
    review_match = REVIEW_RE.match(text)
    if review_match and not thread_ts:
        pr_number = int(review_match.group(1))
        background_tasks.add_task(_handle_review_trigger, pr_number, user)
        return {"ok": True}

    return {"ok": True}


async def _handle_apply(ids_str: str, thread_ts: str, user: str):
    # Find PR by thread_ts
    pr_number = None
    findings = []
    for pr, (ts, f) in pr_store.items():
        if ts == thread_ts:
            pr_number = pr
            findings = f
            break

    if pr_number is None:
        logger.warning("apply_no_matching_thread", thread_ts=thread_ts)
        return

    # Parse requested IDs
    if ids_str.strip().lower() == "all":
        selected = findings
    else:
        try:
            requested_ids = {int(x.strip()) for x in ids_str.split(",")}
        except ValueError:
            await slack_client.post_thread_reply(
                thread_ts=thread_ts,
                text=f"\u274c Could not parse finding IDs from: `{ids_str}`",
            )
            return

        available_ids = {f.id for f in findings}
        missing = requested_ids - available_ids
        selected = [f for f in findings if f.id in requested_ids]

        if missing:
            await slack_client.post_thread_reply(
                thread_ts=thread_ts,
                text=f"\u26a0\ufe0f No findings matched IDs: {sorted(missing)}. Available: {sorted(available_ids)}",
            )
            if not selected:
                return

    try:
        for finding in selected:
            await gh_client.post_review_comment(pr_number=pr_number, finding=finding)
        pr_url = f"https://github.com/{settings.github_repo}/pull/{pr_number}"
        await slack_client.post_thread_reply(
            thread_ts=thread_ts,
            text=f"\u2705 Applied {len(selected)} finding(s) to PR #{pr_number}. {pr_url}",
        )
        logger.info("findings_applied", pr=pr_number, count=len(selected), user=user)
    except Exception as exc:
        await slack_client.post_thread_reply(
            thread_ts=thread_ts,
            text=f"\u274c Failed to apply findings: {exc}",
        )
        logger.exception("apply_failed", pr=pr_number)


async def _handle_review_trigger(pr_number: int, user: str):
    try:
        await gh_client.trigger_review(pr_number=pr_number)
        # Post in channel root (not a thread)
        await slack_client.post_message(
            blocks=[],
            text=f"\U0001f504 Review triggered for PR #{pr_number} by <@{user}>. Findings will appear shortly.",
        )
        logger.info("manual_review_triggered", pr=pr_number, user=user)
    except Exception as exc:
        logger.exception("review_trigger_failed", pr=pr_number)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
PYTHONPATH=local-service:tests .venv/bin/python -m pytest tests/test_routes.py -v
```
Expected: All 5 tests PASS

- [ ] **Step 5: Commit main app**

```bash
git add local-service/main.py tests/test_routes.py
git commit -m "feat: FastAPI routes — /review-complete, /slack/events, /health"
```

---

### Task 6: GitHub Action Workflow

**Files:**
- Create: `.github/workflows/claude-pr-review.yml`

- [ ] **Step 1: Create the workflow file**

Create `.github/workflows/claude-pr-review.yml`:

```yaml
name: Claude PR Review

on:
  pull_request:
    types: [opened, synchronize, ready_for_review]
    branches: [main]
  workflow_dispatch:
    inputs:
      pr_number:
        description: "PR number to review"
        required: true
        type: string

permissions:
  contents: read
  pull-requests: write
  issues: write

jobs:
  review:
    name: Claude Review
    runs-on: ubuntu-latest
    if: >-
      github.actor != 'github-actions[bot]' &&
      (github.event_name == 'workflow_dispatch' ||
       (github.event.pull_request.draft == false &&
        github.event.pull_request.head.repo.full_name == github.repository))
    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Determine PR number
        id: pr
        run: |
          if [ "${{ github.event_name }}" = "workflow_dispatch" ]; then
            echo "number=${{ inputs.pr_number }}" >> "$GITHUB_OUTPUT"
          else
            echo "number=${{ github.event.pull_request.number }}" >> "$GITHUB_OUTPUT"
          fi

      - name: Fetch PR metadata
        id: meta
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          PR_NUM="${{ steps.pr.outputs.number }}"

          # Get PR title and body
          gh pr view "$PR_NUM" --json title,body --jq '.title' > /tmp/pr_title.txt
          gh pr view "$PR_NUM" --json title,body --jq '.body // ""' > /tmp/pr_body.txt
          gh pr view "$PR_NUM" --json author --jq '.author.login' > /tmp/pr_author.txt

          # Get diff
          gh pr diff "$PR_NUM" > /tmp/pr_diff.txt

          # Get changed file paths and detect stacks
          gh pr view "$PR_NUM" --json files --jq '.files[].path' > /tmp/changed_files.txt

          STACKS=""
          if grep -q '^go/' /tmp/changed_files.txt 2>/dev/null; then
            STACKS="$STACKS go"
          fi
          if grep -q '^backend-services-2/' /tmp/changed_files.txt 2>/dev/null; then
            STACKS="$STACKS fastapi"
          fi
          if grep -q '^backend-services/' /tmp/changed_files.txt 2>/dev/null; then
            STACKS="$STACKS django"
          fi
          STACKS=$(echo "$STACKS" | xargs)  # trim

          echo "stacks=$STACKS" >> "$GITHUB_OUTPUT"
          echo "Detected stacks: $STACKS"

      - name: Build skill context
        run: |
          # Always load root skill
          SKILL_FILE=".claude/skills/code-review.md"
          if [ -f "$SKILL_FILE" ]; then
            cat "$SKILL_FILE" > /tmp/combined_skill.md
            echo -e "\n---\n" >> /tmp/combined_skill.md
          else
            echo "No root skill file found at $SKILL_FILE" > /tmp/combined_skill.md
            echo -e "\n---\n" >> /tmp/combined_skill.md
          fi

          # Append stack-specific skills
          STACKS="${{ steps.meta.outputs.stacks }}"
          for stack in $STACKS; do
            case "$stack" in
              go)
                STACK_SKILL="go/.claude/skills/code-review.md"
                ;;
              fastapi)
                STACK_SKILL="backend-services-2/.claude/skills/code-review.md"
                ;;
              django)
                STACK_SKILL="backend-services/.claude/skills/code-review.md"
                ;;
              *)
                continue
                ;;
            esac
            if [ -f "$STACK_SKILL" ]; then
              echo "## Stack: $stack" >> /tmp/combined_skill.md
              cat "$STACK_SKILL" >> /tmp/combined_skill.md
              echo -e "\n---\n" >> /tmp/combined_skill.md
            fi
          done

      - name: Install Claude CLI
        run: npm install -g @anthropic-ai/claude-code

      - name: Invoke Claude
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          PR_TITLE=$(cat /tmp/pr_title.txt)
          PR_BODY=$(cat /tmp/pr_body.txt)
          SKILL_CONTENT=$(cat /tmp/combined_skill.md)
          DIFF=$(cat /tmp/pr_diff.txt)

          PROMPT=$(cat <<'PROMPT_EOF'
          ${SKILL_CONTENT}

          ---

          ## PR Context
          Title: ${PR_TITLE}
          Description: ${PR_BODY}

          ## Diff
          ${DIFF}

          ---

          ## Instructions
          Perform a structured review. For each finding output EXACTLY this format
          (do not deviate — it will be parsed programmatically):

          FINDING_START
          ID: <number starting from 1>
          SEVERITY: <BLOCKER|WARNING|SUGGESTION|NIT>
          FILE: <file path or GENERAL if not file-specific>
          LINE: <line number or 0 if not applicable>
          TITLE: <one line summary>
          BODY: <detailed explanation, can be multiline>
          FINDING_END

          After all findings, add:
          SUMMARY_START
          <2-3 sentence overall assessment>
          SUMMARY_END

          Do not add any text outside of FINDING_START/END and SUMMARY_START/END blocks.
          PROMPT_EOF
          )

          # Use envsubst to expand variables in the prompt
          export SKILL_CONTENT PR_TITLE PR_BODY DIFF
          echo "$PROMPT" | envsubst > /tmp/final_prompt.txt

          claude --print "$(cat /tmp/final_prompt.txt)" > /tmp/raw_review.txt

      - name: Store hidden findings on PR
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          PR_NUM="${{ steps.pr.outputs.number }}"
          RUN_ID="${{ github.run_id }}"
          RAW=$(cat /tmp/raw_review.txt)

          # JSON-encode the raw review text
          JSON_RAW=$(python3 -c "import json,sys; print(json.dumps(sys.stdin.read()))" < /tmp/raw_review.txt)

          COMMENT_BODY=$(cat <<EOF
          <!-- claude-review-data
          {"pr": ${PR_NUM}, "run_id": "${RUN_ID}", "raw": ${JSON_RAW}}
          -->
          EOF
          )

          gh pr comment "$PR_NUM" --body "$COMMENT_BODY"

      - name: Notify local service
        env:
          WEBHOOK_SECRET: ${{ secrets.WEBHOOK_SECRET }}
          LOCAL_SERVICE_URL: ${{ vars.LOCAL_SERVICE_URL }}
          REVIEW_MODE: ${{ vars.REVIEW_MODE }}
        run: |
          PR_NUM="${{ steps.pr.outputs.number }}"
          PR_TITLE=$(cat /tmp/pr_title.txt)
          PR_AUTHOR=$(cat /tmp/pr_author.txt)
          STACKS="${{ steps.meta.outputs.stacks }}"
          RAW_REVIEW=$(cat /tmp/raw_review.txt)
          RUN_ID="${{ github.run_id }}"
          REPO="${{ github.repository }}"
          PR_URL="https://github.com/${REPO}/pull/${PR_NUM}"

          # Build JSON payload
          PAYLOAD=$(python3 -c "
          import json, sys
          print(json.dumps({
              'pr_number': int('${PR_NUM}'),
              'pr_title': open('/tmp/pr_title.txt').read().strip(),
              'pr_url': '${PR_URL}',
              'pr_author': open('/tmp/pr_author.txt').read().strip(),
              'stacks': '${STACKS}',
              'run_id': '${RUN_ID}',
              'raw_review': open('/tmp/raw_review.txt').read(),
              'repo': '${REPO}',
          }))
          ")

          # Compute HMAC signature
          SIG=$(echo -n "$PAYLOAD" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" | awk '{print $NF}')

          # POST to local service
          curl -sf -X POST \
            -H "Content-Type: application/json" \
            -H "X-Webhook-Secret: $SIG" \
            -d "$PAYLOAD" \
            "${LOCAL_SERVICE_URL}/review-complete" \
            || echo "Warning: Could not reach local service at ${LOCAL_SERVICE_URL}"
```

- [ ] **Step 2: Validate YAML syntax**

Run:
```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/claude-pr-review.yml')); print('YAML valid')"
```
Expected: `YAML valid`

- [ ] **Step 3: Commit workflow**

```bash
git add .github/workflows/claude-pr-review.yml
git commit -m "feat: GitHub Action workflow for Claude PR review"
```

---

### Task 7: Gitignore & README Updates

**Files:**
- Modify: `.gitignore`
- Modify: `README.md`

- [ ] **Step 1: Update .gitignore (ensure it exists at repo root)**

The `.gitignore` was created in Task 1. Verify it's at the repo root.

Run:
```bash
cat .gitignore
```
Expected: Contents from Task 1 Step 1.

- [ ] **Step 2: Update README.md with setup instructions**

Replace `README.md` with:

```markdown
# revbot

Automated AI-powered PR code review using Claude. Reviews PRs targeting `main`, posts structured findings to Slack, and lets the reviewer selectively apply findings back to GitHub.

## Components

- **GitHub Action** (`.github/workflows/claude-pr-review.yml`) — triggers on PR events, invokes Claude, posts findings
- **Local Service** (`local-service/`) — FastAPI app that bridges Slack and GitHub for selective comment application

## Quick Start

### 1. Configure GitHub Actions

Add these secrets/variables in your repo settings:

| Name | Type | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Secret | Anthropic API key |
| `WEBHOOK_SECRET` | Secret | Shared HMAC secret |
| `LOCAL_SERVICE_URL` | Variable | Cloudflared tunnel URL |
| `REVIEW_MODE` | Variable | `manual` or `auto` |

### 2. Set up the local service

```bash
cd local-service
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config.yml.example config.yml  # fill in your values
```

### 3. Start the tunnel and service

```bash
cloudflared tunnel --url http://localhost:8000
# In another terminal:
cd local-service && source .venv/bin/activate
uvicorn main:app --port 8000 --reload
```

### 4. Slack commands

| Command | Where | Action |
|---|---|---|
| `apply 1,3,5` | PR review thread | Apply selected findings to GitHub |
| `apply all` | PR review thread | Apply all findings |
| `review PR #42` | Channel root | Trigger new review for PR #42 |

## Development

```bash
cd local-service && source .venv/bin/activate
pip install -r requirements-dev.txt
PYTHONPATH=local-service:tests pytest tests/ -v
```
```

- [ ] **Step 3: Commit README and gitignore**

```bash
git add .gitignore README.md
git commit -m "docs: README with setup instructions and usage guide"
```

---

### Task 8: Run Full Test Suite & Final Verification

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite**

Run:
```bash
cd /Users/rohitekbote/emdash-projects/worktrees/first-draft-y71
PYTHONPATH=local-service:tests .venv/bin/python -m pytest tests/ -v --tb=short
```
Expected: All tests PASS (approximately 23 tests across 4 test files)

- [ ] **Step 2: Verify YAML workflow syntax**

Run:
```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/claude-pr-review.yml')); print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Verify no secrets in committed files**

Run:
```bash
git log --all --diff-filter=A --name-only --pretty=format: | sort -u | xargs grep -l 'ghp_\|xoxb-\|sk-ant-' 2>/dev/null || echo "No secrets found"
```
Expected: `No secrets found`

- [ ] **Step 4: Verify config.yml is gitignored**

Run:
```bash
echo "test" > local-service/config.yml
git status local-service/config.yml
```
Expected: File does not appear in git status (it's ignored)

- [ ] **Step 5: Final commit (if any fixups needed)**

Only if previous steps required changes. Otherwise skip.

---

## Spec Coverage Check

| PRD Section | Tasks Covering It |
|---|---|
| 1. Overview | Plan header, architecture description |
| 2. System Architecture | Tasks 5 (routes), 6 (workflow), overall structure |
| 3. GitHub Action Specification | Task 6 |
| 4. Local Service Specification | Tasks 1-5 |
| 5. Claude Prompt & Output Contract | Task 2 (parser), Task 6 (prompt template in workflow) |
| 6. Slack Integration | Tasks 2 (Block Kit formatter), 3 (Slack client), 5 (event handler routes) |
| 7. Configuration Reference | Task 1 (config.py, config.yml.example) |
| 8. Setup & Deployment Guide | Task 7 (README) |
| 9. Acceptance Criteria — F-01 through F-12 | Tasks 2-6 implement all functional requirements |
| 9. Acceptance Criteria — N-01 through N-07 | Task 1 (gitignore), Task 5 (HMAC auth, Slack sig), Task 6 (secrets masking, fork check) |
| 10. Known Limitations | Acknowledged in design — in-memory store, cloudflared URL |
