"""
test_gemma_e2e_review.py — Gemma 4 修复端到端审计测试

Code Review Phase 5: 端到端验证 C1/C4/C5 改动的全链路正确性。
覆盖：
  E1: 消息管道完整性（Gemma vs 非 Gemma 分流）
  E2: Stop 序列注入一致性（local + google 双 provider）
  E3: Thinking strip 不影响非 assistant 消息
  E4: 边界条件（空历史 + 空 memory + 首轮 + 纯空字符串）
  E5: Token 效率（合并 vs 分离的 system 消息计数对比）
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_DIR = Path(__file__).resolve().parent
SERVER_DIR = PROJECT_DIR / "server"

if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services.message_assembler import (  # noqa: E402
    MessageAssembler,
    STYLE_ISOLATION_MSG,
    SEPARATOR_MSG,
    FIRST_TURN_SENTINEL,
    CORE_CONSTRAINTS_TEMPLATE,
)
from services import local_openai_provider as provider_module  # noqa: E402
from services.local_openai_provider import LocalOpenAIProvider  # noqa: E402


# ─────────────────── Helpers ───────────────────────────────────

def _build_test_messages(model_id: str, turn_num: int = 2,
                         history: list[dict] | None = None,
                         memory: str = "", few_shot: list[dict] | None = None,
                         summary: str = "") -> list[dict]:
    """统一构建测试 messages 的 helper。"""
    assembler = MessageAssembler()
    if history is None:
        history = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好呀！"},
        ]
    if few_shot is None:
        few_shot = [
            {"role": "user", "content": "示例输入"},
            {"role": "assistant", "content": "示例输出"},
        ]
    return assembler.build_messages(
        rendered_system="你是一个AI角色",
        system_after="",
        few_shot_messages=few_shot,
        conversation_history=history,
        dialogue_summary=summary,
        memory_context=memory,
        current_input="今天天气不错",
        relationship="朋友",
        role_name="测试角色",
        personality="温暖",
        turn_num=turn_num,
        model_id=model_id,
    )


def _make_fake_provider(monkeypatch, config_override: dict | None = None):
    """创建一个捕获 API 调用参数的 Provider。"""
    captured: dict = {}
    fake_response = SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content="测试回复", reasoning_content=""),
        )],
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

    default_config = {
        "name": "Gemma4 31B",
        "display_name": "Gemma4 31B",
        "provider": "local_openai",
        "api": {
            "base_url": "http://localhost:19006/v1",
            "api_key": "test",
            "model_name": "gemma4",
        },
        "parameters": {"max_tokens": 256, "temperature": 0.7, "top_p": 0.95},
        "thinking": {"enabled": True},
    }
    if config_override:
        default_config.update(config_override)

    return LocalOpenAIProvider(default_config), captured


# ─────────────────── E1: 消息管道完整性 ───────────────────────

class TestE1MessagePipelineIntegrity:
    """E1: Gemma vs 非 Gemma 消息管道分流验证。"""

    def test_gemma_merges_style_and_memory(self):
        """E1a: Gemma 模型合并 STYLE_ISOLATION + memory 为单条。"""
        messages = _build_test_messages("gemma4-31b", memory="【画像】喜欢猫")
        system_msgs = [m for m in messages if m["role"] == "system"]
        # 找包含 STYLE_ISOLATION 的消息
        merged = [m for m in system_msgs if "遵循System Prompt" in m["content"]]
        assert len(merged) == 1, f"应只有一条包含 STYLE_ISOLATION 的 system 消息，实际 {len(merged)}"
        # 合并块应同时包含 memory
        assert "喜欢猫" in merged[0]["content"], "合并块缺少 memory 内容"
        # 应使用 XML 包裹
        assert "<context_boundary>" in merged[0]["content"], "Gemma 应使用 XML 包裹"

    def test_non_gemma_separates_style_and_memory(self):
        """E1b: 非 Gemma 模型保持分离。"""
        messages = _build_test_messages("doubao-pro-32k", memory="【画像】喜欢狗")
        system_msgs = [m for m in messages if m["role"] == "system"]
        # STYLE_ISOLATION 独立
        style_only = [m for m in system_msgs
                      if "遵循System Prompt" in m["content"] and "喜欢狗" not in m["content"]]
        assert style_only, "非 Gemma: STYLE_ISOLATION 应独立存在"
        # memory 独立
        mem_only = [m for m in system_msgs
                    if "喜欢狗" in m["content"] and "遵循System Prompt" not in m["content"]]
        assert mem_only, "非 Gemma: memory 应独立存在"
        # 不使用 XML
        assert "<context_boundary>" not in style_only[0]["content"], "非 Gemma 不应使用 XML 包裹"

    def test_gemma_xml_wraps_depth_injection(self):
        """E1c: Gemma 模型的 Depth Injection 使用 <system_reminder> XML。"""
        full_history = []
        for i in range(1, 5):
            full_history.extend([
                {"role": "user", "content": f"第{i}轮"},
                {"role": "assistant", "content": f"回复{i}"},
            ])
        messages = _build_test_messages("gemma4-31b-local", turn_num=5, history=full_history)
        inject_msgs = [m for m in messages
                       if m["role"] == "system" and "请记住：你是" in m["content"]]
        assert inject_msgs, "应有 Depth Injection 消息"
        assert "<system_reminder>" in inject_msgs[0]["content"], "Gemma Depth Injection 应使用 XML"

    def test_non_gemma_no_xml_depth_injection(self):
        """E1d: 非 Gemma 模型的 Depth Injection 无 XML。"""
        full_history = []
        for i in range(1, 5):
            full_history.extend([
                {"role": "user", "content": f"第{i}轮"},
                {"role": "assistant", "content": f"回复{i}"},
            ])
        messages = _build_test_messages("doubao-pro-32k", turn_num=5, history=full_history)
        inject_msgs = [m for m in messages
                       if m["role"] == "system" and "请记住：你是" in m["content"]]
        assert inject_msgs, "应有 Depth Injection 消息"
        assert "<system_reminder>" not in inject_msgs[0]["content"]

    def test_first_turn_injects_fewshot_for_both_models(self):
        """E1e: 首轮注入 few-shot，两种模型表现一致。"""
        for model_id in ("gemma4-31b", "doubao-pro-32k"):
            messages = _build_test_messages(model_id, turn_num=1, history=[])
            contents = " ".join(m["content"] for m in messages)
            assert "示例输入" in contents, f"{model_id}: 首轮应注入 few-shot"
            assert FIRST_TURN_SENTINEL in contents, f"{model_id}: 首轮应有哨兵"

    def test_message_order_invariant(self):
        """E1f: 消息顺序不变量 — system prompt 始终在首位，user input 始终在末位。"""
        for model_id in ("gemma4-31b", "doubao-pro-32k"):
            messages = _build_test_messages(model_id, memory="记忆内容")
            assert messages[0]["role"] == "system", "首条必须是 system prompt"
            assert messages[-1]["role"] == "user", "末条必须是 user input"
            assert "<user_input>" in messages[-1]["content"]


# ─────────────────── E2: Stop 序列一致性 ──────────────────────

class TestE2StopSequenceConsistency:
    """E2: 双 provider 的 stop 序列注入验证。"""

    def test_local_provider_stop_present(self, monkeypatch):
        """E2a: LocalOpenAIProvider 注入 stop。"""
        provider, captured = _make_fake_provider(monkeypatch)
        provider.call([{"role": "user", "content": "test"}], thinking_effort="disabled")
        assert captured.get("stop") == ["<end_of_turn>"]

    def test_local_provider_stop_with_thinking(self, monkeypatch):
        """E2b: 开启 thinking 时 stop 仍存在。"""
        provider, captured = _make_fake_provider(monkeypatch)
        provider.call([{"role": "user", "content": "test"}], thinking_effort="high")
        assert captured.get("stop") == ["<end_of_turn>"]
        # thinking 模式应有 extra_body
        assert "extra_body" in captured
        assert captured["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True

    def test_stop_does_not_interfere_with_extra_body(self, monkeypatch):
        """E2c: stop 与 extra_body 参数互不干扰。"""
        provider, captured = _make_fake_provider(monkeypatch)
        provider.call([{"role": "user", "content": "test"}], thinking_effort="disabled")
        assert "stop" in captured
        assert "extra_body" in captured
        assert captured["extra_body"]["skip_special_tokens"] is True


# ─────────────────── E3: Thinking Strip 安全性 ────────────────

class TestE3ThinkingStripSafety:
    """E3: thinking strip 不影响非 assistant 消息。"""

    def test_user_content_preserved_with_think_tags(self):
        """E3a: user 消息即使包含 <think> 也不被修改。"""
        history = [
            {"role": "user", "content": "<think>用户消息中的标签</think>正文"},
            {"role": "assistant", "content": "<think>thinking</think>回复"},
        ]
        messages = _build_test_messages("gemma4-31b", history=history)
        user_msgs = [m for m in messages if m["role"] == "user"
                     and "<think>" in m["content"]]
        assert user_msgs, "user 消息中的 <think> 不应被剥离"

    def test_assistant_stripped_completely(self):
        """E3b: assistant 消息中的多种 thinking 标签全部剥离。"""
        history = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": (
                "<think>思考1</think>"
                "<|channel>thought隐藏思考<channel|>"
                "<thought>思考2</thought>"
                "最终回复"
            )},
        ]
        messages = _build_test_messages("gemma4-31b", history=history)
        assistant_msgs = [m for m in messages
                          if m["role"] == "assistant"]
        for msg in assistant_msgs:
            assert "<think>" not in msg["content"]
            assert "<thought>" not in msg["content"]
            assert "<|channel>" not in msg["content"]
            # strip 后至少有正文残留（可能含 few-shot 的示例输出）
            assert "最终回复" in msg["content"] or msg["content"].strip() != ""

    def test_strip_applies_to_all_models(self):
        """E3c: thinking strip 对所有模型生效（不限 Gemma）。"""
        history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "<think>XXX</think>干净内容"},
        ]
        for model_id in ("gemma4-31b", "doubao-pro-32k", "qwen-plus"):
            messages = _build_test_messages(model_id, history=history)
            asst = [m for m in messages if m["role"] == "assistant"]
            for msg in asst:
                assert "<think>" not in msg["content"], f"{model_id}: strip 未生效"


# ─────────────────── E4: 边界条件 ─────────────────────────────

class TestE4BoundaryConditions:
    """E4: 极端输入不崩溃。"""

    def test_empty_history_empty_memory(self):
        """E4a: 空历史 + 空 memory = 只有 system + sentinel + constraints + user。"""
        messages = _build_test_messages("gemma4-31b", turn_num=1,
                                        history=[], memory="", few_shot=[])
        roles = [m["role"] for m in messages]
        assert roles[0] == "system"
        assert roles[-1] == "user"
        # 不应有 STYLE_ISOLATION（没有历史也没有 memory）
        assert all("遵循System Prompt" not in m["content"] for m in messages)

    def test_whitespace_only_memory_treated_as_empty(self):
        """E4b: 纯空白 memory 等同于空。"""
        messages = _build_test_messages("gemma4-31b", memory="   \n\t  ", history=[])
        style_msgs = [m for m in messages
                      if m["role"] == "system" and "遵循System Prompt" in m["content"]]
        assert not style_msgs, "纯空白 memory 不应触发 STYLE_ISOLATION"

    def test_assistant_with_only_thinking_becomes_empty(self):
        """E4c: assistant 内容全是 thinking 标签，strip 后变空字符串。"""
        history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "<think>全是思考内容</think>"},
        ]
        messages = _build_test_messages("gemma4-31b", history=history)
        asst = [m for m in messages if m["role"] == "assistant"]
        assert asst  # 消息仍然存在
        # 历史中的 assistant 消息 strip 后变空，但 few-shot 的 assistant 也在
        history_asst = [m for m in messages
                        if m["role"] == "assistant"
                        and m["content"] != "示例输出"]
        assert history_asst
        assert history_asst[0]["content"].strip() == "", "全思考内容 strip 后应为空"


# ─────────────────── E5: Token 效率 ──────────────────────────

class TestE5TokenEfficiency:
    """E5: Gemma 合并 vs 非 Gemma 分离的 system 消息计数对比。"""

    def test_gemma_has_fewer_system_messages(self):
        """E5a: 相同输入下，Gemma 的 system 消息数少于非 Gemma。"""
        gemma_msgs = _build_test_messages("gemma4-31b", memory="记忆内容")
        other_msgs = _build_test_messages("doubao-pro-32k", memory="记忆内容")

        gemma_sys_count = sum(1 for m in gemma_msgs if m["role"] == "system")
        other_sys_count = sum(1 for m in other_msgs if m["role"] == "system")

        # Gemma 合并了 style + memory，应少 1 条
        assert gemma_sys_count < other_sys_count, (
            f"Gemma system={gemma_sys_count} 应少于非 Gemma system={other_sys_count}"
        )

    def test_core_constraints_present_for_all_models(self):
        """E5b: Core_Constraints 对所有模型都存在。"""
        for model_id in ("gemma4-31b", "doubao-pro-32k"):
            messages = _build_test_messages(model_id, memory="test")
            constraint_msgs = [m for m in messages
                               if m["role"] == "system" and "<Core_Constraints>" in m["content"]]
            assert constraint_msgs, f"{model_id}: 缺少 Core_Constraints"
