from __future__ import annotations

import json
from types import SimpleNamespace

from services.conversation_summary import generate_summary


class _PromptStore:
    def read_prompt(self, prompt_version: str | None = None) -> dict:
        return {
            "content": (
                "existing={existing_summary}\n"
                "mode={current_mode}\n"
                "log={conversation_log}\n"
                "legacy={conversation_text}\n"
                "role={role_name}\n"
                "type={personal_type}\n"
                "rel={relationship}"
            )
        }


class _CaptureModel:
    def __init__(self) -> None:
        self.messages: list[dict] | None = None

    def chat(self, model_id: str, messages: list[dict], **kwargs):
        self.messages = messages
        return SimpleNamespace(
            success=True,
            content=json.dumps(
                {
                    "scene_description": "书房",
                    "plot_summary": "用户说想喝茶，角色回应会准备",
                    "pending_hooks": "继续聊茶",
                    "character_emotion": "平稳",
                    "user_emotion": "放松",
                    "relationship_shift": "朋友阶段稳定",
                    "user_profile_signals": "偏好热茶",
                },
                ensure_ascii=False,
            ),
            error="",
        )


def test_generate_summary_renders_current_and_legacy_placeholders():
    model = _CaptureModel()
    service = SimpleNamespace(summary_prompt_store=_PromptStore(), model=model)

    summary = generate_summary(
        service,
        conversation_history=[
            {"role": "user", "content": "今晚我想喝热茶"},
            {"role": "assistant", "content": "我去给你泡。"},
        ],
        role_name="齐司礼",
        personal_type="理性沉稳",
        relationship="暧昧",
        model_id="doubao-lite",
        prompt_version="summary-v2.7-style.md",
        dry_run=False,
        summary_template=(
            "=== 之前剧情摘要 ===\n"
            "- 场景：{scene_description}\n"
            "- 剧情：{plot_summary}\n"
            "- 悬念：{pending_hooks}\n"
            "- 角色情绪：{character_emotion}\n"
            "- 用户情绪：{user_emotion}\n"
            "- 关系动态：{relationship_shift}\n"
            "- 用户画像信号：{user_profile_signals}\n"
            "=== 摘要结束 ==="
        ),
    )

    assert "用户说想喝茶" in summary
    assert model.messages is not None
    prompt_text = model.messages[1]["content"]
    assert "今晚我想喝热茶" in prompt_text
    assert "我去给你泡。" in prompt_text
    assert "齐司礼" in prompt_text
    assert "理性沉稳" in prompt_text
    assert "暧昧" in prompt_text
    assert "mode=longform" in prompt_text
    assert "{conversation_log}" not in prompt_text
    assert "{conversation_text}" not in prompt_text
    assert "{existing_summary}" not in prompt_text
    assert "{current_mode}" not in prompt_text
