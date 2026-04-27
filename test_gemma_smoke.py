"""
Gemma 模型消息拼接适配 — 端到端冒烟测试

覆盖路径：
  1. is_gemma_model 判断
  2. DEFAULT_THINKING_BY_MODEL 打分默认 high
  3. 生成路径 Gemma 禁用 Thinking（_execute_single_turn 覆盖）
  4. build_messages Gemma XML 包裹（<rules>/<context_boundary>/<system_reminder>）
  5. build_messages 非 Gemma 无 XML（零影响）
  6. generate_summary Gemma XML 引导
  7. token_trimmer model_id 透传
  8. Temperature 校正 1.0
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "server"))

from services.model_adapter import ModelAdapter
from services.message_assembler import MessageAssembler
from services.token_trimmer import TokenTrimmer

PASSED = 0
FAILED = 0


def check(name: str, condition: bool, detail: str = ""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  [PASS] {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name} — {detail}")


def test_is_gemma_model():
    print("\n=== 1. is_gemma_model 判断 ===")
    check("gemma4-31b", ModelAdapter.is_gemma_model("gemma4-31b"))
    check("gemma4-31b-local", ModelAdapter.is_gemma_model("gemma4-31b-local"))
    check("gemma4-26b", ModelAdapter.is_gemma_model("gemma4-26b"))
    check("gemma-4-anything", ModelAdapter.is_gemma_model("gemma-4-anything"))
    check("GEMMA4-31B (大写)", ModelAdapter.is_gemma_model("GEMMA4-31b"))
    check("doubao-pro 不是 Gemma", not ModelAdapter.is_gemma_model("doubao-pro"))
    check("gemini-2.5 不是 Gemma", not ModelAdapter.is_gemma_model("gemini-2.5-flash"))
    check("空字符串不是 Gemma", not ModelAdapter.is_gemma_model(""))
    check("None 不是 Gemma", not ModelAdapter.is_gemma_model(None))


def test_thinking_defaults():
    print("\n=== 2. Thinking 默认值 — 打分 high / 生成 disabled ===")
    # 打分路径：走 resolve_thinking_effort，未显式设置 → 查 DEFAULT
    resolved = ModelAdapter.resolve_thinking_effort("gemma4-31b", None, "")
    check("打分路径 gemma4-31b 默认 high", resolved == "high", f"got: {resolved}")

    resolved = ModelAdapter.resolve_thinking_effort("gemma4-31b-local", None, "")
    check("打分路径 gemma4-31b-local 默认 high", resolved == "high", f"got: {resolved}")

    # 非 Gemma 不受影响
    resolved = ModelAdapter.resolve_thinking_effort("doubao-pro", None, "")
    check("doubao-pro 默认 disabled", resolved == "disabled", f"got: {resolved}")

    # 用户显式 enabled=True 时 → 走默认 high
    resolved = ModelAdapter.resolve_thinking_effort("gemma4-31b", True, "")
    check("显式 enabled=True → high", resolved == "high", f"got: {resolved}")

    # 用户显式 enabled=False 时 → disabled
    resolved = ModelAdapter.resolve_thinking_effort("gemma4-31b", False, "")
    check("显式 enabled=False → disabled", resolved == "disabled", f"got: {resolved}")

    # 用户显式 effort=medium → medium
    resolved = ModelAdapter.resolve_thinking_effort("gemma4-31b", True, "medium")
    check("显式 effort=medium → medium", resolved == "medium", f"got: {resolved}")


def test_build_messages_gemma_xml():
    print("\n=== 3. build_messages Gemma XML 包裹 ===")
    assembler = MessageAssembler()
    msgs = assembler.build_messages(
        rendered_system="你是角色A",
        system_after="补充设定",
        few_shot_messages=[],
        conversation_history=[
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好呀"},
        ],
        dialogue_summary="",
        memory_context="记忆上下文",
        current_input="今天怎么样",
        relationship="恋人",
        role_name="角色A",
        personality="温柔",
        turn_num=5,
        model_id="gemma4-31b",
    )

    # 检查 Style Isolation 有 <context_boundary>
    style_msgs = [m for m in msgs if "<context_boundary>" in m.get("content", "")]
    check("Style Isolation 有 <context_boundary>", len(style_msgs) == 1,
          f"found {len(style_msgs)}")

    # 检查 Core Constraints 有 <rules>
    rules_msgs = [m for m in msgs if "<rules>" in m.get("content", "")]
    check("Core Constraints 有 <rules>", len(rules_msgs) == 1,
          f"found {len(rules_msgs)}")

    # 检查 Depth Injection 有 <system_reminder>
    reminder_msgs = [m for m in msgs if "<system_reminder>" in m.get("content", "")]
    check("Depth Injection 有 <system_reminder>", len(reminder_msgs) == 1,
          f"found {len(reminder_msgs)}")


def test_build_messages_non_gemma_no_xml():
    print("\n=== 4. build_messages 非 Gemma 无 XML（零影响） ===")
    assembler = MessageAssembler()
    msgs = assembler.build_messages(
        rendered_system="你是角色A",
        system_after="补充设定",
        few_shot_messages=[],
        conversation_history=[
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好呀"},
        ],
        dialogue_summary="",
        memory_context="记忆上下文",
        current_input="今天怎么样",
        relationship="恋人",
        role_name="角色A",
        personality="温柔",
        turn_num=5,
        model_id="doubao-pro",
    )

    all_content = " ".join(m.get("content", "") for m in msgs)
    check("无 <context_boundary>", "<context_boundary>" not in all_content)
    check("无 <rules>", "<rules>" not in all_content)
    check("无 <system_reminder>", "<system_reminder>" not in all_content)


def test_build_messages_empty_model_id():
    print("\n=== 5. build_messages 空 model_id（兼容旧调用） ===")
    assembler = MessageAssembler()
    msgs = assembler.build_messages(
        rendered_system="你是角色A",
        system_after="",
        few_shot_messages=[],
        conversation_history=[],
        dialogue_summary="",
        memory_context="",
        current_input="你好",
        relationship="朋友",
        model_id="",
    )
    all_content = " ".join(m.get("content", "") for m in msgs)
    check("空 model_id 无 XML", "<context_boundary>" not in all_content)
    check("消息非空", len(msgs) >= 2, f"got {len(msgs)} msgs")


def test_temperature_correction():
    print("\n=== 6. Temperature 校正 ===")
    config = ModelAdapter.BUILTIN_MODELS.get("gemma4-31b-local", {})
    temp = config.get("parameters", {}).get("temperature")
    check("gemma4-31b-local Temperature = 1.0", temp == 1.0, f"got: {temp}")


def test_token_trimmer_model_id():
    print("\n=== 7. TokenTrimmer model_id 透传 ===")
    import inspect
    sig = inspect.signature(TokenTrimmer.trim_messages)
    check("trim_messages 有 model_id 参数", "model_id" in sig.parameters,
          f"params: {list(sig.parameters.keys())}")

    sig2 = inspect.signature(TokenTrimmer._rebuild_messages)
    check("_rebuild_messages 有 model_id 参数", "model_id" in sig2.parameters,
          f"params: {list(sig2.parameters.keys())}")


def test_generate_summary_gemma_xml():
    print("\n=== 8. generate_summary Gemma XML 引导（代码检查） ===")
    import ast
    with open(os.path.join("server", "services", "conversation_service.py"),
              encoding="utf-8") as f:
        source = f.read()
    check("generate_summary 含 is_gemma_model 分支",
          "is_gemma_model(model_id)" in source and "<role>" in source)
    check("generate_summary 含 <output_format> 标签", "<output_format>" in source)


def test_generation_thinking_override():
    print("\n=== 9. 生成路径 Gemma Thinking 覆盖（代码检查） ===")
    with open(os.path.join("server", "services", "conversation_service.py"),
              encoding="utf-8") as f:
        source = f.read()
    check("_execute_single_turn 含 Gemma thinking 覆盖",
          "is_gemma_model(model_id) and thinking_enabled is not True" in source)
    check("覆盖值为 disabled",
          'effective_thinking_effort = "disabled"' in source)


if __name__ == "__main__":
    test_is_gemma_model()
    test_thinking_defaults()
    test_build_messages_gemma_xml()
    test_build_messages_non_gemma_no_xml()
    test_build_messages_empty_model_id()
    test_temperature_correction()
    test_token_trimmer_model_id()
    test_generate_summary_gemma_xml()
    test_generation_thinking_override()

    print(f"\n{'='*50}")
    print(f"冒烟测试结果: {PASSED} passed, {FAILED} failed")
    if FAILED > 0:
        sys.exit(1)
    else:
        print("[OK] All passed")
