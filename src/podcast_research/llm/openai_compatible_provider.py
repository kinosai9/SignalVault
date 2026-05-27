"""OpenAI Compatible LLM Provider 预留骨架。

支持任意 OpenAI-compatible API（OpenAI、Claude via proxy、本地模型、Ollama 等）。
P0 不激活此 provider，测试不依赖它。后续接入真实 LLM 时只需配置 .env 即可使用。
"""

from __future__ import annotations

import json
import logging

import httpx

from podcast_research.analysis.models import ExtractionResult
from podcast_research.llm.base import LLMProvider
from podcast_research.llm.prompts import (
    EXTRACT_FACTS_SYSTEM,
    EXTRACT_FACTS_USER,
    RENDER_REPORT_SYSTEM,
    RENDER_REPORT_USER,
)

logger = logging.getLogger(__name__)

_JSON_SCHEMA_HINT = """
输出必须是严格 JSON，schema 如下：
{
  "metadata": {"source": "..."},
  "mentioned_entities": [{"name": "...", "entity_type": "..."}],
  "investment_views": [{"target_name": "...", "target_type": "...", "view_direction": "bullish|bearish|neutral", "logic_chain": "...", "source_quote": "...", "timestamp_start": "...", ...}],
  "risks": [{"description": "...", "target_name": "...", "source_quote": "...", "timestamp": "..."}],
  "tracking_signals": [{"target_name": "...", "signal": "...", "source_quote": "...", "timestamp": "..."}],
  "key_quotes": ["..."],
  "uncertain_items": ["..."]
}
"""


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str = "gpt-4o-mini",
        max_retries: int = 2,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_retries = max_retries
        self.timeout = timeout

    def _chat(self, system: str, user: str) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
        }

        for attempt in range(1, self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(url, headers=headers, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    return data["choices"][0]["message"]["content"]
            except httpx.HTTPStatusError as e:
                logger.warning("LLM API 返回 %d (attempt %d/%d)", e.response.status_code, attempt, self.max_retries)
                if attempt == self.max_retries:
                    raise
            except httpx.RequestError as e:
                logger.warning("LLM 请求失败: %s (attempt %d/%d)", e, attempt, self.max_retries)
                if attempt == self.max_retries:
                    raise

        raise RuntimeError("LLM 调用失败，已达最大重试次数")

    def extract_facts(self, cleaned_text: str, segments_text: str) -> ExtractionResult:
        system = EXTRACT_FACTS_SYSTEM + _JSON_SCHEMA_HINT
        user = EXTRACT_FACTS_USER.format(cleaned_text=segments_text)
        raw = self._chat(system, user)

        # 解析 JSON — LLM 可能在 JSON 前后加 markdown 包装
        json_str = self._strip_markdown_wrapper(raw)
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("LLM 输出 JSON 解析失败，尝试修复")
            data = self._try_repair_json(json_str)

        return ExtractionResult.model_validate(data)

    def render_report(self, extraction: ExtractionResult) -> str:
        extraction_json = json.dumps(extraction.model_dump(), ensure_ascii=False, indent=2)
        system = RENDER_REPORT_SYSTEM
        user = RENDER_REPORT_USER.format(extraction_json=extraction_json)
        return self._chat(system, user)

    def _strip_markdown_wrapper(self, text: str) -> str:
        """去除 LLM 可能添加的 ```json ... ``` 包装。"""
        text = text.strip()
        if text.startswith("```"):
            # 找到第一个换行后的内容
            first_nl = text.index("\n") + 1
            last_backticks = text.rfind("```")
            if last_backticks > first_nl:
                return text[first_nl:last_backticks].strip()
        return text

    def _try_repair_json(self, text: str) -> dict:
        """简单 JSON 修复：截断到最后一个完整的 } 或 ]。"""
        # 找到最后一个 }
        last_brace = text.rfind("}")
        if last_brace > 0:
            try:
                return json.loads(text[:last_brace + 1])
            except json.JSONDecodeError:
                pass
        raise ValueError(f"无法解析 LLM 输出为 JSON: {text[:200]}")