"""P2-L.2 Clean Vault Diagnostic Script.

Scans Obsidian vault + SQLite DB for data integrity across channel metadata,
company relations, language consistency, and sync postconditions.

Usage:
    uv run python scripts/diagnose_clean_vault.py --vault "D:/path/to/vault"
    uv run python scripts/diagnose_clean_vault.py --vault "D:/path/to/vault" --db "data/signalvault.db"
    uv run python scripts/diagnose_clean_vault.py --vault "D:/path/to/vault" --json  # machine-readable output
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

# ── Constants ────────────────────────────────────────────────────────

REQUIRED_FRONTMATTER_FIELDS = [
    "title", "channel", "video_id", "video_url", "published_at",
    "language", "prompt_version", "source_type",
]

CHINESE_SECTION_HEADINGS = [
    "Summary", "Source", "Core Investment Views", "Tech / Industry Insights",
    "Risks", "Tracking Signals", "Entities", "Source Quotes",
    "Related Links", "Notes",
]

KNOWN_NON_CHANNEL = {"unknownchannel", "unknown", "none", "", "youtube"}


# ── Helpers ───────────────────────────────────────────────────────────

def parse_frontmatter(content: str) -> dict:
    """Parse YAML frontmatter from markdown content."""
    if not content.startswith("---"):
        return {}
    end_idx = content.find("---", 3)
    if end_idx == -1:
        return {}

    fm_text = content[3:end_idx].strip()
    result = {}
    for line in fm_text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        colon_idx = line.find(":")
        if colon_idx <= 0:
            continue
        key = line[:colon_idx].strip()
        val = line[colon_idx + 1:].strip()
        if val.startswith('"') and val.endswith('"') or val.startswith("'") and val.endswith("'"):
            val = val[1:-1]
        if key:
            result[key] = val
    return result


def is_chinese_char(ch: str) -> bool:
    """Check if a character is a CJK unified ideograph."""
    cp = ord(ch)
    return (
        0x4E00 <= cp <= 0x9FFF
        or 0x3400 <= cp <= 0x4DBF
        or 0xF900 <= cp <= 0xFAFF
    )


def is_chinese_text(text: str, min_ratio: float = 0.1) -> bool:
    """Check if text contains a minimum ratio of Chinese characters."""
    if not text:
        return False
    chinese_chars = sum(1 for ch in text if is_chinese_char(ch))
    alpha_chars = sum(1 for ch in text if ch.isalpha())
    if alpha_chars == 0 and chinese_chars == 0:
        return False
    return (chinese_chars / max(alpha_chars, 1)) >= min_ratio


def chinese_char_ratio(text: str) -> float:
    """Calculate ratio of Chinese characters in text."""
    if not text:
        return 0.0
    chinese = sum(1 for ch in text if is_chinese_char(ch))
    alpha = sum(1 for ch in text if ch.isalpha())
    total = chinese + alpha
    return chinese / total if total > 0 else 0.0


# ── 1. Report Metadata Audit ──────────────────────────────────────────

def audit_report_metadata(vault_path: Path) -> list[dict]:
    """Scan 01_Reports/*.md and check frontmatter completeness."""
    issues = []
    reports_dir = vault_path / "01_Reports"
    if not reports_dir.exists():
        print(f"  ⚠ 01_Reports/ directory not found at {reports_dir}")
        return issues

    for fpath in sorted(reports_dir.glob("*.md")):
        try:
            content = fpath.read_text(encoding="utf-8")
        except Exception as e:
            issues.append({
                "file": fpath.name, "type": "unreadable",
                "detail": str(e),
            })
            continue

        fm = parse_frontmatter(content)
        filename = fpath.name

        # Check required fields
        for field in REQUIRED_FRONTMATTER_FIELDS:
            if not fm.get(field):
                issues.append({
                    "file": filename,
                    "type": f"missing_{field}",
                    "detail": f"Frontmatter missing '{field}'",
                })

        # Check for UnknownChannel
        channel = fm.get("channel", "").strip()
        if channel and channel.lower() in KNOWN_NON_CHANNEL:
            issues.append({
                "file": filename,
                "type": "unknown_channel",
                "detail": f"channel is '{channel}'",
            })

        # Check filename for UnknownChannel
        if "unknownchannel" in filename.lower():
            issues.append({
                "file": filename,
                "type": "filename_unknown_channel",
                "detail": "Filename contains UnknownChannel",
            })

        # Check source_url
        source_url = fm.get("video_url", "") or fm.get("source_url", "")
        if source_url and "youtube" not in source_url.lower() and "youtu.be" not in source_url.lower():
            if source_url.startswith("http"):
                pass  # Could be another valid source
            else:
                issues.append({
                    "file": filename,
                    "type": "invalid_source_url",
                    "detail": f"source_url='{source_url}'",
                })

        # Check video_id
        video_id = fm.get("video_id", "").strip()
        if not video_id or video_id == "unknown":
            issues.append({
                "file": filename,
                "type": "missing_video_id",
                "detail": f"video_id='{video_id}'",
            })

    return issues


# ── 2. DB Metadata Audit ──────────────────────────────────────────────

def _open_db(db_path: Path):
    """Open SQLite DB connection."""
    import sqlite3
    return sqlite3.connect(str(db_path))


def audit_db_metadata(vault_path: Path, db_path: Path | None = None) -> list[dict]:
    """Check SQLite metadata completeness."""
    import sqlite3

    issues = []

    # Find DB path
    if db_path is None:
        # Try default locations
        for candidate in [
            Path("data/signalvault.db"),
            Path("D:/claude/xyz_analysis/data/signalvault.db"),
        ]:
            if candidate.exists():
                db_path = candidate
                break
        if db_path is None:
            issues.append({
                "file": "N/A", "type": "db_not_found",
                "detail": "SQLite DB not found at default paths",
            })
            return issues

    conn = _open_db(db_path)
    try:
        cur = conn.cursor()

        # Check episodes table
        try:
            cur.execute("SELECT id, title, source_url, video_id, language FROM episodes")
            episodes = cur.fetchall()
            print(f"  Episodes: {len(episodes)} rows")
            for eid, title, source_url, video_id, language in episodes:
                e_issues = []
                if not title:
                    e_issues.append("missing_title")
                if not source_url:
                    e_issues.append("missing_source_url")
                if not video_id:
                    e_issues.append("missing_video_id")
                if not language:
                    e_issues.append("missing_language")
                for ei in e_issues:
                    issues.append({
                        "file": f"episode #{eid}",
                        "type": f"episode_{ei}",
                        "detail": f"Episode {eid}: {ei}",
                    })
        except sqlite3.OperationalError:
            pass  # Table might not exist

        # Check reports table
        try:
            cur.execute("SELECT id, episode_id, extraction_json, prompt_version FROM reports")
            reports = cur.fetchall()
            print(f"  Reports: {len(reports)} rows")
            for rid, eid, ext_json, pv in reports:
                r_issues = []
                if not pv:
                    r_issues.append("missing_prompt_version")

                # Parse extraction_json
                try:
                    extraction = json.loads(ext_json) if ext_json else {}
                except (json.JSONDecodeError, TypeError):
                    extraction = {}

                source_info = extraction.get("source_info", {}) or {}
                si_channel = source_info.get("channel_name", "")

                if not si_channel:
                    r_issues.append("extraction_source_info_missing_channel")
                if not source_info.get("source_url"):
                    r_issues.append("extraction_source_info_missing_url")
                if not source_info.get("video_id"):
                    r_issues.append("extraction_source_info_missing_video_id")
                if not source_info.get("language"):
                    r_issues.append("extraction_source_info_missing_language")

                # Check for views/entities
                views = extraction.get("investment_views", []) or []
                entities = extraction.get("mentioned_entities", []) or []
                if not views:
                    r_issues.append("extraction_no_investment_views")
                if not entities:
                    r_issues.append("extraction_no_entities")

                for ri in r_issues:
                    issues.append({
                        "file": f"report #{rid}",
                        "type": f"report_{ri}",
                        "detail": f"Report {rid} (episode {eid}): {ri}",
                    })
        except sqlite3.OperationalError:
            pass

        # Check channel_videos / channels tables
        try:
            cur.execute("SELECT COUNT(*) FROM channels")
            ch_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM channel_videos")
            cv_count = cur.fetchone()[0]
            print(f"  Channels: {ch_count}, Channel Videos: {cv_count}")

            if cv_count == 0:
                issues.append({
                    "file": "DB",
                    "type": "empty_channel_videos",
                    "detail": "channel_videos table is empty — channel metadata backfill will fail",
                })

            # Check if episodes' video_ids exist in channel_videos
            cur.execute("SELECT DISTINCT video_id FROM episodes WHERE video_id != ''")
            episode_vids = set(row[0] for row in cur.fetchall())
            cur.execute("SELECT DISTINCT video_id FROM channel_videos")
            cv_vids = set(row[0] for row in cur.fetchall())

            unmatched = episode_vids - cv_vids
            if unmatched:
                for vid in unmatched:
                    issues.append({
                        "file": f"video {vid}",
                        "type": "video_not_in_channel_videos",
                        "detail": f"Video {vid} exists in episodes but not in channel_videos",
                    })
        except sqlite3.OperationalError:
            pass

    finally:
        conn.close()

    return issues


# ── 3. Entity / Company Audit ─────────────────────────────────────────

def audit_companies(vault_path: Path, db_path: Path | None = None) -> dict:
    """Check company cards, claim links, signal links, scanner counts."""

    results = {
        "companies": [],
        "summary": {
            "total_companies": 0,
            "total_claims": 0,
            "total_signals": 0,
            "companies_with_zero_claims": 0,
            "companies_with_zero_signals": 0,
            "companies_with_zero_reports": 0,
        },
    }

    # Load DB data
    db_companies_from_extraction = set()
    db_entities_from_extraction = set()

    if db_path is None:
        for candidate in [
            Path("data/signalvault.db"),
            Path("D:/claude/xyz_analysis/data/signalvault.db"),
        ]:
            if candidate.exists():
                db_path = candidate
                break

    if db_path and db_path.exists():
        conn = _open_db(db_path)
        try:
            cur = conn.cursor()
            cur.execute("SELECT extraction_json FROM reports")
            for (ext_json,) in cur.fetchall():
                try:
                    ext = json.loads(ext_json) if ext_json else {}
                except (json.JSONDecodeError, TypeError):
                    continue
                for v in ext.get("investment_views", []) or []:
                    t = v.get("target_name", "")
                    if t:
                        db_companies_from_extraction.add(t)
                for e in ext.get("mentioned_entities", []) or []:
                    et = e.get("entity_type", "")
                    name = e.get("normalized_name") or e.get("name", "")
                    if et in ("company", "startup", "big_tech") and name:
                        db_entities_from_extraction.add(name)
        finally:
            conn.close()

    # Load claims/signals for related_companies
    claim_related = {}  # card_id → related_companies list
    signal_related = {}

    claims_dir = vault_path / "06_Claims"
    if claims_dir.exists():
        for fp in sorted(claims_dir.glob("*.md")):
            try:
                content = fp.read_text(encoding="utf-8")
            except Exception:
                continue
            fm = parse_frontmatter(content)
            rc = fm.get("related_companies", [])
            if isinstance(rc, list):
                claim_related[fp.stem] = rc
            elif isinstance(rc, str) and rc:
                claim_related[fp.stem] = [rc]

    signals_dir = vault_path / "07_Signals"
    if signals_dir.exists():
        for fp in sorted(signals_dir.glob("*.md")):
            try:
                content = fp.read_text(encoding="utf-8")
            except Exception:
                continue
            fm = parse_frontmatter(content)
            rc = fm.get("related_companies", [])
            if isinstance(rc, list):
                signal_related[fp.stem] = rc
            elif isinstance(rc, str) and rc:
                signal_related[fp.stem] = [rc]

    # Scan company cards
    companies_dir = vault_path / "03_Companies"
    if not companies_dir.exists():
        return results

    for fp in sorted(companies_dir.glob("*.md")):
        try:
            content = fp.read_text(encoding="utf-8")
        except Exception:
            continue

        company_name = fp.stem
        fm = parse_frontmatter(content)

        # Count source reports from body
        source_reports = []
        in_section = False
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped == "## Source Reports":
                in_section = True
                continue
            if in_section and stripped.startswith("## "):
                break
            if in_section and "[[" in stripped:
                match = re.search(r"\[\[([^\]]+)\]\]", stripped)
                if match:
                    source_reports.append(match.group(1))

        # Count claims referencing this company
        claim_count = sum(
            1 for rel in claim_related.values()
            if company_name in rel
        )
        signal_count = sum(
            1 for rel in signal_related.values()
            if company_name in rel
        )

        # Check if company mentioned in DB extraction
        in_db = (
            company_name in db_companies_from_extraction
            or company_name in db_entities_from_extraction
            or any(
                company_name.lower() in db_name.lower()
                for db_name in db_companies_from_extraction
            )
            or any(
                company_name.lower() in db_name.lower()
                for db_name in db_entities_from_extraction
            )
        )

        entry = {
            "company": company_name,
            "card_exists": True,
            "report_mentions": len(source_reports),
            "claim_links": claim_count,
            "signal_links": signal_count,
            "in_db_extraction": in_db,
        }

        # Flag issues
        entry["issues"] = []
        if len(source_reports) == 0:
            entry["issues"].append("zero_reports")
        if in_db and claim_count == 0:
            entry["issues"].append("claimed_in_db_but_no_claim_links")
        if len(source_reports) > 0 and claim_count == 0:
            entry["issues"].append("has_reports_but_no_claims")

        results["companies"].append(entry)

    # Summary
    results["summary"]["total_companies"] = len(results["companies"])
    results["summary"]["total_claims"] = len(claim_related)
    results["summary"]["total_signals"] = len(signal_related)
    results["summary"]["companies_with_zero_claims"] = sum(
        1 for c in results["companies"] if c["claim_links"] == 0
    )
    results["summary"]["companies_with_zero_signals"] = sum(
        1 for c in results["companies"] if c["signal_links"] == 0
    )
    results["summary"]["companies_with_zero_reports"] = sum(
        1 for c in results["companies"] if c["report_mentions"] == 0
    )

    return results


# ── 4. Language Audit ─────────────────────────────────────────────────

def audit_language(vault_path: Path) -> list[dict]:
    """Check language consistency in reports."""
    issues = []
    reports_dir = vault_path / "01_Reports"
    if not reports_dir.exists():
        return issues

    for fpath in sorted(reports_dir.glob("*.md")):
        try:
            content = fpath.read_text(encoding="utf-8")
        except Exception:
            continue

        filename = fpath.name

        # Check overall Chinese ratio
        body = content
        if body.startswith("---"):
            end_idx = body.find("---", 3)
            if end_idx != -1:
                body = body[end_idx + 3:]

        overall_ratio = chinese_char_ratio(body)

        # Extract sections
        sections = {}
        current_section = "header"
        current_text = []
        for line in body.split("\n"):
            if line.strip().startswith("## "):
                section_name = line.strip()[3:].strip()
                if current_text:
                    sections[current_section] = "\n".join(current_text)
                current_section = section_name
                current_text = []
            else:
                current_text.append(line)
        if current_text:
            sections[current_section] = "\n".join(current_text)

        # Check headings
        english_headings = []
        for heading in [
            "Summary", "Source", "Core Investment Views",
            "Tech / Industry Insights", "Risks", "Tracking Signals",
            "Entities", "Source Quotes", "Related Links", "Notes",
        ]:
            if heading in body:
                english_headings.append(heading)

        # Note: the current template uses English section headings
        # This is by design (the report template), so only flag truly anomalous ones

        # Check if analysis body paragraphs are too English-heavy
        for section_name, section_text in sections.items():
            if section_name in ("Source Quotes", "header"):
                continue  # Source quotes can be English

            lines = section_text.strip().split("\n")
            for i, line in enumerate(lines):
                stripped = line.strip()
                if len(stripped) < 30:
                    continue
                if stripped.startswith("|") or stripped.startswith("- "):
                    continue  # Table or list

                ratio = chinese_char_ratio(stripped)
                # If a long paragraph is < 10% Chinese, flag it
                if len(stripped) > 50 and ratio < 0.05 and not stripped.startswith(">"):
                    issues.append({
                        "file": filename,
                        "type": "english_paragraph",
                        "detail": f"Section '{section_name}': line has {ratio:.1%} Chinese",
                        "preview": stripped[:100],
                    })

        # Check merged long video specific: look for "chunk" or "Chunk Summary" markers
        if "chunk" in body.lower():
            issues.append({
                "file": filename,
                "type": "chunk_summary_in_body",
                "detail": "Chunk markers found in report body",
            })

    return issues


# ── 5. Sync Postconditions Audit ─────────────────────────────────────

def audit_sync_postconditions(vault_path: Path) -> dict:
    """Check that sync steps produced expected outputs."""
    results = {
        "report_files_exist": False,
        "report_count": 0,
        "channel_cards_exist": False,
        "channel_card_count": 0,
        "topic_cards_exist": False,
        "topic_card_count": 0,
        "company_cards_exist": False,
        "company_card_count": 0,
        "claim_cards_exist": False,
        "claim_card_count": 0,
        "signal_cards_exist": False,
        "signal_card_count": 0,
        "system_files_exist": False,
        "home_dashboard_exists": False,
        "knowledge_map_exists": False,
        "issues": [],
    }

    reports_dir = vault_path / "01_Reports"
    if reports_dir.exists():
        reports = list(reports_dir.glob("*.md"))
        results["report_count"] = len(reports)
        results["report_files_exist"] = len(reports) > 0
        if len(reports) == 0:
            results["issues"].append("no_report_files")

    topics_dir = vault_path / "02_Topics"
    if topics_dir.exists():
        topics = list(topics_dir.glob("*.md"))
        results["topic_card_count"] = len(topics)
        results["topic_cards_exist"] = len(topics) > 0

    companies_dir = vault_path / "03_Companies"
    if companies_dir.exists():
        companies = list(companies_dir.glob("*.md"))
        results["company_card_count"] = len(companies)
        results["company_cards_exist"] = len(companies) > 0

    channels_dir = vault_path / "05_Channels"
    if channels_dir.exists():
        channels = list(channels_dir.glob("*.md"))
        results["channel_card_count"] = len(channels)
        results["channel_cards_exist"] = len(channels) > 0

    claims_dir = vault_path / "06_Claims"
    if claims_dir.exists():
        claims = list(claims_dir.glob("*.md"))
        results["claim_card_count"] = len(claims)
        results["claim_cards_exist"] = len(claims) > 0

    signals_dir = vault_path / "07_Signals"
    if signals_dir.exists():
        signals = list(signals_dir.glob("*.md"))
        results["signal_card_count"] = len(signals)
        results["signal_cards_exist"] = len(signals) > 0

    system_dir = vault_path / "99_System"
    if system_dir.exists():
        sys_files = list(system_dir.glob("*.md"))
        results["system_files_exist"] = len(sys_files) > 0

    # Check Home.md and Knowledge Map
    home = vault_path / "Home.md"
    results["home_dashboard_exists"] = home.exists()
    if not home.exists():
        results["issues"].append("home_dashboard_missing")

    km = vault_path / "Knowledge Map.md"
    results["knowledge_map_exists"] = km.exists()

    # Check if companies have empty source_reports despite having report files
    if results["report_files_exist"] and results["company_cards_exist"]:
        company_audit = audit_companies(vault_path)
        all_zero = all(c["report_mentions"] == 0 for c in company_audit["companies"])
        if all_zero and company_audit["companies"]:
            results["issues"].append("all_company_source_reports_zero")

    return results


# ── Main ──────────────────────────────────────────────────────────────

def run_diagnostic(vault_path: Path, db_path: Path | None = None) -> dict:
    """Run all diagnostic checks."""
    print("=" * 60)
    print("P2-L.2 Clean Vault Diagnostic")
    print("=" * 60)
    print(f"  Vault: {vault_path}")
    print(f"  DB:    {db_path or '(auto-detect)'}")
    print(f"  Time:  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # 1. Report metadata audit
    print("--- 1. Report Metadata Audit ---")
    report_issues = audit_report_metadata(vault_path)
    if report_issues:
        print(f"  Issues found: {len(report_issues)}")
        for issue in report_issues:
            print(f"    [{issue['type']}] {issue['file']}: {issue['detail']}")
    else:
        print("  [PASS] No issues found")
    print()

    # 2. DB metadata audit
    print("--- 2. DB Metadata Audit ---")
    db_issues = audit_db_metadata(vault_path, db_path)
    if db_issues:
        print(f"  Issues found: {len(db_issues)}")
        for issue in db_issues:
            print(f"    [{issue['type']}] {issue['file']}: {issue['detail']}")
    else:
        print("  [PASS] No issues found")
    print()

    # 3. Company audit
    print("--- 3. Entity / Company Audit ---")
    company_results = audit_companies(vault_path, db_path)
    summary = company_results["summary"]
    print(f"  Companies: {summary['total_companies']}")
    print(f"  Claims: {summary['total_claims']}, Signals: {summary['total_signals']}")
    print(f"  Companies with 0 claims: {summary['companies_with_zero_claims']}")
    print(f"  Companies with 0 signals: {summary['companies_with_zero_signals']}")
    print(f"  Companies with 0 reports: {summary['companies_with_zero_reports']}")
    # Show companies with issues
    companies_with_issues = [
        c for c in company_results["companies"] if c.get("issues")
    ]
    if companies_with_issues:
        print(f"  Companies with issues: {len(companies_with_issues)}")
        for c in companies_with_issues[:20]:  # Show first 20
            print(f"    {c['company']}: reports={c['report_mentions']} "
                  f"claims={c['claim_links']} signals={c['signal_links']} "
                  f"in_db={c['in_db_extraction']} issues={c['issues']}")
        if len(companies_with_issues) > 20:
            print(f"    ... and {len(companies_with_issues) - 20} more")
    print()

    # 4. Language audit
    print("--- 4. Language Audit ---")
    lang_issues = audit_language(vault_path)
    if lang_issues:
        print(f"  Issues found: {len(lang_issues)}")
        for issue in lang_issues:
            preview = issue.get("preview", "")[:80]
            print(f"    [{issue['type']}] {issue['file']}: {issue['detail']}")
            if preview:
                print(f"      Preview: {preview}")
    else:
        print("  [PASS] No issues found")
    print()

    # 5. Sync postconditions
    print("--- 5. Sync Postconditions ---")
    sync_results = audit_sync_postconditions(vault_path)
    for key, val in sync_results.items():
        if key == "issues":
            continue
        status = "✅" if val else "❌"
        status_str = "PASS" if val else "FAIL"
    print(f"  [{status_str}] {key}: {val}")
    if sync_results["issues"]:
        print("  Issues:")
        for issue in sync_results["issues"]:
            print(f"    ❌ {issue}")
    print()

    # Overall verdict
    total_issues = (
        len(report_issues)
        + len(db_issues)
        + len(lang_issues)
        + len(sync_results["issues"])
        + sum(len(c.get("issues", [])) for c in company_results["companies"])
    )
    print("=" * 60)
    if total_issues == 0:
        print("[PASS] All checks passed")
    else:
        print(f"[FAIL] Total issues found: {total_issues}")
        print()
        print("  Categories:")
        print(f"    Report metadata: {len(report_issues)}")
        print(f"    DB metadata:     {len(db_issues)}")
        print(f"    Company/entity:  {sum(len(c.get('issues', [])) for c in company_results['companies'])}")
        print(f"    Language:        {len(lang_issues)}")
        print(f"    Sync postcond:   {len(sync_results['issues'])}")
    print("=" * 60)

    return {
        "report_issues": report_issues,
        "db_issues": db_issues,
        "company_results": company_results,
        "lang_issues": lang_issues,
        "sync_results": sync_results,
        "total_issues": total_issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="P2-L.2 Clean Vault Diagnostic",
    )
    parser.add_argument("--vault", required=True, help="Path to Obsidian vault")
    parser.add_argument("--db", help="Path to SQLite database (auto-detect if omitted)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    vault_path = Path(args.vault)
    if not vault_path.exists():
        print(f"Error: Vault path does not exist: {vault_path}", file=sys.stderr)
        return 1

    db_path = Path(args.db) if args.db else None
    if db_path and not db_path.exists():
        print(f"Error: DB path does not exist: {db_path}", file=sys.stderr)
        return 1

    results = run_diagnostic(vault_path, db_path)

    if args.json:
        # Convert Path objects to strings for JSON serialization
        print(json.dumps(results, ensure_ascii=False, indent=2, default=str))

    return 0 if results["total_issues"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
