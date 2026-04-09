# revbot

Automated AI-powered PR code review using Claude. Reviews PRs targeting `main`, posts structured findings to Slack, and lets the reviewer selectively apply findings back to GitHub.

## Components

- **GitHub Action** (`.github/workflows/claude-pr-review.yml`) — triggers on PR events, invokes Claude, posts findings
- **Local Service** (`local-service/`) — FastAPI app that bridges Slack and GitHub for selective comment application

## Setup

See **[docs/setup-guide.md](docs/setup-guide.md)** for the complete step-by-step setup guide covering Slack app creation, GitHub Actions configuration, cloudflared tunnel, and end-to-end verification.

## Docker

The simplest way to run revbot — no Python or cloudflared install needed.

### 1. Configure

```bash
cp local-service/config.yml.example local-service/config.yml
# Edit config.yml with your values (see docs/setup-guide.md)
```

### 2. Run

```bash
docker compose up
```

The tunnel URL will be printed in the logs. Update:
- `LOCAL_SERVICE_URL` in GitHub Actions variables
- Request URL in Slack Event Subscriptions

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