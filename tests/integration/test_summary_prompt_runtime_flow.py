from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import config
import database as db
from services.conversation_service import ConversationService
from services.prompt_service import PromptService


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
        self._lock = threading.Lock()
        self.summary_prompts: list[str] = []
        self.main_output = (
            "（书房里的灯光落在桌沿，茶杯旁还有一页没合上的资料。你说今晚想喝热茶时，"
            "他没有立刻接话，只是把手边的水温试过一遍，又把杯口朝你的方向转了半圈。"
            "窗外的风把树影压得很低，屋内却安静得能听见纸页轻响。他抬眼看你，神色仍旧"
            "克制，像是把所有多余的情绪都收在一句平稳回应之后，却没有把关心藏得太远。"
            "你坐近一些，他便顺手把靠垫挪到你身后，动作不急，也不显得刻意，只让这段夜色"
            "慢慢落回一个更适合说话的位置。）\n\n"
            "先坐好，茶马上就来。"
        )

    def chat(self, model_id: str, messages: list[dict], **kwargs):
        system_text = str(messages[0].get("content", "")) if messages else ""
        if "专业的对话分析助手" in system_text:
            prompt_text = str(messages[1].get("content", ""))
            with self._lock:
                self.summary_prompts.append(prompt_text)
            return SimpleNamespace(
                success=True,
                content=json.dumps(
                    {
                        "scene_description": "测试场景",
                        "plot_summary": "用户提到想喝热茶，角色回应会准备并调整距离",
                        "pending_hooks": "继续围绕夜间谈话展开",
                        "character_emotion": "克制关心",
                        "user_emotion": "放松",
                        "relationship_shift": "信任升温",
                        "user_profile_signals": "偏好热茶和慢节奏陪伴",
                    },
                    ensure_ascii=False,
                ),
                error="",
                input_tokens=128,
                output_tokens=64,
                latency_s=0.01,
            )
        return SimpleNamespace(
            success=True,
            content=self.main_output,
            error="",
            input_tokens=256,
            output_tokens=128,
            latency_s=0.01,
        )


@pytest.fixture
def isolated_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db_path = tmp_path / "summary_prompt_runtime_flow.db"
    assert db_path.name != "longform.db"
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()
    db.migrate_add_score_columns()
    return db_path


def _minimal_config() -> dict:
    return {
        "prompt_file": "",
        "character": {
            "Role_Nickname": "齐司礼",
            "gender": "男",
            "personal_type": "理性沉稳",
            "personality": "理性沉稳",
        },
        "context": {
            "relationship": "暧昧",
            "current_scene": "书房夜谈",
        },
        "modules": {
            "system_prompt": (
                "你是{Role_Nickname}，当前关系阶段是{relationship}。"
                "请输出300-500字，旁白用（）包裹，对白为纯文本。"
            ),
            "dialogueStartPrompt": "",
            "moments": "",
            "dialogue_summary": "",
        },
        "runtime": {
            "summary_prompt_version": "长文模式摘要提示词_v2.7_20260425.md",
            "injection_depth": 4,
        },
    }


def test_run_conversation_summary_prompt_uses_real_history_and_persists_summary(
    isolated_db: Path,
) -> None:
    assert isolated_db.name != "longform.db"

    model = _CaptureModel()
    service = ConversationService(
        model_adapter=model,
        prompt_service=PromptService(),
    )
    service.summary_prompt_store = _PromptStore()

    config_data = _minimal_config()
    conv_id = db.create_conversation(
        model_id="fake-main",
        config=config_data,
        model_mini="fake-summary",
        prompt_version="",
    )

    results = asyncio.run(
        service.run_conversation(
            conv_id=conv_id,
            config=config_data,
            turns=["今晚我想喝热茶", "你会陪我坐一会儿吗？"],
            model_id="fake-main",
            model_mini="fake-summary",
            summary_interval=2,
            dry_run=False,
        )
    )
    service._wait_for_pending_summary(conv_id, config_data, completed_turns=2, timeout_s=2)

    assert len(results) == 2
    assert model.summary_prompts
    summary_prompt = model.summary_prompts[-1]
    assert "今晚我想喝热茶" in summary_prompt
    assert "你会陪我坐一会儿吗？" in summary_prompt
    assert "齐司礼" in summary_prompt
    assert "理性沉稳" in summary_prompt
    assert "暧昧" in summary_prompt
    assert "mode=longform" in summary_prompt
    assert "{conversation_log}" not in summary_prompt
    assert "{conversation_text}" not in summary_prompt
    assert "{existing_summary}" not in summary_prompt
    assert "{current_mode}" not in summary_prompt

    persisted = db.get_conversation(conv_id) or {}
    turn_2 = next(item for item in persisted.get("results", []) if item.get("turn") == 2)
    assert "测试场景" in str(turn_2.get("dialogue_summary", ""))
    assert "用户提到想喝热茶" in str(turn_2.get("dialogue_summary", ""))
