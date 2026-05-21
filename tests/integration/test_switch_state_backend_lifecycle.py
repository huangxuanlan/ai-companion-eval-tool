from __future__ import annotations

from pathlib import Path

import pytest

import config
import database as db
from routers import conversations as conversations_router
from services.conversation_service import ConversationService
from services.prompt_service import PromptService


OLD_SUMMARY = "旧摘要：用户刚从短文切到长文，前面一直在聊周末计划。"
SWITCH_STATE = (
    "（以下为切换接话状态，仅供事实参考，不是回复格式示例。）\n"
    "【最近用户意图】用户问刚才的话题要不要继续。\n"
    "【上一回复意图】角色刚承诺会把周末安排说完。\n"
    "【接话约束】目标模式继续接话，不模仿来源模式。"
)


@pytest.fixture
def isolated_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db_path = tmp_path / "switch_state_lifecycle.db"
    assert db_path.name != "longform.db"
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()
    db.migrate_add_score_columns()
    return db_path


def _minimal_config() -> dict:
    return {
        "prompt_file": "",
        "dialogue_summary": OLD_SUMMARY,
        "character": {
            "Role_Nickname": "林野",
            "gender": "男",
            "personal_type": "温柔可靠",
            "personality": "温柔可靠",
        },
        "context": {
            "relationship": "暧昧",
            "current_scene": "周末下午的客厅",
        },
        "modules": {
            "system_prompt": (
                "你是{Role_Nickname}，当前关系阶段是{relationship}。"
                "请自然接住用户输入。"
            ),
            "dialogueStartPrompt": "",
            "moments": "",
            "dialogue_summary": OLD_SUMMARY,
        },
        "custom_variables": {},
        "runtime": {
            "summary_interval": 1,
            "latest_dialogue_summary": OLD_SUMMARY,
            "last_summary_turn": 0,
            "summary_job_status": "completed",
            "summary_job_target_turn": 0,
            "switch_state": SWITCH_STATE,
            "switch_state_status": "pending",
            "switch_state_target_turn": 1,
            "injection_depth": 4,
        },
    }


def _joined_messages(turn_data: dict) -> str:
    return "\n".join(
        str(item.get("content", ""))
        for item in turn_data.get("messages_snapshot", [])
    )


def test_seed_switch_state_moves_custom_variable_to_transient_runtime() -> None:
    config_data = {
        "custom_variables": {"switch_state": SWITCH_STATE},
        "runtime": {},
    }

    conversations_router._apply_seed_switch_state(config_data)

    assert "switch_state" not in config_data["custom_variables"]
    runtime = config_data["runtime"]
    assert runtime["switch_state"] == SWITCH_STATE
    assert runtime["switch_state_status"] == "pending"
    assert runtime["switch_state_target_turn"] == 1


def test_switch_state_is_injected_once_then_replaced_by_async_summary(
    isolated_db: Path,
) -> None:
    assert isolated_db.name != "longform.db"

    service = ConversationService(
        model_adapter=None,
        prompt_service=PromptService(),
    )
    config_data = _minimal_config()
    conv_id = db.create_conversation(
        model_id="fake-main",
        config=config_data,
        model_mini="fake-summary",
        prompt_version="",
    )

    turn_1 = service.generate_interactive_turn(
        conv_id,
        db.get_conversation(conv_id) or {},
        "那你刚才没说完的周末安排是什么？",
        model_id="fake-main",
        model_mini="fake-summary",
        dry_run=True,
    )

    first_payload = _joined_messages(turn_1)
    assert OLD_SUMMARY in first_payload
    assert "【切换接话状态】" in first_payload
    assert SWITCH_STATE in first_payload
    assert turn_1["dialogue_summary"] == OLD_SUMMARY
    assert SWITCH_STATE not in turn_1["dialogue_summary"]

    persisted_after_first = db.get_conversation(conv_id) or {}
    runtime_after_first = persisted_after_first["config"]["runtime"]
    assert runtime_after_first["switch_state"] == ""
    assert runtime_after_first["switch_state_status"] == "consumed"
    assert runtime_after_first["switch_state_consumed_turn"] == 1
    assert SWITCH_STATE not in str(persisted_after_first["results"][0]["dialogue_summary"])
    assert SWITCH_STATE not in db.get_latest_dialogue_summary(role_name="林野")

    service._wait_for_pending_summary(conv_id, persisted_after_first["config"], completed_turns=1, timeout_s=2)

    turn_2 = service.generate_interactive_turn(
        conv_id,
        db.get_conversation(conv_id) or {},
        "继续说。",
        model_id="fake-main",
        model_mini="fake-summary",
        dry_run=True,
    )

    second_payload = _joined_messages(turn_2)
    assert "【切换接话状态】" not in second_payload
    assert SWITCH_STATE not in second_payload
    assert "[dry-run 模拟场景]" in second_payload
    assert OLD_SUMMARY not in turn_2["dialogue_summary"]
    assert "[dry-run 模拟场景]" in turn_2["dialogue_summary"]
    assert SWITCH_STATE not in db.get_latest_dialogue_summary(role_name="林野")
