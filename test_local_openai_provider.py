from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

PROJECT_DIR = Path(__file__).resolve().parent
SERVER_DIR = PROJECT_DIR / "server"

if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from config import DEFAULT_PRIMARY_MODEL  # noqa: E402
from main import app  # noqa: E402
from routers import conversations as conversations_router  # noqa: E402
from services.conversation_service import ConversationService  # noqa: E402
from services import local_openai_provider as provider_module  # noqa: E402
from services.local_openai_provider import LocalOpenAIProvider  # noqa: E402
from services.model_adapter import ModelAdapter  # noqa: E402
from services.prompt_service import PromptService  # noqa: E402


def test_default_primary_model_switches_to_local_gemma():
    models = {item["id"]: item for item in ModelAdapter().list_models()}
    builtin = ModelAdapter.BUILTIN_MODELS["gemma4-31b-local"]

    assert DEFAULT_PRIMARY_MODEL == "gemma4-31b-local"
    assert "gemma4-31b-local" in models
    assert models["gemma4-31b-local"]["provider"] == "local_openai"
    assert models["gemma4-31b-local"]["capabilities"]["thinking"] is True
    assert builtin["api"]["base_url"] == "http://115.190.27.75:19006/v1"


def test_api_models_exposes_local_gemma_in_pro_bucket():
    with TestClient(app) as client:
        all_response = client.get("/api/models")
        pro_response = client.get("/api/models", params={"tier": "pro"})
        mini_response = client.get("/api/models", params={"tier": "mini"})

    assert all_response.status_code == 200, all_response.text
    assert pro_response.status_code == 200, pro_response.text
    assert mini_response.status_code == 200, mini_response.text

    all_models = {item["id"]: item for item in all_response.json()["models"]}
    pro_ids = {item["id"] for item in pro_response.json()["models"]}
    mini_ids = {item["id"] for item in mini_response.json()["models"]}

    assert "gemma4-31b-local" in all_models
    assert "gemma4-31b-local" in pro_ids
    assert "gemma4-31b-local" not in mini_ids


def test_local_openai_provider_enables_thinking_and_parses_think_block(monkeypatch):
    captured: dict[str, object] = {}
    fake_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="<think>先分析用户意图</think>\n\n最终答案",
                    reasoning_content="",
                    reasoning="补充推理轨迹",
                )
            )
        ],
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=8),
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

    provider = LocalOpenAIProvider(
        {
            "name": "Gemma4 31B 本地版",
            "display_name": "Gemma4 31B 本地版",
            "provider": "local_openai",
            "api": {
                "base_url": "http://115.190.27.75:19006/v1",
                "api_key": "local-test",
                "model_name": "gemma4",
            },
            "parameters": {"max_tokens": 256, "temperature": 0.7, "top_p": 0.95},
            "thinking": {"enabled": True},
        }
    )

    result = provider.call(
        [{"role": "user", "content": "只回复 ok"}],
        thinking_effort="high",
    )

    assert captured["client_kwargs"] == {
        "base_url": "http://115.190.27.75:19006/v1",
        "api_key": "local-test",
    }
    assert captured["model"] == "gemma4"
    assert captured["temperature"] == 0.7
    assert captured["max_tokens"] == 256
    assert captured["extra_body"] == {
        "skip_special_tokens": False,
        "chat_template_kwargs": {"enable_thinking": True},
    }
    assert result.success is True
    assert result.content == "最终答案"
    assert result.thinking == "补充推理轨迹\n\n先分析用户意图"
    assert result.input_tokens == 12
    assert result.output_tokens == 8


