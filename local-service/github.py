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
            await self._http.post(
                f"/repos/{self._repo}/issues/{pr_number}/comments",
                json={"body": body},
            )
        else:
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
