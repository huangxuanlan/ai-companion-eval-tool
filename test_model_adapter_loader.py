from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
SERVER_DIR = PROJECT_DIR / "server"

if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services import model_adapter  # noqa: E402


def _clear_provider_cache():
    prefix = f"{model_adapter._PROVIDER_PACKAGE_NAME}."
    for key in list(sys.modules):
        if key == model_adapter._PROVIDER_PACKAGE_NAME or key.startswith(prefix):
            sys.modules.pop(key, None)


def test_model_adapter_loads_provider_without_sys_path_pollution(
    tmp_path: Path,
    monkeypatch,
):
    provider_dir = tmp_path / "providers"
    provider_dir.mkdir()
    (provider_dir / "base.py").write_text(
        """
from dataclasses import dataclass


@dataclass
class ProviderResult:
    content: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency: float = 0.0
    success: bool = True
    error: str = ""


class BaseProvider:
    def __init__(self, model_config: dict):
        self.config = model_config
        self.parameters = model_config.get("parameters", {})

    def call(self, messages, **kwargs):
        raise NotImplementedError

    def call_with_retry(self, messages, **kwargs):
        return self.call(messages, **kwargs)
""".strip(),
        encoding="utf-8",
    )
    (provider_dir / "echo.py").write_text(
        """
from .base import BaseProvider, ProviderResult


class EchoProvider(BaseProvider):
    def call(self, messages, **kwargs):
        return ProviderResult(
            content=f"echo:{len(messages)}",
            input_tokens=len(messages),
            output_tokens=1,
            latency=0.12,
            success=True,
        )
""".strip(),
        encoding="utf-8",
    )

    _clear_provider_cache()
    monkeypatch.setattr(model_adapter, "_PROVIDER_DIR", provider_dir)
    monkeypatch.setattr(model_adapter, "_PROVIDER_BASE_CACHE", None)
    path_before = list(sys.path)

    try:
        adapter = model_adapter.ModelAdapter()
        adapter._models = {
            "fake": {
                "name": "fake",
                "provider": "fake",
                "api": {},
                "parameters": {},
            }
        }
        monkeypatch.setitem(model_adapter.ModelAdapter.PROVIDER_MAP, "fake", "echo")

        provider = adapter._get_provider("fake")
        result = adapter.chat("fake", [{"role": "user", "content": "hi"}])

        assert provider.__class__.__name__ == "EchoProvider"
        assert result.success is True
        assert result.content == "echo:1"
        assert sys.path == path_before
        assert str(provider_dir) not in sys.path
        assert str(provider_dir.parent) not in sys.path
    finally:
        _clear_provider_cache()
        model_adapter._PROVIDER_BASE_CACHE = None


def test_model_adapter_invalidates_bridge_cache_when_provider_dir_changes(
    tmp_path: Path,
    monkeypatch,
):
    provider_dir = tmp_path / "providers"
    provider_dir.mkdir()
    (provider_dir / "base.py").write_text(
        """
from dataclasses import dataclass


@dataclass
class ProviderResult:
    content: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency: float = 0.0
    success: bool = True
    error: str = ""


class BaseProvider:
    def __init__(self, model_config: dict):
        self.config = model_config
        self.parameters = model_config.get("parameters", {})

    def call(self, messages, **kwargs):
        raise NotImplementedError

    def call_with_retry(self, messages, **kwargs):
        return self.call(messages, **kwargs)
""".strip(),
        encoding="utf-8",
    )
    (provider_dir / "echo.py").write_text(
        """
from .base import BaseProvider, ProviderResult


class EchoProvider(BaseProvider):
    def call(self, messages, **kwargs):
        return ProviderResult(content="echo")
""".strip(),
        encoding="utf-8",
    )

    original_provider_dir = model_adapter._PROVIDER_DIR
    _clear_provider_cache()
    monkeypatch.setattr(model_adapter, "_PROVIDER_DIR", provider_dir)
    monkeypatch.setattr(model_adapter, "_PROVIDER_BASE_CACHE", None)
    monkeypatch.setitem(model_adapter.ModelAdapter.PROVIDER_MAP, "fake", "echo")

    temp_adapter = model_adapter.ModelAdapter()
    temp_adapter._models = {
        "fake": {
            "name": "fake",
            "provider": "fake",
            "api": {},
            "parameters": {},
        }
    }
    provider = temp_adapter._get_provider("fake")
    assert provider.__class__.__name__ == "EchoProvider"

    monkeypatch.setattr(model_adapter, "_PROVIDER_DIR", original_provider_dir)
    real_adapter = model_adapter.ModelAdapter()
    real_provider = real_adapter._get_provider("doubao-1.5-character")
    assert getattr(real_provider, "interface", "") == "chat_completions"
    assert getattr(real_provider, "endpoint_id", "") == "doubao-1-5-pro-32k-character-250715"


