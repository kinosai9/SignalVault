"""Translation service — batch-translate SourceSegments using the configured LLM provider."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from signalvault.db.source_provenance import get_segments

logger = logging.getLogger(__name__)


def translate_segments(
    session: Session,
    source_doc_id: str,
    provider,
    source_lang: str = "en",
    target_lang: str = "zh",
    progress_callback=None,
) -> dict:
    """Translate all untranslated segments for a SourceDocument.

    Segments with translation_status="translated" are skipped.
    Each segment is translated individually via provider.translate_text().
    Results are persisted to SourceSegment.text_translated + translation_status.

    Args:
        session: DB session.
        source_doc_id: The SourceDocument to translate segments for.
        provider: An LLMProvider instance (must implement translate_text).
        source_lang: Source language code.
        target_lang: Target language code.
        progress_callback: Optional callable(translated, total) for progress.

    Returns:
        dict with keys: total, translated, failed, skipped
    """
    from signalvault.db.models import SourceSegment

    segments = (
        session.query(SourceSegment)
        .filter(SourceSegment.source_doc_id == source_doc_id)
        .order_by(SourceSegment.sequence_index)
        .all()
    )

    total = len(segments)
    translated = 0
    failed = 0
    skipped = 0

    for i, seg in enumerate(segments):
        # Skip already translated
        if seg.translation_status == "translated":
            skipped += 1
            if progress_callback:
                progress_callback(translated, total)
            continue

        # Skip empty segments
        text = (seg.text_original or "").strip()
        if not text:
            seg.translation_status = "not_needed"
            skipped += 1
            if progress_callback:
                progress_callback(translated, total)
            continue

        try:
            result = provider.translate_text(text, source_lang, target_lang)
            seg.text_translated = result
            seg.translation_status = "translated"
            seg.translation_metadata_json = _make_translation_meta(
                source_lang, target_lang, "success",
            )
            translated += 1
        except Exception as e:
            logger.warning(
                "Translation failed for segment %s[%d]: %s",
                source_doc_id, i, e,
            )
            seg.translation_status = "failed"
            seg.translation_metadata_json = _make_translation_meta(
                source_lang, target_lang, f"error: {e}",
            )
            failed += 1

        if progress_callback:
            progress_callback(translated, total)

    session.flush()

    logger.info(
        "Translation complete for %s: %d translated, %d failed, %d skipped (total %d)",
        source_doc_id, translated, failed, skipped, total,
    )

    return {
        "total": total,
        "translated": translated,
        "failed": failed,
        "skipped": skipped,
    }


def _make_translation_meta(
    source_lang: str, target_lang: str, status: str,
) -> str:
    import json
    return json.dumps({
        "source_lang": source_lang,
        "target_lang": target_lang,
        "translated_at": datetime.now().isoformat(),
        "status": status,
    }, ensure_ascii=False)
