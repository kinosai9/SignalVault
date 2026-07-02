"""P6-A1: ZSXQ CLI wrapper — subprocess interface to official zsxq-cli.

Only wraps read-only commands. No write operations.
Uses subprocess with timeout; all calls return structured results.
"""

from __future__ import annotations

import json as _json
import logging
import subprocess
from dataclasses import dataclass

from podcast_research.sources.zsxq_models import ZsxqTopic, compute_content_hash

logger = logging.getLogger(__name__)

ZSXQ_CLI = "zsxq-cli"
CALL_TIMEOUT = 30  # seconds


# ── Exceptions ──────────────────────────────────────────────────────────────


class ZsxqCliMissingError(Exception):
    """zsxq-cli not found in PATH."""
    pass


class ZsxqAuthRequiredError(Exception):
    """Not logged in or token expired."""
    pass


class ZsxqPermissionDeniedError(Exception):
    """Access denied to group or topic."""
    pass


class ZsxqParseError(Exception):
    """JSON output could not be parsed."""
    pass


# ── CLI result dataclass ────────────────────────────────────────────────────


@dataclass
class CliResult:
    success: bool = False
    stdout: str = ""
    stderr: str = ""
    data: dict | list | None = None
    error: str = ""
    error_type: str = ""  # "missing" | "auth" | "permission" | "parse" | "timeout" | "unknown"


# ── Internal runner ─────────────────────────────────────────────────────────


