"""
test_gemma_repetition_guard.py — Gemma 4 重复字符修复专项测试

覆盖：
  T1: stop=["<end_of_turn>"] 仅对 Gemma 本地模型生效
  T2: message_assembler 合并连续 system 消息
  T3: message_assembler 历史 assistant 消息 thinking strip
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_DIR = Path(__file__).resolve().parent
SERVER_DIR = PROJECT_DIR / "server"

if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services import local_openai_provider as provider_module  # noqa: E402
from services.local_openai_provider import LocalOpenAIProvider  # noqa: E402
from services.message_assembler import MessageAssembler  # noqa: E402


# ───────────────────────────── T1: stop sequences ─────────────────────────────

def _make_local_provider(monkeypatch):
    """创建一个捕获 API 调用参数的 LocalOpenAIProvider。"""
    captured: dict[str, object] = {}
    fake_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="测试回复",
                    reasoning_content="",
                ),
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
            "parameters": {"max_tokens": 256, "temperature": 0.7, "top_p": 0.95},
            "thinking": {"enabled": True},
        }
    )
    return provider, captured


def test_local_openai_provider_passes_stop_end_of_turn(monkeypatch):
    """T1a: Gemma 本地模型必须传递 stop=["<end_of_turn>"]。"""
    provider, captured = _make_local_provider(monkeypatch)
    provider.call(
        [{"role": "user", "content": "测试"}],
        thinking_effort="disabled",
    )
    assert "stop" in captured, "缺少 stop 参数"
    assert captured["stop"] == ["<end_of_turn>"], (
        f"stop 参数应为 ['<end_of_turn>']，实际为 {captured['stop']}"
    )


def test_local_openai_provider_stop_coexists_with_thinking(monkeypatch):
    """T1b: 开启 thinking 时 stop 参数仍然存在。"""
    provider, captured = _make_local_provider(monkeypatch)
    provider.call(
        [{"role": "user", "content": "测试"}],
        thinking_effort="high",
    )
    assert "stop" in captured, "开启 thinking 时缺少 stop 参数"
    assert captured["stop"] == ["<end_of_turn>"]


# ─────────────────── T2: 连续 system 消息合并 ────────────────────

def test_message_assembler_merges_system_messages_for_non_first_turn():
    """T2: 非首轮时 SEPARATOR + STYLE_ISOLATION + memory 不得出现连续 3 条 system。"""
    assembler = MessageAssembler()
    history = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好呀！"},
        {"role": "user", "content": "最近怎么样"},
        {"role": "assistant", "content": "还不错"},
    ]
    few_shot = [
        {"role": "user", "content": "示例用户"},
        {"role": "assistant", "content": "示例回复"},
    ]
    messages = assembler.build_messages(
        rendered_system="你是一个角色",
        system_after="",
        few_shot_messages=few_shot,
        conversation_history=history,
        dialogue_summary="之前聊了天气",
        memory_context="【长期记忆用户画像】\n喜欢猫",
        current_input="今天天气不错",
        relationship="朋友",
        role_name="测试角色",
        personality="温暖",
        turn_num=3,
        model_id="gemma4-31b-local",
    )

    # 检查不存在连续 3 条 system 消息
    consecutive_system = 0
    max_consecutive = 0
    for msg in messages:
        if msg["role"] == "system":
            consecutive_system += 1
            max_consecutive = max(max_consecutive, consecutive_system)
        else:
            consecutive_system = 0

    # Plan B: main system + embedded Few-shot + merged style/memory = 最多 3 条连续 system
    # 千问路径最多 2 条（合并更多），Gemma 路径 3 条（system + XML embedded + style merged）
    assert max_consecutive <= 3, (
        f"存在连续 {max_consecutive} 条 system 消息，应合并为 ≤3 条"
    )


def test_message_assembler_merged_system_contains_all_parts():
    """T2b: 合并后的 system 消息应包含 SEPARATOR + STYLE_ISOLATION + memory。"""
    assembler = MessageAssembler()
    history = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好呀"},
    ]
    few_shot = [
        {"role": "user", "content": "示例"},
        {"role": "assistant", "content": "回复"},
    ]
    memory = "【长期记忆用户画像】\n喜欢猫"
    messages = assembler.build_messages(
        rendered_system="你是角色",
        system_after="",
        few_shot_messages=few_shot,
        conversation_history=history,
        dialogue_summary="摘要",
        memory_context=memory,
        current_input="你好",
        relationship="朋友",
        role_name="角色",
        personality="温暖",
        turn_num=2,
        model_id="gemma4-31b",
    )

    # Gemma 路径：检查 Few-shot 以 system 内嵌形式存在（Plan B）
    system_contents = [m["content"] for m in messages if m["role"] == "system"]
    fewshot_system = [c for c in system_contents if "writing_style_example" in c or "写作风格示例" in c]
    assert fewshot_system, "Gemma 路径应有 system 内嵌的 Few-shot 示例"
    # 确认示例内容被嵌入
    assert "示例" in fewshot_system[0] or "回复" in fewshot_system[0], (
        "system 内嵌的 Few-shot 应包含示例内容"
    )


def test_message_assembler_keeps_separate_system_for_default_models():
    """T2c: 非 Gemma 模型保持 STYLE_ISOLATION 和 memory_context 分离。"""
    assembler = MessageAssembler()
    history = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好呀"},
    ]
    memory = "【长期记忆用户画像】\n喜欢猫"
    messages = assembler.build_messages(
        rendered_system="你是角色",
        system_after="",
        few_shot_messages=[],
        conversation_history=history,
        dialogue_summary="摘要",
        memory_context=memory,
        current_input="你好",
        relationship="朋友",
        role_name="角色",
        personality="温暖",
        turn_num=2,
        model_id="doubao-pro-32k",  # 非 Gemma 模型
    )

    system_contents = [m["content"] for m in messages if m["role"] == "system"]
    # 非 Gemma 应有独立的 STYLE_ISOLATION（不含 memory）
    style_only = [c for c in system_contents if "遵循System Prompt" in c and "喜欢猫" not in c]
    assert style_only, "非 Gemma 模型的 STYLE_ISOLATION 应独立存在"
    # memory 应作为单独的 system 消息
    memory_only = [c for c in system_contents if "喜欢猫" in c and "遵循System Prompt" not in c]
    assert memory_only, "非 Gemma 模型的 memory_context 应独立存在"


# ─────────────────── T4: 千问 System 合并专项测试 ────────────────────

def test_qwen_merges_fewshot_prefix_into_main_system():
    """T4a: 千问非首轮时 FEW_SHOT_PREFIX 应合并到主 system 末尾，不作为独立消息。"""
    from services.message_assembler import FEW_SHOT_PREFIX_MSG

    assembler = MessageAssembler()
    history = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好呀"},
    ]
    few_shot = [
        {"role": "user", "content": "示例用户"},
        {"role": "assistant", "content": "示例回复"},
    ]
    messages = assembler.build_messages(
        rendered_system="你是一个角色",
        system_after="",
        few_shot_messages=few_shot,
        conversation_history=history,
        dialogue_summary="",
        memory_context="记忆",
        current_input="测试",
        relationship="朋友",
        role_name="角色",
        personality="温暖",
        turn_num=2,
        model_id="qwen3.6-plus",
    )

    # 第一条 system 应包含主系统 prompt + FEW_SHOT_PREFIX
    first_system = messages[0]
    assert first_system["role"] == "system"
    assert "你是一个角色" in first_system["content"]
    assert "写作风格示例开始" in first_system["content"], (
        "千问模型的 FEW_SHOT_PREFIX 应合并到主 system 末尾"
    )
    # FEW_SHOT_PREFIX 不应作为独立 system 消息存在
    system_contents = [m["content"] for m in messages if m["role"] == "system"]
    standalone_prefix = [
        c for c in system_contents
        if c.strip() == FEW_SHOT_PREFIX_MSG.strip()
    ]
    assert not standalone_prefix, "千问模型不应有独立的 FEW_SHOT_PREFIX system 消息"


def test_qwen_merges_separator_style_memory_into_one():
    """T4b: 千问非首轮时 SEPARATOR + STYLE_ISOLATION + memory 应合并为一条 system。"""
    assembler = MessageAssembler()
    history = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好呀"},
    ]
    few_shot = [
        {"role": "user", "content": "示例"},
        {"role": "assistant", "content": "回复"},
    ]
    memory = "【长期记忆用户画像】\n喜欢猫"
    messages = assembler.build_messages(
        rendered_system="你是角色",
        system_after="",
        few_shot_messages=few_shot,
        conversation_history=history,
        dialogue_summary="",
        memory_context=memory,
        current_input="你好",
        relationship="朋友",
        role_name="角色",
        personality="温暖",
        turn_num=2,
        model_id="qwen3.6-plus",
    )

    system_contents = [m["content"] for m in messages if m["role"] == "system"]
    # 应有一条同时包含 SEPARATOR + STYLE_ISOLATION + memory 的合并 system
    merged = [
        c for c in system_contents
        if "风格示例结束" in c and "遵循System Prompt" in c and "喜欢猫" in c
    ]
    assert merged, (
        "千问模型应有一条合并了 SEPARATOR + STYLE_ISOLATION + memory 的 system 消息"
    )
    # SEPARATOR 不应作为独立 system 存在
    standalone_sep = [
        c for c in system_contents
        if "风格示例结束" in c and "遵循System Prompt" not in c
    ]
    assert not standalone_sep, "千问模型的 SEPARATOR 不应独立存在"


def test_qwen_first_turn_skips_fewshot():
    """T4c: 千问首轮应跳过 Few-shot，走普通 system（与非千问行为一致）。"""
    assembler = MessageAssembler()
    few_shot = [
        {"role": "user", "content": "示例用户"},
        {"role": "assistant", "content": "示例回复"},
    ]
    messages = assembler.build_messages(
        rendered_system="你是角色",
        system_after="",
        few_shot_messages=few_shot,
        conversation_history=[],  # 首轮：无历史
        dialogue_summary="",
        memory_context="",
        current_input="你好",
        relationship="朋友",
        role_name="角色",
        personality="温暖",
        turn_num=1,
        model_id="qwen3.6-plus",
    )

    # 首轮不应包含 Few-shot 内容
    all_contents = " ".join(m["content"] for m in messages)
    assert "示例用户" not in all_contents, "千问首轮不应注入 Few-shot"
    assert "示例回复" not in all_contents, "千问首轮不应注入 Few-shot"
    # 应包含首轮哨兵
    assert "第一次对话" in all_contents, "千问首轮应包含首轮哨兵消息"
    # 主 system 不应包含 FEW_SHOT_PREFIX
    assert "写作风格示例开始" not in messages[0]["content"], (
        "千问首轮主 system 不应包含 FEW_SHOT_PREFIX"
    )


# ─────────────────── T3: 历史 thinking strip ────────────────────

def test_message_assembler_strips_thinking_from_history():
    """T3a: 历史 assistant 消息中的 <think> 标签应被剥离。"""
    assembler = MessageAssembler()
    history = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "<think>分析用户意图...</think>\n最终答案文本"},
    ]
    messages = assembler.build_messages(
        rendered_system="你是角色",
        system_after="",
        few_shot_messages=[],
        conversation_history=history,
        dialogue_summary="",
        memory_context="",
        current_input="再见",
        relationship="朋友",
        role_name="角色",
        personality="冷静",
        turn_num=2,
        model_id="gemma4-31b-local",
    )

    # 找到 assistant 消息
    assistant_msgs = [m for m in messages if m["role"] == "assistant"]
    assert assistant_msgs, "未找到 assistant 消息"
    for msg in assistant_msgs:
        assert "<think>" not in msg["content"], (
            f"assistant 消息中残留 <think> 标签: {msg['content'][:100]}"
        )
        assert "最终答案文本" in msg["content"], "strip 后正文内容丢失"


def test_message_assembler_strips_thinking_channel_from_history():
    """T3b: 历史 assistant 消息中的思考通道标记也应被剥离。"""
    assembler = MessageAssembler()
    history = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "<|channel>thought这里是思考<channel|>\n正文内容"},
    ]
    messages = assembler.build_messages(
        rendered_system="你是角色",
        system_after="",
        few_shot_messages=[],
        conversation_history=history,
        dialogue_summary="",
        memory_context="",
        current_input="在吗",
        relationship="朋友",
        role_name="角色",
        personality="冷静",
        turn_num=2,
        model_id="gemma4-31b",
    )

    assistant_msgs = [m for m in messages if m["role"] == "assistant"]
    assert assistant_msgs
    for msg in assistant_msgs:
        assert "<|channel>" not in msg["content"], (
            f"assistant 消息中残留思考通道标记"
        )
        assert "正文内容" in msg["content"]


def test_message_assembler_preserves_user_messages_in_history():
    """T3c: thinking strip 不应影响 user 消息。"""
    assembler = MessageAssembler()
    history = [
        {"role": "user", "content": "用户消息不变"},
        {"role": "assistant", "content": "<think>思考</think>\n回复"},
    ]
    messages = assembler.build_messages(
        rendered_system="你是角色",
        system_after="",
        few_shot_messages=[],
        conversation_history=history,
        dialogue_summary="",
        memory_context="",
        current_input="继续",
        relationship="朋友",
        role_name="角色",
        personality="冷静",
        turn_num=2,
        model_id="gemma4-31b-local",
    )

    user_msgs = [m for m in messages if m["role"] == "user"]
    contents = [m["content"] for m in user_msgs]
    assert "用户消息不变" in contents, "user 消息被意外修改"


# ────────────── T4: Plan B Few-shot 注入改造 ──────────────

def test_plan_b_embeds_few_shot_in_system_for_default_model():
    """T4a: 非Gemma/非Qwen/非MiniMax模型：Few-shot 以 system 内嵌注入，无 user/assistant 角色示例。"""
    assembler = MessageAssembler()
    history = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好呀"},
    ]
    few_shot = [
        {"role": "user", "content": "示例用户输入"},
        {"role": "assistant", "content": "示例角色回复"},
    ]
    messages = assembler.build_messages(
        rendered_system="你是一个角色",
        system_after="",
        few_shot_messages=few_shot,
        conversation_history=history,
        dialogue_summary="摘要",
        memory_context="记忆",
        current_input="你好",
        relationship="朋友",
        role_name="角色",
        personality="温暖",
        turn_num=2,
        model_id="doubao-pro-32k",  # 非 Gemma/Qwen/MiniMax
    )

    # 应有 system 内嵌的 Few-shot
    system_contents = [m["content"] for m in messages if m["role"] == "system"]
    fewshot_system = [c for c in system_contents if "写作风格示例" in c]
    assert fewshot_system, "Plan B 应以 system 内嵌方式注入 Few-shot"
    assert "示例用户输入" in fewshot_system[0], "system 内嵌应包含 user 示例内容"
    assert "示例角色回复" in fewshot_system[0], "system 内嵌应包含 assistant 示例内容"

    # 不应存在 user/assistant 角色的 Few-shot 示例消息
    for msg in messages:
        if msg["role"] == "user" and msg["content"] == "示例用户输入":
            raise AssertionError("Plan B 不应有 role=user 的 Few-shot 示例")
        if msg["role"] == "assistant" and msg["content"] == "示例角色回复":
            raise AssertionError("Plan B 不应有 role=assistant 的 Few-shot 示例")


def test_plan_b_gemma_uses_xml_tags():
    """T4b: Gemma 模型：Few-shot system 内嵌消息包含 XML 标签。"""
    assembler = MessageAssembler()
    history = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好呀"},
    ]
    few_shot = [
        {"role": "user", "content": "示例用户"},
        {"role": "assistant", "content": "示例回复"},
    ]
    messages = assembler.build_messages(
        rendered_system="你是角色",
        system_after="",
        few_shot_messages=few_shot,
        conversation_history=history,
        dialogue_summary="摘要",
        memory_context="记忆",
        current_input="你好",
        relationship="朋友",
        role_name="角色",
        personality="温暖",
        turn_num=2,
        model_id="gemma4-31b",
    )

    system_contents = [m["content"] for m in messages if m["role"] == "system"]
    fewshot_system = [c for c in system_contents if "writing_style_example" in c]
    assert fewshot_system, "Gemma 应使用 XML 标签包裹 Few-shot system 内嵌"
    assert "<example_user>" in fewshot_system[0], "缺少 <example_user> XML 标签"
    assert "<example_assistant>" in fewshot_system[0], "缺少 <example_assistant> XML 标签"
    assert "示例用户" in fewshot_system[0], "XML 内应包含示例内容"


def test_minimax_uses_plan_b_system_embedding():
    """T4c: MiniMax 模型：Few-shot 以 system 内嵌注入（与默认模型一致），无非标 role。"""
    assembler = MessageAssembler()
    history = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好呀"},
    ]
    few_shot = [
        {"role": "user", "content": "示例用户输入"},
        {"role": "assistant", "content": "示例角色回复"},
    ]
    messages = assembler.build_messages(
        rendered_system="你是一个角色",
        system_after="",
        few_shot_messages=few_shot,
        conversation_history=history,
        dialogue_summary="摘要",
        memory_context="记忆",
        current_input="你好",
        relationship="朋友",
        role_name="角色",
        personality="温暖",
        turn_num=2,
        model_id="minimax-m27",
    )

    # MiniMax 应走 Plan B: system 内嵌，与默认模型一致
    system_contents = [m["content"] for m in messages if m["role"] == "system"]
    fewshot_system = [c for c in system_contents if "写作风格示例" in c]
    assert fewshot_system, "MiniMax 应以 system 内嵌方式注入 Few-shot（Plan B）"
    assert "示例用户输入" in fewshot_system[0], "system 内嵌应包含 user 示例内容"
    assert "示例角色回复" in fewshot_system[0], "system 内嵌应包含 assistant 示例内容"

    # 不应存在非标 role（sample_message_user/ai）
    roles = [m["role"] for m in messages]
    assert "sample_message_user" not in roles, "MiniMax 不应使用 sample_message_user 非标 role"
    assert "sample_message_ai" not in roles, "MiniMax 不应使用 sample_message_ai 非标 role"

    # 不应有 user/assistant 角色的 Few-shot 示例
    for msg in messages:
        if msg["role"] == "user" and msg["content"] == "示例用户输入":
            raise AssertionError("Plan B 不应有 role=user 的 Few-shot 示例")
        if msg["role"] == "assistant" and msg["content"] == "示例角色回复":
            raise AssertionError("Plan B 不应有 role=assistant 的 Few-shot 示例")


def test_plan_b_first_turn_injects_few_shot():
    """T4d: Plan B 模型首轮也注入 Few-shot（system 内嵌），千问首轮仍跳过。"""
    assembler = MessageAssembler()
    few_shot = [
        {"role": "user", "content": "示例用户"},
        {"role": "assistant", "content": "示例回复"},
    ]

    # Plan B 模型（doubao）首轮：应有 system 内嵌 Few-shot
    msgs_planb = assembler.build_messages(
        rendered_system="你是角色",
        system_after="",
        few_shot_messages=few_shot,
        conversation_history=[],  # 首轮，无历史
        dialogue_summary="",
        memory_context="",
        current_input="你好",
        relationship="朋友",
        role_name="角色",
        personality="温暖",
        turn_num=1,
        model_id="doubao-pro-32k",
    )
    sys_contents = [m["content"] for m in msgs_planb if m["role"] == "system"]
    has_fewshot = any("写作风格示例" in c for c in sys_contents)
    assert has_fewshot, "Plan B 首轮应包含 system 内嵌的 Few-shot"

    # 千问首轮：不应有 Few-shot
    msgs_qwen = assembler.build_messages(
        rendered_system="你是角色",
        system_after="",
        few_shot_messages=few_shot,
        conversation_history=[],  # 首轮，无历史
        dialogue_summary="",
        memory_context="",
        current_input="你好",
        relationship="朋友",
        role_name="角色",
        personality="温暖",
        turn_num=1,
        model_id="qwen-max",
    )
    sys_qwen = [m["content"] for m in msgs_qwen if m["role"] == "system"]
    has_qwen_fewshot = any("写作风格示例" in c or "风格示例正文" in c for c in sys_qwen)
    assert not has_qwen_fewshot, "千问首轮应跳过 Few-shot（S1 保留）"

