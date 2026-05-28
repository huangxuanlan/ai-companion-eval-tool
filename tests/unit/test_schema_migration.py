from __future__ import annotations

import os
import sqlite3
import pytest
from pathlib import Path

import database as db

# Redirect test database
DB_DIR = Path(__file__).resolve().parent.parent / "output" / "test_runtime"
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / "schema_migration_unit_test.db"
os.environ["LONGFORM_DB_PATH"] = str(DB_PATH)


@pytest.fixture(autouse=True)
def setup_test_db():
    # Remove file if exists to test clean migration from scratch
    if DB_PATH.exists():
        try:
            DB_PATH.unlink()
        except OSError:
            pass
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
    yield


def test_mode_columns_migration():
    conn = db.get_connection()
    tables = [
        "presets",
        "saved_configs",
        "conversations",
        "turn_results",
        "compare_reports",
        "ai_report_summaries",
        "conversation_events",
        "orchestration_runs",
        "ab_sessions"
    ]
    
    for table in tables:
        # Check column exists and its properties
        cursor = conn.execute(f"PRAGMA table_info({table})")
        columns = {row[1]: {"type": row[2], "dflt_value": row[4]} for row in cursor.fetchall()}
        
        assert "mode" in columns, f"Table {table} does not have 'mode' column."
        # Default value might be stored as "'long'" or 'long' in sqlite pragma depending on how it's created
        dflt = columns["mode"]["dflt_value"]
        assert dflt in ("'long'", "long"), f"Table {table} 'mode' column default value is {dflt}, expected 'long'"

    # Verify indexes exist
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
    indexes = {row[0] for row in cursor.fetchall()}
    assert "idx_conversations_mode" in indexes
    assert "idx_turn_results_mode" in indexes
    conn.close()


def test_mode_switches_table_schema():
    conn = db.get_connection()
    cursor = conn.execute("PRAGMA table_info(mode_switches)")
    columns = {row[1]: {"type": row[2]} for row in cursor.fetchall()}
    
    expected_fields = [
        "switch_id", "from_mode", "to_mode", "source_conversation_id", 
        "target_conversation_id", "target_model", "triggered_by", "created_at",
        "switch_summary", "summary_model", "summary_char_count", "summary_token_count", 
        "summary_latency_ms", "summary_delayed", "bridge_turns_requested", 
        "bridge_effective_turns", "bridge_payload_messages", "hetero_assistant_wrapped", 
        "source_counts_json", "bridge_total_available_messages", "first_response_cjk_chars", 
        "first_response_paren_pairs", "first_response_ngram_max_recent_pct", 
        "first_response_format_issues_json", "verification_result", "summary_interval"
    ]
    
    for field in expected_fields:
        assert field in columns, f"Field '{field}' not found in mode_switches table."

    # Verify indexes
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
    indexes = {row[0] for row in cursor.fetchall()}
    assert "idx_mode_switches_from_to" in indexes
    assert "idx_mode_switches_source" in indexes
    assert "idx_mode_switches_created" in indexes
    conn.close()
