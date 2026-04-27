from __future__ import annotations

from pathlib import Path

import config
import database
import pytest


@pytest.fixture
def isolated_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    db_path = tmp_path / "scoring_avg.db"
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.init_db()
    database.migrate_add_score_columns()
    return db_path


def test_recalculate_conversation_avg_ignores_failed_and_unscored_turns(
    isolated_db: Path,
):
    conv_id = database.create_conversation(
        model_id="qwen-plus",
        config={"runtime": {}},
    )

    for turn in (1, 2, 3):
        database.insert_turn_result(
            conv_id,
            {
                "turn": turn,
                "user_input": f"user-{turn}",
                "ai_output": f"assistant-{turn}",
            },
        )

    database.update_turn_scores(
        conv_id,
        1,
        {"mapped_total": 8.2, "score_status": "scored", "success": True},
    )
    database.update_turn_scores(
        conv_id,
        2,
        {"mapped_total": 0, "score_status": "failed", "success": False},
    )
    database.update_turn_scores(
        conv_id,
        3,
        {"mapped_total": 0, "score_status": "unscored", "success": False},
    )

    stats = database.recalculate_conversation_avg(conv_id)

    assert stats == {
        "avg_total": 8.2,
        "scored_count": 1,
        "failed_count": 1,
        "skipped_count": 0,
        "total_count": 3,
    }
