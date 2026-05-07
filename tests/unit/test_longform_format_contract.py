from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_DIR / "server"))

from services.message_assembler import MessageAssembler
from services.quality_guard import QualityGuard


def _build_messages(*, v52: bool) -> list[dict]:
    old = os.environ.get("LONGFORM_V52_MESSAGE_CONTRACT")
    if v52:
        os.environ["LONGFORM_V52_MESSAGE_CONTRACT"] = "1"
    else:
        os.environ.pop("LONGFORM_V52_MESSAGE_CONTRACT", None)
    try:
        return MessageAssembler().build_messages(
            rendered_system="你是测试角色。",
            system_after="",
            few_shot_messages=[],
            conversation_history=[
                {"role": "user", "content": "上一轮用户输入"},
                {"role": "assistant", "content": "上一轮角色回复"},
            ],
            dialogue_summary="",
            memory_context="",
            current_input="今晚月亮好圆啊",
            relationship="暧昧",
            role_name="测试角色",
            personality="温暖",
            turn_num=4,
            model_id="qwen3.6-plus",
        )
    finally:
        if old is None:
            os.environ.pop("LONGFORM_V52_MESSAGE_CONTRACT", None)
        else:
            os.environ["LONGFORM_V52_MESSAGE_CONTRACT"] = old


def test_longform_message_contract_matches_quality_guard_format():
    for v52 in (False, True):
        merged = "\n".join(m.get("content", "") for m in _build_messages(v52=v52))
        assert "旁白用（）包裹" in merged
        assert "对白为纯文本不带任何标记" in merged
        assert "旁白纯文本" not in merged
        assert "对白加粗" not in merged
        assert "加粗双引号" not in merged
        assert '**""**' not in merged


def test_quality_guard_accepts_current_format_and_rejects_legacy_format():
    guard = QualityGuard()
    current = f"（{'叙事' * 150}）\n这句对白是纯文本，不带任何标记。"
    legacy = f"{'叙事' * 155}\n这句对白是纯文本，但旁白没有括号包裹。"

    current_result = guard.check(current)
    legacy_result = guard.check(legacy)

    assert current_result["needs_retry"] is False
    assert legacy_result["needs_retry"] is True
    assert legacy_result["retry_reason"] == "格式错误(缺少（旁白）括号包裹)"


def test_quality_guard_repairs_legacy_wrapped_narration_to_current_format():
    guard = QualityGuard()
    legacy_wrapped = f"*{'叙事' * 150}*\n这句对白是纯文本，不带任何标记。"

    result = guard.check(legacy_wrapped)

    assert result["needs_retry"] is False
    assert result["processed_text"].startswith("（")
    assert "）\n这句对白是纯文本" in result["processed_text"]
    assert "旧版*旁白*转换为（）旁白" in result["fixes_applied"]
