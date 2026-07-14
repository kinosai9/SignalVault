"""Source Provenance — CRUD for SourceDocument and SourceSegment.

Provides create/read/query operations for the provenance layer.
All functions accept a SQLAlchemy Session as the first argument,
following the same pattern as repository.py.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from signalvault.db.models import SourceDocument, SourceSegment


# ── Helpers ────────────────────────────────────────────────────────────────

def compute_content_hash(text: str) -> str:
    """SHA-256 first 16 hex chars of normalized text."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def _new_source_doc_id() -> str:
    """Generate a unique source_doc_id (8-char hex)."""
    return uuid.uuid4().hex[:8]


# ── SourceDocument CRUD ─────────────────────────────────────────────────────

def create_source_document(
    session: Session,
    source_type: str,
    title: str = "",
    canonical_url: str = "",
    source_url: str = "",
    source_path: str = "",
    content_hash: str = "",
    language: str = "",
    original_language: str = "",
    translated_language: str = "",
    status: str = "available",
    raw_text_path: str = "",
    normalized_text_path: str = "",
    translated_text_path: str = "",
    metadata_json: str = "{}",
    access_scope: str = "public_web",
    retention_policy: str = "keep_full_text",
    fetched_at: datetime | None = None,
) -> str:
    """Create a SourceDocument row. Returns the source_doc_id."""
    doc_id = _new_source_doc_id()
    doc = SourceDocument(
        source_doc_id=doc_id,
        source_type=source_type,
        title=title,
        canonical_url=canonical_url,
        source_url=source_url,
        source_path=source_path,
        content_hash=content_hash,
        language=language,
        original_language=original_language,
        translated_language=translated_language,
        status=status,
        raw_text_path=raw_text_path,
        normalized_text_path=normalized_text_path,
        translated_text_path=translated_text_path,
        metadata_json=metadata_json,
        access_scope=access_scope,
        retention_policy=retention_policy,
        fetched_at=fetched_at,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    session.add(doc)
    session.flush()
    return doc_id


def upsert_source_document(
    session: Session,
    source_type: str,
    content_hash: str,
    title: str = "",
    canonical_url: str = "",
    source_url: str = "",
    source_path: str = "",
    **kwargs,
) -> tuple[str, bool]:
    """Upsert by content_hash within same source_type. Returns (source_doc_id, is_new)."""
    existing = (
        session.query(SourceDocument)
        .filter(
            SourceDocument.source_type == source_type,
            SourceDocument.content_hash == content_hash,
            SourceDocument.content_hash != "",
        )
        .first()
    )
    if existing is not None:
        # Update timestamp
        existing.updated_at = datetime.now()
        if title:
            existing.title = title
        session.flush()
        return existing.source_doc_id, False

    return create_source_document(
        session,
        source_type=source_type,
        title=title,
        canonical_url=canonical_url,
        source_url=source_url,
        source_path=source_path,
        content_hash=content_hash,
        **kwargs,
    ), True


def get_source_document(session: Session, source_doc_id: str) -> dict | None:
    """Get a single SourceDocument by source_doc_id."""
    doc = (
        session.query(SourceDocument)
        .filter(SourceDocument.source_doc_id == source_doc_id)
        .first()
    )
    if doc is None:
        return None
    return _source_document_to_dict(doc)


def get_source_document_by_url(
    session: Session, source_url: str, source_type: str | None = None,
) -> dict | None:
    """Find a SourceDocument by source_url (and optionally source_type)."""
    q = session.query(SourceDocument).filter(
        SourceDocument.source_url == source_url,
        SourceDocument.source_url != "",
    )
    if source_type:
        q = q.filter(SourceDocument.source_type == source_type)
    doc = q.first()
    if doc is None:
        return None
    return _source_document_to_dict(doc)


def list_source_documents(
    session: Session,
    source_type: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """List SourceDocuments with optional filters."""
    q = session.query(SourceDocument)
    if source_type:
        q = q.filter(SourceDocument.source_type == source_type)
    if status:
        q = q.filter(SourceDocument.status == status)
    q = q.order_by(SourceDocument.created_at.desc()).offset(offset).limit(limit)
    return [_source_document_to_dict(d) for d in q.all()]


def count_source_documents(
    session: Session,
    source_type: str | None = None,
    status: str | None = None,
) -> int:
    """Count SourceDocuments with optional filters."""
    from sqlalchemy import func as sqlfunc
    q = session.query(sqlfunc.count(SourceDocument.id))
    if source_type:
        q = q.filter(SourceDocument.source_type == source_type)
    if status:
        q = q.filter(SourceDocument.status == status)
    return q.scalar() or 0


def update_source_document_status(
    session: Session, source_doc_id: str, status: str,
) -> bool:
    """Update the status field of a SourceDocument."""
    doc = (
        session.query(SourceDocument)
        .filter(SourceDocument.source_doc_id == source_doc_id)
        .first()
    )
    if doc is None:
        return False
    doc.status = status
    doc.updated_at = datetime.now()
    session.flush()
    return True


# ── SourceSegment CRUD ──────────────────────────────────────────────────────

def create_source_segments(
    session: Session,
    source_doc_id: str,
    segments: list[dict],
) -> int:
    """Batch-create SourceSegment rows. Returns count of segments created.

    Each segment dict should have keys matching SourceSegment fields:
    segment_id, sequence_index, segment_type, text_original, text_normalized,
    text_translated, start_time, end_time, page_number, paragraph_index,
    heading_path, char_start, char_end, locator_json, content_hash,
    translation_status.
    """
    created = 0
    for seg in segments:
        ss = SourceSegment(
            source_doc_id=source_doc_id,
            segment_id=seg.get("segment_id", ""),
            sequence_index=seg.get("sequence_index", 0),
            segment_type=seg.get("segment_type", "paragraph"),
            text_original=seg.get("text_original", ""),
            text_normalized=seg.get("text_normalized", ""),
            text_translated=seg.get("text_translated", ""),
            start_time=seg.get("start_time", ""),
            end_time=seg.get("end_time", ""),
            page_number=seg.get("page_number"),
            paragraph_index=seg.get("paragraph_index"),
            heading_path=seg.get("heading_path", ""),
            char_start=seg.get("char_start"),
            char_end=seg.get("char_end"),
            locator_json=seg.get("locator_json", "{}"),
            content_hash=seg.get("content_hash", ""),
            translation_status=seg.get("translation_status", "not_needed"),
            translation_metadata_json=seg.get("translation_metadata_json", "{}"),
        )
        session.add(ss)
        created += 1
    session.flush()
    return created


def get_segments(
    session: Session,
    source_doc_id: str,
    segment_type: str | None = None,
    limit: int = 500,
) -> list[dict]:
    """Get all segments for a SourceDocument, ordered by sequence_index."""
    q = (
        session.query(SourceSegment)
        .filter(SourceSegment.source_doc_id == source_doc_id)
    )
    if segment_type:
        q = q.filter(SourceSegment.segment_type == segment_type)
    q = q.order_by(SourceSegment.sequence_index).limit(limit)
    return [_source_segment_to_dict(s) for s in q.all()]


def find_segment_by_locator(
    session: Session,
    source_doc_id: str,
    page_number: int | None = None,
    timestamp: str | None = None,
    paragraph_index: int | None = None,
) -> dict | None:
    """Find a segment by its source-type-specific locator.

    Only one locator type is used at a time (caller picks).
    """
    q = session.query(SourceSegment).filter(
        SourceSegment.source_doc_id == source_doc_id,
    )
    if page_number is not None:
        q = q.filter(SourceSegment.page_number == page_number)
    if timestamp:
        q = q.filter(SourceSegment.start_time == timestamp)
    if paragraph_index is not None:
        q = q.filter(SourceSegment.paragraph_index == paragraph_index)
    seg = q.first()
    if seg is None:
        return None
    return _source_segment_to_dict(seg)


def count_segments(
    session: Session,
    source_doc_id: str,
) -> int:
    """Count segments for a SourceDocument."""
    from sqlalchemy import func as sqlfunc
    return (
        session.query(sqlfunc.count(SourceSegment.id))
        .filter(SourceSegment.source_doc_id == source_doc_id)
        .scalar()
    ) or 0


def delete_segments(session: Session, source_doc_id: str) -> int:
    """Delete all segments for a SourceDocument. Returns deleted count."""
    count = (
        session.query(SourceSegment)
        .filter(SourceSegment.source_doc_id == source_doc_id)
        .delete()
    )
    session.flush()
    return count


# ── Serialization helpers ───────────────────────────────────────────────────

def _source_document_to_dict(doc: SourceDocument) -> dict:
    return {
        "id": doc.id,
        "source_doc_id": doc.source_doc_id,
        "source_type": doc.source_type,
        "title": doc.title,
        "canonical_url": doc.canonical_url,
        "source_url": doc.source_url,
        "source_path": doc.source_path,
        "content_hash": doc.content_hash,
        "language": doc.language,
        "original_language": doc.original_language,
        "translated_language": doc.translated_language,
        "status": doc.status,
        "raw_text_path": doc.raw_text_path,
        "normalized_text_path": doc.normalized_text_path,
        "translated_text_path": doc.translated_text_path,
        "metadata_json": doc.metadata_json,
        "access_scope": doc.access_scope,
        "retention_policy": doc.retention_policy,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "fetched_at": doc.fetched_at.isoformat() if doc.fetched_at else None,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
    }


def _source_segment_to_dict(seg: SourceSegment) -> dict:
    return {
        "id": seg.id,
        "source_doc_id": seg.source_doc_id,
        "segment_id": seg.segment_id,
        "sequence_index": seg.sequence_index,
        "segment_type": seg.segment_type,
        "text_original": seg.text_original,
        "text_normalized": seg.text_normalized,
        "text_translated": seg.text_translated,
        "start_time": seg.start_time,
        "end_time": seg.end_time,
        "page_number": seg.page_number,
        "paragraph_index": seg.paragraph_index,
        "heading_path": seg.heading_path,
        "char_start": seg.char_start,
        "char_end": seg.char_end,
        "locator_json": seg.locator_json,
        "content_hash": seg.content_hash,
        "translation_status": seg.translation_status,
        "translation_metadata_json": seg.translation_metadata_json,
        "created_at": seg.created_at.isoformat() if seg.created_at else None,
    }
