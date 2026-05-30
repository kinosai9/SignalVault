"""Mock LLM Provider：基于字幕文本的规则分析引擎。

用关键词匹配、模式识别从字幕中提取投资观点、风险、待验证信号。
不是真实 LLM，但产出与输入内容关联，使 pipeline 测试更有代表性。
"""

from __future__ import annotations

import re

from podcast_research.analysis.models import (
    ExtractionResult,
    InvestmentView,
    Evidence,
    TrackingSignal,
    Entity,
    Risk,
    SubtitleSegment,
)
from podcast_research.llm.base import LLMProvider


# ── 关词库 ──

BULLISH_WORDS = ["看多", "看好", "上涨", "增持", "利好", "乐观", "积极", "突破", "反弹", "回升", "值得关注", "值得关注", "优势", "增长", "扩张", "偏低", "适合"]
BEARISH_WORDS = ["看空", "看淡", "下跌", "减持", "利空", "悲观", "谨慎", "消极", "回调", "回落", "放缓", "减弱", "不同意", "吸引力减弱", "风险", "警惕"]
NEUTRAL_WORDS = ["中性", "观望", "平衡", "不确定", "难以判断", "视情况"]
RISK_WORDS = ["风险", "警惕", "担忧", "隐患", "波动", "不确定性", "政策风险", "竞争风险", "地缘", "汇率"]
SIGNAL_WORDS = ["关注", "跟踪", "观察", "验证", "待确认", "后续", "值得留意", "值得关注", "信号"]
STOCK_PATTERN = re.compile(
    r"(宁德时代|比亚迪|茅台|五粮液|腾讯|阿里|美团|京东|拼多多|平安银行|招商银行|工商银行"
    r"|恒瑞医药|药明康德|中芯国际|隆基绿能|通威股份|阳光电源|中远海控|万华化学"
    r"|格力电器|美的集团|海尔智家|伊利股份|蒙牛|海天味业|中国平安|中国人寿"
    r"|紫光股份|科大讯飞|大疆|小米|华为|OPPO|vivo|联想|比亚迪电子"
    r"|港股|A股|美股|创业板|科创板|红利|ETF|基金|债券|黄金|原油|铜|锂|镍)"
)
MARKET_PATTERN = re.compile(r"(A股|港股|美股|创业板|科创板|新三板|纳斯达克|港股通)")
SPEAKER_PATTERN = re.compile(r"(嘉宾[ABCD]|主持人|主持|主播|主讲|嘉宾)")
ENTITY_TYPE_MAP = {
    "A股": "market", "港股": "market", "美股": "market",
    "创业板": "market", "科创板": "market",
    "红利": "asset_class", "ETF": "asset_class", "基金": "fund", "债券": "asset_class",
    "黄金": "asset_class", "原油": "asset_class",
}

_direction_label = {"bullish": "看多", "bearish": "看空", "neutral": "中性"}


