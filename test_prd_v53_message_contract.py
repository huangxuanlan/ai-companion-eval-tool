"""
PRD v5.3 消息合同合规测试
按 §3.4/§3.4.2/§3.8 验证 MessageAssembler 的两套路径。

覆盖的 PRD 条款:
  - §3.4   单 system + assistant 摘要 + 历史 + user
  - §3.4.1 T1-T4 消息传输合同
  - §3.4.2 System 消息合并策略
  - §3.8   异质上下文隔离（双向三明治）
  - §3.7   Depth 角色锚定
  - v5.0   首轮 Few-shot 注入
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR / "server"))

from services.message_assembler import (
    MessageAssembler,
    FIRST_TURN_SENTINEL,
    STYLE_ISOLATION_MSG,
    CORE_CONSTRAINTS_TEMPLATE,
    SYSTEM_EMBEDDED_FEW_SHOT,
    V52_SUMMARY_PREFIX,
    V52_SUMMARY_START,
    V52_SUMMARY_END,
    V52_SUMMARY_SUFFIX,
    V52_USER_CORE_CONSTRAINTS,
    SHORTFORM_HISTORY_PREFIX,
    SHORTFORM_HISTORY_SUFFIX,
    LONGFORM_HISTORY_PREFIX,
    LONGFORM_HISTORY_SUFFIX,
)


# ═══════════════════════════════════════════════════════════════════
# 测试工具
# ═══════════════════════════════════════════════════════════════════

def _assembler():
    return MessageAssembler()

SAMPLE_SYSTEM = "你是林缼，24岁商业分析师。"
SAMPLE_AFTER = "性格: 慢条斯理、压迫感强"
SAMPLE_FEWSHOT = [
    {"role": "user", "content": "不用送了，这条路我很熟的。"},
    {"role": "assistant", "content": "小巷的路灯是老式的那种……"},
]
SAMPLE_HISTORY = [
    {"role": "user", "content": "上一轮用户输入"},
    {"role": "assistant", "content": "上一轮角色回复"},
]
SAMPLE_SUMMARY = "【本次对话智能摘要】用户加班到很晚，角色陪她聊天。"
SAMPLE_MEMORY = "【长期记忆用户画像】身份:上班族\n\n【历史对话摘要】\n用户加班到很晚。"
SAMPLE_INPUT = "今晚月亮好圆啊"
SAMPLE_RELATIONSHIP = "暧昧"
SAMPLE_ROLE = "林缼"
SAMPLE_PERSONALITY = "慢条斯理"


def _build_v52(
    *,
    history=None,
    summary="",
    memory="",
    fewshot=None,
    model_id="qwen3.6-plus",
    history_source_mode="",
    turn_num=2,
):
    """v5.2 路径快捷构建"""
    old = os.environ.get("LONGFORM_V52_MESSAGE_CONTRACT")
    os.environ["LONGFORM_V52_MESSAGE_CONTRACT"] = "1"
    try:
        return _assembler().build_messages(
            rendered_system=SAMPLE_SYSTEM,
            system_after=SAMPLE_AFTER,
            few_shot_messages=fewshot or SAMPLE_FEWSHOT,
            conversation_history=history if history is not None else SAMPLE_HISTORY,
            dialogue_summary=summary,
            memory_context=memory,
            current_input=SAMPLE_INPUT,
            relationship=SAMPLE_RELATIONSHIP,
            role_name=SAMPLE_ROLE,
            personality=SAMPLE_PERSONALITY,
            turn_num=turn_num,
            model_id=model_id,
            history_source_mode=history_source_mode,
        )
    finally:
        if old is None:
            os.environ.pop("LONGFORM_V52_MESSAGE_CONTRACT", None)
        else:
            os.environ["LONGFORM_V52_MESSAGE_CONTRACT"] = old


def _build_legacy(*, history=None, model_id="doubao-pro", turn_num=2, fewshot=None):
    """原路径快捷构建"""
    os.environ.pop("LONGFORM_V52_MESSAGE_CONTRACT", None)
    return _assembler().build_messages(
        rendered_system=SAMPLE_SYSTEM,
        system_after=SAMPLE_AFTER,
        few_shot_messages=fewshot or SAMPLE_FEWSHOT,
        conversation_history=history if history is not None else SAMPLE_HISTORY,
        dialogue_summary=SAMPLE_SUMMARY,
        memory_context=SAMPLE_MEMORY,
        current_input=SAMPLE_INPUT,
        relationship=SAMPLE_RELATIONSHIP,
        role_name=SAMPLE_ROLE,
        personality=SAMPLE_PERSONALITY,
        turn_num=turn_num,
        model_id=model_id,
    )


# ═══════════════════════════════════════════════════════════════════
# §3.4.2 T1: v5.2 路径 — 单 system 消息合同
# ═══════════════════════════════════════════════════════════════════

class TestV52SingleSystemContract:
    """PRD §3.4.2: messages[0] 为唯一 system，所有指令合并其中。"""

    def test_only_one_system_message(self):
        """v5.2 路径应仅输出 1 条 system 消息（messages[0]）"""
        msgs = _build_v52()
        system_msgs = [m for m in msgs if m["role"] == "system"]
        assert len(system_msgs) == 1, (
            f"PRD §3.4.2 要求单 system，实际有 {len(system_msgs)} 条"
        )
        assert msgs[0]["role"] == "system"

    def test_system_contains_few_shot(self):
        """PRD §3.4: Few-shot 应嵌入 messages[0].system.content"""
        msgs = _build_v52()
        system_content = msgs[0]["content"]
        assert "写作风格示例" in system_content, "Few-shot 未嵌入主 system"

    def test_system_contains_style_isolation(self):
        """PRD §3.4: 风格隔离声明应嵌入 messages[0]"""
        msgs = _build_v52()
        system_content = msgs[0]["content"]
        assert "风格隔离声明" in system_content

    def test_system_contains_depth_rule(self):
        """PRD §3.4: Depth 角色锚定规则应嵌入 messages[0]"""
        msgs = _build_v52()
        system_content = msgs[0]["content"]
        assert "角色锚定规则" in system_content
        assert SAMPLE_ROLE in system_content

    def test_system_contains_core_constraints(self):
        """PRD §3.4: Core_Constraints 总则应嵌入 messages[0]"""
        msgs = _build_v52()
        system_content = msgs[0]["content"]
        assert "Core_Constraints" in system_content or "300-500字" in system_content


# ═══════════════════════════════════════════════════════════════════
# §3.4.2 T2: 动态摘要 → assistant 角色
# ═══════════════════════════════════════════════════════════════════

class TestV52SummaryAsAssistant:
    """PRD §3.4.1 T2: dialogue_summary 使用 role=assistant + 隔离边界。"""

    def test_summary_injected_as_assistant(self):
        """有摘要时，应作为 assistant 消息注入"""
        msgs = _build_v52(summary=SAMPLE_SUMMARY)
        # 第二条消息应是 assistant（摘要）
        assert msgs[1]["role"] == "assistant"

    def test_summary_has_isolation_boundary(self):
        """摘要 assistant 消息应包含 §3.4.1 T2 隔离边界"""
        msgs = _build_v52(summary=SAMPLE_SUMMARY)
        content = msgs[1]["content"]
        assert V52_SUMMARY_PREFIX in content or "内部认知记录" in content
        assert V52_SUMMARY_END in content or "摘要结束" in content

    def test_no_summary_when_empty(self):
        """无摘要时，不应注入 assistant 消息"""
        msgs = _build_v52(summary="", memory="")
        roles = [m["role"] for m in msgs]
        # 消息顺序: system → 历史 → user（无 assistant 摘要块）
        assert roles[0] == "system"
        assert roles[-1] == "user"
        if len(msgs) > 2:
            # 不应有单独的空摘要 assistant
            for m in msgs[1:-1]:
                if m["role"] == "assistant":
                    assert V52_SUMMARY_PREFIX not in m["content"]


# ═══════════════════════════════════════════════════════════════════
# §3.8: 异质上下文三明治隔离 (v5.2 路径)
# ═══════════════════════════════════════════════════════════════════

class TestV52CrossModeIsolation:
    """PRD §3.8: 异质 assistant 上下文应执行格式隔离。"""

    def test_short_in_long_gets_prefix(self):
        """短文 assistant 进入长文目标请求时，应添加隔离前缀"""
        history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "短文回复", "source_mode": "short"},
        ]
        msgs = _build_v52(history=history, model_id="qwen3.6-plus")
        # 找到经过隔离处理后的 assistant
        asst_msgs = [m for m in msgs if m["role"] == "assistant" and "短文回复" in m["content"]]
        assert len(asst_msgs) >= 1
        isolated = asst_msgs[0]["content"]
        assert SHORTFORM_HISTORY_PREFIX in isolated, (
            f"短文→长文隔离前缀缺失。实际内容: {isolated[:100]}"
        )
        assert SHORTFORM_HISTORY_SUFFIX in isolated

    def test_long_in_short_gets_prefix(self):
        """长文 assistant 进入短文目标请求时，应添加隔离前缀"""
        history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "长文回复", "source_mode": "long"},
        ]
        msgs = _build_v52(history=history, model_id="doubao-pro")
        asst_msgs = [m for m in msgs if m["role"] == "assistant" and "长文回复" in m["content"]]
        assert len(asst_msgs) >= 1
        isolated = asst_msgs[0]["content"]
        assert LONGFORM_HISTORY_PREFIX in isolated, (
            f"长文→短文隔离前缀缺失。实际内容: {isolated[:100]}"
        )

    def test_same_mode_no_isolation(self):
        """同模式 assistant 不应添加隔离标记"""
        history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "正常长文回复", "source_mode": "long"},
        ]
        msgs = _build_v52(history=history, model_id="qwen3.6-plus")
        asst_msgs = [m for m in msgs if m["role"] == "assistant" and "正常长文回复" in m["content"]]
        assert len(asst_msgs) >= 1
        isolated = asst_msgs[0]["content"]
        assert SHORTFORM_HISTORY_PREFIX not in isolated
        assert LONGFORM_HISTORY_PREFIX not in isolated

    def test_user_messages_never_isolated(self):
        """PRD §3.8: role=user 消息不做任何处理"""
        history = [
            {"role": "user", "content": "用户消息不处理"},
            {"role": "assistant", "content": "回复"},
        ]
        msgs = _build_v52(history=history)
        user_in_hist = [m for m in msgs if m["role"] == "user" and "用户消息不处理" in m["content"]]
        assert len(user_in_hist) == 1
        assert user_in_hist[0]["content"] == "用户消息不处理"

    def test_already_isolated_not_double_wrapped(self):
        """已包含隔离标记的消息不应二次包裹"""
        already_wrapped = f"{SHORTFORM_HISTORY_PREFIX}\n短文回复\n{SHORTFORM_HISTORY_SUFFIX}"
        history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": already_wrapped, "source_mode": "short"},
        ]
        msgs = _build_v52(history=history, model_id="qwen3.6-plus")
        asst_msgs = [m for m in msgs if m["role"] == "assistant" and "短文回复" in m["content"]]
        assert len(asst_msgs) >= 1
        count = asst_msgs[0]["content"].count(SHORTFORM_HISTORY_PREFIX)
        assert count == 1, f"隔离前缀被重复添加 {count} 次"


# ═══════════════════════════════════════════════════════════════════
# v5.0: 首轮 Few-shot 注入
# ═══════════════════════════════════════════════════════════════════

class TestFirstTurnFewShotInjection:
    """PRD v5.0 修订: 首轮也注入 Few-shot"""

    def test_v52_first_turn_has_fewshot(self):
        """v5.2 路径首轮: system 中应包含 Few-shot"""
        msgs = _build_v52(history=[], turn_num=1)
        system_content = msgs[0]["content"]
        assert "写作风格示例" in system_content, "首轮应注入 Few-shot"

    def test_v52_second_turn_has_fewshot(self):
        """v5.2 路径非首轮: system 中应包含 Few-shot"""
        msgs = _build_v52(history=SAMPLE_HISTORY)
        system_content = msgs[0]["content"]
        assert "写作风格示例" in system_content, "非首轮应注入 Few-shot"

    def test_v52_summary_cleared_history_still_has_fewshot_after_first_turn(self):
        """摘要清空历史后，第 11/21 等非首轮仍应注入 Few-shot。"""
        msgs = _build_v52(history=[], summary=SAMPLE_SUMMARY, turn_num=11)
        system_content = msgs[0]["content"]
        assert "写作风格示例" in system_content, "摘要清空后的非首轮应继续注入 Few-shot"
        assert msgs[1]["role"] == "assistant", "摘要应保持 assistant 独立消息"

    def test_legacy_first_turn_has_fewshot(self):
        """原路径首轮: 应注入 Few-shot"""
        msgs = _build_legacy(history=[], turn_num=1)
        merged = "\n".join(m.get("content", "") for m in msgs)
        assert "写作风格示例" in merged

    def test_legacy_first_turn_has_sentinel(self):
        """原路径首轮: 应包含首次对话哨兵"""
        msgs = _build_legacy(history=[], turn_num=1)
        sentinel_msgs = [m for m in msgs if FIRST_TURN_SENTINEL in m.get("content", "")]
        assert len(sentinel_msgs) == 1

    def test_legacy_second_turn_has_fewshot(self):
        """原路径非首轮: 应注入 Few-shot"""
        msgs = _build_legacy(history=SAMPLE_HISTORY, turn_num=2, model_id="doubao-pro")
        merged = "\n".join(m.get("content", "") for m in msgs)
        assert "写作风格示例" in merged, "非首轮应注入 Few-shot"


# ═══════════════════════════════════════════════════════════════════
# §3.4: 当前用户输入 — Core_Constraints + <user_input>
# ═══════════════════════════════════════════════════════════════════

class TestUserInputFormat:
    """PRD §3.4: 长文目标请求使用 Core + <user_input>"""

    def test_v52_long_mode_user_has_core_and_input(self):
        """v5.2 长文目标请求: user 消息包含 Core_Constraints + user_input"""
        msgs = _build_v52(model_id="qwen3.6-plus")
        last_user = msgs[-1]
        assert last_user["role"] == "user"
        assert "<Core_Constraints>" in last_user["content"]
        assert "<user_input>" in last_user["content"]
        assert SAMPLE_INPUT in last_user["content"]

    def test_v52_short_mode_user_no_core(self):
        """v5.2 短文目标请求: user 消息不新增 Core"""
        msgs = _build_v52(model_id="doubao-pro")
        last_user = msgs[-1]
        assert last_user["role"] == "user"
        assert "<Core_Constraints>" not in last_user["content"]

    def test_legacy_user_has_user_input_tag(self):
        """原路径: user 消息包含 <user_input> 标签"""
        msgs = _build_legacy()
        last_user = msgs[-1]
        assert last_user["role"] == "user"
        assert f"<user_input>{SAMPLE_INPUT}</user_input>" in last_user["content"]


# ═══════════════════════════════════════════════════════════════════
# 原路径: 多模型分支 system 消息计数
# ═══════════════════════════════════════════════════════════════════

class TestLegacyModelBranches:
    """验证原路径的多模型分支消息结构正确性。"""

    @pytest.mark.parametrize("model_id,expected_max_system", [
        ("qwen3.6-plus", 3),    # system + few_shot_prefix, system(SEP+STYLE+memory), Core
        ("doubao-pro", 5),      # system, system(fewshot), system(STYLE), system(memory), Core
        ("gemma4-31b", 4),      # system, system(fewshot_xml), system(STYLE+memory), Core
    ])
    def test_system_count_per_model(self, model_id, expected_max_system):
        """各模型分支的 system 消息数量应在预期范围内"""
        msgs = _build_legacy(model_id=model_id)
        system_count = sum(1 for m in msgs if m["role"] == "system")
        assert system_count <= expected_max_system, (
            f"{model_id}: system 消息 {system_count} 条，超过上限 {expected_max_system}"
        )

    def test_first_message_is_system(self):
        """所有模型: 第一条消息固定为 system"""
        for model_id in ("qwen3.6-plus", "doubao-pro", "gemma4-31b"):
            msgs = _build_legacy(model_id=model_id)
            assert msgs[0]["role"] == "system"

    def test_last_message_is_user(self):
        """所有模型: 最后一条消息固定为 user"""
        for model_id in ("qwen3.6-plus", "doubao-pro", "gemma4-31b"):
            msgs = _build_legacy(model_id=model_id)
            assert msgs[-1]["role"] == "user"


# ═══════════════════════════════════════════════════════════════════
# 记忆上下文单次注入
# ═══════════════════════════════════════════════════════════════════

class TestMemorySingleInjection:
    """所有路径: 记忆内容只出现 1 次，无重复注入。"""

    def test_v52_memory_not_duplicated(self):
        """v5.2: memory_context 中的内容只出现 1 次"""
        marker = "UNIQUE_PROFILE_MARKER_789"
        msgs = _build_v52(memory=f"【长期记忆用户画像】\n{marker}")
        full_text = "\n".join(m.get("content", "") for m in msgs)
        assert full_text.count(marker) == 1, "记忆上下文被重复注入"

    def test_legacy_memory_not_duplicated(self):
        """原路径: memory_context 中的内容只出现 1 次"""
        marker = "UNIQUE_PROFILE_MARKER_789"
        os.environ.pop("LONGFORM_V52_MESSAGE_CONTRACT", None)
        msgs = _assembler().build_messages(
            rendered_system=SAMPLE_SYSTEM,
            system_after=SAMPLE_AFTER,
            few_shot_messages=SAMPLE_FEWSHOT,
            conversation_history=SAMPLE_HISTORY,
            dialogue_summary="",
            memory_context=f"【长期记忆用户画像】\n{marker}",
            current_input=SAMPLE_INPUT,
            relationship=SAMPLE_RELATIONSHIP,
            role_name=SAMPLE_ROLE,
            personality=SAMPLE_PERSONALITY,
            turn_num=2,
            model_id="doubao-pro",
        )
        full_text = "\n".join(m.get("content", "") for m in msgs)
        assert full_text.count(marker) == 1


# ═══════════════════════════════════════════════════════════════════
# Thinking 标签 strip
# ═══════════════════════════════════════════════════════════════════

class TestThinkingStrip:
    """PRD v4.0 §3.5 #11: 历史 assistant 消息中思考标签必须剥离"""

    def test_v52_strips_think_tags(self):
        """v5.2: <think>...</think> 应从历史 assistant 中剥离"""
        history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "<think>内部推理</think>实际回复"},
        ]
        msgs = _build_v52(history=history)
        asst_msgs = [m for m in msgs if m["role"] == "assistant"]
        for m in asst_msgs:
            assert "<think>" not in m["content"]
            assert "</think>" not in m["content"]

    def test_legacy_strips_think_tags(self):
        """原路径: <think>...</think> 应从历史 assistant 中剥离"""
        history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "<think>内部推理</think>实际回复"},
        ]
        msgs = _build_legacy(history=history)
        asst_msgs = [m for m in msgs if m["role"] == "assistant"]
        for m in asst_msgs:
            assert "<think>" not in m["content"]


# ═══════════════════════════════════════════════════════════════════
# v5.2 路径: 消息顺序合约
# ═══════════════════════════════════════════════════════════════════

class TestV52MessageOrder:
    """PRD §3.4: 消息物理位置顺序。"""

    def test_order_with_summary_and_history(self):
        """有摘要+历史: system → assistant(摘要) → 历史 → user"""
        msgs = _build_v52(summary=SAMPLE_SUMMARY, history=SAMPLE_HISTORY)
        roles = [m["role"] for m in msgs]
        assert roles[0] == "system"
        assert roles[1] == "assistant"  # 摘要
        assert roles[-1] == "user"       # 当前输入

    def test_order_first_turn(self):
        """首轮: system → user（无摘要、无历史）"""
        msgs = _build_v52(history=[], summary="", memory="", turn_num=1)
        assert len(msgs) == 2, f"首轮无历史应只有 2 条消息，实际 {len(msgs)}"
        assert msgs[0]["role"] == "system"
        assert msgs[-1]["role"] == "user"
