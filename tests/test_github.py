from __future__ import annotations

import pytest
import httpx
import respx

from github import GitHubClient
from parser import Finding


@pytest.fixture
async def gh_client(settings) -> GitHubClient:
    client = GitHubClient(token=settings.github_token, repo=settings.github_repo)
    yield client
    await client.close()


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
