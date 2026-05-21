"""
ScoringService — 打分管道对接。

评分配置与 few-shot 仍复用 pipeline 目录；
打分提示词正文改为从文档仓版本目录读取，支持前端在线切换版本。
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import inspect
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import partial
from pathlib import Path

import database as db
from config import (
    DEFAULT_AI_SUMMARY_MODEL,
    PIPELINE_SCRIPTS_DIR,
    SCORING_PIPELINE_DIR,
)
from services.model_adapter import ModelAdapter
from services.prompt_version_service import VersionedPromptStore
from services import task_control

PIPELINE_SCRIPTS = PIPELINE_SCRIPTS_DIR
_SCORE_EXCEL_MODULE_NAME = "_score_excel_bridge"


class _AdaptiveConcurrencyLimiter:
    """支持运行中收缩目标并发的轻量限流器。"""

    def __init__(self, target: int):
        self._target = max(1, int(target))
        self._active = 0
        self._condition = asyncio.Condition()

    @property
    def target(self) -> int:
        return self._target

    async def update_target(self, target: int) -> None:
        async with self._condition:
            self._target = max(1, int(target))
            self._condition.notify_all()

    async def acquire(self) -> None:
        async with self._condition:
            await self._condition.wait_for(lambda: self._active < self._target)
            self._active += 1

    async def release(self) -> None:
        async with self._condition:
            self._active = max(0, self._active - 1)
            self._condition.notify_all()

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.release()
        return False


async def invoke_score_turn_compat(
    service,
    turn_payload: dict,
    *,
    timeout_s: float | None = None,
    retry_delays: tuple[float, ...] | list[float] | None = None,
    provider_retry_delays: tuple[float, ...] | list[float] | None = None,
    prompt_version: str = "",
    model_id: str = "",
    thinking_effort: str = "",
) -> dict:
    """
    兼容旧版/过渡版/新版 score_turn 签名。

    旧版只接受 turn_data；
    过渡版只接受 timeout_s/retry_delays；
    新版同时接受 prompt_version/model_id。
    """
    score_turn = service.score_turn
    forwarded = {
        "timeout_s": timeout_s,
        "retry_delays": retry_delays,
        "provider_retry_delays": provider_retry_delays,
        "prompt_version": prompt_version,
        "model_id": model_id,
        "thinking_effort": thinking_effort,
    }
    try:
        signature = inspect.signature(score_turn)
        parameters = signature.parameters
        accepts_var_kwargs = any(
            param.kind == inspect.Parameter.VAR_KEYWORD
            for param in parameters.values()
        )
    except (TypeError, ValueError):
        parameters = {}
        accepts_var_kwargs = False

    if accepts_var_kwargs:
        filtered_kwargs = forwarded
    else:
        filtered_kwargs = {
            key: value for key, value in forwarded.items() if key in parameters
        }

    result = score_turn(turn_payload, **filtered_kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


def _invoke_score_one_sync_compat(
    score_one_sync,
    row: dict,
    *,
    timeout_s: float | None = None,
    retry_delays: tuple[float, ...] | list[float] | None = None,
    provider_retry_delays: tuple[float, ...] | list[float] | None = None,
    prompt_version: str | None = None,
    model_id: str | None = None,
    thinking_effort: str = "",
) -> dict:
    forwarded = {
        "timeout_s": timeout_s,
        "retry_delays": retry_delays,
        "provider_retry_delays": provider_retry_delays,
        "prompt_version": prompt_version,
        "model_id": model_id,
        "thinking_effort": thinking_effort,
    }
    try:
        signature = inspect.signature(score_one_sync)
        parameters = signature.parameters
        accepts_var_kwargs = any(
            param.kind == inspect.Parameter.VAR_KEYWORD
            for param in parameters.values()
        )
    except (TypeError, ValueError):
        parameters = {}
        accepts_var_kwargs = False

    if accepts_var_kwargs:
        filtered_kwargs = forwarded
    else:
        filtered_kwargs = {
            key: value for key, value in forwarded.items() if key in parameters
        }
    return score_one_sync(row, **filtered_kwargs)


def _get_score_excel_module():
    module = sys.modules.get(_SCORE_EXCEL_MODULE_NAME)
    if module is not None:
        return module

    module_path = PIPELINE_SCRIPTS / "score_excel.py"
    spec = importlib.util.spec_from_file_location(
        _SCORE_EXCEL_MODULE_NAME,
        module_path,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 score_excel 模块: {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[_SCORE_EXCEL_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


class ScoringService:
    """打分管道：复用 score_excel.py 核心函数。"""

    def __init__(self):
        self.pipeline_prompt_dir = SCORING_PIPELINE_DIR
        self.prompt_store = VersionedPromptStore(kind="scoring")
        self.scoring_report_prompt_store = VersionedPromptStore(kind="scoring_report")
        self.compare_report_prompt_store = VersionedPromptStore(kind="compare_report")
        self._config = None
        self._client = None
        self._max_workers = self._read_max_workers()
        self._executor = ThreadPoolExecutor(max_workers=self._max_workers)
        self._adaptive_concurrency = self._max_workers
        self._adaptive_limiter: _AdaptiveConcurrencyLimiter | None = None
        self._adaptive_loop: asyncio.AbstractEventLoop | None = None
        self._last_error = ""
        self._default_timeout_s = max(
            1.0,
            float(os.environ.get("SCORING_REQUEST_TIMEOUT_S", "120")),
        )
        self._timeout_fallback_model_id = str(
            os.environ.get("SCORING_TIMEOUT_FALLBACK_MODEL_ID", "gemma4-26b") or ""
        ).strip()
        self._max_tokens = max(
            256,
            int(os.environ.get("SCORING_MAX_TOKENS", "8192")),
        )
        self._default_retry_delays = self._parse_retry_delays(
            os.environ.get("SCORING_RETRY_DELAYS", "5,15,30")
        )
        self._template_cache: dict[str, tuple[str | None, str]] = {}
        self._model_adapter: ModelAdapter | None = None
        self._resolved_scoring_api_keys: list[str] = []
        self._resolved_scoring_api_key = ""
        self._resolved_scoring_base_url = ""
        self._key_index = 0
        self._key_lock = threading.Lock()
        self._adaptive_lock = threading.Lock()
        self._report_generation_locks: dict[str, asyncio.Lock] = {}

    SCORING_REPORT_REQUIRED_SECTIONS = (
        "## 总体统计",
        "## 维度分析",
        "## 逐条打分结果",
        "## Top 3 差评 Case",
        "## Top 3 优秀 Case",
        "## 优化建议",
    )
    COMPARE_REPORT_REQUIRED_MARKERS = (
        "维度分析",
        "概括性结论",
        "逐条对比",
    )

    @staticmethod
    def _read_max_workers() -> int:
        raw = str(os.environ.get("SCORING_MAX_WORKERS", "6") or "").strip()
        try:
            return max(1, min(int(raw), 24))
        except ValueError:
            return 6

    @staticmethod
    def _parse_retry_delays(raw: str) -> tuple[float, ...]:
        delays = []
        for item in str(raw or "").split(","):
            value = item.strip()
            if not value:
                continue
            try:
                delays.append(max(0.0, float(value)))
            except ValueError:
                continue
        return tuple(delays)

    @staticmethod
    def _is_timeout_error(exc: Exception) -> bool:
        text = str(exc or "").strip().lower()
        if not text:
            return isinstance(exc, TimeoutError)
        return isinstance(exc, TimeoutError) or "timed out" in text or "timeout" in text

    @staticmethod
    def _sanitize_error_message(text: str, limit: int = 240) -> str:
        """把上游返回的 HTML 500 页之类噪音，压缩成人类可读的短消息。"""
        msg = str(text or "").strip()
        if not msg:
            return "未知错误"
        lower = msg.lower()
        if "<html" in lower or "nginx" in lower or "internal server error" in lower:
            status_match = re.search(r"\b([45]\d{2})\b", msg)
            code = status_match.group(1) if status_match else "5xx"
            return f"上游打分服务 {code} 错误（稍后重试或切换模型）"
        if len(msg) > limit:
            return msg[:limit].rstrip() + "…"
        return msg

    @staticmethod
    def _is_rate_limit_error(exc: Exception) -> bool:
        text = str(exc or "").strip().lower()
        return "429" in text or "rate limit" in text or "rate_limit" in text

    def _get_model_adapter(self) -> ModelAdapter:
        if self._model_adapter is None:
            self._model_adapter = ModelAdapter()
        return self._model_adapter

    def _resolve_requested_scoring_alias(self, model_id: str | None) -> str:
        score_excel = _get_score_excel_module()
        requested = str(model_id or score_excel.SCORING_MODEL).strip()
        if not requested:
            return ""
        try:
            normalized = self._get_model_adapter().normalize_model_id(requested)
        except Exception:
            normalized = requested
        return str(normalized or requested).strip()

    def _resolve_ai_summary_model_id(self, model_id: str | None) -> str:
        requested = str(model_id or DEFAULT_AI_SUMMARY_MODEL).strip()
        if not requested:
            return DEFAULT_AI_SUMMARY_MODEL
        try:
            normalized = self._get_model_adapter().normalize_model_id(requested)
        except Exception:
            normalized = requested
        return str(normalized or requested).strip() or DEFAULT_AI_SUMMARY_MODEL

    def _get_model_config(self, model_id: str | None) -> dict:
        requested = self._resolve_requested_scoring_alias(model_id)
        if not requested:
            return {}
        try:
            return dict(getattr(self._get_model_adapter(), "_models", {}).get(requested, {}) or {})
        except Exception:
            return {}

    def _resolve_scoring_provider(self, model_id: str | None) -> str:
        model_cfg = self._get_model_config(model_id)
        return str(model_cfg.get("provider", "") or "").strip().lower()

    @staticmethod
    def _resolve_env_reference(value: str | None) -> str:
        raw = str(value or "").strip()
        match = re.fullmatch(r"\$\{([A-Z0-9_]+)\}", raw)
        if match:
            return str(os.environ.get(match.group(1), "") or "").strip()
        return raw

    @staticmethod
    def _extract_env_name(value: str | None) -> str:
        raw = str(value or "").strip()
        match = re.fullmatch(r"\$\{([A-Z0-9_]+)\}", raw)
        return match.group(1) if match else ""

    def _resolve_scoring_base_url(self, model_id: str | None = None) -> str:
        model_cfg = self._get_model_config(model_id)
        api = dict(model_cfg.get("api", {}) or {})
        base_url = self._resolve_env_reference(api.get("base_url", ""))
        if base_url:
            return base_url
        score_excel = _get_score_excel_module()
        return str(getattr(score_excel, "SCORING_BASE_URL", "") or "").strip()

    def _model_supports_thinking(self, model_id: str | None) -> bool:
        model_cfg = self._get_model_config(model_id)
        capabilities = dict(model_cfg.get("capabilities", {}) or {})
        return bool(capabilities.get("thinking", False))

    def _uses_local_scoring_provider(self, model_id: str | None) -> bool:
        return self._resolve_scoring_provider(model_id) == "local_openai"

    def _uses_google_scoring_provider(self, model_id: str | None) -> bool:
        return self._resolve_scoring_provider(model_id) in {"google", "google_gemini", "gemini"}

    def resolve_scoring_thinking_effort(
        self,
        model_id: str | None,
        scoring_thinking_enabled: bool | None,
        scoring_thinking_effort: str | None,
        runtime_scoring_thinking_enabled: bool | None = None,
    ) -> str:
        enabled = (
            scoring_thinking_enabled
            if scoring_thinking_enabled is not None
            else runtime_scoring_thinking_enabled
        )
        adapter = self._get_model_adapter()
        resolver = getattr(adapter, "resolve_thinking_effort", None)
        if callable(resolver):
            return resolver(model_id or "", enabled, scoring_thinking_effort)
        return ModelAdapter.resolve_thinking_effort(
            model_id or "",
            enabled,
            scoring_thinking_effort,
        )

    def _ensure_loaded(
        self,
        require_api_key: bool = True,
        model_id: str | None = None,
    ):
        """懒加载打分配置与客户端。"""
        score_excel = _get_score_excel_module()
        if self._config is None:
            self.prompt_store.ensure_initialized()
            self._config = score_excel.load_scene_config(self.pipeline_prompt_dir)
            self._load_prompt_bundle()
        if not require_api_key:
            self._last_error = ""
            return

        api_keys = self._resolve_scoring_api_keys(model_id)
        api_key = api_keys[0] if api_keys else ""
        if not api_key:
            self._resolved_scoring_api_key = ""
            self._resolved_scoring_api_keys = []
            self._resolved_scoring_base_url = ""
            raise RuntimeError("SCORING_API_KEY 未配置")

        score_excel.SCORING_API_KEY = api_key
        self._resolved_scoring_api_key = api_key
        self._resolved_scoring_api_keys = api_keys
        self._resolved_scoring_base_url = self._resolve_scoring_base_url(model_id)
        self._client = True
        self._last_error = ""

    def _resolve_scoring_api_key(self, model_id: str | None = None) -> str:
        model_cfg = self._get_model_config(model_id)
        api = dict(model_cfg.get("api", {}) or {})
        api_key_env = str(api.get("api_key_env", "") or "").strip()
        if api_key_env:
            provider_key = str(os.environ.get(api_key_env, "") or "").strip()
            if provider_key:
                return provider_key
        inline_key = self._resolve_env_reference(api.get("api_key", ""))
        if inline_key:
            return inline_key
        if self._uses_google_scoring_provider(model_id):
            scoring_key = str(os.environ.get("SCORING_API_KEY", "") or "").strip()
            if scoring_key:
                return scoring_key
            google_key = str(os.environ.get("GOOGLE_API_KEY", "") or "").strip()
            if google_key:
                return google_key
        scoring_key = str(os.environ.get("SCORING_API_KEY", "") or "").strip()
        if scoring_key:
            return scoring_key
        for env_name in ("ARK_API_KEY", "VOLCENGINE_API_KEY"):
            value = str(os.environ.get(env_name, "") or "").strip()
            if value:
                return value
        return ""

    def _resolve_scoring_api_keys(self, model_id: str | None = None) -> list[str]:
        """Resolve the scoring API key pool, preserving priority and de-duplicating."""
        provider = self._resolve_scoring_provider(model_id)
        model_cfg = self._get_model_config(model_id)
        api = dict(model_cfg.get("api", {}) or {})
        env_candidates: list[str] = []

        if provider in {"google", "google_gemini", "gemini"}:
            env_candidates.extend(
                [
                    "SCORING_API_KEYS",
                    "SCORING_API_KEY",
                    "GOOGLE_API_KEYS",
                    "GOOGLE_API_KEY",
                ]
            )
        else:
            api_key_env = str(api.get("api_key_env", "") or "").strip()
            if not api_key_env:
                api_key_env = self._extract_env_name(api.get("api_key", ""))
            if api_key_env.endswith("_API_KEY"):
                # 例：VOLCENGINE_API_KEY -> VOLCENGINE_API_KEYS（保留下划线分隔）
                env_candidates.append(f"{api_key_env}S")

        resolved: list[str] = []
        seen: set[str] = set()
        for env_name in env_candidates:
            raw = str(os.environ.get(env_name, "") or "").strip()
            for key in (item.strip() for item in raw.split(",")):
                if not key or key in seen:
                    continue
                seen.add(key)
                resolved.append(key)
        if resolved:
            return resolved

        single = self._resolve_scoring_api_key(model_id)
        return [single] if single else []

    def _resolve_scoring_model_id(self, model_id: str | None) -> str:
        """将前端/运行时使用的模型别名解析为真实 API endpoint。"""
        requested = self._resolve_requested_scoring_alias(model_id)
        if not requested:
            return requested
        model_cfg = self._get_model_config(requested)
        api = dict(model_cfg.get("api", {}) or {})
        provider = str(model_cfg.get("provider", "") or "").strip().lower()
        if provider in {"aliyun", "dashscope"}:
            # DashScope 的兼容接口仍要求使用原始模型 id，例如 qwen-plus。
            resolved = api.get("model") or requested
            return str(resolved).strip()
        resolved = (
            api.get("model_name")
            or api.get("model")
            or model_cfg.get("name")
            or requested
        )
        return str(resolved).strip()

    def _load_prompt_bundle(
        self,
        prompt_version: str | None = None,
    ) -> tuple[str | None, str]:
        """按打分提示词版本解析 system/user 模板。"""
        self.prompt_store.ensure_initialized()
        resolved = self.prompt_store.resolve_filename(prompt_version or "latest")
        if resolved in self._template_cache:
            return self._template_cache[resolved]

        score_excel = _get_score_excel_module()
        prompt_path = self.prompt_store.download_path(resolved)
        full_template = prompt_path.read_text(encoding="utf-8")
        normalizer = getattr(score_excel, "_normalize_longform_scoring_template", None)
        if callable(normalizer):
            full_template = normalizer(full_template)

        examples_path = self.pipeline_prompt_dir / "examples_v3.json"
        if not examples_path.exists():
            examples_path = self.pipeline_prompt_dir / "examples_v2.json"
        examples = []
        if examples_path.exists():
            data = json.loads(examples_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                examples = data
            elif isinstance(data, dict):
                examples = data.get("examples", [])

        examples_block = ""
        if examples:
            blocks = ["---\n\n# 评分参考示例 (Few-Shot)\n"]
            for ex in examples:
                desc = ex.get("description", "")
                inp = ex.get("input", {})
                expected = ex.get("expected_output", {})
                blocks.append(f"## {desc}\n")
                blocks.append(
                    f"**角色**: {inp.get('Role_Nickname', '')} | "
                    f"**关系**: {inp.get('relationship', '')} | "
                    f"**性格**: {inp.get('personality', '')}\n"
                )
                blocks.append(f"**用户输入**: {inp.get('user_input', '')}\n")
                blocks.append(f"**AI输出**: {inp.get('output', '')}\n")
                blocks.append(f"**AI思考**: {inp.get('thinking', '')}\n")
                blocks.append(
                    "**参考评分**:\n```json\n"
                    f"{json.dumps(expected, ensure_ascii=False, indent=2)}\n```\n"
                )
            examples_block = "\n".join(blocks)

        eval_start = full_template.find("<evaluation_input>")
        eval_end = full_template.find("</evaluation_input>")
        if eval_start == -1 or eval_end == -1:
            bundle = (None, full_template)
            self._template_cache[resolved] = bundle
            return bundle

        before_eval = full_template[:eval_start].strip()
        after_eval = full_template[eval_end + len("</evaluation_input>"):].strip()
        system_prompt = before_eval + "\n\n" + examples_block + "\n\n" + after_eval
        user_template = full_template[eval_start:eval_end + len("</evaluation_input>")]
        bundle = (system_prompt, user_template)
        self._template_cache[resolved] = bundle
        return bundle

    def is_available(self, model_id: str | None = None) -> bool:
        """检查打分脚本与当前提示词是否可用。"""
        if not PIPELINE_SCRIPTS.exists():
            self._last_error = f"打分脚本目录不存在: {PIPELINE_SCRIPTS}"
            return False
        try:
            score_excel = _get_score_excel_module()
            self.prompt_store.ensure_initialized()
            score_excel.load_scene_config(self.pipeline_prompt_dir)
            self._load_prompt_bundle()
            require_api_key = not self._uses_local_scoring_provider(model_id)
            if require_api_key and not self._resolve_scoring_api_key(model_id):
                self._last_error = "SCORING_API_KEY 未配置"
                return False
            self._ensure_loaded(require_api_key=require_api_key, model_id=model_id)
            self._last_error = ""
            return True
        except Exception as exc:
            self._last_error = str(exc)
            return False

    def get_last_error(self) -> str:
        return self._last_error

    def get_scoring_prompts(self) -> list[str]:
        return [item["filename"] for item in self.prompt_store.list_versions()["prompts"]]

    def get_prompt_meta(self) -> dict:
        listing = self.prompt_store.list_versions()
        return {
            "active_filename": listing.get("active_filename", ""),
            "latest_filename": listing.get("latest_filename", ""),
        }

    def get_max_workers(self) -> int:
        return self._max_workers

    def set_max_workers(self, n: int) -> int:
        next_value = max(1, min(int(n), 24))
        with self._adaptive_lock:
            if next_value == self._max_workers:
                return self._max_workers
            old_executor = self._executor
            self._max_workers = next_value
            self._adaptive_concurrency = next_value
            self._executor = ThreadPoolExecutor(max_workers=next_value)
        old_executor.shutdown(wait=False, cancel_futures=False)
        return self._max_workers

    def _bind_adaptive_limiter(
        self,
        limiter: _AdaptiveConcurrencyLimiter,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        with self._adaptive_lock:
            self._adaptive_limiter = limiter
            self._adaptive_loop = loop
            self._adaptive_concurrency = limiter.target

    def _clear_adaptive_limiter(self) -> None:
        with self._adaptive_lock:
            self._adaptive_limiter = None
            self._adaptive_loop = None
            self._adaptive_concurrency = self._max_workers

    def _on_rate_limit(self, model_alias: str) -> int:
        with self._adaptive_lock:
            current = max(1, int(self._adaptive_concurrency or self._max_workers))
            next_value = max(1, current // 2)
            limiter = self._adaptive_limiter
            loop = self._adaptive_loop
            if next_value == current:
                return current
            self._adaptive_concurrency = next_value
        print(f"  [限流] {model_alias or 'unknown'} 命中 429，并发 {current} -> {next_value}")
        if limiter and loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(
                limiter.update_target(next_value),
                loop,
            )
        return next_value

    def get_dimensions(self, model_id: str | None = None) -> dict:
        self._ensure_loaded(
            require_api_key=not self._uses_local_scoring_provider(model_id),
            model_id=model_id,
        )
        return {
            "dimensions": self._config.get("dimensions", []),
            "weights": self._config.get("weights", {}),
            "dims_display": self._config.get("dims_display", {}),
        }

    def _get_client(
        self,
        timeout_s: float | None = None,
        model_id: str | None = None,
    ):
        self._ensure_loaded(require_api_key=True, model_id=model_id)
        # round-robin 选 Key
        keys = self._resolved_scoring_api_keys or [self._resolved_scoring_api_key]
        with self._key_lock:
            ki = self._key_index % len(keys)
            self._key_index += 1
        chosen_key = keys[ki]

        from openai import OpenAI

        client_kwargs = {
            "base_url": self._resolved_scoring_base_url,
            "api_key": chosen_key,
            "timeout": timeout_s or self._default_timeout_s,
        }
        try:
            signature = inspect.signature(OpenAI)
            parameters = signature.parameters
            accepts_var_kwargs = any(
                param.kind == inspect.Parameter.VAR_KEYWORD
                for param in parameters.values()
            )
        except (TypeError, ValueError):
            parameters = {}
            accepts_var_kwargs = True
        if accepts_var_kwargs or "max_retries" in parameters:
            client_kwargs["max_retries"] = 0
        return OpenAI(**client_kwargs)

    def _call_scoring_via_openai(
        self,
        *,
        model_alias: str,
        candidate_model: str,
        system_prompt: str | None,
        user_content: str,
        thinking_effort: str = "",
        timeout_s: float | None = None,
    ) -> dict:
        client = self._get_client(timeout_s=timeout_s, model_id=model_alias)
        start = time.time()
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_content})

        request_kwargs = {
            "model": candidate_model,
            "max_tokens": self._max_tokens,
            "temperature": 0,
            "messages": messages,
        }
        provider = self._resolve_scoring_provider(model_alias)
        if (
            thinking_effort
            and thinking_effort != "disabled"
            and self._model_supports_thinking(model_alias)
        ):
            if provider in {"google", "google_gemini", "nvidia"}:
                request_kwargs["reasoning_effort"] = thinking_effort
            elif provider in {"aliyun", "dashscope", "volcengine", ""}:
                budget_map = {"low": 256, "medium": 1024, "high": 4096}
                extra_body = dict(request_kwargs.get("extra_body", {}) or {})
                extra_body["enable_thinking"] = True
                if thinking_effort in budget_map:
                    extra_body["thinking_budget"] = budget_map[thinking_effort]
                request_kwargs["extra_body"] = extra_body

        response = client.chat.completions.create(**request_kwargs)
        latency = round(time.time() - start, 2)
        message = response.choices[0].message
        raw = message.content or ""
        reasoning_raw = getattr(message, "reasoning_content", "") or ""
        parsed = self._parse_score_payload(raw)
        if parsed.get("_parse_failed"):
            raise RuntimeError(f"JSON 解析失败，触发重试: {raw[:120]}")
        usage = response.usage
        return {
            **parsed,
            "raw_response": raw,
            "reasoning_content": reasoning_raw,
            "input_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
            "output_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
            "latency": latency,
            "success": True,
            "error": None,
            "model_id": candidate_model,
        }

    def _call_scoring_via_model_adapter(
        self,
        *,
        candidate_alias: str,
        system_prompt: str | None,
        user_content: str,
        thinking_effort: str = "",
        provider_retry_delays: tuple[float, ...] | list[float] | None = None,
    ) -> dict:
        adapter = self._get_model_adapter()
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_content})
        request_kwargs = {
            "max_tokens": self._max_tokens,
            "thinking_effort": thinking_effort or "disabled",
            "temperature": 0,
            "top_p": 1,
        }
        if provider_retry_delays is not None:
            request_kwargs["provider_retry_delays"] = provider_retry_delays
        result = adapter.chat(candidate_alias, messages, **request_kwargs)
        if not result.success:
            raise RuntimeError(result.error or f"{candidate_alias} 打分调用失败")
        parsed = self._parse_score_payload(result.content or "")
        if parsed.get("_parse_failed"):
            raise RuntimeError(f"JSON 解析失败，触发重试: {(result.content or '')[:120]}")
        return {
            **parsed,
            "raw_response": result.content or "",
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "latency": result.latency_s,
            "success": True,
            "error": None,
            "model_id": candidate_alias,
        }

    @staticmethod
    def _extract_balanced_json_objects(text: str) -> list[str]:
        """提取文本中所有花括号平衡的 JSON 对象，优先供多对象场景取最后一个。"""
        candidates: list[str] = []
        source = str(text or "").strip()
        if not source:
            return candidates

        start: int | None = None
        depth = 0
        in_string = False
        escape = False

        for idx, ch in enumerate(source):
            if escape:
                escape = False
                continue
            if ch == "\\" and in_string:
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                if depth == 0:
                    start = idx
                depth += 1
                continue
            if ch != "}":
                continue
            if depth <= 0:
                continue
            depth -= 1
            if depth == 0 and start is not None:
                candidates.append(source[start : idx + 1])
                start = None
        return candidates

    @staticmethod
    def _repair_json(text: str) -> str:
        """修复常见 JSON 格式问题：围栏、前后文字、尾部截断。"""
        text = text.strip()
        text = re.sub(r'^```(?:json)?\s*\n?', '', text)
        text = re.sub(r'\n?```\s*$', '', text)
        balanced = ScoringService._extract_balanced_json_objects(text)
        if balanced:
            return balanced[-1]
        start = text.find('{')
        if start == -1:
            return text
        text = text[start:]
        # 补齐未闭合的花括号（覆盖尾部截断场景）
        unclosed = text.count('{') - text.count('}')
        if unclosed > 0:
            text += '}' * unclosed
        return text

    def _parse_score_payload(self, text: str) -> dict:
        score_excel = _get_score_excel_module()
        extractors = [
            lambda t: json.loads(t.strip()),
            lambda t: json.loads(
                re.search(r"```(?:json)?\s*\n?(.*?)\n?```", t, re.DOTALL).group(1).strip()
            ),
            lambda t: json.loads(self._repair_json(t)),
        ]
        for extractor in extractors:
            try:
                return score_excel.validate_scores(extractor(text), self._config)
            except Exception:
                continue
        return {
            "scores": {d: 0 for d in self._config.get("dimensions", [])},
            "weighted_total": 0,
            "mapped_total": 0,
            "reasoning": f"[JSON解析失败] {text[:300]}",
            "_parse_failed": True,
        }

    @staticmethod
    def _build_history_context(
        results: list[dict],
        current_index: int,
        *,
        max_turns: int = 10,
        max_chars: int = 8000,
    ) -> str:
        start = max(0, int(current_index or 0) - max(1, int(max_turns or 10)))
        history_turns = list(results[start:int(current_index or 0)] or [])
        if not history_turns:
            return ""

        lines: list[str] = []
        for item in history_turns:
            user_input = str(item.get("user_input", "") or "").strip()
            ai_output = str(item.get("ai_output", "") or "").strip()
            if user_input:
                lines.append(f"[用户] {user_input}")
            if ai_output:
                lines.append(f"[AI] {ai_output}")
        history = "\n".join(lines)
        max_chars = max(256, int(max_chars or 8000))
        if len(history) > max_chars:
            history = history[-max_chars:]
        return history

    def _call_scoring_api(
        self,
        *,
        system_prompt: str | None,
        user_content: str,
        model_id: str | None = None,
        thinking_effort: str = "",
        timeout_s: float | None = None,
        retry_delays: tuple[float, ...] | list[float] | None = None,
        provider_retry_delays: tuple[float, ...] | list[float] | None = None,
    ) -> dict:
        score_excel = _get_score_excel_module()
        effective_thinking_effort = self.resolve_scoring_thinking_effort(
            model_id,
            None,
            thinking_effort,
            None,
        )

        delays = (
            tuple(retry_delays)
            if retry_delays is not None
            else self._default_retry_delays
        )
        requested_alias = self._resolve_requested_scoring_alias(model_id)
        requested_provider = self._resolve_scoring_provider(model_id)
        requested_model = self._resolve_scoring_model_id(model_id)
        fallback_alias = self._resolve_requested_scoring_alias(self._timeout_fallback_model_id)
        fallback_provider = self._resolve_scoring_provider(self._timeout_fallback_model_id)
        fallback_model = self._resolve_scoring_model_id(self._timeout_fallback_model_id)
        if (
            not fallback_model
            or (
                fallback_model == requested_model
                and fallback_alias == requested_alias
            )
        ):
            fallback_alias = ""
            fallback_provider = ""
            fallback_model = ""

        last_error: Exception | None = None
        candidate_models = [
            {
                "alias": requested_alias or requested_model,
                "provider": requested_provider,
                "resolved_model": requested_model,
                "public_model_id": (
                    requested_alias or requested_model
                    if requested_provider == "local_openai"
                    else requested_model
                ),
            }
        ]
        for candidate_index, candidate in enumerate(candidate_models):
            timeout_fallback_triggered = False
            for attempt, delay in enumerate(list(delays) + [None], start=1):
                try:
                    if candidate["provider"] == "local_openai":
                        return self._call_scoring_via_model_adapter(
                            candidate_alias=candidate["alias"],
                            system_prompt=system_prompt,
                            user_content=user_content,
                            thinking_effort=effective_thinking_effort,
                            provider_retry_delays=provider_retry_delays,
                        )
                    return self._call_scoring_via_openai(
                        model_alias=candidate["alias"],
                        candidate_model=candidate["resolved_model"],
                        system_prompt=system_prompt,
                        user_content=user_content,
                        thinking_effort=effective_thinking_effort,
                        timeout_s=timeout_s,
                    )
                except Exception as exc:
                    last_error = exc
                    if self._is_rate_limit_error(exc):
                        self._on_rate_limit(candidate["alias"] or candidate["resolved_model"])
                    if (
                        candidate_index == 0
                        and fallback_model
                        and candidate["resolved_model"] != fallback_model
                        and self._is_timeout_error(exc)
                    ):
                        print(f"  [降级] 打分模型超时: {candidate['public_model_id']} -> {fallback_alias or fallback_model}")
                        timeout_fallback_triggered = True
                        break
                    if delay is None:
                        break
                    print(f"  [重试] 打分失败 ({attempt}): {exc}，{delay}s 后重试")
                    time.sleep(delay)
            if timeout_fallback_triggered:
                candidate_models.append(
                    {
                        "alias": fallback_alias or fallback_model,
                        "provider": fallback_provider,
                        "resolved_model": fallback_model,
                        "public_model_id": (
                            fallback_alias or fallback_model
                            if fallback_provider == "local_openai"
                            else fallback_model
                        ),
                    }
                )

        final_error = self._sanitize_error_message(str(last_error or "未知错误"))
        return {
            "scores": {d: 0 for d in self._config.get("dimensions", [])},
            "weighted_total": 0,
            "mapped_total": 0,
            "reasoning": f"[打分失败] {final_error}",
            "latency": 0,
            "success": False,
            "error": final_error,
            "model_id": candidate_models[-1]["public_model_id"],
        }

    def _score_one_sync(
        self,
        row: dict,
        timeout_s: float | None = None,
        retry_delays: tuple[float, ...] | list[float] | None = None,
        provider_retry_delays: tuple[float, ...] | list[float] | None = None,
        prompt_version: str | None = None,
        model_id: str | None = None,
        thinking_effort: str = "",
    ) -> dict:
        """同步打分单条数据（在线程池中执行）。"""
        score_excel = _get_score_excel_module()

        self._ensure_loaded(
            require_api_key=not self._uses_local_scoring_provider(model_id),
            model_id=model_id,
        )
        score_excel._active_config = self._config
        system_prompt, user_template = self._load_prompt_bundle(prompt_version)

        user_content = (
            score_excel.fill_user_prompt(user_template, row, self._config)
            if system_prompt
            else user_template
        )
        if not system_prompt:
            filled = user_template
            for key, value in row.items():
                filled = filled.replace(f"{{{{{key}}}}}", str(value) if value else "")
            user_content = filled

        result = self._call_scoring_api(
            system_prompt=system_prompt,
            user_content=user_content,
            model_id=model_id,
            thinking_effort=thinking_effort,
            timeout_s=timeout_s,
            retry_delays=retry_delays,
            provider_retry_delays=provider_retry_delays,
        )

        dims = self._config.get("dimensions", [])
        if result["success"]:
            scores = result["scores"]
            return {
                "success": True,
                "scores": {d: scores.get(d, 0) for d in dims},
                "weighted_total": result["weighted_total"],
                "mapped_total": result["mapped_total"],
                "reasoning": result["reasoning"],
                "reasoning_content": result.get("reasoning_content", ""),
                "latency": result["latency"],
                "model_id": result.get("model_id", model_id or ""),
                "score_status": "scored",
            }
        sanitized_error = self._sanitize_error_message(result.get("error", ""))
        return {
            "success": False,
            "scores": {d: 0 for d in dims},
            "weighted_total": 0,
            "mapped_total": 0,
            "reasoning": f"[打分失败] {sanitized_error}",
            "reasoning_content": result.get("reasoning_content", ""),
            "latency": 0,
            "error": sanitized_error,
            "model_id": result.get("model_id", model_id or ""),
            "score_status": "failed",
        }

    async def score_turn(
        self,
        turn_data: dict,
        timeout_s: float | None = None,
        retry_delays: tuple[float, ...] | list[float] | None = None,
        provider_retry_delays: tuple[float, ...] | list[float] | None = None,
        prompt_version: str | None = None,
        model_id: str | None = None,
        thinking_effort: str = "",
    ) -> dict:
        """异步打分单轮。"""
        self._ensure_loaded(
            require_api_key=not self._uses_local_scoring_provider(model_id),
            model_id=model_id,
        )
        config = self._config
        alias = config.get("column_alias", {})

        row = {
            alias.get("user_message", "用户输入"): turn_data.get("user_input", ""),
            alias.get("output", "AI输出"): turn_data.get("ai_output", ""),
            "测试对应提示词": turn_data.get("prompt_name", ""),
            "轮次": turn_data.get("turn", 0),
            "Role_Nickname": turn_data.get("role_name", ""),
            "personality": turn_data.get("personality", ""),
            "relationship": turn_data.get("relationship", ""),
            "dialogueStartPrompt": turn_data.get("dialogueStartPrompt", ""),
            "moments": turn_data.get("moments", ""),
            "dialogue_summary": turn_data.get("dialogue_summary", ""),
            alias.get("history_context", "近期对话历史"): turn_data.get("history_context", ""),
        }

        loop = asyncio.get_event_loop()
        score_call = partial(
            _invoke_score_one_sync_compat,
            self._score_one_sync,
            row,
            timeout_s=timeout_s,
            retry_delays=retry_delays,
            provider_retry_delays=provider_retry_delays,
            prompt_version=prompt_version,
            model_id=model_id,
            thinking_effort=thinking_effort,
        )
        return await loop.run_in_executor(
            self._executor,
            score_call,
        )

    async def score_conversation(
        self,
        conv_id: str,
        results: list,
        config: dict,
        on_progress=None,
        max_workers: int | None = None,
    ) -> list[dict]:
        """批量打分整个对话，支持进度回调。"""
        runtime = config.get("runtime", {})
        scoring_model_id = runtime.get("scoring_model_id", "")
        self._ensure_loaded(
            require_api_key=not self._uses_local_scoring_provider(scoring_model_id or None),
            model_id=scoring_model_id or None,
        )
        char = config.get("character", {})
        ctx = config.get("context", {})
        prompt_version = runtime.get("scoring_prompt_version", "")
        scoring_thinking_effort = self.resolve_scoring_thinking_effort(
            scoring_model_id,
            runtime.get("scoring_thinking_enabled", None),
            runtime.get("scoring_thinking_effort", ""),
            None,
        )
        total = len(results)
        dims = self._config.get("dimensions", [])
        requested_workers = max_workers
        if requested_workers is None:
            requested_workers = runtime.get("scoring_max_workers", None)
        if requested_workers is not None:
            self.set_max_workers(requested_workers)
        active_workers = self.get_max_workers()
        retry_count = runtime.get("scoring_retry_count", 3)
        try:
            max_attempts = max(1, int(retry_count))
        except (TypeError, ValueError):
            max_attempts = 3
        retry_schedule = self._default_retry_delays or (5.0, 15.0, 30.0)
        limiter = _AdaptiveConcurrencyLimiter(active_workers)
        progress_lock = asyncio.Lock()
        progress_state = {"current": 0, "failed": 0, "skipped": 0}
        self._bind_adaptive_limiter(limiter, asyncio.get_running_loop())
        control_id = f"score_{conv_id}"

        async def _score_one(index: int, result: dict) -> dict:
            turn_number = result.get("turn", index + 1)
            turn_data = {
                "user_input": result.get("user_input", ""),
                "ai_output": result.get("ai_output", ""),
                "turn": turn_number,
                "role_name": char.get("Role_Nickname", ""),
                "personality": char.get("personality", ""),
                "relationship": ctx.get("relationship", ""),
                "prompt_name": config.get("prompt_file", ""),
                "dialogueStartPrompt": dict(config.get("modules", {}) or {}).get("dialogueStartPrompt", ""),
                "moments": dict(config.get("modules", {}) or {}).get("moments", ""),
                "dialogue_summary": result.get("dialogue_summary", runtime.get("latest_dialogue_summary", "")),
                "history_context": self._build_history_context(results, index),
            }
            if not str(turn_data.get("ai_output", "") or "").strip():
                score_result = {
                    "success": False,
                    "scores": {d: 0 for d in dims},
                    "weighted_total": 0,
                    "mapped_total": 0,
                    "reasoning": "[跳过] ai_output 为空，未发起打分",
                    "reasoning_content": "",
                    "error": "",
                    "model_id": scoring_model_id,
                    "score_status": "skipped",
                }
            else:
                score_result = None
                for attempt in range(1, max_attempts + 1):
                    try:
                        async with limiter:
                            score_result = await self.score_turn(
                                turn_data,
                                prompt_version=prompt_version,
                                model_id=scoring_model_id,
                                thinking_effort=scoring_thinking_effort,
                            )
                    except Exception as turn_exc:
                        sanitized_err = self._sanitize_error_message(str(turn_exc))
                        print(f"  [打分异常] 轮次 {turn_number}: {sanitized_err}")
                        score_result = {
                            "success": False,
                            "scores": {d: 0 for d in dims},
                            "weighted_total": 0,
                            "mapped_total": 0,
                            "reasoning": f"[打分异常] {sanitized_err}",
                            "reasoning_content": "",
                            "error": sanitized_err,
                            "model_id": scoring_model_id,
                            "score_status": "failed",
                        }
                    if score_result.get("success") or score_result.get("score_status") == "skipped":
                        break
                    if attempt >= max_attempts:
                        break
                    delay_s = retry_schedule[min(attempt - 1, len(retry_schedule) - 1)]
                    if on_progress:
                        await on_progress(
                            {
                                "type": "retry",
                                "turn": turn_number,
                                "attempt": attempt,
                                "max_retries": max_attempts,
                                "next_delay_s": delay_s,
                            }
                        )
                    await asyncio.sleep(delay_s)

            async with progress_lock:
                progress_state["current"] += 1
                if score_result.get("score_status") == "skipped":
                    progress_state["skipped"] += 1
                elif not score_result.get("success", False):
                    progress_state["failed"] += 1
                current = progress_state["current"]
                failed = progress_state["failed"]
                skipped = progress_state["skipped"]
            if on_progress:
                await on_progress(
                    {
                        "type": "score_progress",
                        "turn": turn_number,
                        "total": total,
                        "current": current,
                        "score": score_result.get("mapped_total", 0),
                        "success": score_result.get("success", False),
                        "failed_count": failed,
                        "skipped_count": skipped,
                    }
                )
            return {"turn": turn_number, **score_result}

        try:
            if total <= 0:
                return []

            next_index = 0
            next_index_lock = asyncio.Lock()
            completed: list[tuple[int, dict]] = []

            async def _worker():
                nonlocal next_index
                while True:
                    ctrl = task_control.get(control_id)
                    if ctrl:
                        try:
                            await ctrl.checkpoint()
                        except asyncio.CancelledError:
                            return
                    async with next_index_lock:
                        if next_index >= total:
                            return
                        current_index = next_index
                        next_index += 1
                    item = await _score_one(current_index, results[current_index])
                    completed.append((current_index, item))

            worker_count = max(1, min(active_workers, total))
            await asyncio.gather(*[_worker() for _ in range(worker_count)])
            completed.sort(key=lambda item: item[0])
            return [item for _, item in completed]
        finally:
            self._clear_adaptive_limiter()

    async def score_rows(
        self,
        rows: list[dict],
        on_progress=None,
        model_id: str | None = None,
        prompt_version: str | None = None,
        thinking_effort: str = "",
    ) -> list[dict]:
        """直接按现成 row 数据批量打分。"""
        self._ensure_loaded(
            require_api_key=not self._uses_local_scoring_provider(model_id),
            model_id=model_id,
        )
        loop = asyncio.get_event_loop()
        scored_rows = []
        total = len(rows)
        active_prompt = prompt_version or self.prompt_store.get_active_filename()

        for idx, row in enumerate(rows, start=1):
            score_call = partial(
                _invoke_score_one_sync_compat,
                self._score_one_sync,
                row,
                timeout_s=None,
                retry_delays=None,
                provider_retry_delays=None,
                prompt_version=active_prompt,
                model_id=model_id,
                thinking_effort=thinking_effort,
            )
            result = await loop.run_in_executor(
                self._executor,
                score_call,
            )
            scored_rows.append({**row, **result})
            if on_progress:
                await on_progress(
                    {
                        "type": "score_progress",
                        "current": idx,
                        "total": total,
                        "score": result.get("mapped_total", 0),
                    }
                )
        return scored_rows

    # ──────────────────────────────────────────
    # AI 摘要报告生成
    # ──────────────────────────────────────────
    @staticmethod
    def _read_report_prompt_template(
        store: VersionedPromptStore,
        prompt_version: str | None = None,
    ) -> tuple[str, str]:
        prompt_data = store.read_prompt(prompt_version or "latest")
        return prompt_data["filename"], prompt_data["content"]

    @staticmethod
    def _fill_prompt_template(template: str, replacements: dict[str, str]) -> str:
        rendered = str(template or "")
        for key, value in replacements.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
        return rendered

    @staticmethod
    def _extract_markdown_report(raw_text: str) -> str:
        text = str(raw_text or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text, count=1).strip()
            text = re.sub(r"\s*```$", "", text, count=1).strip()
        return text

    @staticmethod
    def _validate_markdown_report(
        markdown: str,
        required_markers: tuple[str, ...],
    ) -> None:
        missing_sections = [section for section in required_markers if section not in markdown]
        if missing_sections:
            raise ValueError(f"报告缺少必要章节: {', '.join(missing_sections)}")

    @staticmethod
    def _build_source_signature(payload: dict) -> str:
        stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha1(stable.encode("utf-8")).hexdigest()

    async def _generate_report_markdown(
        self,
        *,
        model_id: str,
        prompt: str,
        max_tokens: int = 4096,
    ) -> str:
        adapter = self._get_model_adapter()
        loop = asyncio.get_event_loop()

        def _call():
            return adapter.chat(
                model_id,
                [{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.2,
            )

        result = await loop.run_in_executor(self._executor, _call)
        if not result.success:
            raise RuntimeError(result.error or "AI 摘要生成失败")
        return self._extract_markdown_report(result.content or "")

    def _build_summary_dimension_stats(self, success_items: list[dict]) -> list[dict]:
        weights = dict((self._config or {}).get("weights", {}) or {})
        dim_keys = list((self._config or {}).get("dimensions", []) or [])
        if not dim_keys:
            dim_keys = list(weights.keys())
        if not dim_keys and success_items:
            dim_keys = list((success_items[0].get("scores", {}) or {}).keys())
        dim_labels = dict((self._config or {}).get("dims_display", {}) or {})
        stats: list[dict] = []
        for dim_key in dim_keys:
            values = [
                float(item.get("scores", {}).get(dim_key, 0) or 0)
                for item in success_items
            ]
            if not values:
                continue
            weight = weights.get(dim_key)
            stats.append(
                {
                    "key": dim_key,
                    "label": dim_labels.get(dim_key, dim_key),
                    "weight": f"{round(float(weight) * 100)}%" if isinstance(weight, (int, float)) else "-",
                    "avg_score": round(sum(values) / len(values), 2),
                    "mapped_avg_score": round(sum(values) / len(values) * 2, 2),
                    "max_score": round(max(values), 2),
                    "min_score": round(min(values), 2),
                }
            )
        return stats

    @staticmethod
    def _build_summary_case_items(
        scored_items: list[dict],
        dimension_order: list[str] | tuple[str, ...],
    ) -> list[dict]:
        items = []
        for item in scored_items:
            raw_status = str(item.get("status", "") or "").strip().lower()
            success = raw_status == "scored" or bool(item.get("success", False))
            total = float(item.get("mapped_total", 0) or 0)
            status = (
                "✅" if success and total >= 8
                else "❌" if success
                else "FAIL" if raw_status == "failed"
                else "⏳"
            )
            item_scores = dict(item.get("scores", {}) or {})
            items.append(
                {
                    "case_id": item.get("turn"),
                    "case_type": f"Turn {item.get('turn')}",
                    "total": round(total, 2) if success else "N/A",
                    "status": status,
                    "dimensions": {
                        key: round(float(item_scores.get(key, 0) or 0), 2) if success else "N/A"
                        for key in dimension_order
                    },
                    "reasoning": str(item.get("reasoning", "") or "").strip(),
                    "success": success,
                }
            )
        return items

    @staticmethod
    def _build_summary_report_meta(
        scored_items: list[dict],
        success_items: list[dict],
        config: dict,
        model_id: str,
        prompt_filename: str,
        pass_threshold: float = 8.0,
    ) -> dict:
        runtime = dict(config.get("runtime", {}) or {})
        totals = [float(item.get("mapped_total", 0) or 0) for item in success_items]
        failed_count = len([
            item for item in scored_items
            if str(item.get("status", "") or "").strip().lower() == "failed"
        ])
        pending_count = len(scored_items) - len(success_items) - failed_count
        prompt_name = str(config.get("prompt_file", "") or runtime.get("prompt_version", "") or "").strip()
        role_name = str(config.get("character", {}).get("Role_Nickname", "") or "未知角色").strip()
        pass_count = len([score for score in totals if score >= pass_threshold])
        report_title = Path(prompt_name).stem if prompt_name else role_name
        task_status = "已完成" if failed_count == 0 and pending_count == 0 else "部分完成"
        return {
            "report_title": report_title,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "task_status": task_status,
            "generation_model": runtime.get("model_id", "") or runtime.get("model_ids", [""])[0] or model_id,
            "scoring_model": runtime.get("scoring_model_id", "") or model_id,
            "scoring_prompt": runtime.get("scoring_prompt_version", "") or config.get("scoring_prompt_version", ""),
            "total_cases": len(scored_items),
            "scored_cases": len(success_items),
            "failed_cases": failed_count,
            "pending_cases": pending_count,
            "avg_total": round(sum(totals) / len(totals), 2) if totals else 0,
            "max_total": round(max(totals), 2) if totals else 0,
            "min_total": round(min(totals), 2) if totals else 0,
            "pass_threshold": f"{pass_threshold:.1f}",
            "pass_count": pass_count,
            "pass_rate": f"{round((pass_count / len(success_items)) * 100, 1)}%" if success_items else "0%",
            "prompt_filename": prompt_filename,
        }

    @staticmethod
    def _truncate_compare_output(text: str, limit: int = 120) -> str:
        normalized = re.sub(r"\s+", " ", str(text or "")).strip()
        if len(normalized) <= limit:
            return normalized
        return normalized[:limit].rstrip() + "..."

    @staticmethod
    def _build_compare_report_meta(
        report: dict,
        model_id: str,
        prompt_filename: str,
    ) -> dict:
        group_results = list(report.get("group_results", []) or [])
        compare_mode = str(report.get("compare_mode", "") or "compare").strip()
        group_labels = [str(group.get("label", "") or "").strip() for group in group_results]
        report_title = str(report.get("report_title", "") or "").strip() or f"{compare_mode.upper()} 对比报告".strip()
        return {
            "report_id": str(report.get("id", "") or "").strip(),
            "report_title": report_title,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "compare_mode": compare_mode,
            "group_count": len(group_results),
            "group_labels": group_labels,
            "summary_model": model_id,
            "prompt_filename": prompt_filename,
        }

    @staticmethod
    def _build_compare_group_summaries(report: dict) -> list[dict]:
        groups = []
        for group in list(report.get("group_results", []) or []):
            groups.append(
                {
                    "label": group.get("label", ""),
                    "conv_id": group.get("conv_id", ""),
                    "model_id": group.get("model_id", ""),
                    "prompt_version": group.get("prompt_version", ""),
                    "avg_scores": dict(group.get("avg_scores", {}) or {}),
                    "turn_count": int(group.get("turn_count", 0) or 0),
                    "scored_count": int(group.get("scored_count", 0) or 0),
                    "failed_count": int(group.get("failed_count", 0) or 0),
                    "pending_count": int(group.get("pending_count", 0) or 0),
                    "pass_count": int(group.get("pass_count", 0) or 0),
                    "manual_avg": group.get("manual_avg"),
                    "total_input_tokens": int(group.get("total_input_tokens", 0) or 0),
                    "total_output_tokens": int(group.get("total_output_tokens", 0) or 0),
                    "avg_latency_s": round(float(group.get("avg_latency_s", 0) or 0), 2),
                }
            )
        return groups

    def _build_compare_per_turn_prompt_rows(self, report: dict) -> list[dict]:
        rows = []
        for row in list(report.get("per_turn_comparison", []) or []):
            groups = []
            for group in list(row.get("groups", []) or []):
                groups.append(
                    {
                        "label": group.get("label", ""),
                        "model_id": group.get("model_id", ""),
                        "prompt_version": group.get("prompt_version", ""),
                        "turn": group.get("turn"),
                        "total": group.get("total"),
                        "status": group.get("status", ""),
                        "manual_star_score": group.get("manual_star_score"),
                        "dimension_scores": dict(group.get("dimension_scores", {}) or {}),
                        "reasoning": str(group.get("reasoning", "") or "").strip(),
                        "ai_output": self._truncate_compare_output(group.get("ai_output", "")),
                    }
                )
            rows.append(
                {
                    "turn": row.get("turn"),
                    "winners": list(row.get("winners", []) or []),
                    "groups": groups,
                }
            )
        return rows

    async def generate_scoring_report(
        self,
        scored_items: list[dict],
        config: dict,
        model_id: str | None = None,
        prompt_version: str | None = None,
        conversation_id: str = "",
    ) -> dict:
        """生成单会话评分 Markdown 报告。

        当 conversation_id 非空时，使用异步锁去重：如果同一会话的报告正在
        生成（预热 or 用户请求），后到的调用等待前者完成后直接读取缓存，
        避免并发发起重复的 LLM 调用。
        """
        self._ensure_loaded(require_api_key=False)
        success_items = [it for it in scored_items if it.get("success", False)]
        if not success_items:
            return {"error": "无有效打分数据，无法生成 AI 摘要"}

        # 并发去重：同一 conversation_id 只允许一个 LLM 调用在跑
        lock_key = f"scoring_report_{conversation_id}" if conversation_id else ""
        if lock_key:
            if lock_key not in self._report_generation_locks:
                self._report_generation_locks[lock_key] = asyncio.Lock()
            report_lock = self._report_generation_locks[lock_key]
        else:
            report_lock = None

        if report_lock:
            return await self._generate_scoring_report_locked(
                report_lock, scored_items, success_items, config,
                model_id, prompt_version, conversation_id,
            )
        return await self._generate_scoring_report_inner(
            scored_items, success_items, config,
            model_id, prompt_version, conversation_id,
        )

    async def _generate_scoring_report_locked(
        self,
        report_lock: asyncio.Lock,
        scored_items: list[dict],
        success_items: list[dict],
        config: dict,
        model_id: str | None,
        prompt_version: str | None,
        conversation_id: str,
    ) -> dict:
        """在去重锁保护下生成报告。锁获取后先检查缓存。"""
        async with report_lock:
            # 锁获取后再查一次缓存：前一个请求可能已完成并写入
            resolved_model = self._resolve_ai_summary_model_id(model_id)
            prompt_filename, _ = self._read_report_prompt_template(
                self.scoring_report_prompt_store, prompt_version,
            )
            signature = self._build_source_signature(
                self._build_signature_payload(
                    scored_items, success_items, config, resolved_model,
                    prompt_filename,
                )
            )
            cached = db.get_ai_report_summary(
                target_type="conversation_scoring",
                target_id=conversation_id,
                report_kind="scoring_report",
                model_id=resolved_model,
                prompt_filename=prompt_filename,
                source_signature=signature,
            )
            if cached:
                try:
                    db.log_conversation_event(
                        conversation_id,
                        scope="scoring",
                        level="info",
                        event_type="summary_cache_hit",
                        detail={"report_kind": "scoring_report", "model_id": resolved_model, "dedup": True},
                    )
                except Exception:
                    pass
                return {
                    "markdown": cached.get("markdown", ""),
                    "model_id": resolved_model,
                    "prompt_version": prompt_filename,
                    "report_title": cached.get("report_title", ""),
                    "role_name": config.get("character", {}).get("Role_Nickname", "") or "未知角色",
                    "prompt_name": config.get("prompt_file", "") or "",
                    "cached": True,
                }
            return await self._generate_scoring_report_inner(
                scored_items, success_items, config,
                model_id, prompt_version, conversation_id,
            )

    def _build_signature_payload(
        self,
        scored_items: list[dict],
        success_items: list[dict],
        config: dict,
        resolved_model: str,
        prompt_filename: str,
    ) -> dict:
        """构造用于缓存签名计算的 payload。"""
        report_meta = self._build_summary_report_meta(
            scored_items, success_items, config, resolved_model, prompt_filename,
        )
        dimension_stats = self._build_summary_dimension_stats(success_items)
        case_items = self._build_summary_case_items(
            scored_items,
            list((self._config or {}).get("dimensions", []) or [])
            or list((self._config or {}).get("weights", {}).keys())
            or list((success_items[0].get("scores", {}) or {}).keys() if success_items else []),
        )
        return {
            "report_title": report_meta.get("report_title", ""),
            "generation_model": report_meta.get("generation_model", ""),
            "scoring_model": report_meta.get("scoring_model", ""),
            "scoring_prompt": report_meta.get("scoring_prompt", ""),
            "relationship": dict(config.get("context", {}) or {}).get("relationship", ""),
            "dimension_stats": dimension_stats,
            "case_items": case_items,
        }

    async def _generate_scoring_report_inner(
        self,
        scored_items: list[dict],
        success_items: list[dict],
        config: dict,
        model_id: str | None = None,
        prompt_version: str | None = None,
        conversation_id: str = "",
    ) -> dict:
        """实际执行报告生成的内部方法。"""
        resolved_model = self._resolve_ai_summary_model_id(model_id)
        prompt_filename, template = self._read_report_prompt_template(
            self.scoring_report_prompt_store,
            prompt_version,
        )
        report_meta = self._build_summary_report_meta(
            scored_items,
            success_items,
            config,
            resolved_model,
            prompt_filename,
        )
        report_meta["progress_summary"] = f"已评分 {len(success_items)} / 总轮数 {len(scored_items)}"
        dimension_stats = self._build_summary_dimension_stats(success_items)
        case_items = self._build_summary_case_items(
            scored_items,
            list((self._config or {}).get("dimensions", []) or [])
            or list((self._config or {}).get("weights", {}).keys())
            or list((success_items[0].get("scores", {}) or {}).keys() if success_items else []),
        )
        signature = self._build_source_signature(
            self._build_signature_payload(
                scored_items, success_items, config, resolved_model, prompt_filename,
            )
        )
        if conversation_id:
            cached = db.get_ai_report_summary(
                target_type="conversation_scoring",
                target_id=conversation_id,
                report_kind="scoring_report",
                model_id=resolved_model,
                prompt_filename=prompt_filename,
                source_signature=signature,
            )
            if cached:
                try:
                    db.log_conversation_event(
                        conversation_id,
                        scope="scoring",
                        level="info",
                        event_type="summary_cache_hit",
                        detail={"report_kind": "scoring_report", "model_id": resolved_model},
                    )
                except Exception:
                    pass
                return {
                    "markdown": cached.get("markdown", ""),
                    "model_id": resolved_model,
                    "prompt_version": prompt_filename,
                    "report_title": report_meta.get("report_title", ""),
                    "role_name": config.get("character", {}).get("Role_Nickname", "") or "未知角色",
                    "prompt_name": config.get("prompt_file", "") or "",
                    "cached": True,
                }
        prompt = self._fill_prompt_template(
            template,
            {
                "report_meta_json": json.dumps(report_meta, ensure_ascii=False, indent=2),
                "dimension_stats_json": json.dumps(dimension_stats, ensure_ascii=False, indent=2),
                "case_items_json": json.dumps(case_items, ensure_ascii=False, indent=2),
            },
        )
        try:
            markdown = await self._generate_report_markdown(
                model_id=resolved_model,
                prompt=prompt,
                max_tokens=4096,
            )
            self._validate_markdown_report(markdown, self.SCORING_REPORT_REQUIRED_SECTIONS)
        except Exception as exc:
            return {
                "error": str(exc),
            }
        if conversation_id:
            db.save_ai_report_summary(
                target_type="conversation_scoring",
                target_id=conversation_id,
                report_kind="scoring_report",
                model_id=resolved_model,
                prompt_filename=prompt_filename,
                source_signature=signature,
                markdown=markdown,
            )
            try:
                db.log_conversation_event(
                    conversation_id,
                    scope="scoring",
                    level="info",
                    event_type="summary_generated",
                    detail={"report_kind": "scoring_report", "model_id": resolved_model},
                )
            except Exception:
                pass
        return {
            "markdown": markdown,
            "model_id": resolved_model,
            "prompt_version": prompt_filename,
            "report_title": report_meta.get("report_title", ""),
            "role_name": config.get("character", {}).get("Role_Nickname", "") or "未知角色",
            "prompt_name": config.get("prompt_file", "") or "",
            "cached": False,
        }

    async def generate_compare_report(
        self,
        report: dict,
        model_id: str | None = None,
        prompt_version: str | None = None,
    ) -> dict:
        """生成 A/B/C 对比文本摘要。"""
        resolved_model = self._resolve_ai_summary_model_id(model_id)
        prompt_filename, template = self._read_report_prompt_template(
            self.compare_report_prompt_store,
            prompt_version,
        )
        report_meta = self._build_compare_report_meta(report, resolved_model, prompt_filename)
        groups_summary = self._build_compare_group_summaries(report)
        per_dim_comparison = dict(report.get("per_dim_comparison", {}) or {})
        per_turn_comparison = self._build_compare_per_turn_prompt_rows(report)
        winners = dict(report.get("winners", {}) or {})
        report_id = str(report.get("id", "") or "").strip()
        signature = self._build_source_signature(
            {
                "report_meta": {
                    "compare_mode": report_meta.get("compare_mode", ""),
                    "group_count": report_meta.get("group_count", 0),
                    "group_labels": report_meta.get("group_labels", []),
                },
                "groups_summary": groups_summary,
                "per_dim_comparison": per_dim_comparison,
                "per_turn_comparison": per_turn_comparison,
                "winners": winners,
            }
        )
        if report_id:
            cached = db.get_ai_report_summary(
                target_type="compare_report",
                target_id=report_id,
                report_kind="compare_report",
                model_id=resolved_model,
                prompt_filename=prompt_filename,
                source_signature=signature,
            )
            if cached:
                return {
                    "markdown": cached.get("markdown", ""),
                    "model_id": resolved_model,
                    "prompt_version": prompt_filename,
                    "report_title": report_meta.get("report_title", ""),
                    "group_count": report_meta.get("group_count", 0),
                    "cached": True,
                }
        prompt = self._fill_prompt_template(
            template,
            {
                "report_meta_json": json.dumps(report_meta, ensure_ascii=False, indent=2),
                "groups_summary_json": json.dumps(groups_summary, ensure_ascii=False, indent=2),
                "per_dim_comparison_json": json.dumps(per_dim_comparison, ensure_ascii=False, indent=2),
                "per_turn_comparison_json": json.dumps(per_turn_comparison, ensure_ascii=False, indent=2),
                "winners_json": json.dumps(winners, ensure_ascii=False, indent=2),
            },
        )
        try:
            markdown = await self._generate_report_markdown(
                model_id=resolved_model,
                prompt=prompt,
                max_tokens=4096,
            )
            self._validate_markdown_report(markdown, self.COMPARE_REPORT_REQUIRED_MARKERS)
        except Exception as exc:
            return {"error": str(exc)}
        if report_id:
            db.save_ai_report_summary(
                target_type="compare_report",
                target_id=report_id,
                report_kind="compare_report",
                model_id=resolved_model,
                prompt_filename=prompt_filename,
                source_signature=signature,
                markdown=markdown,
            )
        return {
            "markdown": markdown,
            "model_id": resolved_model,
            "prompt_version": prompt_filename,
            "report_title": report_meta.get("report_title", ""),
            "group_count": report_meta.get("group_count", 0),
            "cached": False,
        }

    async def generate_ai_summary(
        self,
        scored_items: list[dict],
        config: dict,
        model_id: str | None = None,
        prompt_version: str | None = None,
        conversation_id: str = "",
    ) -> dict:
        """兼容旧接口，转发到单会话评分报告生成器。"""
        return await self.generate_scoring_report(
            scored_items,
            config,
            model_id=model_id,
            prompt_version=prompt_version,
            conversation_id=conversation_id,
        )
