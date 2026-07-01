"""P3-B: Vault Lint — health check for Obsidian vaults.

Scans vault .md files and reports: frontmatter issues, dead wikilinks,
duplicate reports, orphan cards. Does NOT modify files (read-only lint).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]+)?\]\]")

_REQUIRED_FIELDS: dict[str, set[str]] = {
    "report": {"type", "source_type", "channel", "video_id", "analyzed_at"},
    "topic": {"type", "status"},
    "company": {"type", "status"},
    "claim": {"type", "claim_id", "status"},
    "signal": {"type", "signal_id", "status"},
}

_DIR_TYPE_MAP: dict[str, str] = {
    "01_Reports": "report",
    "02_Topics": "topic",
    "03_Companies": "company",
    "06_Claims": "claim",
    "07_Signals": "signal",
}

_STALE_DAYS = 90


# ── Helpers ──────────────────────────────────────────────────────────────────


def _parse_frontmatter(text: str) -> tuple[dict | None, str | None]:
    """Parse YAML frontmatter from markdown text.

    Returns (parsed_dict, error_message).
    parsed_dict is None if no frontmatter or parse error.
    """
    if not text.startswith("---"):
        return None, None  # No frontmatter — not an error
    end = text.find("\n---", 3)
    if end == -1:
        return None, "frontmatter 未闭合，缺少第二个 ---"
    yaml_str = text[3:end]
    try:
        import yaml as _yaml
        data = _yaml.safe_load(yaml_str)
        if not isinstance(data, dict):
            return None, "frontmatter 不是有效的 YAML 映射"
        return data, None
    except Exception as e:
        return None, f"frontmatter YAML 解析失败: {e}"


def _collect_all_files(vault_path: Path) -> set[str]:
    """Build a set of all .md filenames in the vault (for wikilink resolution)."""
    files: set[str] = set()
    for md in vault_path.rglob("*.md"):
        files.add(md.name)
        # Also add without .md for wikilink matching
        files.add(md.name[:-3] if md.name.endswith(".md") else md.name)
    return files


# ── Lint Rules ───────────────────────────────────────────────────────────────


def lint_frontmatter_invalid(vault_path: Path) -> list[dict]:
    """Rule: Check for unparseable YAML frontmatter.

    Returns list of findings: {rule, severity, file_path, message, detail}
    """
    findings: list[dict] = []
    for md in vault_path.rglob("*.md"):
        # Skip system/template dirs
        rel = md.relative_to(vault_path)
        if str(rel).startswith(("90_", "99_", ".trash", ".obsidian")):
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except Exception:
            continue
        _data, error = _parse_frontmatter(text)
        if error:
            findings.append({
                "rule": "frontmatter_invalid",
                "severity": "error",
                "file_path": str(rel),
                "message": f"[{rel}] {error}",
                "detail": error,
                "item_type": "lint_frontmatter_invalid",
            })
    return findings


def lint_frontmatter_missing_fields(vault_path: Path) -> list[dict]:
    """Rule: Check for missing required frontmatter fields."""
    findings: list[dict] = []
    for md in vault_path.rglob("*.md"):
        rel = md.relative_to(vault_path)
        rel_str = str(rel)
        # Determine expected type from parent directory
        expected_type = None
        for dir_prefix, ftype in _DIR_TYPE_MAP.items():
            if rel_str.startswith(dir_prefix + "/") or rel_str.startswith(dir_prefix + "\\"):
                expected_type = ftype
                break
        if expected_type is None:
            continue

        try:
            text = md.read_text(encoding="utf-8")
        except Exception:
            continue
        fm, error = _parse_frontmatter(text)
        if error or fm is None:
            continue  # Already caught by lint_frontmatter_invalid

        required = _REQUIRED_FIELDS.get(expected_type, set())
        for field in required:
            val = fm.get(field)
            if val is None or val == "":
                findings.append({
                    "rule": "frontmatter_missing_field",
                    "severity": "warning",
                    "file_path": str(rel),
                    "message": f"[{rel}] 缺少必填字段 '{field}'（类型: {expected_type}）",
                    "detail": f"缺少字段: {field}",
                    "item_type": "lint_frontmatter_missing",
                })
    return findings


def lint_dead_wikilinks(vault_path: Path) -> list[dict]:
    """Rule: Check for [[wikilinks]] pointing to non-existent files."""
    findings: list[dict] = []
    all_files = _collect_all_files(vault_path)
    for md in vault_path.rglob("*.md"):
        rel = md.relative_to(vault_path)
        try:
            text = md.read_text(encoding="utf-8")
        except Exception:
            continue
        for match in _WIKILINK_RE.finditer(text):
            link = match.group(1)
            if link not in all_files and f"{link}.md" not in all_files:
                findings.append({
                    "rule": "dead_wikilink",
                    "severity": "warning",
                    "file_path": str(rel),
                    "message": f"[{rel}] [[{link}]] 指向不存在的文件",
                    "detail": f"wikilink: {link}",
                    "item_type": "lint_dead_wikilink",
                })
    return findings


def lint_duplicate_reports(vault_path: Path) -> list[dict]:
    """Rule: Check for duplicate reports (same video_id or content_hash)."""
    findings: list[dict] = []
    reports_dir = vault_path / "01_Reports"
    if not reports_dir.exists():
        return findings

    seen_video_ids: dict[str, Path] = {}
    seen_hashes: dict[str, Path] = {}

    for md in sorted(reports_dir.glob("*.md")):
        rel = md.relative_to(vault_path)
        try:
            text = md.read_text(encoding="utf-8")
        except Exception:
            continue
        fm, _error = _parse_frontmatter(text)
        if fm is None:
            continue

        video_id = fm.get("video_id", "")
        content_hash = fm.get("content_hash", "")

        if video_id and video_id != "UnknownChannel":
            if video_id in seen_video_ids:
                existing = seen_video_ids[video_id].relative_to(vault_path)
                findings.append({
                    "rule": "duplicate_report",
                    "severity": "warning",
                    "file_path": str(rel),
                    "message": f"[{rel}] 与 [{existing}] 具有相同的 video_id: {video_id}",
                    "detail": f"video_id: {video_id}",
                    "item_type": "lint_duplicate_report",
                })
            else:
                seen_video_ids[video_id] = md

        if content_hash:
            if content_hash in seen_hashes:
                existing = seen_hashes[content_hash].relative_to(vault_path)
                findings.append({
                    "rule": "duplicate_report",
                    "severity": "warning",
                    "file_path": str(rel),
                    "message": f"[{rel}] 与 [{existing}] 内容哈希相同: {content_hash[:12]}",
                    "detail": f"content_hash: {content_hash}",
                    "item_type": "lint_duplicate_report",
                })
            else:
                seen_hashes[content_hash] = md

    return findings


def lint_orphan_cards(vault_path: Path) -> list[dict]:
    """Rule: Check for Topic/Company/Claim/Signal cards with no backlinks from reports.

    An "orphan" card has no report that references it by name or topic tag.
    """
    findings: list[dict] = []
    card_dirs = {
        "02_Topics": "topic",
        "03_Companies": "company",
        "06_Claims": "claim",
        "07_Signals": "signal",
    }

    # Collect all report references
    report_refs: set[str] = set()
    reports_dir = vault_path / "01_Reports"
    if reports_dir.exists():
        for md in reports_dir.glob("*.md"):
            try:
                text = md.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            # Collect normalized names mentioned in reports
            fm, _ = _parse_frontmatter(text)
            if fm:
                for key in ("topic_tags", "target_name"):
                    val = fm.get(key, "")
                    if isinstance(val, list):
                        for v in val:
                            report_refs.add(str(v).lower())
                    elif val:
                        report_refs.add(str(val).lower())

    for dir_name, _card_type in card_dirs.items():
        card_dir = vault_path / dir_name
        if not card_dir.exists():
            continue
        for md in card_dir.glob("*.md"):
            rel = md.relative_to(vault_path)
            try:
                text = md.read_text(encoding="utf-8")
            except Exception:
                continue
            fm, _ = _parse_frontmatter(text)
            if fm is None:
                continue
            # Check if any report references this card
            card_name = (
                fm.get("name", "")
                or fm.get("title", "")
                or md.stem
            )
            if card_name.lower() not in report_refs:
                # Also check wikilink references
                wikilink_ref = f"[[{card_name}]]".lower()
                found_ref = False
                if reports_dir.exists():
                    for rmd in reports_dir.glob("*.md"):
                        try:
                            rtext = rmd.read_text(encoding="utf-8", errors="replace").lower()
                        except Exception:
                            continue
                        if wikilink_ref in rtext or card_name.lower() in rtext:
                            found_ref = True
                            break
                if not found_ref:
                    findings.append({
                        "rule": "orphan_card",
                        "severity": "info",
                        "file_path": str(rel),
                        "message": f"[{rel}] 卡片 '{card_name}' 没有关联报告引用",
                        "detail": f"card_name: {card_name}",
                        "item_type": "lint_orphan_card",
                    })
    return findings


# ── Runner ───────────────────────────────────────────────────────────────────


def run_vault_lint(
    vault_path: Path,
    rules: list[str] | None = None,
    exclude: list[str] | None = None,
) -> dict[str, Any]:
    """Run vault lint and return structured results.

    Args:
        vault_path: Path to the Obsidian vault root.
        rules: Optional list of rule names to run. None = all.
        exclude: Optional list of rule names to skip.

    Returns:
        {run_id, vault_path, total_findings, findings: list[dict], rule_counts: dict}
    """
    import uuid

    all_rules: dict[str, Any] = {
        "frontmatter_invalid": lint_frontmatter_invalid,
        "frontmatter_missing": lint_frontmatter_missing_fields,
        "dead_wikilink": lint_dead_wikilinks,
        "duplicate_report": lint_duplicate_reports,
        "orphan_card": lint_orphan_cards,
    }

    # Filter rules
    if rules:
        selected = {k: v for k, v in all_rules.items() if k in rules}
    else:
        selected = dict(all_rules)
    if exclude:
        for ex in exclude:
            selected.pop(ex, None)

    all_findings: list[dict] = []
    rule_counts: dict[str, int] = {}

    for rule_name, rule_fn in selected.items():
        try:
            findings = rule_fn(vault_path)
            all_findings.extend(findings)
            rule_counts[rule_name] = len(findings)
        except Exception as e:
            logger.error("Lint rule '%s' failed: %s", rule_name, e)
            rule_counts[rule_name] = -1  # Error marker

    return {
        "run_id": uuid.uuid4().hex[:12],
        "vault_path": str(vault_path),
        "total_findings": len(all_findings),
        "findings": all_findings,
        "rule_counts": rule_counts,
    }


def write_lint_to_review(
    findings: list[dict],
    session=None,
) -> int:
    """Write lint findings to review_items table. Returns count created."""
    from podcast_research.sources.review_items import ReviewItemManager
    return ReviewItemManager.create_from_lint_findings(findings, session=session)
