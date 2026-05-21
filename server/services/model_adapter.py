"""
ModelAdapter — 统一多模型调用接口

复用 prompt-validator-llm 的 Provider 体系，提供简化的 chat() 接口。
"""
import importlib.util
import os
import sys
import threading
import types
import yaml
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from config import MODELS_CONFIG_DIR, PROVIDER_LLM_DIR
from services.local_openai_provider import LocalOpenAIProvider

_PROVIDER_PACKAGE_NAME = "_longform_provider_bridge"
_PROVIDER_DIR = PROVIDER_LLM_DIR / "providers"
_PROVIDER_BASE_CACHE: tuple[type, type] | None = None
_PROVIDER_CACHE_DIR: str | None = None
_PROVIDER_LOAD_LOCK = threading.RLock()

# --- Google API Key 多 Key 轮转（TPM 无限制）---
_google_key_pool: list[str] = []
_google_key_index = 0
_google_key_lock = threading.Lock()


def _next_google_api_key() -> str:
    """线程安全地从 GOOGLE_API_KEYS 池中 round-robin 选取下一个 Key。"""
    global _google_key_pool, _google_key_index
    if not _google_key_pool:
        raw = os.environ.get("GOOGLE_API_KEYS", "").strip()
        if raw:
            _google_key_pool = [k.strip() for k in raw.split(",") if k.strip()]
        if not _google_key_pool:
            fallback = os.environ.get("GOOGLE_API_KEY", "").strip()
            if fallback:
                _google_key_pool = [fallback]
    if not _google_key_pool:
        return ""
    with _google_key_lock:
        key = _google_key_pool[_google_key_index % len(_google_key_pool)]
        _google_key_index += 1
        return key


def _clear_provider_module_cache() -> None:
    global _PROVIDER_BASE_CACHE, _PROVIDER_CACHE_DIR
    prefix = f"{_PROVIDER_PACKAGE_NAME}."
    for key in list(sys.modules):
        if key == _PROVIDER_PACKAGE_NAME or key.startswith(prefix):
            sys.modules.pop(key, None)
    _PROVIDER_BASE_CACHE = None
    _PROVIDER_CACHE_DIR = None


def _current_provider_dir() -> str:
    return str(_PROVIDER_DIR.resolve())


def _ensure_provider_package() -> types.ModuleType:
    global _PROVIDER_CACHE_DIR
    with _PROVIDER_LOAD_LOCK:
        current_dir = _current_provider_dir()
        if _PROVIDER_CACHE_DIR and _PROVIDER_CACHE_DIR != current_dir:
            _clear_provider_module_cache()

        package = sys.modules.get(_PROVIDER_PACKAGE_NAME)
        if package is not None:
            package_path = list(getattr(package, "__path__", []) or [])
            if package_path == [current_dir]:
                _PROVIDER_CACHE_DIR = current_dir
                return package
            _clear_provider_module_cache()

        if not _PROVIDER_DIR.exists():
            raise FileNotFoundError(f"Provider 目录不存在: {_PROVIDER_DIR}")

        package = types.ModuleType(_PROVIDER_PACKAGE_NAME)
        package.__file__ = str(_PROVIDER_DIR / "__init__.py")
        package.__package__ = _PROVIDER_PACKAGE_NAME
        package.__path__ = [current_dir]
        sys.modules[_PROVIDER_PACKAGE_NAME] = package
        _PROVIDER_CACHE_DIR = current_dir
        return package


