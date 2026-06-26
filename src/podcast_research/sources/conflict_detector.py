"""P2-S.3.1: ConflictDetector — detect import conflicts before writing."""

from __future__ import annotations

import logging
from pathlib import Path

from podcast_research.sources.models import ConflictInfo

logger = logging.getLogger(__name__)


class ConflictDetector:
    """Detect conflicts for a prospective import URL against vault and DB.

    Checks (in order, most specific first):
      1. same_video_id_report — video_id already has a Report in DB
      2. same_video_id_deep_notes — Deep Notes exists for this video_id
      3. same_content_hash — content hash matches existing source archive
      4. same_canonical_url — canonical URL matches existing source archive
      5. same_url — exact URL already imported as source archive
    """

    def __init__(self, vault_path: Path) -> None:
        self._vault_path = vault_path

    # ── Public API ───────────────────────────────────────────────────────

    def detect(
        self,
        url: str,
        canonical_url: str,
        content_hash: str,
        detected_youtube_video_id: str,
    ) -> list[ConflictInfo]:
        """Run all conflict checks and return a list of ConflictInfo.

        Returns empty list if no conflicts found.
        """
        conflicts: list[ConflictInfo] = []

        # 1. DB: same YouTube video_id → existing Report
        if detected_youtube_video_id:
            conflict = self._check_video_id_report(detected_youtube_video_id)
            if conflict:
                conflicts.append(conflict)

        # 2. Vault: same YouTube video_id → existing Deep Notes
        if detected_youtube_video_id:
            conflict = self._check_video_id_deep_notes(detected_youtube_video_id)
            if conflict:
                conflicts.append(conflict)

        # 3. Vault: same content_hash → duplicate source archive
        if content_hash:
            conflict = self._check_content_hash(content_hash)
            if conflict:
                conflicts.append(conflict)

        # 4. Vault: same canonical_url → already imported
        if canonical_url:
            conflict = self._check_canonical_url(canonical_url)
            if conflict:
                conflicts.append(conflict)

        # 5. Vault: same source_url → already imported
        if url:
            conflict = self._check_source_url(url)
            if conflict:
                conflicts.append(conflict)

        return conflicts

    # ── Individual checks ────────────────────────────────────────────────

    def _check_video_id_report(self, video_id: str) -> ConflictInfo | None:
        """Check if video_id already has a Report in DB."""
        try:
            from podcast_research.db.repository import find_report_by_video_id
            from podcast_research.db.session import get_session, init_db

            init_db()
            session = get_session()
            try:
                report_info = find_report_by_video_id(session, video_id)
                if report_info:
                    return ConflictInfo(
                        conflict_type="same_video_id_report",
                        severity="blocker",
                        description=(
                            f"YouTube 视频 {video_id} 已有投资分析报告 "
                            f"(Report #{report_info['id']})"
                        ),
                        existing_path=f"Report #{report_info['id']}",
                    )
            finally:
                session.close()
        except Exception as e:
            logger.warning("DB conflict check failed: %s", e)

        return None

    def _check_video_id_deep_notes(self, video_id: str) -> ConflictInfo | None:
        """Check if Deep Notes already exists for this video_id."""
        deep_notes_dir = self._vault_path / "01_Reports" / "DeepNotes"
        if not deep_notes_dir.exists():
            return None

        for md_file in deep_notes_dir.glob("*.md"):
            try:
                # Read first 1KB to check frontmatter
                head = md_file.read_text(encoding="utf-8")[:1024]
                if f"youtube_video_id: {video_id}" in head:
                    return ConflictInfo(
                        conflict_type="same_video_id_deep_notes",
                        severity="warning",
                        description=(
                            f"YouTube 视频 {video_id} 已有 Deep Notes: "
                            f"{md_file.name}"
                        ),
                        existing_path=str(md_file.relative_to(self._vault_path)),
                    )
            except Exception:
                pass

        return None

    def _check_content_hash(self, content_hash: str) -> ConflictInfo | None:
        """Check if content_hash already exists in SourceArchive."""
        archive_dir = self._vault_path / "01_Reports" / "SourceArchive"
        if not archive_dir.exists():
            return None

        for md_file in archive_dir.glob("*.md"):
            try:
                head = md_file.read_text(encoding="utf-8")[:2048]
                if f"content_hash: {content_hash}" in head:
                    return ConflictInfo(
                        conflict_type="same_content_hash",
                        severity="blocker",
                        description=(
                            f"内容完全相同的页面已存在于归档中: {md_file.name}"
                        ),
                        existing_path=str(md_file.relative_to(self._vault_path)),
                    )
            except Exception:
                pass

        return None

    def _check_canonical_url(self, canonical_url: str) -> ConflictInfo | None:
        """Check if canonical_url already imported."""
        archive_dir = self._vault_path / "01_Reports" / "SourceArchive"
        if not archive_dir.exists():
            return None

        for md_file in archive_dir.glob("*.md"):
            try:
                head = md_file.read_text(encoding="utf-8")[:2048]
                if f"canonical_url: {canonical_url}" in head:
                    return ConflictInfo(
                        conflict_type="same_canonical_url",
                        severity="warning",
                        description=(
                            f"相同规范 URL 的页面已导入: {md_file.name}"
                        ),
                        existing_path=str(md_file.relative_to(self._vault_path)),
                    )
            except Exception:
                pass

        return None

    def _check_source_url(self, url: str) -> ConflictInfo | None:
        """Check if exact source_url already imported."""
        archive_dir = self._vault_path / "01_Reports" / "SourceArchive"
        if not archive_dir.exists():
            return None

        for md_file in archive_dir.glob("*.md"):
            try:
                head = md_file.read_text(encoding="utf-8")[:2048]
                if f"source_url: {url}" in head:
                    return ConflictInfo(
                        conflict_type="same_url",
                        severity="info",
                        description=(
                            f"相同 URL 的页面已导入: {md_file.name}"
                        ),
                        existing_path=str(md_file.relative_to(self._vault_path)),
                    )
            except Exception:
                pass

        return None
