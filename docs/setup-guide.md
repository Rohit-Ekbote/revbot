# Setup Guide

## Core Setup (Notifications Only)

Review findings posted to Slack automatically. No local service needed.

### Step 1: Add the Workflow

Copy `.github/workflows/claude-pr-review.yml` to your repository's `.github/workflows/` directory.

### Step 2: Add Anthropic API Key

In your repo **Settings** > **Secrets and variables** > **Actions** > **Secrets**, add:

| Secret | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key for Claude |

The workflow also uses `SLACK_BOT_TOKEN`, which should already exist as an org-level secret (used by `reusable_build_push_notify.yml` and other workflows).

### Step 3: (Optional) Set Slack Channel

By default, reviews post to `#notifications`. To use a different channel, add a **variable** (not a secret):

**Settings** > **Secrets and variables** > **Actions** > **Variables**:

| Variable | Description |
|---|---|
| `SLACK_CHANNEL` | Channel name or ID (e.g., `#code-reviews` or `C01234567`) |

### Step 4: Test It

1. Open a PR targeting `main`
2. Go to the **Actions** tab and confirm the `Claude PR Review` workflow runs
3. Check the Slack channel for the review thread

### Step 5: (Optional) Add Skill Files

Create skill files in the repository being reviewed to customize what Claude checks:

```
.claude/skills/code-review.md              # Always loaded — cross-cutting concerns
go/.claude/skills/code-review.md            # Go-specific rules
backend-services-2/.claude/skills/code-review.md  # FastAPI-specific rules
backend-services/.claude/skills/code-review.md     # Django-specific rules
```

Example root skill:

```markdown
## Code Review Standards

### Security
- Check for SQL injection, XSS, and SSRF vulnerabilities
- Verify secrets are not hardcoded

### Logging
- All API endpoints must use structlog
- Never log PII or secrets

### Testing
- New features must include tests
- Test edge cases and error paths
```

---

## Advanced: Interactive Apply Mode

This optional setup lets you selectively apply review findings to GitHub PRs directly from Slack by typing `apply 1,3` in the review thread.

### Prerequisites

- Docker (recommended) or Python 3.11+ with cloudflared
- The Slack App must have Event Subscriptions enabled (see below)

### Step A: Enable Slack Event Subscriptions

Your existing Slack App (the one providing `SLACK_BOT_TOKEN`) needs Event Subscriptions enabled:

1. Go to [https://api.slack.com/apps](https://api.slack.com/apps) and select your app
2. Navigate to **Event Subscriptions** > toggle **Enable Events** to **On**
3. Set the **Request URL** to your tunnel URL + `/slack/events` (see Step C)
4. Under **Subscribe to bot events**, add `message.channels` (and `message.groups` for private channels)
5. Ensure **OAuth & Permissions** includes scopes: `chat:write`, `channels:history`
6. Click **Save Changes**

### Step B: Create Local Config

```bash
cd local-service
cp config.yml.example config.yml
```

Edit `config.yml`:

```yaml
github_token: "ghp_your_pat_with_repo_scope"
github_repo: "your-org/your-repo"
slack_bot_token: "xoxb-your-bot-token"
slack_signing_secret: "your-signing-secret"
slack_channel: "C01234567"
allowed_slack_users:
  - "U_YOUR_SLACK_ID"
```

### Step C: Start with Docker

```bash
docker compose up
```

The tunnel URL will be printed in the logs. Set this as the **Request URL** in Slack Event Subscriptions (Step A, item 3).

### Step D: Start without Docker

```bash
# Terminal 1: tunnel
brew install cloudflare/cloudflare/cloudflared
cloudflared tunnel --url http://localhost:8000

# Terminal 2: service
cd local-service
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --port 8000 --reload
```

### Step E: Test Interactive Mode

1. Find a review thread in Slack
2. Reply: `apply 1`
3. Verify the finding appears as a comment on the GitHub PR

### Troubleshooting

**"apply" command doesn't work:**
- Make sure you're replying in the review thread, not the channel root
- Check your Slack user ID is in `allowed_slack_users` in `config.yml`
- Verify the local service is running and the tunnel is active

**Tunnel URL changed:**
After restarting cloudflared/Docker, update the Request URL in Slack Event Subscriptions.
