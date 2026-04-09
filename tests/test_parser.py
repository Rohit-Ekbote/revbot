from __future__ import annotations

from parser import Finding, parse_review, format_slack_blocks


def test_parse_review_extracts_all_findings(sample_review_text: str):
    findings, summary = parse_review(sample_review_text)
    assert len(findings) == 4
    assert findings[0].id == 1
    assert findings[0].severity == "BLOCKER"
    assert findings[0].file == "src/auth.py"
    assert findings[0].line == 42
    assert findings[0].title == "SQL injection in login query"
    assert "parameterized queries" in findings[0].body


def test_parse_review_extracts_summary(sample_review_text: str):
    findings, summary = parse_review(sample_review_text)
    assert "SQL injection vulnerability" in summary


def test_parse_review_handles_general_file(sample_review_text: str):
    findings, summary = parse_review(sample_review_text)
    nit = findings[3]
    assert nit.file == "GENERAL"
    assert nit.line == 0


def test_parse_review_empty_input():
    findings, summary = parse_review("")
    assert findings == []
    assert summary == ""


def test_parse_review_no_summary():
    text = (
        "FINDING_START\n"
        "ID: 1\n"
        "SEVERITY: NIT\n"
        "FILE: GENERAL\n"
        "LINE: 0\n"
        "TITLE: Minor issue\n"
        "BODY: Details here.\n"
        "FINDING_END\n"
    )
    findings, summary = parse_review(text)
    assert len(findings) == 1
    assert summary == ""


def test_parse_review_multiline_body():
    text = (
        "FINDING_START\n"
        "ID: 1\n"
        "SEVERITY: WARNING\n"
        "FILE: src/api.py\n"
        "LINE: 25\n"
        "TITLE: Missing error handling\n"
        "BODY: The endpoint lacks error handling.\n"
        "\n"
        "Consider adding:\n"
        "- Try/except around the DB call\n"
        "- Proper HTTP error responses\n"
        "FINDING_END\n"
    )
    findings, summary = parse_review(text)
    assert len(findings) == 1
    assert "Try/except" in findings[0].body
    assert "HTTP error responses" in findings[0].body


def test_format_slack_blocks_contains_findings(sample_review_text: str):
    findings, summary = parse_review(sample_review_text)
    blocks = format_slack_blocks(
        findings=findings,
        summary=summary,
        pr_number=42,
        pr_title="Add auth middleware",
        pr_url="https://github.com/org/repo/pull/42",
        pr_author="dev-user",
        repo="org/repo",
        stacks="go fastapi",
    )
    # Must be a list of Block Kit blocks
    assert isinstance(blocks, list)
    assert len(blocks) > 0
    # Header block should mention PR number
    header_text = blocks[0]["text"]["text"]
    assert "#42" in header_text
    # Should contain all severity emojis present in findings
    all_text = str(blocks)
    assert "BLOCKER" in all_text or "\U0001f6a8" in all_text


def test_format_slack_blocks_includes_footer_instructions(sample_review_text: str):
    findings, summary = parse_review(sample_review_text)
    blocks = format_slack_blocks(
        findings=findings,
        summary=summary,
        pr_number=42,
        pr_title="Test",
        pr_url="https://github.com/org/repo/pull/42",
        pr_author="dev",
        repo="org/repo",
        stacks="go",
    )
    footer_text = str(blocks[-1])
    assert "apply" in footer_text.lower()


from parser import format_thread_header_blocks, format_findings_data_message


def test_format_thread_header_blocks(sample_review_text: str):
    findings, summary = parse_review(sample_review_text)
    blocks = format_thread_header_blocks(
        pr_number=42,
        pr_title="Add auth middleware",
        pr_url="https://github.com/org/repo/pull/42",
        pr_author="dev-user",
        repo="org/repo",
        stacks="go fastapi",
        summary=summary,
        findings=findings,
    )
    assert isinstance(blocks, list)
    header_text = blocks[0]["text"]["text"]
    assert "#42" in header_text
    all_text = str(blocks)
    assert "dev-user" in all_text
    assert "Summary" in all_text


def test_format_findings_data_message(sample_review_text: str):
    findings, summary = parse_review(sample_review_text)
    text = format_findings_data_message(
        findings=findings,
        pr_number=42,
        repo="org/repo",
    )
    assert "<!-- revbot-findings-data" in text
    assert '"pr_number": 42' in text
    assert "SQL injection" in text
    assert "apply" in text.lower()


def test_format_findings_data_message_json_is_parseable(sample_review_text: str):
    import json, re
    findings, _ = parse_review(sample_review_text)
    text = format_findings_data_message(findings=findings, pr_number=42, repo="org/repo")
    match = re.search(r"<!-- revbot-findings-data\n(.*?)\n-->", text, re.DOTALL)
    assert match is not None
    data = json.loads(match.group(1))
    assert data["pr_number"] == 42
    assert len(data["findings"]) == 4
    assert data["findings"][0]["id"] == 1
    assert data["findings"][0]["severity"] == "BLOCKER"
