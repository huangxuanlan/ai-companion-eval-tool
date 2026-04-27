from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Any

from openai import OpenAI


_THINK_BLOCK_RE = re.compile(r"(?is)<(?:think|thought)>\s*(.*?)\s*</(?:think|thought)>")
_OPEN_THINK_TAG_RE = re.compile(r"(?is)^\s*<(?:think|thought)>\s*")


def _resolve_env_token(value: str, fallback: str = "") -> str:
    text = str(value or "").strip()
    if text.startswith("${") and text.endswith("}"):
        return os.getenv(text[2:-1], fallback)
    return text or fallback


def _merge_thinking_texts(*parts: str) -> str:
    merged: list[str] = []
    for part in parts:
        text = str(part or "").strip()
        if text and text not in merged:
            merged.append(text)
    return "\n\n".join(merged)


def _split_embedded_thinking(raw_text: str) -> tuple[str, str]:
    text = str(raw_text or "")
    thought_parts: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        thought = match.group(1).strip()
        if thought:
            thought_parts.append(thought)
        return ""

    cleaned = _THINK_BLOCK_RE.sub(_replace, text).strip()
    if thought_parts:
        return cleaned, "\n\n".join(thought_parts)

    if _OPEN_THINK_TAG_RE.match(text):
        return "", _OPEN_THINK_TAG_RE.sub("", text, count=1).strip()

    return text.strip(), ""


def _coerce_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
                continue
            text = getattr(item, "text", None)
            if text:
                parts.append(str(text))
        return "".join(parts)
    return str(content or "")


@dataclass
class LocalProviderResult:
    content: str = ""
    thinking: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency: float = 0.0
    success: bool = True
    error: str = ""


class LocalOpenAIProvider:
    """本地 OpenAI 兼容 Provider，当前用于 Gemma4 31B 本地版。"""

    def __init__(self, model_config: dict):
        self.config = model_config
        self.name = model_config.get("name", "unknown")
        self.display_name = model_config.get("display_name", self.name)
        self.api_config = model_config.get("api", {})
        self.parameters = dict(model_config.get("parameters", {}))
        self.thinking_config = model_config.get("thinking", {})
        self.rate_limit = model_config.get("rate_limit", {})
        self.retry_delays = self.rate_limit.get("retry_delays", [1, 2, 4])

        self.base_url = _resolve_env_token(
            self.api_config.get("base_url", ""),
            "http://115.190.27.75:19006/v1",
        ).rstrip("/")
        self.api_key = _resolve_env_token(
            self.api_config.get("api_key", ""),
            "local-placeholder",
        )
        self.model_name = self.api_config.get("model_name", "gemma4")
        self.max_tokens = self.parameters.get("max_tokens", 4096)
        self.temperature = self.parameters.get("temperature", 0.7)
        self.top_p = self.parameters.get("top_p", 0.95)

        self.client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
        )

    def supports_thinking(self) -> bool:
        return self.thinking_config.get("enabled", True)

    def call_with_retry(
        self,
        messages: list[dict],
        *,
        retry_delays: list[float] | tuple[float, ...] | None = None,
        **kwargs,
    ) -> LocalProviderResult:
        delays = list(self.retry_delays if retry_delays is None else retry_delays)
        for attempt, delay in enumerate(delays + [0]):
            try:
                start_time = time.time()
                result = self.call(messages, **kwargs)
                result.latency = round(time.time() - start_time, 2)
                return result
            except Exception as exc:
                if attempt < len(delays):
                    print(
                        f"[重试] {self.display_name} API调用失败 "
                        f"(尝试 {attempt + 1}/{len(delays) + 1}): {exc}，"
                        f"{delay}秒后重试..."
                    )
                    time.sleep(delay)
                else:
                    return LocalProviderResult(success=False, error=str(exc), latency=0.0)

        return LocalProviderResult(success=False, error="Unknown error")

    def call(self, messages: list[dict], **kwargs) -> LocalProviderResult:
        thinking_effort = str(kwargs.get("thinking_effort", "disabled") or "disabled")
        thinking_enabled = thinking_effort != "disabled" and self.supports_thinking()

        api_kwargs: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "stop": ["<end_of_turn>"],
        }
        if self.max_tokens:
            api_kwargs["max_tokens"] = self.max_tokens

        extra_body: dict[str, Any] = {
            "skip_special_tokens": not thinking_enabled,
        }
        if thinking_enabled:
            extra_body["chat_template_kwargs"] = {"enable_thinking": True}
        if extra_body:
            api_kwargs["extra_body"] = extra_body

        response = self.client.chat.completions.create(**api_kwargs)
        result = self._parse_response(response)
        if thinking_enabled and not result.content and result.thinking:
            raise ValueError("模型只返回了思考内容，缺少最终答案")
        return result

    def _parse_response(self, response: Any) -> LocalProviderResult:
        content_text = ""
        thinking_text = ""

        if response.choices and len(response.choices) > 0:
            message = response.choices[0].message
            raw_content = _coerce_content_text(getattr(message, "content", ""))
            content_text, embedded_thinking = _split_embedded_thinking(raw_content)
            reasoning_content = getattr(message, "reasoning_content", "") or ""
            reasoning_text = getattr(message, "reasoning", "") or ""
            thinking_text = _merge_thinking_texts(
                reasoning_content,
                reasoning_text,
                embedded_thinking,
            )

        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
        output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0

        return LocalProviderResult(
            content=content_text,
            thinking=thinking_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            success=True,
        )