def _run_zsxq(args: list[str], timeout: int = CALL_TIMEOUT) -> CliResult:
    """Run zsxq-cli with args and parse JSON output.

    All external calls go through this function for consistent error handling.
    """
    import shutil
    if not shutil.which(ZSXQ_CLI):
        return CliResult(
            error=f"{ZSXQ_CLI} not found in PATH",
            error_type="missing",
        )

    try:
        proc = subprocess.run(
            [ZSXQ_CLI] + args,
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return CliResult(error="zsxq-cli timed out", error_type="timeout")
    except Exception as e:
        return CliResult(error=str(e), error_type="unknown")

    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()

    # Check for auth errors in stderr
    stderr_lower = stderr.lower()
    if "not logged in" in stderr_lower or "unauthorized" in stderr_lower or "token" in stderr_lower:
        return CliResult(stdout=stdout, stderr=stderr,
                         error="ZSXQ authentication required. Run 'zsxq-cli auth login'.",
                         error_type="auth")

    if "permission denied" in stderr_lower or "forbidden" in stderr_lower or "access denied" in stderr_lower:
        return CliResult(stdout=stdout, stderr=stderr,
                         error="Permission denied for this group/topic.",
                         error_type="permission")

    if proc.returncode != 0:
        return CliResult(stdout=stdout, stderr=stderr,
                         error=stderr or f"zsxq-cli exited with code {proc.returncode}",
                         error_type="unknown")

    # Parse JSON
    if not stdout:
        return CliResult(success=True, stdout=stdout, stderr=stderr, data={})

    try:
        data = _json.loads(stdout)
        return CliResult(success=True, stdout=stdout, stderr=stderr, data=data)
    except _json.JSONDecodeError as e:
        return CliResult(stdout=stdout, stderr=stderr,
                         error=f"Failed to parse zsxq-cli JSON output: {e}",
                         error_type="parse")


# ── Public API ──────────────────────────────────────────────────────────────


def check_cli() -> dict:
    """Check zsxq-cli availability and login status.

    Returns:
        {"available": bool, "version": str, "logged_in": bool, "error": str}
    """
    import shutil
    available = shutil.which(ZSXQ_CLI) is not None
    if not available:
        return {"available": False, "version": "", "logged_in": False,
                "error": f"{ZSXQ_CLI} not found in PATH"}

    version = ""
    try:
        proc = subprocess.run([ZSXQ_CLI, "--version"], capture_output=True, text=True, timeout=10)
        version = proc.stdout.strip() or proc.stderr.strip()
    except Exception:
        pass

    # Check login status
    result = _run_zsxq(["auth", "status", "--json"])
    logged_in = result.success

    return {
        "available": True,
        "version": version,
        "logged_in": logged_in,
        "error": result.error if not logged_in else "",
    }


def list_groups() -> CliResult:
    """List groups the current user has access to.

    Returns CliResult with data = [{"group_id": ..., "name": ..., "topic_count": ...}, ...]
    """
    return _run_zsxq(["group", "+list", "--json"])


def fetch_topic(group_id: str, topic_id: str) -> ZsxqTopic:
    """Fetch a single topic by group_id and topic_id.

    Raises:
        ZsxqCliMissingError if CLI not found.
        ZsxqAuthRequiredError if not logged in.
        ZsxqPermissionDeniedError if access denied.
        ZsxqParseError if JSON parse fails.
    """
    result = _run_zsxq(["topic", "+detail", "--group-id", group_id, "--topic-id", topic_id, "--json"])
    _raise_on_error(result)

    data = result.data or {}
    topic_data = data if isinstance(data, dict) else {}

    text = _strip_html(topic_data.get("content", "") or topic_data.get("content_text", ""))
    content_hash = compute_content_hash(text)

    tags = topic_data.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    attachments = topic_data.get("attachments", []) or topic_data.get("files", []) or []

    return ZsxqTopic(
        group_id=group_id,
        group_name=topic_data.get("group_name", ""),
        topic_id=topic_id,
        topic_type=topic_data.get("type", "") or topic_data.get("topic_type", "talk"),
        topic_title=topic_data.get("title", "") or topic_data.get("topic_title", ""),
        author_name=topic_data.get("author", "") or topic_data.get("author_name", ""),
        create_time=topic_data.get("create_time", "") or topic_data.get("created_at", ""),
        update_time=topic_data.get("update_time", "") or topic_data.get("updated_at", ""),
        tags=tags,
        content_text=text,
        attachment_metadata=attachments,
        source_url=topic_data.get("url", "") or topic_data.get("source_url", ""),
        content_hash=content_hash,
        char_count=len(text),
        parse_quality=_assess_quality(text),
    )


def fetch_topics(group_id: str, limit: int = 20) -> list[ZsxqTopic]:
    """Fetch recent topics from a group.

    Raises same exceptions as fetch_topic().
    """
    result = _run_zsxq(["group", "+topics", "--group-id", group_id, "--limit", str(limit), "--json"])
    _raise_on_error(result)

    data = result.data or {}
    items = data if isinstance(data, list) else data.get("topics", []) or data.get("items", [])

    topics: list[ZsxqTopic] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        tid = item.get("topic_id", "") or item.get("id", "")
        text = _strip_html(item.get("content", "") or item.get("content_text", ""))
        content_hash = compute_content_hash(text)
        tags = item.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]

        topics.append(ZsxqTopic(
            group_id=group_id,
            group_name=item.get("group_name", ""),
            topic_id=tid,
            topic_type=item.get("type", "") or item.get("topic_type", "talk"),
            topic_title=item.get("title", "") or item.get("topic_title", ""),
            author_name=item.get("author", "") or item.get("author_name", ""),
            create_time=item.get("create_time", "") or item.get("created_at", ""),
            update_time=item.get("update_time", "") or item.get("updated_at", ""),
            tags=tags,
            content_text=text,
            source_url=item.get("url", "") or item.get("source_url", ""),
            content_hash=content_hash,
            char_count=len(text),
            parse_quality=_assess_quality(text),
        ))
    return topics


# ── Helpers ─────────────────────────────────────────────────────────────────


def _raise_on_error(result: CliResult) -> None:
    """Convert CliResult error to appropriate exception."""
    if result.success:
        return
    error_type = result.error_type
    if error_type == "missing":
        raise ZsxqCliMissingError(result.error)
    elif error_type == "auth":
        raise ZsxqAuthRequiredError(result.error)
    elif error_type == "permission":
        raise ZsxqPermissionDeniedError(result.error)
    elif error_type == "parse":
        raise ZsxqParseError(result.error)
    else:
        raise ZsxqParseError(result.error or "Unknown zsxq-cli error")


def _strip_html(text: str) -> str:
    """Strip HTML tags from text, keeping plain text."""
    if not text:
        return ""
    import re
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = re.sub(r"&[a-z]+;", " ", clean)
    return re.sub(r"\s+", " ", clean).strip()


def _assess_quality(text: str) -> str:
    if not text or len(text) < 100:
        return "minimal"
    if len(text) < 500:
        return "degraded"
    return "good"
