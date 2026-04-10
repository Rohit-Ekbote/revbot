from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
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
    r"BODY:\s*(?P<body>.*?)\s*(?=FINDING_END)",
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


def format_thread_header_blocks(
    *,
    pr_number: int,
    pr_title: str,
    pr_url: str,
    pr_author: str,
    repo: str,
    stacks: str,
    summary: str,
    findings: list[Finding],
) -> list[dict]:
    """Build Slack Block Kit blocks for the thread-starting header message."""
    blocks: list[dict] = []

    blocks.append({
        "type": "header",
        "text": {"type": "plain_text", "text": f"#{pr_number}: {pr_title}"[:150]},
    })

    meta_lines = [
        f"*Repo:* {repo}  |  *Author:* {pr_author}  |  *Stacks:* {stacks}",
        f"<{pr_url}|View PR on GitHub>",
    ]
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": "\n".join(meta_lines)},
    })

    if summary:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Summary:* {summary}"},
        })

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

    return blocks


def format_findings_data_message(
    *,
    findings: list[Finding],
    pr_number: int,
    repo: str,
) -> str:
    """Build the thread reply text containing findings + hidden JSON data blob."""
    import json

    parts: list[str] = []

    for f in findings:
        emoji = SEVERITY_EMOJI.get(f.severity, "")
        location = f"`{f.file}:{f.line}`" if f.file != "GENERAL" and f.line > 0 else "_General_"
        parts.append(f"*{emoji} #{f.id} [{f.severity}]* {f.title}\n{location}\n{f.body}")

    parts.append("")
    parts.append("Reply: `apply 1,3,5` to post selected findings to GitHub  |  `apply all` for all findings")

    findings_data = [
        {"id": f.id, "severity": f.severity, "file": f.file, "line": f.line, "title": f.title, "body": f.body}
        for f in findings
    ]
    json_blob = json.dumps({"pr_number": pr_number, "repo": repo, "findings": findings_data})
    parts.append(f"\n<!-- revbot-findings-data\n{json_blob}\n-->")

    return "\n\n".join(parts)
