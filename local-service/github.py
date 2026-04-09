from __future__ import annotations

import json

import httpx

from parser import Finding, SEVERITY_EMOJI

GITHUB_API = "https://api.github.com"
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

    async def post_review_comment(self, *, pr_number: int, finding: Finding) -> None:
        """Post a finding as a PR review comment (file-specific) or issue comment (general)."""
        icon = SEVERITY_EMOJI.get(finding.severity, "")
        body = f"{icon} **[{finding.severity}] {finding.title}**\n\n{finding.body}\n\n{BOT_TAG}"

        if finding.file == "GENERAL" or finding.line == 0:
            resp = await self._http.post(
                f"/repos/{self._repo}/issues/{pr_number}/comments",
                json={"body": body},
            )
            resp.raise_for_status()
        else:
            pr_resp = await self._http.get(f"/repos/{self._repo}/pulls/{pr_number}")
            pr_resp.raise_for_status()
            head_sha = pr_resp.json()["head"]["sha"]

            resp = await self._http.post(
                f"/repos/{self._repo}/pulls/{pr_number}/comments",
                json={
                    "body": body,
                    "commit_id": head_sha,
                    "path": finding.file,
                    "line": finding.line,
                },
            )
            resp.raise_for_status()

    async def trigger_review(self, *, pr_number: int) -> None:
        """Trigger the claude-pr-review workflow via workflow_dispatch."""
        resp = await self._http.post(
            f"/repos/{self._repo}/actions/workflows/claude-pr-review.yml/dispatches",
            json={
                "ref": "main",
                "inputs": {"pr_number": str(pr_number)},
            },
        )
        resp.raise_for_status()

    async def close(self) -> None:
        await self._http.aclose()
