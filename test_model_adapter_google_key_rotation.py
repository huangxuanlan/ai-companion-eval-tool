from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
SERVER_DIR = PROJECT_DIR / "server"

if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services.model_adapter import ModelAdapter  # noqa: E402


def test_google_provider_is_not_cached_so_api_key_can_rotate(monkeypatch):
    adapter = ModelAdapter()
    adapter._models["google-rotation-test"] = {"provider": "google_gemini"}
    created = []

    def fake_instantiate(model_id):
        provider = object()
        created.append((model_id, provider))
        return provider

    monkeypatch.setattr(adapter, "_instantiate_provider", fake_instantiate)

    first = adapter._get_provider("google-rotation-test")
    second = adapter._get_provider("google-rotation-test")

    assert first is not second
    assert [item[0] for item in created] == [
        "google-rotation-test",
        "google-rotation-test",
    ]
    assert "google-rotation-test" not in adapter._providers


def test_non_google_provider_still_uses_cache(monkeypatch):
    adapter = ModelAdapter()
    adapter._models["cached-provider-test"] = {"provider": "mock_provider"}
    created = []

    def fake_instantiate(model_id):
        provider = object()
        created.append((model_id, provider))
        return provider

    monkeypatch.setattr(adapter, "_instantiate_provider", fake_instantiate)

    first = adapter._get_provider("cached-provider-test")
    second = adapter._get_provider("cached-provider-test")

    assert first is second
    assert len(created) == 1
