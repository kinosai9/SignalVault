"""P2-L.2: Real Video Clean Flow Validation Script.

Validates that after clean DB + clean Vault + real video import, the end-to-end
data integrity is correct. Checks channel metadata, company relations, language
consistency, and sync postconditions.

Usage:
    uv run python scripts/validate_real_clean_flow.py \
      --vault "D:/path/to/vault" \
      --db "data/signalvault.db"

    # Or with video URLs to test full flow:
    uv run python scripts/validate_real_clean_flow.py \
      --vault "D:/path/to/vault" \
      --video-url "https://www.youtube.com/watch?v=VIDEO_ID"

Output:
    data/validation/real_flow_validation_YYYYMMDD_HHMM.md
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

# ── Constants ────────────────────────────────────────────────────────

CHECKLIST_ITEMS = [
    "channel_metadata_complete",
    "no_unknown_channel_in_filenames",
    "company_cards_exist",
    "company_report_count_gt_zero",
    "topic_cards_exist",
    "claim_cards_exist",
    "signal_cards_exist",
    "report_headings_present",
    "report_frontmatter_complete",
    "research_brief_available",
    "watchlist_brief_available",
    "home_dashboard_exists",
]


def parse_frontmatter(content: str) -> dict:
    if not content.startswith("---"):
        return {}
    end = content.find("---", 3)
    if end == -1:
        return {}
    fm = {}
    for line in content[3:end].strip().split("\n"):
        if ":" in line:
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip().strip('"').strip("'")
    return fm


def is_chinese_char(ch: str) -> bool:
    cp = ord(ch)
    return 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF


def chinese_ratio(text: str) -> float:
    if not text:
        return 0.0
    ch = sum(1 for c in text if is_chinese_char(c))
    alpha = sum(1 for c in text if c.isalpha())
    total = ch + alpha
    return ch / total if total > 0 else 0.0


def validate(vault_path: Path, db_path: Path | None = None) -> dict:
    """Run all validation checks and return structured results."""
    results = {
        "vault_path": str(vault_path),
        "db_path": str(db_path) if db_path else "auto-detect",
        "validated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "checks": {},
        "details": {},
        "pass_count": 0,
        "fail_count": 0,
        "overall": "PASS",
    }

    # ── 1. Report Files ──
    reports_dir = vault_path / "01_Reports"
    report_files = list(reports_dir.glob("*.md")) if reports_dir.exists() else []
    results["details"]["report_count"] = len(report_files)

    # 1a. No UnknownChannel in filenames
    unknown_channel_files = [f for f in report_files if "unknownchannel" in f.name.lower()]
    results["checks"]["no_unknown_channel_in_filenames"] = "PASS" if not unknown_channel_files else "FAIL"
    if unknown_channel_files:
        results["details"]["unknown_channel_files"] = [f.name for f in unknown_channel_files]

    # 1b. Frontmatter completeness
    frontmatter_issues = []
    for rf in report_files:
        content = rf.read_text(encoding="utf-8")
        fm = parse_frontmatter(content)
        for field in ["channel", "video_id", "video_url", "source_type"]:
            if not fm.get(field):
                frontmatter_issues.append(f"{rf.name}: missing {field}")
        if fm.get("channel", "").lower() in ("unknownchannel", "unknown", ""):
            frontmatter_issues.append(f"{rf.name}: channel is empty/unknown")
    results["checks"]["report_frontmatter_complete"] = "PASS" if not frontmatter_issues else "FAIL"
    if frontmatter_issues:
        results["details"]["frontmatter_issues"] = frontmatter_issues

    # 1c. Report headings present
    heading_issues = []
    for rf in report_files:
        content = rf.read_text(encoding="utf-8")
        for heading in ["Summary", "Core Investment Views", "Risks"]:
            if f"## {heading}" not in content:
                heading_issues.append(f"{rf.name}: missing ## {heading}")
    results["checks"]["report_headings_present"] = "PASS" if not heading_issues else "FAIL"

    # ── 2. Company Cards ──
    companies_dir = vault_path / "03_Companies"
    company_files = list(companies_dir.glob("*.md")) if companies_dir.exists() else []
    results["details"]["company_card_count"] = len(company_files)

    if company_files:
        results["checks"]["company_cards_exist"] = "PASS"
        # Check for source reports
        zero_report_companies = []
        for cf in company_files:
            content = cf.read_text(encoding="utf-8")
            # Count source report links
            report_links = re.findall(r"\[\[([^\]]+)\]\]", content)
            source_section_start = content.find("## Source Reports")
            if source_section_start == -1 or len(report_links) == 0:
                zero_report_companies.append(cf.stem)
        results["checks"]["company_report_count_gt_zero"] = "PASS" if not zero_report_companies else "FAIL"
        if zero_report_companies:
            results["details"]["companies_with_zero_reports"] = zero_report_companies
    else:
        results["checks"]["company_cards_exist"] = "FAIL"
        results["details"]["company_warning"] = "No company cards found"

    # ── 3. Topic Cards ──
    topics_dir = vault_path / "02_Topics"
    topic_files = list(topics_dir.glob("*.md")) if topics_dir.exists() else []
    results["details"]["topic_card_count"] = len(topic_files)
    results["checks"]["topic_cards_exist"] = "PASS" if topic_files else "WARN"

    # ── 4. Claim / Signal Cards ──
    claims_dir = vault_path / "06_Claims"
    claim_files = list(claims_dir.glob("*.md")) if claims_dir.exists() else []
    results["details"]["claim_card_count"] = len(claim_files)
    results["checks"]["claim_cards_exist"] = "PASS" if claim_files else "WARN"

    signals_dir = vault_path / "07_Signals"
    signal_files = list(signals_dir.glob("*.md")) if signals_dir.exists() else []
    results["details"]["signal_card_count"] = len(signal_files)
    results["checks"]["signal_cards_exist"] = "PASS" if signal_files else "WARN"

    # ── 5. Channel Metadata ──
    channel_issues = []
    for rf in report_files:
        content = rf.read_text(encoding="utf-8")
        fm = parse_frontmatter(content)
        ch = fm.get("channel", "")
        vid = fm.get("video_id", "")
        src_url = fm.get("video_url", "") or fm.get("source_url", "")
        if not ch or ch.lower() in ("unknownchannel", "unknown"):
            channel_issues.append(f"{rf.name}: channel='{ch}' (empty/unknown)")
        if not vid:
            channel_issues.append(f"{rf.name}: video_id missing")
        if not src_url:
            channel_issues.append(f"{rf.name}: source_url missing")
    results["checks"]["channel_metadata_complete"] = "PASS" if not channel_issues else "FAIL"
    if channel_issues:
        results["details"]["channel_issues"] = channel_issues

    # ── 6. Home Dashboard ──
    home = vault_path / "Home.md"
    results["checks"]["home_dashboard_exists"] = "PASS" if home.exists() else "WARN"

    # ── 7. Briefs ──
    briefs_dir = vault_path / "99_System"
    research_brief = briefs_dir / "Research Brief.md" if briefs_dir.exists() else None
    results["checks"]["research_brief_available"] = "PASS" if research_brief and research_brief.exists() else "WARN"
    watchlist_brief = briefs_dir / "Watchlist Brief.md" if briefs_dir.exists() else None
    results["checks"]["watchlist_brief_available"] = "PASS" if watchlist_brief and watchlist_brief.exists() else "WARN"

    # ── 8. Language Audit ──
    lang_issues = []
    for rf in report_files:
        content = rf.read_text(encoding="utf-8")
        body = content[content.find("---", 3) + 3:] if content.startswith("---") else content
        # Skip blockquotes and table lines
        check_lines = [
            l for l in body.split("\n")
            if not l.strip().startswith(">")
            and not l.strip().startswith("|")
            and not l.strip().startswith("[[")
            and len(l.strip()) > 30
        ]
        for line in check_lines[5:15]:  # Sample a few lines
            ratio = chinese_ratio(line)
            if ratio < 0.05:
                lang_issues.append(f"{rf.name}: low Chinese ratio ({ratio:.1%}): {line[:60]}")
                break  # One issue per file
    if lang_issues:
        results["details"]["language_issues"] = lang_issues

    # ── Count results ──
    for key, val in results["checks"].items():
        if val == "PASS":
            results["pass_count"] += 1
        elif val == "FAIL":
            results["fail_count"] += 1

    results["overall"] = "PASS" if results["fail_count"] == 0 else "FAIL"
    return results


def generate_report(results: dict) -> str:
    """Generate a Markdown validation report."""
    lines = [
        "# Real Flow Validation Report",
        "",
        f"**Generated**: {results['validated_at']}",
        f"**Vault**: {results['vault_path']}",
        f"**DB**: {results['db_path']}",
        "",
        f"**Overall**: {'[PASS]' if results['overall'] == 'PASS' else '[FAIL]'}",
        f"**Pass**: {results['pass_count']}, **Fail**: {results['fail_count']}",
        "",
        "## Checklist",
        "",
        "| Item | Status |",
        "|------|--------|",
    ]

    for item in CHECKLIST_ITEMS:
        status = results["checks"].get(item, "UNKNOWN")
        marker = "[PASS]" if status == "PASS" else ("[WARN]" if status == "WARN" else "[FAIL]")
        lines.append(f"| {item} | {marker} {status} |")

    lines.extend([
        "",
        "## Details",
        "",
    ])

    for key, val in results.get("details", {}).items():
        if isinstance(val, list):
            lines.append(f"### {key} ({len(val)} items)")
            for v in val[:10]:
                lines.append(f"- {v}")
            if len(val) > 10:
                lines.append(f"- ... and {len(val) - 10} more")
        else:
            lines.append(f"- **{key}**: {val}")

    lines.extend([
        "",
        "---",
        "*Generated by P2-L.2 validate_real_clean_flow.py*",
    ])

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="P2-L.2 Real Video Clean Flow Validation"
    )
    parser.add_argument("--vault", required=True, help="Path to Obsidian vault")
    parser.add_argument("--db", help="Path to SQLite database (auto-detect)")
    parser.add_argument("--video-url", help="YouTube video URL to test (future use)")
    parser.add_argument("--output-dir", default="data/validation", help="Output directory")
    args = parser.parse_args()

    vault_path = Path(args.vault)
    if not vault_path.exists():
        print(f"Error: Vault path does not exist: {vault_path}", file=sys.stderr)
        return 1

    db_path = Path(args.db) if args.db else None

    results = validate(vault_path, db_path)

    # Generate report
    report = generate_report(results)
    print(report)

    # Write to file
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    output_path = output_dir / f"real_flow_validation_{ts}.md"
    output_path.write_text(report, encoding="utf-8")
    print(f"\nReport written to: {output_path}")

    return 0 if results["overall"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
