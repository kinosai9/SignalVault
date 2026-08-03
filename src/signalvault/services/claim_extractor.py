"""M4-B.2: Claim Extractor — extract core investment claims from Report/View/Signal.

Claims are the core value of investment research: not reports themselves,
but the judgments and predictions they contain.

Extraction sources (deterministic, no LLM required):
  1. From Views: bullish/bearish views → claim_text = "{target} {direction} - {logic}"
  2. From Signals: tracking signals → claim_text = "{target} - {signal_description}"

Design principles:
- Deterministic extraction: claims are derived from structured data, not LLM inference
- Source traceability: every claim links back to report/view/signal
- Idempotent: re-extraction for same report skips existing claims (by report+view)
- Confidence mapping: speaker_confidence → numeric confidence score
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from signalvault.db.models import Claim

logger = logging.getLogger(__name__)


# ── Confidence mapping ───────────────────────────────────────────────────────

# speaker_confidence → numeric score
_CONFIDENCE_MAP: dict[str, float] = {
    "high": 0.85,
    "medium": 0.65,
    "low": 0.40,
    "": 0.50,
}

# view_direction → claim_type
_DIRECTION_CLAIM_TYPE: dict[str, str] = {
    "bullish": "prediction",
    "bearish": "prediction",
    "neutral": "opinion",
    "": "opinion",
}


@dataclass
class ClaimData:
    """Structured claim data before persistence."""
    claim_text: str
    claim_type: str = "prediction"
    confidence: float = 0.5
    confidence_source: str = "system"
    source_report_id: int = 0
    source_view_id: int | None = None
    source_quote: str = ""
    timestamp: str = ""
    evidence_page: int | None = None
    supporting_sources: list[str] = field(default_factory=list)


# ── Claim Extractor ──────────────────────────────────────────────────────────

class ClaimExtractor:
    """Extract claims from existing reports, views, and signals.

    Usage:
        extractor = ClaimExtractor()
        claims = extractor.extract_from_report(report_id=42)
        # → list[Claim] persisted to DB

        # Batch extraction:
        stats = extractor.extract_all()
        # → {"reports_processed": N, "claims_extracted": M, "errors": [...]}
    """

    def __init__(self, session: Session | None = None):
        self._session = session
        self._owns_session = session is None

    @property
    def session(self) -> Session:
        if self._session is None:
            from signalvault.db.session import get_session
            self._session = get_session()
        return self._session

    def extract_from_report(self, report_id: int) -> list[Claim]:
        """Extract claims from a single report.

        1. Query views for this report → extract claims from bullish/bearish views
        2. Query signals for this report → extract claims from signals
        3. Persist claims to DB (skip if already exists for same view+report)

        Args:
            report_id: The report ID to extract claims from.

        Returns:
            List of persisted Claim objects.
        """
        from signalvault.db.models import InvestmentViewRecord, TrackingSignalRecord

        claims: list[Claim] = []

        # 1. Extract from views
        views = (
            self.session.query(InvestmentViewRecord)
            .filter_by(report_id=report_id)
            .all()
        )

        for view in views:
            claim_data = self._view_to_claim(view)
            if claim_data and not self._claim_exists_for_view(report_id, view.id):
                claim = self._persist_claim(claim_data)
                claims.append(claim)

        # 2. Extract from signals
        signals = (
            self.session.query(TrackingSignalRecord)
            .filter_by(report_id=report_id)
            .all()
        )

        for signal in signals:
            claim_data = self._signal_to_claim(signal)
            if claim_data and not self._claim_exists_for_signal(report_id, signal.id):
                claim = self._persist_claim(claim_data)
                claims.append(claim)

        self.session.commit()

        logger.info(
            "Extracted %d claims from report %d (%d views, %d signals)",
            len(claims), report_id, len(views), len(signals),
        )
        return claims

    def extract_all(self) -> dict[str, Any]:
        """Extract claims from all existing reports.

        Idempotent: reports that already have claims extracted will be skipped
        for those specific views/signals.

        Returns:
            Stats dict with processing summary.
        """
        from signalvault.db.models import Report

        reports = self.session.query(Report).all()
        stats = {
            "reports_processed": 0,
            "reports_skipped": 0,
            "claims_extracted": 0,
            "errors": [],
        }

        for report in reports:
            try:
                claims = self.extract_from_report(report.id)
                if claims:
                    stats["claims_extracted"] += len(claims)
                stats["reports_processed"] += 1
            except Exception as e:
                logger.exception(f"Failed to extract claims from report {report.id}")
                stats["errors"].append({
                    "report_id": report.id,
                    "error": str(e),
                })

        self.session.commit()
        logger.info(
            "Batch claim extraction complete: %d claims from %d reports",
            stats["claims_extracted"], stats["reports_processed"],
        )
        return stats

    def get_claims_for_report(self, report_id: int) -> list[Claim]:
        """Get all claims associated with a report."""
        return (
            self.session.query(Claim)
            .filter_by(source_report_id=report_id)
            .all()
        )

    def get_claims_for_entity(self, entity_name: str) -> list[Claim]:
        """Search claims by entity name (mentioned in claim_text)."""
        return (
            self.session.query(Claim)
            .filter(Claim.claim_text.contains(entity_name))
            .all()
        )

    # ── Private helpers ──────────────────────────────────────────────────────

    def _view_to_claim(self, view) -> ClaimData | None:
        """Convert an investment view to a claim.

        Only bullish/bearish views produce claims. Neutral views without
        logic_chain are skipped.
        """
        direction = (view.view_direction or "").lower()

        # Only directional views produce meaningful claims
        if direction not in ("bullish", "bearish") and not (view.logic_chain or "").strip():
            return None

        # Build claim text
        parts = [view.target_name or "Unknown"]
        if direction:
            direction_cn = {"bullish": "看多", "bearish": "看空", "neutral": "中性"}
            parts.append(direction_cn.get(direction, direction))

        logic = (view.logic_chain or "")[:150]
        if logic:
            parts.append(f"— {logic}")

        claim_text = " ".join(parts)

        # Confidence: use speaker_confidence if available
        confidence = _CONFIDENCE_MAP.get(
            (view.speaker_confidence or "").lower(), 0.5
        )

        return ClaimData(
            claim_text=claim_text,
            claim_type=_DIRECTION_CLAIM_TYPE.get(direction, "opinion"),
            confidence=confidence,
            confidence_source="speaker" if view.speaker_confidence else "system",
            source_report_id=view.report_id,
            source_view_id=view.id,
            source_quote=(view.source_quote or "")[:500],
            timestamp=view.timestamp_start or "",
            evidence_page=view.evidence_page,
        )

    def _signal_to_claim(self, signal) -> ClaimData | None:
        """Convert a tracking signal to a claim."""
        signal_text = (signal.signal or "").strip()
        if not signal_text:
            return None

        target = signal.target_name or "Unknown"
        claim_text = f"{target} — {signal_text[:200]}"

        return ClaimData(
            claim_text=claim_text,
            claim_type="prediction",
            confidence=0.6,  # signals are inherently lower confidence
            confidence_source="system",
            source_report_id=signal.report_id,
            source_quote=(signal.source_quote or "")[:500],
            timestamp=signal.timestamp or "",
        )

    def _claim_exists_for_view(self, report_id: int, view_id: int | None) -> bool:
        """Check if a claim already exists for this view."""
        if view_id is None:
            return False
        return (
            self.session.query(Claim)
            .filter_by(source_report_id=report_id, source_view_id=view_id)
            .first()
            is not None
        )

    def _claim_exists_for_signal(self, report_id: int, signal_id: int) -> bool:
        """Check if a claim already exists for this signal."""
        # Signals don't have source_view_id, so match by report + claim_text pattern
        from signalvault.db.models import TrackingSignalRecord

        signal = (
            self.session.query(TrackingSignalRecord)
            .filter_by(id=signal_id)
            .first()
        )
        if not signal:
            return False

        claim_text = f"{signal.target_name or 'Unknown'} — {(signal.signal or '')[:200]}"
        return (
            self.session.query(Claim)
            .filter_by(source_report_id=report_id)
            .filter(Claim.claim_text == claim_text)
            .first()
            is not None
        )

    def _persist_claim(self, data: ClaimData) -> Claim:
        """Persist a ClaimData to the claims table."""
        claim = Claim(
            claim_text=data.claim_text,
            claim_type=data.claim_type,
            confidence=data.confidence,
            confidence_source=data.confidence_source,
            source_report_id=data.source_report_id,
            source_view_id=data.source_view_id,
            source_quote=data.source_quote,
            timestamp=data.timestamp,
            evidence_page=data.evidence_page,
            supporting_sources=json.dumps(data.supporting_sources, ensure_ascii=False),
        )
        self.session.add(claim)
        self.session.flush()
        return claim

    def close(self):
        """Close the session if we own it."""
        if self._owns_session and self._session:
            self._session.close()
            self._session = None


# ── Convenience function ─────────────────────────────────────────────────────

def extract_claims(report_id: int | None = None) -> dict[str, Any]:
    """Extract claims from reports. If report_id is None, extract from all.

    Returns stats dict.
    """
    extractor = ClaimExtractor()
    try:
        if report_id:
            claims = extractor.extract_from_report(report_id)
            return {
                "report_id": report_id,
                "claims_extracted": len(claims),
            }
        return extractor.extract_all()
    finally:
        extractor.close()