def test_model_adapter_runtime_overrides_use_isolated_provider_instance(
    tmp_path: Path,
    monkeypatch,
):
    provider_dir = tmp_path / "providers"
    provider_dir.mkdir()
    (provider_dir / "base.py").write_text(
        """
from dataclasses import dataclass


@dataclass
class ProviderResult:
    content: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency: float = 0.0
    success: bool = True
    error: str = ""


class BaseProvider:
    def __init__(self, model_config: dict):
        self.config = model_config
        self.parameters = dict(model_config.get("parameters", {}))

    def call(self, messages, **kwargs):
        raise NotImplementedError

    def call_with_retry(self, messages, **kwargs):
        return self.call(messages, **kwargs)
""".strip(),
        encoding="utf-8",
    )
    (provider_dir / "echo.py").write_text(
        """
from .base import BaseProvider, ProviderResult


class EchoProvider(BaseProvider):
    def __init__(self, model_config: dict):
        super().__init__(model_config)
        self.temperature = self.parameters.get("temperature", 1.0)
        self.top_p = self.parameters.get("top_p", 0.95)
        self.max_tokens = self.parameters.get("max_tokens", 128)

    def call(self, messages, **kwargs):
        return ProviderResult(
            content=f"{self.temperature}|{self.top_p}|{self.max_tokens}",
            input_tokens=len(messages),
            output_tokens=1,
            latency=0.01,
            success=True,
        )
""".strip(),
        encoding="utf-8",
    )

    _clear_provider_cache()
    monkeypatch.setattr(model_adapter, "_PROVIDER_DIR", provider_dir)
    monkeypatch.setattr(model_adapter, "_PROVIDER_BASE_CACHE", None)
    monkeypatch.setitem(model_adapter.ModelAdapter.PROVIDER_MAP, "fake", "echo")

    adapter = model_adapter.ModelAdapter()
    adapter._models = {
        "fake": {
            "name": "fake",
            "provider": "fake",
            "api": {},
            "parameters": {"temperature": 1.0, "top_p": 0.95, "max_tokens": 128},
        }
    }

    cached = adapter._get_provider("fake")
    result = adapter.chat(
        "fake",
        [{"role": "user", "content": "hi"}],
        max_tokens=256,
        temperature=0.6,
        top_p=0.8,
    )

    assert result.success is True
    assert result.content == "0.6|0.8|256"
    assert cached.temperature == 1.0
    assert cached.top_p == 0.95
    assert cached.max_tokens == 128


def test_minimax_her_uses_dedicated_api_key_env(monkeypatch):
    adapter = model_adapter.ModelAdapter()
    monkeypatch.setenv("MINIMAX_API_KEY", "general-key")
    monkeypatch.setenv("MINIMAX_HER_API_KEY", "her-key")

    provider = adapter._instantiate_provider("minimax-her")

    assert provider.api_key == "her-key"
    assert provider.model_name == "M2-her"
