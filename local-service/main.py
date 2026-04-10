from __future__ import annotations

import json
import re
from contextlib import asynccontextmanager

import structlog
from fastapi import BackgroundTasks, FastAPI, Request, Response

from config import load_settings
from github import GitHubClient
from parser import Finding
from slack import SlackClient, verify_slack_signature

logger = structlog.get_logger()

settings = load_settings()

slack_client = SlackClient(bot_token=settings.slack_bot_token, channel=settings.slack_channel)
gh_client = GitHubClient(token=settings.github_token, repo=settings.github_repo)

APPLY_RE = re.compile(r"^apply\s+(.+)$", re.IGNORECASE)
REVIEW_RE = re.compile(r"^review\s+pr\s*#?\s*(\d+)$", re.IGNORECASE)
FINDINGS_DATA_RE = re.compile(r"<!-- revbot-findings-data\n(.*?)\n-->", re.DOTALL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await slack_client.close()
    await gh_client.close()


app = FastAPI(title="Claude PR Review Service", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/slack/events")
async def slack_events(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return Response(status_code=400, content="Invalid JSON")

    # URL verification challenge
    if payload.get("type") == "url_verification":
        challenge = payload.get("challenge", "")
        if isinstance(challenge, str) and challenge:
            return {"challenge": challenge}
        return Response(status_code=400, content="Invalid challenge")

    # Verify Slack signature
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
        logger.warning("slack_user_not_allowed", user=user)
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
    try:
        messages = await slack_client.read_thread_replies(thread_ts=thread_ts)
    except Exception:
        logger.exception("apply_read_thread_failed", thread_ts=thread_ts)
        return

    # Find the message with the findings data blob
    findings_data = None
    for msg in messages:
        match = FINDINGS_DATA_RE.search(msg.get("text", ""))
        if match:
            findings_data = json.loads(match.group(1))
            break

    if findings_data is None:
        await slack_client.post_thread_reply(
            thread_ts=thread_ts,
            text="\u274c No review findings found in this thread.",
        )
        return

    pr_number = findings_data["pr_number"]
    repo = findings_data["repo"]
    findings = [
        Finding(
            id=f["id"],
            severity=f["severity"],
            file=f["file"],
            line=f["line"],
            title=f["title"],
            body=f["body"],
        )
        for f in findings_data["findings"]
    ]

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
        pr_url = f"https://github.com/{repo}/pull/{pr_number}"
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
        await slack_client.post_message(
            blocks=[],
            text=f"\U0001f504 Review triggered for PR #{pr_number} by <@{user}>. Findings will appear shortly.",
        )
        logger.info("manual_review_triggered", pr=pr_number, user=user)
    except Exception as exc:
        await slack_client.post_message(
            blocks=[],
            text=f"\u274c Failed to trigger review for PR #{pr_number}: {exc}",
        )
        logger.exception("review_trigger_failed", pr=pr_number)
