from __future__ import annotations

import os
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

import database as db
from main import app

# Redirect test database
DB_DIR = Path(__file__).resolve().parent.parent / "output" / "test_runtime"
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / "mode_routing_unit_test.db"
os.environ["LONGFORM_DB_PATH"] = str(DB_PATH)


@pytest.fixture(autouse=True)
def setup_test_db():
    db.init_db()
    db.migrate_add_score_columns()
    db.migrate_add_v51_columns()
    db.migrate_add_compare_reports_table()
    db.migrate_add_ai_report_summaries_table()
    db.migrate_add_conversation_events_table()
    db.migrate_add_orchestration_runs_table()
    db.migrate_add_ab_sessions_table()
    db.migrate_add_mode_columns()
    db.migrate_add_mode_switches_table()
    
    # Clean tables
    conn = db.get_connection()
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("DELETE FROM conversations")
        conn.execute("DELETE FROM saved_configs")
        conn.execute("DELETE FROM presets")
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.close()
    yield


def test_conversations_mode_routing():
    client = TestClient(app)
    
    # 1. Create a shortform conversation
    payload_short = {
        "model_id": "ds-v4-flash",
        "character": {"Role_Nickname": "萧逸"},
        "custom_variables": {},
        "mode": "short"
    }
    res = client.post("/api/conversations/interactive", json=payload_short)
    assert res.status_code == 200, res.text
    conv_short_id = res.json()["id"]
    
    # 2. Create a longform conversation
    payload_long = {
        "model_id": "ds-v4-flash",
        "character": {"Role_Nickname": "萧逸"},
        "custom_variables": {},
        "mode": "long"
    }
    res = client.post("/api/conversations/interactive", json=payload_long)
    assert res.status_code == 200, res.text
    conv_long_id = res.json()["id"]
    
    # 3. Query with mode=short
    res = client.get("/api/conversations?mode=short")
    assert res.status_code == 200
    convs = res.json()["conversations"]
    assert any(c["id"] == conv_short_id for c in convs)
    assert not any(c["id"] == conv_long_id for c in convs)
    
    # 4. Query with mode=long
    res = client.get("/api/conversations?mode=long")
    assert res.status_code == 200
    convs = res.json()["conversations"]
    assert any(c["id"] == conv_long_id for c in convs)
    assert not any(c["id"] == conv_short_id for c in convs)


def test_configs_mode_routing():
    client = TestClient(app)
    
    # Save a configuration with mode="short"
    # Using unicode escape for config name to avoid GBK coding issues
    payload_save_short = {
        "name": "\u77ed\u6587\u6d4b\u8bd5\u914d\u7f6e",
        "mode": "short",
        "type": "custom",
        "character": {"Role_Nickname": "\u8427\u9038"},
        "context": {"relationship": "\u604b\u7231\u5173\u7cfb"},
        "modules": {},
        "custom_variables": {}
    }
    res = client.post("/api/configs", json=payload_save_short)
    assert res.status_code == 200
    
    # Save a configuration with mode="long"
    payload_save_long = {
        "name": "\u957f\u6587\u6d4b\u8bd5\u914d\u7f6e",
        "mode": "long",
        "type": "custom",
        "character": {"Role_Nickname": "\u8427\u9038"},
        "context": {"relationship": "\u5aa7\u6627\u9636\u6bb5"},
        "modules": {},
        "custom_variables": {}
    }
    res = client.post("/api/configs", json=payload_save_long)
    assert res.status_code == 200
    
    # Fetch configs with mode=short
    res = client.get("/api/configs?mode=short")
    assert res.status_code == 200
    configs_short = res.json()["configs"]
    assert any(c["name"] == "\u77ed\u6587\u6d4b\u8bd5\u914d\u7f6e" for c in configs_short)
    assert not any(c["name"] == "\u957f\u6587\u6d4b\u8bd5\u914d\u7f6e" for c in configs_short)
    
    # Fetch configs with mode=long
    res = client.get("/api/configs?mode=long")
    assert res.status_code == 200
    configs_long = res.json()["configs"]
    assert any(c["name"] == "\u957f\u6587\u6d4b\u8bd5\u914d\u7f6e" for c in configs_long)
    assert not any(c["name"] == "\u77ed\u6587\u6d4b\u8bd5\u914d\u7f6e" for c in configs_long)
