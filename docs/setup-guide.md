# Setup Guide

Complete step-by-step guide to set up the Claude PR Review System. This covers creating the Slack app, configuring GitHub Actions, running the local service, and verifying everything works end-to-end.

## Prerequisites

- GitHub repository with a `main` branch
- Anthropic API key with Claude access
- Slack workspace where you can create apps
- macOS with Homebrew (for cloudflared)
- Python 3.11+

## Quick Start with Docker

If you prefer Docker over a local Python install, you can skip Steps 3, 4, and 6 and use Docker instead:

```bash
# Create your config
cp local-service/config.yml.example local-service/config.yml
# Edit config.yml with your Slack, GitHub, and webhook values

# Start the service + tunnel
docker compose up
```

The container runs both the FastAPI service and cloudflared tunnel. The tunnel URL is printed in the logs — use it for the `LOCAL_SERVICE_URL` GitHub Actions variable and the Slack Event Subscriptions request URL.

You still need to complete Step 1 (Slack App), Step 2 (GitHub Actions), and Step 5 (Slack Event Subscriptions) manually.

## Step 1: Create the Slack App

1. Go to [https://api.slack.com/apps](https://api.slack.com/apps) and click **Create New App** > **From scratch**
2. Name it something like `Claude Reviewer` and select your workspace

### Add Bot Scopes

3. Navigate to **OAuth & Permissions** in the sidebar
4. Under **Bot Token Scopes**, add:
   - `chat:write` — post messages and thread replies
   - `channels:history` — read messages in public channels (or `groups:history` for private channels)

### Install to Workspace

5. Click **Install to Workspace** at the top of the OAuth & Permissions page
6. Authorize the app
7. Copy the **Bot User OAuth Token** (`xoxb-...`) — you'll need this for `config.yml`

### Get the Signing Secret

8. Go to **Basic Information** in the sidebar
9. Under **App Credentials**, copy the **Signing Secret** — you'll need this for `config.yml`

### Create a Review Channel

10. Create a dedicated Slack channel for reviews (e.g., `#claude-reviews`)
11. Invite the bot to the channel: type `/invite @Claude Reviewer` in the channel
12. Get the **Channel ID**: right-click the channel name > **View channel details** > the ID is at the bottom of the modal (starts with `C`)

> **Don't configure Event Subscriptions yet** — you need the tunnel URL first (Step 4).

## Step 2: Configure GitHub Actions

In your GitHub repository:

1. Go to **Settings** > **Secrets and variables** > **Actions**

2. Add these **secrets**:

   | Secret | Value |
   |---|---|
   | `ANTHROPIC_API_KEY` | Your Anthropic API key |
   | `WEBHOOK_SECRET` | A random string (generate with `openssl rand -hex 32`) |

3. Add these **variables**:

   | Variable | Value |
   |---|---|
   | `LOCAL_SERVICE_URL` | Placeholder for now — you'll update this in Step 4 |
   | `REVIEW_MODE` | `manual` (findings go to Slack for approval) or `auto` (posted directly to PR) |

4. (Optional) Protect the workflow file by adding a `CODEOWNERS` file at the repo root:

   ```
   .github/workflows/ @your-github-username
   ```

## Step 3: Configure the Local Service

### Create a GitHub Personal Access Token

1. Go to [https://github.com/settings/tokens](https://github.com/settings/tokens)
2. Click **Generate new token (classic)**
3. Select scopes: `repo` (full) and `workflow`
4. Copy the token (`ghp_...`)

### Set Up the Service

```bash
cd local-service
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Create Your Config File

```bash
cp config.yml.example config.yml
```

Edit `config.yml` with your values:

```yaml
# GitHub
github_token: "ghp_your_token_from_above"
github_repo: "your-org/your-repo"

# Slack (from Step 1)
slack_bot_token: "xoxb-your-bot-token"
slack_signing_secret: "your-signing-secret"
slack_channel: "C01234567"  # Channel ID from Step 1

# Security (must match WEBHOOK_SECRET from Step 2)
webhook_secret: "your-random-string-from-step-2"

# Review mode: manual | auto
review_mode: "manual"

# Your Slack user ID (find it in your Slack profile > three dots > Copy member ID)
allowed_slack_users:
  - "U01234567"
```

> **Security note:** `config.yml` is gitignored and should never be committed.

## Step 4: Start the Cloudflared Tunnel

The tunnel exposes your local service to the internet so Slack and GitHub Actions can reach it.

### Install cloudflared

```bash
brew install cloudflare/cloudflare/cloudflared
```

### Start the Tunnel

```bash
cloudflared tunnel --url http://localhost:8000
```

You'll see output like:

```
+--------------------------------------------------------------------------------------------+
|  Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):  |
|  https://abc-def-ghi.trycloudflare.com                                                    |
+--------------------------------------------------------------------------------------------+
```

Copy this URL. You need to update **two places**:

1. **GitHub Actions variable:** Go to your repo Settings > Secrets and variables > Actions > Variables, and set `LOCAL_SERVICE_URL` to the tunnel URL (e.g., `https://abc-def-ghi.trycloudflare.com`)

2. **Slack Event Subscriptions** (next step)

> **Note:** This URL changes every time you restart cloudflared. For a stable URL, create a free Cloudflare account and set up a [named tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/).

## Step 5: Configure Slack Event Subscriptions

Now that you have the tunnel URL:

1. Go back to your Slack app at [https://api.slack.com/apps](https://api.slack.com/apps)
2. Navigate to **Event Subscriptions** in the sidebar
3. Toggle **Enable Events** to **On**
4. Set the **Request URL** to: `https://your-tunnel-url/slack/events`

   > The local service must be running for Slack to verify this URL. Start it first (Step 6) if you haven't already.

5. Under **Subscribe to bot events**, add:
   - `message.channels` (for public channels)
   - `message.groups` (for private channels, if needed)

6. Click **Save Changes**

## Step 6: Start the Local Service

In a new terminal (keep cloudflared running in the other one):

```bash
cd local-service
source .venv/bin/activate
uvicorn main:app --port 8000 --reload
```

### Verify It's Working

Test the health endpoint through the tunnel:

```bash
curl https://your-tunnel-url/health
```

Expected response:

```json
{"status": "ok", "tracked_prs": []}
```

### Verify Slack Connection

Go back to your Slack app's **Event Subscriptions** page. The Request URL should now show **Verified** with a green checkmark.

## Step 7: End-to-End Test

1. **Open a test PR** targeting `main` with changes in any stack directory (`go/`, `backend-services-2/`, or `backend-services/`)

2. **Watch the GitHub Action** — go to the Actions tab in your repo and confirm the `Claude PR Review` workflow starts and completes successfully

3. **Check Slack** — a new message should appear in your review channel with numbered findings, severity indicators, and a summary

4. **Test the apply command** — reply in the Slack thread with:
   ```
   apply 1
   ```

5. **Verify on GitHub** — check the PR for a new review comment matching finding #1

6. **Test manual trigger** — in the channel (not in a thread), type:
   ```
   review PR #1
   ```
   This should trigger a new review run.

## Troubleshooting

### GitHub Action fails at "Invoke Claude"

- Check that `ANTHROPIC_API_KEY` is set correctly in repo secrets
- Verify the API key has Claude access

### Slack doesn't show the review

- Verify the local service is running and reachable: `curl https://your-tunnel-url/health`
- Check that `LOCAL_SERVICE_URL` in GitHub Actions variables matches your current tunnel URL
- Check the local service logs for errors

### "apply" command doesn't work

- Make sure you're replying **in the review thread**, not in the channel root
- Check that your Slack user ID is in `allowed_slack_users` in `config.yml`
- Verify the bot is invited to the channel

### Slack Event Subscriptions won't verify

- The local service must be running and reachable through the tunnel
- Check that the Request URL is `https://your-tunnel-url/slack/events` (not just `/slack`)
- Check cloudflared is still running

### Tunnel URL changed

After restarting cloudflared, update both:
1. `LOCAL_SERVICE_URL` in GitHub Actions variables
2. Request URL in Slack Event Subscriptions

## Skill Files (Optional)

The review system loads skill files to give Claude domain-specific review context. Create these in the **repository being reviewed** (not in revbot):

| File | Purpose |
|---|---|
| `.claude/skills/code-review.md` | Root skill — cross-cutting review concerns (always loaded) |
| `go/.claude/skills/code-review.md` | Go-specific review rules |
| `backend-services-2/.claude/skills/code-review.md` | FastAPI-specific review rules |
| `backend-services/.claude/skills/code-review.md` | Django-specific review rules |

These files contain markdown instructions that are injected into Claude's prompt. Example content for a root skill:

```markdown
## Code Review Standards

### Security
- Check for SQL injection, XSS, and SSRF vulnerabilities
- Verify secrets are not hardcoded
- Check authentication/authorization on all endpoints

### Logging
- All API endpoints must use structlog
- Include request_id in all log entries
- Never log PII or secrets

### Testing
- New features must include tests
- Test edge cases and error paths
```