class MockLLMProvider(LLMProvider):

    def extract_facts(self, cleaned_text: str, segments_text: str, focus_areas: list[str] | None = None) -> ExtractionResult:
        segments = self._parse_segments_text(segments_text)
        entities = self._extract_entities(cleaned_text)
        views = self._extract_views(segments, entities, cleaned_text)
        insights = self._extract_insights(segments, entities, cleaned_text)
        risks = self._extract_risks(segments, cleaned_text)
        signals = self._extract_signals(segments, entities, cleaned_text)
        quotes = self._extract_quotes(segments)
        uncertain = self._extract_uncertain(segments, views)

        return ExtractionResult(
            metadata={"source": "mock-rule-engine", "model": "mock-v2"},
            mentioned_entities=entities,
            investment_views=views,
            tech_industry_insights=insights,
            risks=risks,
            tracking_signals=signals,
            key_quotes=quotes,
            uncertain_items=uncertain,
            non_focus_items=[],
            prompt_version="tech_ai_v2",
        )

    def render_report(self, extraction: ExtractionResult) -> str:
        lines = [
            "# 投资播客研究报告",
            "",
            "> **免责声明**：本报告仅为播客内容的结构化整理，不构成任何投资建议。",
            "> 所有观点均来自播客嘉宾原文，不代表分析工具的判断。",
            "",
        ]

        # 数据来源展示 (P2-A2.1: 频道/视频元数据增强)
        source_info = extraction.source_info
        if source_info:
            lines.append("## 数据来源")
            lines.append("")
            source_type = source_info.get("source_type", "")
            if source_type == "youtube":
                # 频道（优先展示）
                channel = source_info.get("channel_name", "")
                if channel:
                    lines.append(f"- **来源频道**：{channel}")
                channel_url = source_info.get("channel_url", "")
                if channel_url:
                    lines.append(f"- **频道链接**：{channel_url}")
                # 视频标题
                title = source_info.get("title", "")
                if title:
                    lines.append(f"- **视频标题**：{title}")
                # 视频 ID + 链接
                vid = source_info.get("video_id", "")
                if vid:
                    lines.append(f"- **视频 ID**：{vid}")
                video_url = source_info.get("video_url", "")
                if video_url:
                    lines.append(f"- **视频链接**：{video_url}")
                elif vid:
                    lines.append(f"- **视频链接**：https://www.youtube.com/watch?v={vid}")
                # 发布日期
                published = source_info.get("published_at", "")
                if published:
                    lines.append(f"- **发布日期**：{published}")
                # 字幕信息
                lang = source_info.get("language", "")
                if lang:
                    lines.append(f"- **字幕语言**：{lang}")
                seg_count = source_info.get("transcript_segment_count", 0)
                if seg_count:
                    lines.append(f"- **字幕段数**：{seg_count}")
                is_gen = source_info.get("is_generated", False)
                lines.append(f"- **字幕类型**：{'自动生成' if is_gen else '人工上传'}")
                # 频道标签
                tags = source_info.get("channel_tags", [])
                if tags:
                    tags_str = ", ".join(f"#{t}" for t in tags)
                    lines.append(f"- **频道标签**：{tags_str}")
            else:
                path = source_info.get("source_path", "")
                lines.append(f"- **来源**：本地字幕文件")
                if path:
                    lines.append(f"- **文件**：{path}")
            lines.append("")

        # 关注点展示
        if extraction.focus_areas:
            focus_display = ", ".join(extraction.focus_areas)
            lines.append(f"**关注点**：{focus_display}")
            lines.append("")
            lines.append("---")
            lines.append("")

        lines.append("## 执行摘要")
        lines.append("")

        view_count = len(extraction.investment_views)
        entity_names = ", ".join(e.name for e in extraction.mentioned_entities) or "未识别标的"
        lines.append(f"本期讨论涉及 **{entity_names}**，共提取 **{view_count}** 条投资观点。")

        # View matrix (v2: expanded columns)
        lines.append("")
        lines.append("## 核心观点矩阵")
        lines.append("")
        lines.append("| 标的 | 方向 | AI价值链 | 商业影响 | 逻辑 | 证据类型 | 证据强度 | 时间范围 | 发言人 | 时间戳 |")
        lines.append("|------|------|----------|----------|------|----------|----------|----------|--------|--------|")
        for v in extraction.investment_views:
            direction = v.view_direction_label or _direction_label.get(v.view_direction, v.view_direction)
            logic_display = v.logic_chain[:50] if len(v.logic_chain) > 50 else v.logic_chain
            horizon = v.time_horizon or "unknown"
            lines.append(
                f"| {v.target_name} | {direction} "
                f"| {v.ai_value_chain_layer or '-'} "
                f"| {v.business_impact or '-'} "
                f"| {logic_display} | {v.evidence.evidence_type} "
                f"| {v.evidence.evidence_strength} "
                f"| {horizon} "
                f"| {v.speaker_label or 'unknown_speaker'} | {v.timestamp_start} |"
            )

        # Tech/Industry Insights (v2 new section)
        lines.append("")
        lines.append("## Tech/Industry Insights")
        lines.append("")
        if extraction.tech_industry_insights:
            for ins in extraction.tech_industry_insights:
                implication = f" [投资含义: {ins.investment_implication}]" if ins.investment_implication != "none" else ""
                tags = f" `{' '.join('#' + t for t in ins.topic_tags)}`" if ins.topic_tags else ""
                lines.append(f"- **{ins.insight}**{implication}{tags}")
                if ins.source_quote:
                    lines.append(f"  > {ins.source_quote}")
        else:
            lines.append("本期未识别到技术/产业洞察。")

        # Risks
        lines.append("")
        lines.append("## 风险提示")
        lines.append("")
        if extraction.risks:
            for r in extraction.risks:
                label = f"（{r.target_name}，{r.speaker_label or 'unknown_speaker'} @ {r.timestamp}）" if r.target_name else ""
                lines.append(f"- **{r.description}**{label}")
        else:
            lines.append("本期未识别到明确风险提示。")

        # Tracking signals
        lines.append("")
        lines.append("## 待验证信号")
        lines.append("")
        if extraction.tracking_signals:
            for s in extraction.tracking_signals:
                extra = f"（{s.target_name}，触发条件：{s.trigger_condition}，预期时间：{s.expected_date}）" if s.target_name else f"（触发条件：{s.trigger_condition}）"
                lines.append(f"- {s.signal}{extra}")
        else:
            lines.append("本期未识别到待验证信号。")

        # Non-focus Items (v2 new section)
        lines.append("")
        lines.append("## Non-focus Items")
        lines.append("")
        if extraction.non_focus_items:
            for nf in extraction.non_focus_items:
                lines.append(f"- {nf}")
        else:
            lines.append("本期未识别到非关注项。")

        # Key quotes
        lines.append("")
        lines.append("## 关键原文引用")
        lines.append("")
        for q in extraction.key_quotes:
            lines.append(f"> {q}")

        # Uncertain items
        if extraction.uncertain_items:
            lines.append("")
            lines.append("## 不确定项")
            lines.append("")
            for u in extraction.uncertain_items:
                lines.append(f"- {u}")

        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("*分析方式：规则引擎 mock-v2（非真实 LLM） | 不构成投资建议*")

        return "\n".join(lines)

    # ── 内部方法 ──

    def _parse_segments_text(self, segments_text: str) -> list[dict]:
        """从 pipeline 传入的 segments_text 格式: [start-end] text"""
        result = []
        for line in segments_text.strip().split("\n"):
            match = re.match(r"\[([^\]]+)\]\s*(.*)", line.strip())
            if match:
                timestamps = match.group(1)
                text = match.group(2)
                parts = timestamps.split("-", 1)
                start = parts[0] if parts else ""
                end = parts[1] if len(parts) > 1 else ""
                result.append({"start": start, "end": end, "text": text})
        return result

    def _extract_entities(self, text: str) -> list[Entity]:
        seen: set[str] = set()
        entities = []
        for m in STOCK_PATTERN.finditer(text):
            name = m.group(1)
            if name not in seen:
                seen.add(name)
                entity_type = ENTITY_TYPE_MAP.get(name, "stock")
                entities.append(Entity(name=name, normalized_name=name, entity_type=entity_type))
        return entities

    def _detect_direction(self, text: str) -> str:
        bullish_hits = sum(1 for w in BULLISH_WORDS if w in text)
        bearish_hits = sum(1 for w in BEARISH_WORDS if w in text)
        neutral_hits = sum(1 for w in NEUTRAL_WORDS if w in text)
        if bullish_hits > bearish_hits:
            return "bullish"
        if bearish_hits > bullish_hits and bearish_hits > 0:
            return "bearish"
        if neutral_hits > 0:
            return "neutral"
        return "neutral"

    def _detect_speaker(self, text: str) -> tuple[str, str, str]:
        m = SPEAKER_PATTERN.search(text)
        if m:
            return m.group(1), "guest" if "嘉宾" in m.group(1) else "host", "medium"
        return "未识别发言人", "unknown", "low"

    def _extract_views(self, segments: list[dict], entities: list[Entity], full_text: str) -> list[InvestmentView]:
        views = []
        used_segments: set[int] = set()

        for entity in entities:
            target = entity.name
            # 找到所有提到该标的的段索引
            target_indices = [i for i, s in enumerate(segments) if target in s["text"]]
            if not target_indices:
                continue

            for idx in target_indices:
                if idx in used_segments:
                    continue

                # 扩展窗口：该段 ± 2 段，构成上下文
                window_start = max(0, idx - 2)
                window_end = min(len(segments), idx + 3)
                window_texts = [segments[i]["text"] for i in range(window_start, window_end)]
                window_combined = " ".join(window_texts)

                direction = self._detect_direction(window_combined)
                # 如果窗口内没有方向词，跳过（仅提及标的不构成观点）
                if not any(w in window_combined for w in BULLISH_WORDS + BEARISH_WORDS + NEUTRAL_WORDS):
                    continue

                # 观点来源段：优先取包含方向词的段
                source_idx = idx
                for i in range(window_start, window_end):
                    if any(w in segments[i]["text"] for w in BULLISH_WORDS + BEARISH_WORDS + NEUTRAL_WORDS):
                        source_idx = i
                        break

                source_seg = segments[source_idx]
                speaker, role, conf = self._detect_speaker(source_seg["text"])

                # logic_chain: 合并窗口内的相关句子
                relevant = [s for s in window_texts if target in s or any(w in s for w in BULLISH_WORDS + BEARISH_WORDS + NEUTRAL_WORDS)]
                logic_chain = " ".join(relevant)[:120] if relevant else source_seg["text"][:120]

                evidence_type = self._infer_evidence_type(window_combined, direction)

                views.append(InvestmentView(
                    target_name=target,
                    normalized_target_name=target,
                    target_type=entity.entity_type,
                    view_direction=direction,
                    view_direction_label=_direction_label.get(direction, direction),
                    logic_chain=logic_chain,
                    time_horizon="unknown",
                    confidence="cautious",
                    evidence=Evidence(evidence_type=evidence_type, evidence_strength="weak"),
                    risk_warning="",
                    speaker_label=speaker if speaker != "未识别发言人" else "unknown_speaker",
                    speaker_role="podcast_participant" if conf == "low" else role,
                    speaker_confidence=conf,
                    source_quote=source_seg["text"][:100],
                    timestamp_start=source_seg["start"],
                    timestamp_end=source_seg["end"],
                    uncertainty="[规则引擎推断，未经 LLM 验证]" if conf == "low" else "",
                    ai_value_chain_layer="other",
                    technology_driver="",
                    business_impact="unknown",
                    investment_relevance="medium",
                    topic_tags=[],
                    quote_support_strength="medium",
                ))
                used_segments.add(source_idx)

        return views

    def _infer_evidence_type(self, text: str, direction: str) -> str:
        if any(kw in text for kw in ["数据", "财报", "业绩", "报告", "统计", "出货", "增速", "营收", "利润", "ARR", "收入"]):
            return "financial_metric"
        if any(kw in text for kw in ["估值", "PE", "PB", "市值", "溢价", "偏低", "偏高"]):
            return "valuation_metric"
        if any(kw in text for kw in ["增长", "增长率", "增速", "同比", "环比"]):
            return "growth_metric"
        if any(kw in text for kw in ["资本开支", "CapEx", "capex", "数据中心", "基础设施"]):
            return "capex_or_infrastructure"
        if any(kw in text for kw in ["政策", "规定", "监管", "改革", "海外政策", "法规"]):
            return "policy_or_regulation"
        if any(kw in text for kw in ["市场份额", "竞争", "格局", "龙头", "垄断"]):
            return "market_structure"
        if any(kw in text for kw in ["技术", "模型", "算法", "架构", "芯片"]):
            return "technical_claim"
        if direction != "neutral":
            return "expert_judgment"
        return "unsupported_claim"

    def _extract_insights(self, segments: list[dict], entities: list[Entity], full_text: str) -> list:
        """P2-A1: 提取技术/产业洞察（mock 简单版）。"""
        from podcast_research.analysis.models import TechIndustryInsight
        insights = []
        tech_keywords = ["模型", "训练", "推理", "芯片", "云", "数据中心", "agent", "开源", "GPU", "AI", "部署", "工程"]
        tag_keywords = {
            "model": ["模型", "推理", "训练", "大模型"],
            "compute": ["算力", "GPU", "芯片", "H100", "B200"],
            "semiconductor": ["芯片", "半导体", "制程", "晶圆"],
            "cloud": ["云", "多云", "混合云"],
            "agent": ["agent", "Agent", "智能体"],
            "opensource": ["开源", "open source"],
            "enterprise": ["企业", "部署", "落地"],
        }
        for seg in segments:
            hits = sum(1 for kw in tech_keywords if kw in seg["text"])
            if hits >= 2:
                has_view = any(w in seg["text"] for w in BULLISH_WORDS + BEARISH_WORDS + NEUTRAL_WORDS)
                if not has_view:  # 纯技术叙述，不构成投资观点
                    tags = [tag for tag, kws in tag_keywords.items() if any(kw in seg["text"] for kw in kws)]
                    insights.append(TechIndustryInsight(
                        insight=seg["text"][:80],
                        ai_value_chain_layer="other",
                        investment_implication="low",
                        topic_tags=tags[:3],
                        source_quote=seg["text"][:100],
                        timestamp=seg["start"],
                    ))
        return insights[:5]

    def _extract_risks(self, segments: list[dict], full_text: str) -> list[Risk]:
        risks = []
        for seg in segments:
            seg_text = seg["text"]
            risk_hits = [w for w in RISK_WORDS if w in seg_text]
            if not risk_hits:
                continue
            speaker, _, _ = self._detect_speaker(seg_text)
            # 尝试绑定附近标的
            targets = [e.name for e in self._extract_entities(seg_text)]
            target_name = targets[0] if targets else ""
            risks.append(Risk(
                description=f"{', '.join(risk_hits[:2])}相关风险",
                target_name=target_name,
                speaker_label=speaker,
                source_quote=seg_text[:60],
                timestamp=seg["start"],
            ))
        return risks

    def _extract_signals(self, segments: list[dict], entities: list[Entity], full_text: str) -> list[TrackingSignal]:
        signals = []
        for seg in segments:
            seg_text = seg["text"]
            if not any(w in seg_text for w in SIGNAL_WORDS):
                continue
            targets = [e.name for e in entities if e.name in seg_text]
            if not targets:
                continue
            for target in targets:
                signals.append(TrackingSignal(
                    target_name=target,
                    signal=seg_text[:50],
                    trigger_condition="需人工确认",
                    expected_date="待定",
                    source_quote=seg_text[:60],
                    timestamp=seg["start"],
                ))
        return signals

    def _extract_quotes(self, segments: list[dict]) -> list[str]:
        """提取包含投资关键词的原文作为 key_quotes。"""
        quotes = []
        for seg in segments:
            seg_text = seg["text"]
            has_direction = any(w in seg_text for w in BULLISH_WORDS + BEARISH_WORDS + NEUTRAL_WORDS)
            has_target = STOCK_PATTERN.search(seg_text) is not None
            has_signal = any(w in seg_text for w in SIGNAL_WORDS)
            if has_direction or (has_target and has_signal):
                quotes.append(seg_text)
        return quotes[:8]

    def _extract_uncertain(self, segments: list[dict], views: list[InvestmentView]) -> list[str]:
        uncertain = []
        low_conf_views = [v for v in views if v.speaker_confidence == "low"]
        if low_conf_views:
            uncertain.append(f"{len(low_conf_views)} 条观点来自低置信度发言人，需进一步验证")
        no_evidence_views = [v for v in views if v.evidence.evidence_type == "未给依据"]
        if no_evidence_views:
            uncertain.append(f"{len(no_evidence_views)} 条观点未给出明确证据类型，为规则引擎推断")
        return uncertain