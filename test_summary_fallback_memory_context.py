from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parent
SERVER_DIR = PROJECT_DIR / "server"
os.environ.setdefault(
    "LONGFORM_DB_PATH",
    str(PROJECT_DIR / "output" / "test_runtime" / "summary_fallback_memory_context.db"),
)

if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import config  # noqa: E402
import database as db  # noqa: E402
from services import conversation_service as conversation_service_module  # noqa: E402
from services.conversation_service import ConversationService  # noqa: E402
from services.prompt_service import PromptService  # noqa: E402


class FakeModelResult:
    def __init__(
        self,
        content: str,
        *,
        success: bool = True,
        error: str = "",
        input_tokens: int = 32,
        output_tokens: int = 96,
        latency_s: float = 0.01,
    ):
        self.content = content
        self.success = success
        self.error = error
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.latency_s = latency_s


class SlowSummaryModelAdapter:
    def __init__(self, summary_delay_s: float = 0.15):
        self.summary_delay_s = summary_delay_s
        self.main_output = (
            "书房的壁灯把木质桌沿照得泛暖，指尖轻轻敲过杯壁时带起一声很低的脆响。"
            "他抬眼看向你，视线在夜色里压得很稳，像是已经把这一轮对话的节奏扣在掌心。\n\n"
            '**"先坐过来。"**\n\n'
            "他说得不高，却把距离和分寸都安排得明明白白。窗外的风压着树影晃了一下，"
            "他把手边温着的水杯往你面前推了半寸，指节擦过桌面的时候没有半点多余动作，"
            "连关心都显得克制而清醒。你还没开口，他已经微微偏过身，给你让出更近的位置，"
            "目光仍停在你脸上，像是在等你自己把后面的话接上来。空气里是纸页和热水混在一起的淡淡温度，"
            "他低声补了一句，尾音压得很轻，却把那点不容置疑的在意藏得并不彻底。\n\n"
            '**"今晚你慢慢说，我在听。"**'
        )

    def chat(self, model_id: str, messages: list[dict], **kwargs):
        system_text = str(messages[0].get("content", "")) if messages else ""
        if "专业的对话分析助手" in system_text:
            time.sleep(self.summary_delay_s)
            return FakeModelResult(
                '{"scene_description":"测试场景","plot_summary":"测试剧情","pending_hooks":"测试悬念",'
                '"character_emotion":"克制","user_emotion":"放松","relationship_shift":"升温",'
                '"user_profile_signals":"偏好慢节奏"}',
                latency_s=self.summary_delay_s,
            )
        return FakeModelResult(self.main_output, latency_s=0.01)


@pytest.fixture
def isolated_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    db_path = tmp_path / "summary_fallback_memory_context.db"
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()
    db.migrate_add_score_columns()
    return db_path


def test_summary_timeout_falls_back_to_recent_ten_turns_then_recovers(
    monkeypatch: pytest.MonkeyPatch,
    isolated_db: Path,
):
    monkeypatch.setattr(conversation_service_module, "MEMORY_WAIT_TIMEOUT_S", 0.05)

    service = ConversationService(
        model_adapter=SlowSummaryModelAdapter(summary_delay_s=0.15),
        prompt_service=PromptService(),
    )
    config_data = service.build_config_from_preset("xiaoJingYan")
    config_data["prompt_file"] = config.get_latest_prompt_file()
    conv_id = db.create_conversation(
        model_id="slow-main",
        config=config_data,
        model_mini="slow-summary",
        prompt_version=config_data["prompt_file"],
    )

    started_at = time.perf_counter()
    results = asyncio.run(
        service.run_conversation(
            conv_id=conv_id,
            config=config_data,
            turns=[f"U{i}" for i in range(1, 14)],
            model_id="slow-main",
            model_mini="slow-summary",
            summary_interval=10,
            dry_run=False,
        )
    )
    elapsed = time.perf_counter() - started_at

    turn_11 = results[10]
    turn_13 = results[12]
    messages_11 = (turn_11.get("request_payload_snapshot") or {}).get("messages") or []
    message_contents_11 = [str(item.get("content", "")) for item in messages_11]

    assert turn_11.get("summary_source") == "pending-fallback"
    assert any(content == "U1" for content in message_contents_11)
    assert any(content == "U10" for content in message_contents_11)
    assert not any("测试场景" in content for content in message_contents_11)
    assert elapsed < 2.5

    assert turn_13.get("summary_source") == "completed"
    assert "测试场景" in str(
        (turn_13.get("request_payload_snapshot") or {})
        .get("memory_context_snapshot", {})
        .get("dialogue_summary", "")
    )

    persisted = db.get_conversation(conv_id) or {}
    persisted_turn_10 = next(
        item for item in persisted.get("results", []) if item.get("turn") == 10
    )
    assert "测试场景" in str(persisted_turn_10.get("dialogue_summary", ""))
