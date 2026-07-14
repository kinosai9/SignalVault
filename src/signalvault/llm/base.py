"""LLM Provider 抽象基类。"""

from __future__ import annotations

from signalvault.analysis.models import ExtractionResult


class LLMProvider:
    def extract_facts(self, cleaned_text: str, segments_text: str, focus_areas: list[str] | None = None) -> ExtractionResult:
        raise NotImplementedError

    def render_report(self, extraction: ExtractionResult) -> str:
        raise NotImplementedError

    def translate_text(self, text: str, source_lang: str = "en", target_lang: str = "zh") -> str:
        """Translate text from source_lang to target_lang. Best-effort."""
        raise NotImplementedError
