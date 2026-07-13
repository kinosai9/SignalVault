"""P6-A1: ZSXQ topic import — profile, eligibility, ingest_jobs integration."""

from __future__ import annotations

import json as _json
import logging

from signalvault.sources.zsxq_cli import (
    ZsxqAuthRequiredError,
    ZsxqCliMissingError,
    ZsxqParseError,
    ZsxqPermissionDeniedError,
    fetch_topic,
    fetch_topics,
)
from signalvault.sources.zsxq_models import (
    ZsxqSourceProfile,
    ZsxqTopic,
    _now_iso,
)
from signalvault.sources.zsxq_registry import get_group

logger = logging.getLogger(__name__)


# ── Source Profile Builder ──────────────────────────────────────────────────


def build_zsxq_source_profile(topic: ZsxqTopic) -> ZsxqSourceProfile:
    """Build a source profile from a ZsxqTopic.

    Checks eligibility: content_text ≥ 100 chars, content_hash exists,
    parse_quality != "minimal".
    """
    eligible = True
    reason = ""
    warnings: list[str] = []

    if topic.parse_quality == "minimal":
        eligible = False
        reason = "内容解析质量过低，无法提取有效文本。"
    elif not topic.content_text or len(topic.content_text) < 100:
        eligible = False
        reason = f"文本内容过短（{len(topic.content_text)} 字），不适合分析。"
    elif not topic.content_hash:
        eligible = False
        reason = "无法计算内容哈希。"

    # Check group access status from registry
    group = get_group(topic.group_id)
    group_access = group.access_status if group else "active"

    return ZsxqSourceProfile(
        source_type="zsxq_topic",
        group_id=topic.group_id,
        group_name=topic.group_name,
        group_access_status=group_access,
        topic_id=topic.topic_id,
        topic_type=topic.topic_type,
        topic_title=topic.topic_title,
        author_name=topic.author_name,
        create_time=topic.create_time,
        update_time=topic.update_time,
        tags=topic.tags,
        content_text=topic.content_text,
        content_hash=topic.content_hash,
        source_url=topic.source_url,
        attachment_metadata=topic.attachment_metadata,
        import_eligible=eligible,
        ineligible_reason=reason,
        parse_quality=topic.parse_quality,
        quality_warnings=warnings,
        imported_at=_now_iso(),
    )


def _profile_to_dict(profile: ZsxqSourceProfile) -> dict:
    """Serialize profile to JSON-safe dict for ingest_jobs payload."""
    return {
        "source_type": profile.source_type,
        "group_id": profile.group_id,
        "group_name": profile.group_name,
        "group_access_status": profile.group_access_status,
        "topic_id": profile.topic_id,
        "topic_type": profile.topic_type,
        "topic_title": profile.topic_title,
        "author_name": profile.author_name,
        "create_time": profile.create_time,
        "update_time": profile.update_time,
        "tags": profile.tags,
        "content_text": profile.content_text[:2000],
        "content_hash": profile.content_hash,
        "source_url": profile.source_url,
        "attachment_metadata": profile.attachment_metadata,
        "import_eligible": profile.import_eligible,
        "ineligible_reason": profile.ineligible_reason,
        "parse_quality": profile.parse_quality,
        "quality_warnings": profile.quality_warnings,
        "imported_at": profile.imported_at,
    }


# ── Ingest Job Creation ─────────────────────────────────────────────────────