def test_local_openai_provider_disables_thinking_and_skips_special_tokens(monkeypatch):
    captured: dict[str, object] = {}
    fake_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="纯文本答案",
                    reasoning_content="",
                )
            )
        ],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=3),
    )

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return fake_response

    class FakeChat:
        completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = FakeChat()

    monkeypatch.setattr(provider_module, "OpenAI", FakeOpenAI)

    provider = LocalOpenAIProvider(
        {
            "name": "Gemma4 31B 本地版",
            "display_name": "Gemma4 31B 本地版",
            "provider": "local_openai",
            "api": {
                "base_url": "http://115.190.27.75:19006/v1",
                "api_key": "local-test",
                "model_name": "gemma4",
            },
            "parameters": {"max_tokens": 128, "temperature": 0.7, "top_p": 0.95},
            "thinking": {"enabled": True},
        }
    )

    result = provider.call(
        [{"role": "user", "content": "只回复 ok"}],
        thinking_effort="disabled",
    )

    assert captured["extra_body"] == {
        "skip_special_tokens": True,
    }
    assert result.success is True
    assert result.content == "纯文本答案"
    assert result.thinking == ""


def test_model_adapter_normalizes_gemma_thinking_defaults():
    assert ModelAdapter.normalize_thinking_effort("gemma4-31b-local", "disabled") == "high"
    assert ModelAdapter.normalize_thinking_effort("gemma4-31b", "") == "high"
    assert ModelAdapter.normalize_thinking_effort("doubao-pro", "disabled") == "disabled"
    assert ModelAdapter.normalize_thinking_effort("gemma4-31b", "high") == "high"


def test_interactive_generate_defaults_gemma_local_to_high_thinking(tmp_path: Path):
    prompt_path = tmp_path / "gemma_prompt.md"
    prompt_path.write_text(
        (
            "你是{{Role_Nickname}}，请只用中文简短回复。\n"
            "<!-- ======================== 以上为 messages[0] role=system 的内容 ======================== -->\n"
        ),
        encoding="utf-8",
    )

    class FakeAdapter:
        def __init__(self):
            self.calls: list[dict] = []

        def chat(self, model_id: str, messages: list[dict], **kwargs):
            self.calls.append(
                {
                    "model_id": model_id,
                    "messages": list(messages),
                    "kwargs": dict(kwargs),
                }
            )
            return SimpleNamespace(
                content=(
                    "厨房窗边的风铃被晚风轻轻拨了一下，声音清脆地晃进安静的客厅。"
                    "她抬眼看向门口，手里还捏着刚关掉火的锅铲，神色并不夸张，却明显把注意力放到了你身上。"
                    "目光在你脸上停了两秒后，她才慢慢把锅铲搁回台面，顺手抽了张纸巾擦干指尖沾到的水汽。"
                    "“在。”她答得很短，却没有把话截断，反而往旁边让出一点位置，像是默认你已经可以靠近。"
                    "灶上余温还在，空气里有一点淡淡的葱香和热汤气息，她把保温中的杯子往你那边推了推，语气依旧克制，"
                    "“先过来，把手暖一下，再说你这么晚找我做什么。”"
                ),
                input_tokens=8,
                output_tokens=3,
                latency_s=0.1,
                success=True,
                error="",
            )

    adapter = FakeAdapter()
    conversations_router._conv_service = ConversationService(
        model_adapter=adapter,
        prompt_service=PromptService(),
    )

    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/api/conversations/interactive",
                json={
                    "model_id": "gemma4-31b-local",
                    "model_mini": "doubao-mini",
                    "prompt_version": str(prompt_path),
                    "character": {"Role_Nickname": "测试角色", "personality": "冷静"},
                    "context": {"relationship": "朋友"},
                    "modules": {},
                    "custom_variables": {},
                },
            )
            assert create_response.status_code == 200, create_response.text
            conv_id = create_response.json()["id"]

            generate_response = client.post(
                f"/api/conversations/{conv_id}/generate",
                json={
                    "user_input": "在吗",
                    "model_id": "gemma4-31b-local",
                },
            )
            assert generate_response.status_code == 200, generate_response.text
    finally:
        conversations_router._conv_service = None

    assert adapter.calls, f"adapter 未捕获任何调用: model_ids={[c.get('model_id') for c in adapter.calls]}"
    primary_calls = [call for call in adapter.calls if call["model_id"] == "gemma4-31b-local"]
    assert primary_calls, (
        "未捕获到 gemma4-31b-local 主模型调用: "
        f"all_model_ids={[c.get('model_id') for c in adapter.calls]}"
    )
    assert all(call["kwargs"]["thinking_effort"] == "high" for call in primary_calls)
