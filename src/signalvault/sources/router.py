"""M3-C-2b: Universal Intake — Router.

Orchestrator 的 Detect → Router 阶段。基于 DetectionResult + 冲突 + 质量 +
成本开关，输出 RoutingDecision。

设计原则（约束 2）：
- RoutingDecision 支持动作组合：archive / analyze / review / ignore 是可同时
  为真的「路径布尔」，不锁定唯一动作。这样未来「自动归档 + 自动分析」可组合。
- should_analyze 是「系统建议是否自动分析」的独立标志，与 analyze 路径可用性
  解耦（用户始终可手动选分析；系统是否自动分析受成本开关约束）。
- 成本红线：should_analyze 仅在 allow_auto_analyze=True 且 quality=good 且
  无 blocker 冲突时为 True。默认 allow_auto_analyze=False —— 绝不默认自动花真钱。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from signalvault.sources.detector import DetectedKind, DetectionResult
from signalvault.sources.models import ActionEnum, ConflictInfo

# 哪些 DetectedKind 语义丰富、适合触发 LLM 分析
_ANALYZABLE_KINDS = frozenset({
    DetectedKind.youtube_video,
    DetectedKind.pdf_file,
    DetectedKind.docx_file,
    DetectedKind.text_file,
})
# M3-C-3c: 高价值来源（值得花 LLM 成本分析）：视频字幕、PDF
_HIGH_VALUE_KINDS = frozenset({
    DetectedKind.youtube_video,
    DetectedKind.pdf_file,
})
# 哪些适合归档（资料留存）
_ARCHIVEABLE_KINDS = frozenset({
    DetectedKind.web_url,
    DetectedKind.youtube_video,
    DetectedKind.pdf_file,
    DetectedKind.docx_file,
    DetectedKind.text_file,
})


@dataclass
class RoutingDecision:
    """路由决策：动作路径可组合，不锁定唯一动作。

    archive/analyze/review/ignore 是「可选路径」布尔，可同时为真
    （例如 archive=True 且 analyze=True：先归档再分析）。
    should_analyze / requires_confirmation 是独立判定标志。
    """

    # 可组合的动作路径
    archive: bool = False
    analyze: bool = False
    review: bool = False
    ignore: bool = False

    # 独立判定标志
    should_analyze: bool = False
    requires_confirmation: bool = True
    reason: str = ""

    # 向后兼容：现有 confirm 流程仍消费 ActionEnum
    recommended_action: ActionEnum = ActionEnum.skip
    available_actions: list[ActionEnum] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def route_action(
    detected: DetectionResult,
    *,
    conflicts: list[ConflictInfo] | None = None,
    parse_quality: str = "good",
    allow_auto_analyze: bool = False,
    auto_mode: str = "off",
) -> RoutingDecision:
    """判定一个已检测输入的处理路径。

    Args:
        detected: detect_kind() 的输出。
        conflicts: 冲突检测结果。blocker 级冲突强制人工确认。
        parse_quality: "good" / "degraded" / "minimal"。
        allow_auto_analyze: 是否允许系统建议自动分析（向后兼容快捷开关）。
        auto_mode: M3-C-3c 自动分析分级 "off"/"high_value"/"all"。
            - off: 不自动分析（默认，绝不自动花真钱）
            - high_value: 仅高价值来源（YouTube/PDF）自动分析
            - all: 所有可分析来源自动分析
            auto_mode 优先于 allow_auto_analyze；allow_auto_analyze=True 在
            auto_mode=off 时等价 all（向后兼容旧测试）。
    """
    conflicts = conflicts or []
    has_blocker = any(c.severity == "blocker" for c in conflicts)

    # unknown → ignore
    if detected.kind == DetectedKind.unknown:
        return RoutingDecision(
            ignore=True,
            requires_confirmation=False,
            reason="无法识别输入类型",
            recommended_action=ActionEnum.skip,
            available_actions=[ActionEnum.skip],
        )

    # 极低质量 → ignore + review
    if parse_quality == "minimal":
        return RoutingDecision(
            ignore=True,
            review=True,
            requires_confirmation=True,
            reason="解析质量极低，无法提取有效内容",
            warnings=["内容质量不足以处理，建议跳过或人工复核。"],
            recommended_action=ActionEnum.skip,
            available_actions=[ActionEnum.skip],
        )

    decision = RoutingDecision()

    # 路径可用性（可组合）
    if detected.kind in _ARCHIVEABLE_KINDS:
        decision.archive = True
    if detected.kind in _ANALYZABLE_KINDS:
        decision.analyze = True

    # M3-C-3c: 成本分级。auto_mode 优先；allow_auto_analyze=True 在 off 时等价 all。
    if auto_mode == "high_value":
        decision.should_analyze = (
            detected.kind in _HIGH_VALUE_KINDS
            and parse_quality == "good"
            and not has_blocker
        )
    else:
        effective_all = auto_mode == "all" or (auto_mode == "off" and allow_auto_analyze)
        decision.should_analyze = (
            effective_all
            and detected.kind in _ANALYZABLE_KINDS
            and parse_quality == "good"
            and not has_blocker
        )

    # 是否需要人工确认
    warnings: list[str] = [c.description for c in conflicts if c.description]
    auto_enabled = auto_mode != "off" or allow_auto_analyze

    if has_blocker:
        decision.requires_confirmation = True
        decision.review = True
        decision.reason = "存在阻断级冲突（重复内容），需人工确认"
    elif parse_quality == "degraded":
        decision.requires_confirmation = True
        decision.review = True
        decision.reason = "解析质量退化，建议人工确认"
    elif not auto_enabled:
        # 未开启自动 → 默认需确认（保守，花钱前必须用户意愿）
        decision.requires_confirmation = True
        decision.reason = "需用户确认处理方式"
    else:
        # 自动模式 + 无冲突 + 质量良好 → 可免确认（自动归档）
        decision.requires_confirmation = False
        decision.reason = "自动处理（无冲突且质量良好）"

    decision.warnings = warnings

    # 向后兼容的 ActionEnum 映射
    available: list[ActionEnum] = []
    if decision.archive:
        available.append(ActionEnum.confirm_archive)
    if decision.analyze:
        available.append(ActionEnum.analyze)
    available.append(ActionEnum.skip)
    decision.available_actions = available

    if decision.should_analyze:
        decision.recommended_action = ActionEnum.analyze
    elif decision.archive:
        decision.recommended_action = ActionEnum.confirm_archive
    else:
        decision.recommended_action = ActionEnum.skip

    return decision
