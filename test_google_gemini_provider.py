from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_DIR = Path(__file__).resolve().parent
PROVIDER_PROJECT_DIR = PROJECT_DIR.parent / "prompt-validator-llm"

if str(PROVIDER_PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROVIDER_PROJECT_DIR))

from providers import google_gemini as provider_module  # noqa: E402
from providers.google_gemini import GoogleGeminiProvider  # noqa: E402


def test_google_gemini_provider_passes_reasoning_effort(monkeypatch):
    captured: dict[str, object] = {}
    fake_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="最终答案",
                    reasoning_content="先思考再作答",
                )
            )
        ],
        usage=SimpleNamespace(prompt_tokens=9, completion_tokens=7),
    )

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return fake_response

    class FakeChat:
        completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            self.chat = FakeChat()

    monkeypatch.setattr(provider_module, "OpenAI", FakeOpenAI)

    provider = GoogleGeminiProvider(
        {
            "name": "gemma-4-31b-it",
            "display_name": "Gemma4 31B",
            "provider": "google_gemini",
            "api": {
                "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
                "api_key": "google-test",
                "model_name": "gemma-4-31b-it",
            },
            "parameters": {"max_tokens": 512, "temperature": 1.0, "top_p": 0.95},
            "thinking": {"enabled": True},
        }
    )

    result = provider.call(
        [{"role": "user", "content": "只回复 ok"}],
        thinking_effort="low",
    )

    assert captured["client_kwargs"] == {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_key": "google-test",
    }
    assert captured["model"] == "gemma-4-31b-it"
    assert captured["reasoning_effort"] == "low"
    assert result.success is True
    assert result.content == "最终答案"
    assert result.thinking == "先思考再作答"
