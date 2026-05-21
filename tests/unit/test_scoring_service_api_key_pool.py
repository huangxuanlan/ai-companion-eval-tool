"""Regression tests for scoring API key pool env-name resolution."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
SERVER_DIR = PROJECT_DIR / "server"
for path in (PROJECT_DIR, SERVER_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from services import scoring_service as scoring_service_module


def _make_service_with_models(monkeypatch, models: dict) -> scoring_service_module.ScoringService:
    service = scoring_service_module.ScoringService()
    fake_adapter = type("_FakeAdapter", (), {})()
    fake_adapter._models = models
    fake_adapter.normalize_model_id = staticmethod(lambda mid: str(mid or ""))
    monkeypatch.setattr(service, "_get_model_adapter", lambda: fake_adapter)
    return service


def test_resolve_scoring_api_keys_builds_correct_pool_env_name_for_volcengine(
    monkeypatch,
) -> None:
    """Ensure VOLCENGINE_API_KEY expands to VOLCENGINE_API_KEYS (with underscore)."""
    service = _make_service_with_models(
        monkeypatch,
        {
            "doubao-lite": {
                "provider": "volcengine",
                "api": {
                    "base_url": "https://ark.cn-beijing.volces.com/api/v3",
                    "api_key_env": "VOLCENGINE_API_KEY",
                    "model": "doubao-seed-2-0-lite-260215",
                },
            }
        },
    )

    monkeypatch.delenv("SCORING_API_KEYS", raising=False)
    monkeypatch.delenv("SCORING_API_KEY", raising=False)
    monkeypatch.delenv("VOLCENGINEAPI_KEYS", raising=False)  # the broken name must not be used
    monkeypatch.setenv("VOLCENGINE_API_KEYS", "primary-key,secondary-key")
    monkeypatch.delenv("VOLCENGINE_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    keys = service._resolve_scoring_api_keys("doubao-lite")

    assert keys == ["primary-key", "secondary-key"], (
        "Expected multi-key pool to be read from VOLCENGINE_API_KEYS; "
        f"got keys={keys!r}"
    )


def test_resolve_scoring_api_keys_handles_inline_api_key_env_reference(
    monkeypatch,
) -> None:
    """When api.api_key uses ${ENV_VAR} syntax, derive the pool name the same way."""
    service = _make_service_with_models(
        monkeypatch,
        {
            "kimi-k25": {
                "provider": "moonshot",
                "api": {
                    "base_url": "https://api.moonshot.cn/v1",
                    "api_key": "${MOONSHOT_API_KEY}",
                    "model_name": "kimi-k2.5",
                },
            }
        },
    )

    monkeypatch.delenv("SCORING_API_KEYS", raising=False)
    monkeypatch.delenv("SCORING_API_KEY", raising=False)
    monkeypatch.setenv("MOONSHOT_API_KEYS", "kimi-a,kimi-b")
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)

    keys = service._resolve_scoring_api_keys("kimi-k25")

    assert keys == ["kimi-a", "kimi-b"]
