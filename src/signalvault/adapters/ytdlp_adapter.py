"""YtDlpAdapter — yt-dlp based video metadata and subtitle download.

Fallback for when youtube-transcript-api fails (captions disabled, region-locked, etc.).
Also provides richer metadata: title, duration, channel name, publish date.
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from signalvault.adapters.base import TranscriptAdapter, TranscriptResult
from signalvault.analysis.models import SubtitleSegment

logger = logging.getLogger(__name__)


class YtDlpAdapter(TranscriptAdapter):
    """Fetch video metadata and subtitles via yt-dlp CLI.

    Uses yt-dlp's --write-auto-subs and --write-subs to attempt subtitle download.
    Falls back to metadata-only if no subtitles are available.

    Args:
        cache_dir: Directory to store downloaded subtitles.
        preferred_langs: Comma-separated language priority (e.g. "zh-Hans,en").
    """

    def __init__(
        self,
        cache_dir: str | Path = "",
        preferred_langs: str = "zh-Hans,en",
    ):
        self.cache_dir = Path(cache_dir) if cache_dir else Path(tempfile.gettempdir()) / "ytdlp_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.preferred_langs = preferred_langs

    def fetch(self, url: str = "", video_id: str = "") -> TranscriptResult:
        """Fetch video metadata and attempt subtitle download.

        Args:
            url: Full YouTube URL (preferred).
            video_id: YouTube video ID (alternative to url).

        Returns:
            TranscriptResult with metadata. Segments may be empty if no subtitles.
        """
        if url:
            target = url
        elif video_id:
            target = f"https://www.youtube.com/watch?v={video_id}"
        else:
            raise ValueError("Either url or video_id must be provided")

        metadata = self._fetch_metadata(target)

        segments: list[SubtitleSegment] = []
        try:
            segments = self._fetch_subtitles(target)
        except Exception as e:
            logger.warning("yt-dlp subtitle download failed: %s", e)

        return TranscriptResult(
            source_type="youtube",
            source_url=target,
            video_id=metadata.get("id", video_id or ""),
            language=metadata.get("language", ""),
            title=metadata.get("title", ""),
            channel_name=metadata.get("channel", ""),
            is_generated=metadata.get("is_auto_generated", False),
            fetched_at=datetime.now().isoformat(),
            segments=segments,
            metadata=metadata,
        )

    def fetch_metadata_only(self, url: str = "", video_id: str = "") -> dict:
        """Fetch video metadata without attempting subtitle download."""
        target = url or (f"https://www.youtube.com/watch?v={video_id}" if video_id else "")
        if not target:
            raise ValueError("Either url or video_id must be provided")
        return self._fetch_metadata(target)

    # ── Internal ──────────────────────────────────────────────────────────

    def _fetch_metadata(self, target: str) -> dict:
        """Extract video metadata via yt-dlp --dump-json."""
        try:
            result = subprocess.run(
                [
                    "yt-dlp", "--dump-json", "--no-playlist",
                    "--skip-download", "--no-warnings",
                    target,
                ],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0 or not result.stdout.strip():
                logger.warning("yt-dlp metadata fetch returned empty")
                return self._minimal_metadata(target)

            info = json.loads(result.stdout)
            return {
                "id": info.get("id", ""),
                "title": info.get("title", ""),
                "channel": info.get("channel") or info.get("uploader", ""),
                "channel_id": info.get("channel_id", ""),
                "duration": info.get("duration", 0),
                "language": info.get("language", ""),
                "is_auto_generated": False,
                "upload_date": info.get("upload_date", ""),
                "view_count": info.get("view_count", 0),
                "description": (info.get("description", "") or "")[:500],
                "categories": info.get("categories", []),
                "tags": info.get("tags", []),
            }
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
            logger.warning("yt-dlp metadata fetch failed: %s", e)
            return self._minimal_metadata(target)

    def _fetch_subtitles(self, target: str) -> list[SubtitleSegment]:
        """Download subtitles via yt-dlp and parse into SubtitleSegments."""
        output_dir = self.cache_dir / f"subs_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_template = str(output_dir / "%(id)s")

        result = subprocess.run(
            [
                "yt-dlp",
                "--write-auto-subs",
                "--sub-langs", self.preferred_langs,
                "--convert-subs", "vtt",
                "--skip-download",
                "--no-playlist",
                "--no-warnings",
                "-o", output_template,
                target,
            ],
            capture_output=True, text=True, timeout=60,
        )

        if result.returncode != 0:
            raise RuntimeError(f"yt-dlp subtitle download failed: {result.stderr[:200]}")

        # Find the downloaded VTT file
        vtt_files = list(output_dir.glob("*.vtt"))
        if not vtt_files:
            vtt_files = list(output_dir.glob("*.srt"))

        if not vtt_files:
            raise RuntimeError("No subtitle file found after yt-dlp download")

        vtt_path = vtt_files[0]
        return self._parse_vtt(vtt_path)

    def _parse_vtt(self, path: Path) -> list[SubtitleSegment]:
        """Parse a VTT/SRT subtitle file into SubtitleSegments."""
        text = path.read_text(encoding="utf-8", errors="replace")
        segments = []
        # Simple VTT/SRT parser: extract timestamp blocks
        import re
        # Pattern: timestamp line followed by text
        pattern = re.compile(
            r'(\d{2}:\d{2}:\d{2}[.,]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[.,]\d{3})\s*\n(.*?)(?=\n\n|\n\d+\n|\Z)',
            re.DOTALL,
        )
        matches = pattern.findall(text)
        for i, (start, end, content) in enumerate(matches):
            content = content.strip().replace('\n', ' ')
            if content:
                segments.append(SubtitleSegment(
                    segment_id=f"yt_{i:04d}",
                    start_time=start.replace(',', '.'),
                    end_time=end.replace(',', '.'),
                    text=content,
                ))
        return segments

    @staticmethod
    def _minimal_metadata(target: str) -> dict:
        return {
            "id": "", "title": target, "channel": "", "channel_id": "",
            "duration": 0, "language": "", "is_auto_generated": False,
            "upload_date": "", "view_count": 0, "description": "",
            "categories": [], "tags": [],
        }
