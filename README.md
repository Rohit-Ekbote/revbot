# revbot

Automated AI-powered PR code review using Claude. Reviews PRs targeting `main` and posts structured findings to Slack.

## How It Works

1. A PR is opened or updated on `main`
2. GitHub Action invokes Claude to review the diff
3. Findings are posted to a Slack channel as a thread (header + findings)

That's it. No extra services, no setup beyond adding the workflow and one secret.

## Setup

### 1. Add the workflow

Copy `.github/workflows/claude-pr-review.yml` to your repository.

### 2. Configure secrets

Your repo likely already has `SLACK_BOT_TOKEN` (used by other workflows). You only need to add:

| Name | Type | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Secret | Anthropic API key for Claude |

The workflow uses `SLACK_BOT_TOKEN` (existing org secret) and posts to `#notifications` by default.

### 3. (Optional) Change the Slack channel

To post to a different channel, add a repository variable:

| Name | Type | Description |
|---|---|---|
| `SLACK_CHANNEL` | Variable | Channel name or ID (default: `#notifications`) |

### 4. (Optional) Add review skill files

Create skill files in the repo being reviewed to give Claude domain-specific context:

| File | Purpose |
|---|---|
| `.claude/skills/code-review.md` | Root skill — always loaded |
| `go/.claude/skills/code-review.md` | Go-specific review rules |
| `backend-services-2/.claude/skills/code-review.md` | FastAPI-specific review rules |
| `backend-services/.claude/skills/code-review.md` | Django-specific review rules |

### 5. Manual trigger

Trigger a review for any PR via the Actions tab: **Claude PR Review** > **Run workflow** > enter PR number.

## Advanced: Interactive Apply Mode

If you want to selectively apply review findings to GitHub PRs from Slack (via `apply 1,3` commands), you can run the optional local service. This requires:

- The existing Slack App to have **Event Subscriptions** enabled
- A local FastAPI service + cloudflared tunnel on your machine
- Docker (recommended) or Python 3.11+

See **[docs/setup-guide.md](docs/setup-guide.md)** for the full interactive mode setup.

### Slack Commands (Interactive Mode Only)

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