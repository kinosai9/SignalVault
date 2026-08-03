"""M3-C-2b: Universal Intake — Detector.

独立的输入类型检测层（Orchestrator 的 Input → Detect 阶段）。

设计原则（约束 1）：
- 纯函数，无副作用，不触网、不读文件内容
- 只看输入字符串本身（URL 主机名 / 文件扩展名）
- 不依赖 SourceKind / ImportPreview 等现有来源模型 —— DetectedKind 可独立演进
- DetectionResult.metadata 携带 video_id / extension / domain 等下游可用信息
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urlparse


class DetectedKind(str, Enum):
    """输入类型分类。独立于 SourceKind，后续可扩展（rss / audio / transcript_file 等）。"""

    youtube_video = "youtube_video"
    youtube_channel = "youtube_channel"
    web_url = "web_url"
    pdf_file = "pdf_file"
    docx_file = "docx_file"
    text_file = "text_file"  # .txt / .md / .html / .htm
    unknown = "unknown"


@dataclass
class DetectionResult:
    """Detector 输出：识别出的类型 + 原始值 + 置信度 + 追溯元数据。

    metadata 常见键: video_id / channel_handle / extension / domain / scheme。
    """

    kind: DetectedKind
    confidence: float  # 0.0–1.0
    source_value: str  # 原始输入（URL 或文件名）
    metadata: dict[str, str] = field(default_factory=dict)


# ── 检测规则 ──────────────────────────────────────────────────────────────────

_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"}
_VIDEO_ID_RE = re.compile(r"(?:v=|youtu\.be/|/embed/|/shorts/)([a-zA-Z0-9_-]{11})")
_CHANNEL_RE = re.compile(r"(?:/channel/|/c/|/user/|/@)([a-zA-Z0-9_\-.]+)")
_PDF_EXT = ".pdf"
_DOCX_EXT = ".docx"
_TEXT_EXTS = {".txt", ".md", ".html", ".htm"}


def detect_kind(raw: str) -> DetectionResult:
    """识别输入字符串的类型。

    检测顺序（首匹配胜出）：
      1. http(s) URL —— YouTube 视频/频道，否则通用 web_url
         （URL 优先于扩展名，避免 .html/.pdf 网页被误判为本地文件）
      2. 文件扩展名（pdf / docx / txt / md / html）
      3. unknown
    """
    if not raw or not isinstance(raw, str):
        return DetectionResult(DetectedKind.unknown, 0.0, raw or "")

    value = raw.strip()

    # 1. http(s) URL
    if "://" in value:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        if parsed.scheme in ("http", "https") and host:
            if host in _YOUTUBE_HOSTS or host.endswith("youtube.com") or host.endswith("youtu.be"):
                return _detect_youtube(value, host)
            return DetectionResult(
                DetectedKind.web_url,
                confidence=0.9,
                source_value=value,
                metadata={"scheme": parsed.scheme, "domain": host},
            )

    # 2. 文件扩展名（文件名 / 本地路径）
    ext = _extract_extension(value)
    if ext:
        return _detect_file(value, ext)

    # 3. 无法识别
    return DetectionResult(
        DetectedKind.unknown,
        confidence=0.2,
        source_value=value,
        metadata={"reason": "无法识别为 URL 或支持的文件类型"},
    )


def _detect_youtube(value: str, host: str) -> DetectionResult:
    video_match = _VIDEO_ID_RE.search(value)
    if video_match:
        return DetectionResult(
            DetectedKind.youtube_video,
            confidence=1.0,
            source_value=value,
            metadata={"video_id": video_match.group(1), "domain": host},
        )
    channel_match = _CHANNEL_RE.search(value)
    if channel_match:
        return DetectionResult(
            DetectedKind.youtube_channel,
            confidence=0.9,
            source_value=value,
            metadata={"channel_handle": channel_match.group(1), "domain": host},
        )
    # YouTube 域名但无法定位具体视频/频道
    return DetectionResult(
        DetectedKind.youtube_channel,
        confidence=0.5,
        source_value=value,
        metadata={"domain": host, "note": "youtube domain, no specific video/channel"},
    )


def _detect_file(value: str, ext: str) -> DetectionResult:
    if ext == _PDF_EXT:
        kind, conf = DetectedKind.pdf_file, 1.0
    elif ext == _DOCX_EXT:
        kind, conf = DetectedKind.docx_file, 1.0
    elif ext in _TEXT_EXTS:
        kind, conf = DetectedKind.text_file, 1.0
    else:
        return DetectionResult(
            DetectedKind.unknown,
            confidence=0.2,
            source_value=value,
            metadata={"extension": ext, "reason": "不支持该扩展名"},
        )
    return DetectionResult(
        kind,
        confidence=conf,
        source_value=value,
        metadata={"extension": ext},
    )


def _extract_extension(value: str) -> str:
    """从文件名/路径提取小写扩展名；无扩展名或不像文件返回空串。"""
    cleaned = re.split(r"[?#]", value)[0].rstrip("/\\")
    last = cleaned.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if "." not in last:
        return ""
    ext = last[last.rfind("."):].lower()
    # 扩展名长度合理性（1–6 字符），过滤 "example.somethingweird"
    if not (1 <= len(ext) - 1 <= 6):
        return ""
    return ext
