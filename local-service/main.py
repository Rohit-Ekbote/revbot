from __future__ import annotations

import hashlib
import hmac
import json
import re
from contextlib import asynccontextmanager

import structlog
from fastapi import BackgroundTasks, FastAPI, Request, Response

from config import load_settings
from github import GitHubClient
from parser import Finding, parse_review, format_slack_blocks
from slack import SlackClient, verify_slack_signature

logger = structlog.get_logger()

settings = load_settings()

slack_client = SlackClient(bot_token=settings.slack_bot_token, channel=settings.slack_channel)
gh_client = GitHubClient(token=settings.github_token, repo=settings.github_repo)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await slack_client.close()
    await gh_client.close()


app = FastAPI(title="Claude PR Review Service", lifespan=lifespan)

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

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return Response(status_code=400, content="Invalid JSON")
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
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return Response(status_code=400, content="Invalid JSON")

    # URL verification challenge (no signature check needed)
    if payload.get("type") == "url_verification":
        challenge = payload.get("challenge", "")
        if isinstance(challenge, str) and challenge:
            return {"challenge": challenge}
        return Response(status_code=400, content="Invalid challenge")

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
        remaining = [f for f in findings if f.id not in {s.id for s in selected}]
        if remaining:
            pr_store[pr_number] = (thread_ts, remaining)
        else:
            del pr_store[pr_number]
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
