#!/usr/bin/env python
"""P2-N.3: Run knowledge graph quality audit.

Usage:
    python scripts/audit_knowledge_graph.py --db data/signalvault.db --vault "<vault_path>" --output data/validation
"""

import argparse
import sys
from pathlib import Path

# Ensure src is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from signalvault.workspace.quality_audit import (
    export_audit_json,
    export_audit_markdown,
    run_quality_audit,
)


def main():
    parser = argparse.ArgumentParser(description="Knowledge Graph Quality Audit")
    parser.add_argument("--db", default="data/signalvault.db", help="Path to SQLite DB")
    parser.add_argument("--vault", default=None, help="Path to Obsidian vault (optional)")
    parser.add_argument("--output", default="data/validation", help="Output directory")
    args = parser.parse_args()

    db_path = args.db
    vault_path = args.vault
    output_dir = Path(args.output)

    print(f"Running audit: db={db_path}, vault={vault_path}")
    result = run_quality_audit(db_path=db_path, vault_path=vault_path)

    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M")

    json_path = output_dir / f"knowledge_quality_audit_{ts}.json"
    md_path = output_dir / f"knowledge_quality_audit_{ts}.md"

    export_audit_json(result, json_path)
    export_audit_markdown(result, md_path)

    print("\nAudit complete:")
    print(f"  Reports: {result.total_reports}")
    print(f"  Blocking issues: {len(result.blocking_issues)}")
    print(f"  Warnings: {len(result.warnings)}")
    print(f"  Duplicate groups: {len(result.duplicate_report_ids)}")
    print(f"  Entity confusions: {len(result.entity_confusions)}")
    print(f"  Low density reports: {len(result.low_density_reports)}")
    print(f"  Orphan claims: {len(result.orphan_claims)}")
    print(f"  Orphan signals: {len(result.orphan_signals)}")
    print(f"\nOutput: {json_path}")
    print(f"Output: {md_path}")

    if result.blocking_issues:
        print("\n[!] Blocking issues:")
        for b in result.blocking_issues:
            print(f"  - {b}")


if __name__ == "__main__":
    main()
