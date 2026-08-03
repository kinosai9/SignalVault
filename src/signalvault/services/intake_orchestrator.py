"""M3-C-2c: Universal Intake Orchestrator.

唯一 intake 入口的编排核心（约束 5：不是新增一个导入页面，而是建设未来
orchestrator 的唯一入口）。串联 M3-C-2b 的 Detector → Router → handler 映射。

设计原则：
- 纯编排，不执行副作用（不抓取、不写库、不调 LLM）。实际写入/分析由现有
  路由（/content/analyze、/sources/import/preview 等）按 handler 指引执行。
- handler 是「指向现有处理路径的标识」，让 /intake 成为智能分流入口而非又
  一个并行表单。未来 orchestrator 可在此层逐步吸纳真实执行（M3-C-3）。
"""

from __future__ import annotations

from dataclasses import dataclass

from signalvault.sources.detector import DetectedKind, DetectionResult, detect_kind
from signalvault.sources.router import RoutingDecision, route_action


# handler 标识：指向现有处理路径
class IntakeHandler:
    YOUTUBE_ANALYZE = "youtube_analyze"      # → /content/new（YouTube 分析表单）
    CHANNEL_MANAGE = "channel_manage"        # → /sources/channels
    URL_IMPORT = "url_import"                # → /sources/import（网页预览-确认）
    FILE_IMPORT = "file_import"              # → /sources/files/import（文件上传）
    IGNORE = "ignore"                        # 无法识别


@dataclass
class IntakeResult:
    """Universal Intake 的编排结果。"""

    detection: DetectionResult
    routing: RoutingDecision
    handler: str
    target_route: str  # 引导用户前往的现有路由


# kind → (handler, target_route) 映射表
_HANDLER_MAP: dict[DetectedKind, tuple[str, str]] = {
    DetectedKind.youtube_video: (IntakeHandler.YOUTUBE_ANALYZE, "/content/new"),
    DetectedKind.youtube_channel: (IntakeHandler.CHANNEL_MANAGE, "/sources/channels"),
    DetectedKind.web_url: (IntakeHandler.URL_IMPORT, "/sources/import"),
    DetectedKind.pdf_file: (IntakeHandler.FILE_IMPORT, "/sources/files/import"),
    DetectedKind.docx_file: (IntakeHandler.FILE_IMPORT, "/sources/files/import"),
    DetectedKind.text_file: (IntakeHandler.FILE_IMPORT, "/sources/files/import"),
    DetectedKind.unknown: (IntakeHandler.IGNORE, "/sources/import/new"),
}


def orchestrate_intake(
    raw_input: str,
    *,
    allow_auto_analyze: bool = False,
) -> IntakeResult:
    """编排一个 Universal Intake 输入：detect → route → handler 映射。

    Args:
        raw_input: 用户提供的原始字符串（URL / 文件名 / 路径）。
        allow_auto_analyze: 是否允许建议自动分析（成本红线，默认 False）。
    """
    detection = detect_kind(raw_input)
    routing = route_action(detection, allow_auto_analyze=allow_auto_analyze)
    handler, target = _HANDLER_MAP.get(
        detection.kind, (IntakeHandler.IGNORE, "/sources/import/new")
    )
    return IntakeResult(
        detection=detection,
        routing=routing,
        handler=handler,
        target_route=target,
    )


def handler_label(handler: str) -> str:
    """handler → 用户可读的中文说明。"""
    labels = {
        IntakeHandler.YOUTUBE_ANALYZE: "YouTube 视频分析",
        IntakeHandler.CHANNEL_MANAGE: "频道管理",
        IntakeHandler.URL_IMPORT: "网页导入",
        IntakeHandler.FILE_IMPORT: "文件上传",
        IntakeHandler.IGNORE: "无法识别",
    }
    return labels.get(handler, "未知")


def auto_process_pending(auto_mode: str = "off") -> dict:
    """M3-C-3c: 按自动分析模式处理 pending_preview jobs。

    遍历待确认 job，重新 detect + route（带 auto_mode），根据 routing 决策：
    - ignore → auto_ignore（写 reason）
    - archive + 无需确认 → auto_archive（写 reason）
    - 其余（需确认 / 待分析）→ 保留人工

    MVP 边界：只做自动**决策**（标状态 + reason），不写归档文件、不调 LLM。
    真正的归档写入与 LLM 分析是后续执行层。这样处理中心先具备「可解释的自动决策」。

    Returns:
        {auto_archived, auto_ignored, kept_manual, mode}
    """
    from signalvault.sources.ingest_jobs import IngestJobManager

    pending = IngestJobManager.get_pending_previews()
    stats = {"auto_archived": 0, "auto_ignored": 0, "kept_manual": 0, "mode": auto_mode}

    for job in pending:
        source = job.get("source_url") or job.get("source_name") or ""
        detection = detect_kind(source)
        routing = route_action(detection, auto_mode=auto_mode)

        if routing.ignore:
            IngestJobManager.auto_ignore_job(
                job["preview_id"],
                reason=routing.reason or "自动忽略（无法识别或质量不足）",
            )
            stats["auto_ignored"] += 1
        elif routing.archive and not routing.requires_confirmation:
            IngestJobManager.auto_archive_job(
                job["preview_id"],
                reason=routing.reason or "自动归档（无冲突且质量良好）",
            )
            stats["auto_archived"] += 1
        else:
            stats["kept_manual"] += 1
    return stats