def import_topic_to_ingest(
    group_id: str,
    topic_id: str,
    session=None,
) -> dict:
    """Fetch a ZSXQ topic and create an ingest_job.

    Args:
        group_id: ZSXQ group ID.
        topic_id: ZSXQ topic ID.
        session: Optional DB session for ingest_jobs.

    Returns:
        {"success": bool, "profile": ZsxqSourceProfile | None,
         "job": dict | None, "error": str, "error_type": str,
         "review_findings": list[dict]}
    """
    review_findings: list[dict] = []

    # 1. Fetch topic from the external ZSXQ CLI
    try:
        topic = fetch_topic(group_id, topic_id)
    except ZsxqCliMissingError:
        return _error_result("ZSXQ CLI not found in PATH", "zsxq_cli_missing",
                             [{"rule": "zsxq_cli_missing", "severity": "error",
                               "file_path": f"zsxq:group:{group_id}",
                               "message": "ZSXQ CLI not found in PATH.",
                               "detail": "请从官方 GitHub 仓库按 README 安装/构建，并确保 zsxq 或 zsxq-cli 在 PATH；也可设置 ZSXQ_CLI_PATH。"}])
    except ZsxqAuthRequiredError:
        return _error_result("ZSXQ authentication required", "zsxq_auth_required",
                             [{"rule": "zsxq_auth_required", "severity": "warning",
                               "file_path": f"zsxq:group:{group_id}",
                               "message": "ZSXQ authentication required.",
                               "detail": "Run 'zsxq auth login' or the equivalent command name from your install."}])
    except ZsxqPermissionDeniedError:
        return _error_result("Permission denied", "zsxq_permission_denied",
                             [{"rule": "zsxq_permission_denied", "severity": "warning",
                               "file_path": f"zsxq:group:{group_id}",
                               "message": f"Permission denied for topic {topic_id}.",
                               "detail": "Check group subscription status."}])
    except ZsxqParseError as e:
        return _error_result(f"Parse error: {e}", "zsxq_parse_failed",
                             [{"rule": "zsxq_parse_failed", "severity": "error",
                               "file_path": f"zsxq:group:{group_id}:topic:{topic_id}",
                               "message": f"Failed to parse topic JSON: {e}",
                               "detail": "Check ZSXQ CLI version and output format."}])

    # 2. Build profile
    profile = build_zsxq_source_profile(topic)

    # 3. Check attachments
    for att in topic.attachment_metadata:
        att_type = (att.get("type") or att.get("file_type") or "").lower()
        if att_type and att_type not in ("pdf", "image", "doc", "txt", "md", "html"):
            review_findings.append({
                "rule": "zsxq_attachment_unsupported",
                "severity": "info",
                "file_path": f"zsxq:topic:{topic_id}",
                "message": f"Unsupported attachment type: {att_type}",
                "detail": f"File: {att.get('name', 'unknown')}",
            })

    # 4. Create ingest job
    from signalvault.sources.ingest_jobs import IngestJobManager

    payload = _json.dumps(_profile_to_dict(profile), ensure_ascii=False)
    job = IngestJobManager.create_job(
        source_type="zsxq_topic",
        source_hash=profile.content_hash,
        source_name=profile.topic_title[:500],
        source_url=profile.source_url,
        preview_data=payload,
        session=session,
    )

    if job is None:
        # Likely duplicate — partial unique index blocked it
        return {
            "success": False,
            "profile": profile,
            "job": None,
            "error": "Duplicate topic (same content_hash already pending)",
            "error_type": "duplicate",
            "review_findings": review_findings,
        }

    return {
        "success": True,
        "profile": profile,
        "job": job,
        "error": "",
        "error_type": "",
        "review_findings": review_findings,
    }


def sync_group_to_ingest(
    group_id: str,
    limit: int = 20,
    session=None,
) -> dict:
    """Fetch recent topics from a group and create ingest_jobs.

    Returns:
        {"success": bool, "imported": int, "skipped": int,
         "errors": int, "results": list[dict],
         "review_findings": list[dict]}
    """
    all_review_findings: list[dict] = []
    results: list[dict] = []
    imported = 0
    skipped = 0
    errors = 0

    # Fetch topics
    try:
        topics = fetch_topics(group_id, limit=limit)
    except ZsxqCliMissingError:
        return _sync_error("ZSXQ CLI not found", "zsxq_cli_missing", group_id)
    except ZsxqAuthRequiredError:
        return _sync_error("Authentication required", "zsxq_auth_required", group_id)
    except ZsxqPermissionDeniedError:
        return _sync_error("Permission denied", "zsxq_permission_denied", group_id)
    except ZsxqParseError as e:
        return _sync_error(f"Parse error: {e}", "zsxq_parse_failed", group_id)

    for topic in topics:
        if not topic.topic_id:
            skipped += 1
            continue

        r = import_topic_to_ingest(topic.group_id, topic.topic_id, session=session)
        results.append(r)
        all_review_findings.extend(r.get("review_findings", []))

        if r["success"]:
            imported += 1
        elif r.get("error_type") == "duplicate":
            skipped += 1
        else:
            errors += 1

    return {
        "success": errors == 0,
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "results": results,
        "review_findings": all_review_findings,
    }


# ── Helpers ─────────────────────────────────────────────────────────────────


def _error_result(msg: str, etype: str, findings: list[dict]) -> dict:
    return {
        "success": False,
        "profile": None,
        "job": None,
        "error": msg,
        "error_type": etype,
        "review_findings": findings,
    }


def _sync_error(msg: str, etype: str, group_id: str) -> dict:
    return {
        "success": False,
        "imported": 0,
        "skipped": 0,
        "errors": 1,
        "results": [],
        "review_findings": [{
            "rule": etype,
            "severity": "error" if "missing" in etype else "warning",
            "file_path": f"zsxq:group:{group_id}",
            "message": msg,
            "detail": f"group_id={group_id}",
        }],
    }