def _load_provider_module(module_name: str):
    with _PROVIDER_LOAD_LOCK:
        current_dir = _current_provider_dir()
        expected_path = str((_PROVIDER_DIR / f"{module_name}.py").resolve())
        if _PROVIDER_CACHE_DIR and _PROVIDER_CACHE_DIR != current_dir:
            _clear_provider_module_cache()

        qualified_name = f"{_PROVIDER_PACKAGE_NAME}.{module_name}"
        cached = sys.modules.get(qualified_name)
        if cached is not None:
            cached_path = str(Path(getattr(cached, "__file__", "")).resolve())
            if cached_path == expected_path:
                return cached
            sys.modules.pop(qualified_name, None)

        _ensure_provider_package()
        module_path = Path(expected_path)
        spec = importlib.util.spec_from_file_location(qualified_name, module_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法加载 Provider 模块: {module_name}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[qualified_name] = module
        spec.loader.exec_module(module)
        return module


def _get_provider_base_types() -> tuple[type, type]:
    global _PROVIDER_BASE_CACHE, _PROVIDER_CACHE_DIR
    with _PROVIDER_LOAD_LOCK:
        current_dir = _current_provider_dir()
        if _PROVIDER_CACHE_DIR and _PROVIDER_CACHE_DIR != current_dir:
            _clear_provider_module_cache()

        if _PROVIDER_BASE_CACHE is None:
            base_module = _load_provider_module("base")
            _PROVIDER_BASE_CACHE = (
                base_module.BaseProvider,
                base_module.ProviderResult,
            )
        return _PROVIDER_BASE_CACHE


class ChatResult:
    """统一的模型调用结果"""
    __slots__ = ("content", "input_tokens", "output_tokens", "latency_s",
                 "success", "error")

    def __init__(self, content="", input_tokens=0, output_tokens=0,
                 latency_s=0.0, success=True, error=""):
        self.content = content
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.latency_s = latency_s
        self.success = success
        self.error = error

    def to_dict(self) -> dict:
        return {
            "output": self.content,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_s": self.latency_s,
            "success": self.success,
            "error": self.error,
        }


class ModelAdapter:
    """
    多模型统一调用适配器。

    加载 YAML 配置文件，根据 model_id 选择对应 Provider 并调用。
    同时保留原引擎的 call_api() 兼容接口（使用火山引擎 SDK 直接调用）。
    """

    # 已知的 Provider 映射
    PROVIDER_MAP = {
        "volcengine": "volcengine",
        "moonshot": "moonshot",
        "minimax": "minimax",
        "aliyun": "aliyun",
        "openrouter": "openrouter",
        "dashscope": "aliyun",
        "google": "google_gemini",
        "google_gemini": "google_gemini",
        "nvidia": "google_gemini",
        "local_openai": "local_openai",
    }
    GEMMA_MODEL_PREFIXES = ("gemma4-", "gemma-4-", "gemma4")
    THINKING_LEVELS = frozenset({"disabled", "low", "medium", "high", "max", "xhigh"})
    # 打分/摘要等分析型场景的默认 Thinking 级别
    DEFAULT_THINKING_BY_MODEL = {
        "gemma4-31b": "high",
        "gemma4-31b-local": "high",
    }

    # 内置模型 ID 到配置的映射（不依赖 YAML 文件）
    BUILTIN_MODELS = {
        "doubao-pro": {
            "name": "doubao-seed-2-0-pro-260215",
            "display_name": "豆包 Pro",
            "provider": "volcengine",
            "api": {
                "base_url": "https://ark.cn-beijing.volces.com/api/v3",
                "api_key_env": "VOLCENGINE_API_KEY",
                "model": "doubao-seed-2-0-pro-260215",
            },
            "parameters": {"temperature": 1.0, "max_tokens": 4096, "top_p": 0.95},
            "capabilities": {"web_search": True, "thinking": True},
        },
        "doubao-mini": {
            "name": "doubao-seed-2-0-mini-260215",
            "display_name": "豆包 Mini",
            "provider": "volcengine",
            "api": {
                "base_url": "https://ark.cn-beijing.volces.com/api/v3",
                "api_key_env": "VOLCENGINE_API_KEY",
                "model": "doubao-seed-2-0-mini-260215",
            },
            "parameters": {"temperature": 0.7, "max_tokens": 800, "top_p": 0.95},
            "capabilities": {"web_search": True, "thinking": True},
        },
        "doubao-lite": {
            "name": "doubao-seed-2-0-lite-260215",
            "display_name": "豆包 Lite",
            "provider": "volcengine",
            "api": {
                "base_url": "https://ark.cn-beijing.volces.com/api/v3",
                "api_key_env": "VOLCENGINE_API_KEY",
                "model": "doubao-seed-2-0-lite-260215",
            },
            "parameters": {"temperature": 1.0, "max_tokens": 4096, "top_p": 0.95},
            "capabilities": {"web_search": True, "thinking": True},
        },
        "doubao-1.5-character": {
            "name": "doubao-1-5-pro-32k-character-250715",
            "display_name": "豆包 1.5 角色",
            "provider": "volcengine",
            "api": {
                "base_url": "https://ark.cn-beijing.volces.com/api/v3",
                "api_key_env": "ARK_API_KEY",
                "interface": "chat_completions",
                "model_name": "doubao-1-5-pro-32k-character-250715",
            },
            "parameters": {"temperature": 1.0, "max_tokens": 4096, "top_p": 0.95},
            "capabilities": {"web_search": False, "thinking": False},
        },
        "doubao-character": {
            "name": "doubao-seed-character-251128",
            "display_name": "豆包角色",
            "provider": "volcengine",
            "api": {
                "base_url": "https://ark.cn-beijing.volces.com/api/v3",
                "api_key_env": "VOLCENGINE_API_KEY",
                "model": "doubao-seed-character-251128",
            },
            "parameters": {"temperature": 1.0, "max_tokens": 4096, "top_p": 0.95},
            "capabilities": {"web_search": False, "thinking": False},
        },
        "minimax-m27": {
            "name": "MiniMax-M2.7",
            "display_name": "MiniMax M2.7",
            "provider": "minimax",
            "api": {
                "base_url": "https://api.minimaxi.com",
                "api_key": "${MINIMAX_API_KEY}",
                "model_name": "MiniMax-M2.7",
            },
            "parameters": {"temperature": 1.0, "max_completion_tokens": 4096, "top_p": 0.95},
            "capabilities": {"web_search": False, "thinking": False},
        },
        "minimax-m25": {
            "name": "MiniMax-M2.5",
            "display_name": "MiniMax M2.5",
            "provider": "aliyun",
            "api": {
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "api_key": "${DASHSCOPE_API_KEY}",
                "model_name": "MiniMax-M2.5",
            },
            "parameters": {"temperature": 1.0, "max_tokens": 4096, "top_p": 0.95},
            "thinking": {"enabled": True},
            "capabilities": {"web_search": False, "thinking": True},
        },
        "minimax-her": {
            "name": "M2-her",
            "display_name": "MiniMax Her",
            "provider": "minimax",
            "api": {
                "base_url": "https://api.minimaxi.com",
                "api_key_env": "MINIMAX_HER_API_KEY",
                "model_name": "M2-her",
            },
            "parameters": {"temperature": 1.0, "max_completion_tokens": 2048, "top_p": 0.95},
            "capabilities": {"web_search": False, "thinking": False},
        },
        "stepfun-flash": {
            "name": "step-3.5-flash",
            "display_name": "StepFun 3.5 Flash",
            "provider": "openrouter",
            "status": "deprecated",
            "ui_hidden": True,
            "api": {
                "base_url": "https://openrouter.ai/api/v1",
                "api_key": "${OPENROUTER_API_KEY}",
                "model_name": "stepfun/step-3.5-flash:free",
            },
            "parameters": {"temperature": 1.0, "max_tokens": 4096, "top_p": 0.95},
            "capabilities": {"web_search": False, "thinking": True},
        },
        "qwen-plus": {
            "name": "qwen3.5-plus",
            "display_name": "千问 3.5 Plus",
            "provider": "aliyun",
            "api": {
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "api_key": "${DASHSCOPE_API_KEY}",
                "model_name": "qwen3.5-plus",
            },
            "parameters": {"temperature": 1.0, "max_tokens": 4096, "top_p": 0.95},
            "capabilities": {"web_search": False, "thinking": True},
        },
        "qwen3.6-plus": {
            "name": "qwen3.6-plus",
            "display_name": "千问 3.6 Plus",
            "provider": "aliyun",
            "api": {
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "api_key": "${DASHSCOPE_API_KEY}",
                "model_name": "qwen3.6-plus",
            },
            "parameters": {"temperature": 1.0, "max_tokens": 4096, "top_p": 0.95},
            "thinking": {"enabled": True},
            "capabilities": {"web_search": False, "thinking": True},
        },
        "kimi-k25": {
            "name": "kimi-k2.5",
            "display_name": "Kimi K2.5",
            "provider": "moonshot",
            "api": {
                "base_url": "https://api.moonshot.cn/v1",
                "api_key": "${MOONSHOT_API_KEY}",
                "model_name": "kimi-k2.5",
            },
            "parameters": {"temperature": 1.0, "max_tokens": 4096, "top_p": 0.95},
            "capabilities": {"web_search": False, "thinking": True},
        },
        "deepseek-v3.1": {
            "name": "deepseek-v3-1-terminus",
            "display_name": "DeepSeek V3.1",
            "provider": "volcengine",
            "api": {
                "base_url": "https://ark.cn-beijing.volces.com/api/v3",
                "api_key_env": "VOLCENGINE_API_KEY",
                "interface": "chat_completions",
                "model": "deepseek-v3-1-terminus",
            },
            "parameters": {"temperature": 1.0, "max_tokens": 4096, "top_p": 0.95},
            "capabilities": {"web_search": False, "thinking": False},
        },
        "deepseek-v3.2": {
            "name": "deepseek-v3-2-251201",
            "display_name": "DeepSeek V3.2",
            "provider": "volcengine",
            "api": {
                "base_url": "https://ark.cn-beijing.volces.com/api/v3",
                "api_key_env": "VOLCENGINE_API_KEY",
                "interface": "chat_completions",
                "model": "deepseek-v3-2-251201",
            },
            "parameters": {"temperature": 1.0, "max_tokens": 4096, "top_p": 0.95},
            "capabilities": {"web_search": False, "thinking": False},
        },
        "deepseek-v4-flash": {
            "name": "deepseek-v4-flash",
            "display_name": "DeepSeek V4 Flash",
            "provider": "aliyun",
            "api": {
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "api_key": "${DASHSCOPE_API_KEY}",
                "model_name": "deepseek-v4-flash",
            },
            "parameters": {"temperature": 1.0, "max_tokens": 4096, "top_p": 1.0},
            "thinking": {"enabled": True, "supports_reasoning_effort": True},
            "capabilities": {"web_search": False, "thinking": True},
        },
        "deepseek-v4-pro": {
            "name": "deepseek-v4-pro",
            "display_name": "DeepSeek V4 Pro",
            "provider": "aliyun",
            "api": {
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "api_key": "${DASHSCOPE_API_KEY}",
                "model_name": "deepseek-v4-pro",
            },
            "parameters": {"temperature": 1.0, "max_tokens": 4096, "top_p": 1.0},
            "thinking": {"enabled": True, "supports_reasoning_effort": True},
            "capabilities": {"web_search": False, "thinking": True},
        },
        "deepseek-v3": {
            "name": "deepseek-v3-250324",
            "display_name": "DeepSeek V3",
            "provider": "volcengine",
            "api": {
                "base_url": "https://ark.cn-beijing.volces.com/api/v3",
                "api_key_env": "DEEPSEEK_API_KEY",
                "interface": "chat_completions",
                "model": "deepseek-v3-250324",
            },
            "parameters": {"temperature": 1.0, "max_tokens": 4096, "top_p": 0.95},
            "capabilities": {"web_search": False, "thinking": False},
        },
        "glm-5": {
            "name": "glm-5",
            "display_name": "GLM-5",
            "provider": "aliyun",
            "api": {
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "api_key": "${DASHSCOPE_API_KEY}",
                "model_name": "glm-5",
            },
            "parameters": {"temperature": 1.0, "max_tokens": 4096, "top_p": 0.95},
            "thinking": {"enabled": True},
            "capabilities": {"web_search": False, "thinking": True},
        },
        "gemma4-31b": {
            "name": "gemma-4-31b-it",
            "display_name": "Gemma4 31B",
            "provider": "google_gemini",
            "api": {
                "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
                "api_key": "${GOOGLE_API_KEY}",
                "model_name": "gemma-4-31b-it",
            },
            "parameters": {"temperature": 1.0, "max_tokens": 8192, "top_p": 0.95},
            "thinking": {"enabled": True},
            "capabilities": {"web_search": False, "thinking": True},
        },
        "gemma4-31b-local": {
            "name": "Gemma4 31B 本地版",
            "display_name": "Gemma4 31B 本地版",
            "provider": "local_openai",
            "api": {
                "base_url": "http://115.190.27.75:19006/v1",
                "api_key": "${LONGFORM_LOCAL_GEMMA_API_KEY}",
                "model_name": "gemma4",
            },
            "parameters": {"temperature": 1.0, "max_tokens": 8192, "top_p": 0.95},
            "thinking": {"enabled": True},
            "rate_limit": {"retry_delays": [1, 2, 4]},
            "capabilities": {"web_search": False, "thinking": True},
        },
        "gemma4-26b": {
            "name": "gemma-4-26b-a4b-it",
            "display_name": "Gemma4 26B A4B",
            "provider": "google_gemini",
            "api": {
                "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
                "api_key": "${GOOGLE_API_KEY}",
                "model_name": "gemma-4-26b-a4b-it",
            },
            "parameters": {"temperature": 1.0, "max_tokens": 8192, "top_p": 0.95},
            "thinking": {"enabled": True},
            "capabilities": {"web_search": False, "thinking": True},
        },
    }

    @classmethod
    def normalize_model_id(cls, model_id: str | None) -> str:
        """兼容旧的 provider model 名称，统一返回内部模型 ID。"""
        requested = str(model_id or "").strip()
        if not requested:
            return ""
        if requested in cls.BUILTIN_MODELS:
            return requested

        lowered = requested.lower()
        for builtin_id, cfg in cls.BUILTIN_MODELS.items():
            api = dict(cfg.get("api", {}) or {})
            aliases = {
                str(cfg.get("name", "")).strip(),
                str(cfg.get("display_name", "")).strip(),
                str(api.get("model", "")).strip(),
                str(api.get("model_name", "")).strip(),
            }
            if lowered in {alias.lower() for alias in aliases if alias}:
                return builtin_id
        return requested

    def __init__(self):
        self._models: dict[str, dict] = {}
        self._providers: dict[str, Any] = {}
        self._load_models()

    def _load_models(self):
        """加载所有模型配置（内置 + YAML）"""
        # 1. 内置模型
        for model_id, config in self.BUILTIN_MODELS.items():
            self._models[model_id] = config

        # 2. YAML 配置文件（不覆盖内置模型）
        builtin_api_names = set()
        for cfg in self.BUILTIN_MODELS.values():
            api = cfg.get("api", {})
            builtin_api_names.add(api.get("model_name", ""))
            builtin_api_names.add(api.get("model", ""))
        builtin_api_names.discard("")

        if MODELS_CONFIG_DIR.exists():
            for yaml_file in MODELS_CONFIG_DIR.glob("*.yaml"):
                try:
                    model_id = yaml_file.stem
                    if model_id in self.BUILTIN_MODELS:
                        continue  # BUILTIN 优先（stem完全匹配）
                    with open(yaml_file, "r", encoding="utf-8") as f:
                        cfg = yaml.safe_load(f)
                    if cfg and "name" in cfg:
                        api = cfg.get("api", {})
                        y_name = api.get("model_name", api.get("model", ""))
                        if y_name in builtin_api_names:
                            continue  # API model name 与 BUILTIN 重复
                        self._models[model_id] = cfg
                except Exception as e:
                    print(f"[警告] 加载模型配置失败 {yaml_file.name}: {e}")

    def list_models(self, *, include_hidden: bool = False) -> list[dict]:
        """返回可用模型列表（含能力矩阵）"""
        result = []
        for model_id, cfg in self._models.items():
            if not include_hidden and bool(cfg.get("ui_hidden", False)):
                continue
            caps = cfg.get("capabilities", {})
            item = {
                "id": model_id,
                "name": cfg.get("name", model_id),
                "display_name": cfg.get("display_name", model_id),
                "provider": cfg.get("provider", "unknown"),
                "capabilities": {
                    "web_search": caps.get("web_search", False),
                    "thinking": caps.get("thinking", False),
                },
            }
            status = str(cfg.get("status", "") or "").strip()
            if status:
                item["status"] = status
            result.append(item)
        return result

    def _get_provider(self, model_id: str):
        """获取或创建指定模型的 Provider 实例"""
        model_id = self.normalize_model_id(model_id)
        raw_config = self._models.get(model_id, {}) or {}
        provider_type = str(raw_config.get("provider", "") or "").strip()
        if provider_type in ("google", "google_gemini", "nvidia"):
            return self._instantiate_provider(model_id)
        with _PROVIDER_LOAD_LOCK:
            if model_id in self._providers:
                return self._providers[model_id]

            provider = self._instantiate_provider(model_id)
            self._providers[model_id] = provider
            return provider

    def _instantiate_provider(self, model_id: str):
        """创建指定模型的 Provider 实例，不写入缓存。"""
        model_id = self.normalize_model_id(model_id)
        raw_config = self._models.get(model_id)
        if not raw_config:
            raise ValueError(f"未知模型 ID: {model_id}")

        # NOTE: provider 初始化会直接持有 config/api/parameters 的引用。
        # 在并发场景下如果复用同一份 dict，会导致 api_key/temperature 等运行时字段相互污染。
        config = deepcopy(raw_config)

        provider_type = config.get("provider", "")
        if provider_type == "local_openai":
            return LocalOpenAIProvider(config)

        module_path = self.PROVIDER_MAP.get(provider_type)
        if not module_path:
            raise ValueError(
                f"不支持 provider 类型: {provider_type}（模型: {model_id}）"
            )

        mod = _load_provider_module(module_path)
        base_provider_cls, _ = _get_provider_base_types()
        provider_cls = None
        for attr_name in dir(mod):
            attr = getattr(mod, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, base_provider_cls)
                and attr is not base_provider_cls
            ):
                provider_cls = attr
                break

        if not provider_cls:
            raise ValueError(f"Provider 模块 {module_path} 中未找到 Provider 类")

        api_cfg = config.get("api", {})

        # Google Gemini 模型使用多 Key 轮转
        if provider_type in ("google", "google_gemini", "nvidia"):
            api_cfg["api_key"] = _next_google_api_key()
        else:
            api_key_env = api_cfg.get("api_key_env", "")
            if api_key_env and not api_cfg.get("api_key"):
                api_cfg["api_key"] = os.environ.get(api_key_env, "")

        return provider_cls(config)

    @staticmethod
    def is_gemma_model(model_id: str) -> bool:
        """判断 model_id 是否属于 Gemma 模型族。"""
        normalized = ModelAdapter.normalize_model_id(model_id).lower()
        return any(normalized.startswith(p) for p in ModelAdapter.GEMMA_MODEL_PREFIXES)

    @staticmethod
    def is_minimax_model(model_id: str) -> bool:
        """判断 model_id 是否属于 MiniMax 模型族。"""
        normalized = ModelAdapter.normalize_model_id(model_id).lower()
        return normalized.startswith("minimax")

    @staticmethod
    def _apply_runtime_overrides(provider, runtime_overrides: dict[str, Any]) -> None:
        """将运行时参数写入 provider 实例，避免只改静态配置。"""
        parameters = getattr(provider, "parameters", None)
        if not isinstance(parameters, dict):
            parameters = {}

        if "max_tokens" in runtime_overrides:
            max_tokens = runtime_overrides["max_tokens"]
            if "max_tokens" in parameters or (
                "max_completion_tokens" not in parameters
                and "max_output_tokens" not in parameters
            ):
                parameters["max_tokens"] = max_tokens
            if "max_completion_tokens" in parameters:
                parameters["max_completion_tokens"] = max_tokens
            if "max_output_tokens" in parameters:
                parameters["max_output_tokens"] = max_tokens
            for attr_name in ("max_tokens", "max_completion_tokens", "max_output_tokens"):
                if hasattr(provider, attr_name):
                    setattr(provider, attr_name, max_tokens)

        if "temperature" in runtime_overrides:
            parameters["temperature"] = runtime_overrides["temperature"]
            if hasattr(provider, "temperature"):
                provider.temperature = runtime_overrides["temperature"]

        if "top_p" in runtime_overrides:
            parameters["top_p"] = runtime_overrides["top_p"]
            if hasattr(provider, "top_p"):
                provider.top_p = runtime_overrides["top_p"]

        provider.parameters = parameters

    @classmethod
    def normalize_thinking_effort(
        cls,
        model_id: str,
        thinking_effort: str | None,
    ) -> str:
        """按模型返回最终思考强度，避免 Gemma4 31B 默认落到 disabled。"""
        normalized = str(thinking_effort or "").strip().lower() or "disabled"
        if normalized == "xhigh":
            normalized = "max"
        if normalized not in cls.THINKING_LEVELS:
            normalized = "disabled"
        model_default = cls.DEFAULT_THINKING_BY_MODEL.get(cls.normalize_model_id(model_id))
        if normalized == "disabled" and model_default:
            return model_default
        return normalized

    @classmethod
    def resolve_thinking_effort(
        cls,
        model_id: str,
        thinking_enabled: bool | None,
        thinking_effort: str | None,
    ) -> str:
        normalized_effort = str(thinking_effort or "").strip().lower() or "disabled"
        if normalized_effort == "xhigh":
            normalized_effort = "max"
        if normalized_effort not in cls.THINKING_LEVELS:
            normalized_effort = "disabled"
        if thinking_enabled is False:
            return "disabled"
        if thinking_enabled is True:
            if normalized_effort != "disabled":
                return normalized_effort
            return cls.DEFAULT_THINKING_BY_MODEL.get(cls.normalize_model_id(model_id), "high")
        return cls.normalize_thinking_effort(model_id, normalized_effort)

    def chat(self, model_id: str, messages: list[dict],
             max_tokens: int | None = None,
             web_search: bool = False,
             thinking_effort: str = "disabled",
             temperature: float | None = None,
             top_p: float | None = None,
             provider_retry_delays: list[float] | tuple[float, ...] | None = None) -> ChatResult:
        """
        统一调用接口。

        Args:
            model_id: 模型 ID
            messages: 标准 messages 数组
            max_tokens: 覆盖默认的 max_tokens
            web_search: 是否启用联网搜索
            thinking_effort: 思考深度 (disabled/low/medium/high)
            temperature: 运行时 temperature
            top_p: 运行时 top_p
        """
        try:
            model_id = self.normalize_model_id(model_id)
            thinking_effort = self.normalize_thinking_effort(model_id, thinking_effort)
            config = self._models.get(model_id, {})
            caps = config.get("capabilities", {})
            runtime_overrides: dict[str, Any] = {}
            if max_tokens is not None:
                runtime_overrides["max_tokens"] = int(max_tokens)
            if temperature is not None:
                runtime_overrides["temperature"] = float(temperature)
            if top_p is not None:
                runtime_overrides["top_p"] = float(top_p)

            provider = (
                self._instantiate_provider(model_id)
                if runtime_overrides or provider_retry_delays is not None
                else self._get_provider(model_id)
            )
            if runtime_overrides:
                self._apply_runtime_overrides(provider, runtime_overrides)

            # 构造运行时kwargs
            call_kwargs = {}
            if web_search and caps.get("web_search", False):
                call_kwargs["web_search"] = True
            if caps.get("thinking", False):
                call_kwargs["thinking_effort"] = thinking_effort
            if provider_retry_delays is not None:
                call_kwargs["retry_delays"] = list(provider_retry_delays)

            result = provider.call_with_retry(messages, **call_kwargs)

            return ChatResult(
                content=result.content,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                latency_s=result.latency,
                success=result.success,
                error=result.error,
            )
        except Exception as e:
            return ChatResult(success=False, error=str(e))

    def chat_legacy(self, messages: list[dict], model: str = None,
                    max_tokens: int = None) -> dict:
        """
        兼容原引擎 call_api() 的接口。
        直接使用火山引擎 SDK 调用（不走 Provider 体系）。

        Returns:
            {"output": str, "input_tokens": int, "output_tokens": int, "latency_s": float}
        """
        from volcenginesdkarkruntime import Ark

        base_url = os.environ.get(
            "DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"
        )
        api_key = os.environ.get(
            "VOLCENGINE_API_KEY",
            os.environ.get("DOUBAO_API_KEY", ""),
        )
        use_model = model or "doubao-seed-2-0-pro-260215"
        use_max_tokens = max_tokens or 4096

        client = Ark(base_url=base_url, api_key=api_key)
        api_kwargs = {
            "model": use_model,
            "messages": messages,
            "temperature": 1.0,
            "max_tokens": use_max_tokens,
        }

        start = time.time()
        response = client.chat.completions.create(**api_kwargs)
        latency = round(time.time() - start, 2)

        content = ""
        if response.choices:
            content = response.choices[0].message.content or ""

        usage = response.usage if hasattr(response, "usage") else None
        return {
            "output": content,
            "input_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
            "output_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
            "latency_s": latency,
        }
