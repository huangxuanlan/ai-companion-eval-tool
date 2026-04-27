from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
SERVER_DIR = PROJECT_DIR / "server"
DB_DIR = PROJECT_DIR / "output" / "test_runtime"
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / "history_runtime_reconciliation.db"

for suffix in ("", "-wal", "-shm"):
    target = Path(str(DB_PATH) + suffix)
    if target.exists():
        target.unlink()

os.environ["LONGFORM_DB_PATH"] = str(DB_PATH)

if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import database as db  # noqa: E402
from routers import conversations  # noqa: E402


db.init_db()


def clear_db():
    conn = db.get_connection()
    conn.execute("DELETE FROM turn_results")
    conn.execute("DELETE FROM conversations")
    conn.commit()
    conn.close()


def build_config(total_turns: int, next_turn_index: int, resume_supported: bool = True) -> dict:
    turns = ["第一轮", "第二轮"][:max(total_turns, 0)]
    return {
        "character": {"Role_Nickname": "测试角色"},
        "context": {"relationship": "暧昧"},
        "modules": {},
        "runtime": {
            "conversation_mode": "batch",
            "turns": turns,
            "total_turns": total_turns,
            "next_turn_index": next_turn_index,
            "resume_supported": resume_supported,
        },
    }


def test_list_conversations_prefers_created_at_desc_even_if_old_record_was_touched():
    clear_db()
    old_conv = db.create_conversation("model-a", build_config(total_turns=1, next_turn_index=1))
    new_conv = db.create_conversation("model-b", build_config(total_turns=1, next_turn_index=1))

    conn = db.get_connection()
    conn.execute(
        "UPDATE conversations SET created_at=?, updated_at=?, status=? WHERE id=?",
        ("2026-04-14 08:00:00", "2026-04-16 12:00:00", "completed", old_conv),
    )
    conn.execute(
        "UPDATE conversations SET created_at=?, updated_at=?, status=? WHERE id=?",
        ("2026-04-15 09:00:00", "2026-04-15 09:10:00", "completed", new_conv),
    )
    conn.commit()
    conn.close()

    conversations_list = db.list_conversations()
    assert [item["id"] for item in conversations_list[:2]] == [new_conv, old_conv]


def test_reconcile_stale_running_conversation_marks_completed_when_all_turns_finished():
    clear_db()
    conv_id = db.create_conversation("model-a", build_config(total_turns=1, next_turn_index=1))
    db.insert_turn_result(
        conv_id,
        {
            "turn": 1,
            "user_input": "你好",
            "ai_output": "你好呀",
            "messages_snapshot": [],
            "request_payload_snapshot": {},
            "model_id": "model-a",
        },
    )
    db.update_conversation_status(conv_id, "running")

    conversation = db.get_conversation(conv_id)
    reconciled = conversations._reconcile_stale_conversation_status(conv_id, conversation)

    assert reconciled["status"] == "completed"


def test_reconcile_stale_running_conversation_marks_interrupted_when_partial_results_exist():
    clear_db()
    conv_id = db.create_conversation("model-a", build_config(total_turns=2, next_turn_index=1))
    db.insert_turn_result(
        conv_id,
        {
            "turn": 1,
            "user_input": "第一轮",
            "ai_output": "已完成第一轮",
            "messages_snapshot": [],
            "request_payload_snapshot": {},
            "model_id": "model-a",
        },
    )
    db.update_conversation_status(conv_id, "running")

    conversation = db.get_conversation(conv_id)
    reconciled = conversations._reconcile_stale_conversation_status(conv_id, conversation)

    assert reconciled["status"] == "interrupted"
