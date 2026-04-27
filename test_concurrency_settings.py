from __future__ import annotations

import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient

PROJECT_DIR = Path(__file__).resolve().parent
SERVER_DIR = PROJECT_DIR / "server"

if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import config as config_module  # noqa: E402
import database as db  # noqa: E402
from main import app  # noqa: E402
from routers import scoring as scoring_router  # noqa: E402
from services import scoring_service as scoring_service_module  # noqa: E402


def _reload_config():
    return importlib.reload(config_module)


def _shutdown_executor(service) -> None:
    service._executor.shutdown(wait=False, cancel_futures=True)


def test_config_uses_twenty_four_as_default_max_concurrent_conversations(monkeypatch):
    monkeypatch.delenv("LONGFORM_MAX_CONCURRENT_CONVERSATIONS", raising=False)
    config = _reload_config()

    assert config.DEFAULT_MAX_CONCURRENT_CONVERSATIONS == 24
    assert config.MAX_CONCURRENT_CONVERSATIONS == 24

    _reload_config()


def test_config_allows_env_override_for_max_concurrent_conversations(monkeypatch):
    monkeypatch.setenv("LONGFORM_MAX_CONCURRENT_CONVERSATIONS", "9")
    config = _reload_config()

    assert config.MAX_CONCURRENT_CONVERSATIONS == 9

    monkeypatch.delenv("LONGFORM_MAX_CONCURRENT_CONVERSATIONS", raising=False)
    _reload_config()


def test_conversation_service_background_executor_tracks_concurrency_cap():
    from services.conversation_service import ConversationService

    service = ConversationService()
    try:
        assert service._background_executor._max_workers == max(8, config_module.MAX_CONCURRENT_CONVERSATIONS)
    finally:
        service._background_executor.shutdown(wait=False, cancel_futures=True)


def test_scoring_service_uses_six_as_default_max_workers(monkeypatch):
    monkeypatch.delenv("SCORING_MAX_WORKERS", raising=False)

    service = scoring_service_module.ScoringService()
    try:
        assert service.get_max_workers() == 6
    finally:
        _shutdown_executor(service)


def test_scoring_service_allows_env_override_for_max_workers(monkeypatch):
    monkeypatch.setenv("SCORING_MAX_WORKERS", "8")

    service = scoring_service_module.ScoringService()
    try:
        assert service.get_max_workers() == 8
    finally:
        _shutdown_executor(service)


def test_config_allows_env_override_for_default_scoring_model(monkeypatch):
    monkeypatch.setenv("DEFAULT_SCORING_MODEL", "custom-score-model")
    config = _reload_config()

    assert config.DEFAULT_SCORING_MODEL == "custom-score-model"

    monkeypatch.delenv("DEFAULT_SCORING_MODEL", raising=False)
    _reload_config()


def test_scoring_service_falls_back_to_six_on_invalid_max_workers(monkeypatch):
    monkeypatch.setenv("SCORING_MAX_WORKERS", "invalid")

    service = scoring_service_module.ScoringService()
    try:
        assert service.get_max_workers() == 6
    finally:
        _shutdown_executor(service)


def test_scoring_status_exposes_max_workers(monkeypatch):
    class _StubScoringService:
        def is_available(self, model_id=None):
            return True

        def get_prompt_meta(self):
            return {"active_filename": "长文模式打分提示词_v2.1.md"}

        def get_scoring_prompts(self):
            return ["长文模式打分提示词_v2.1.md"]

        def get_last_error(self):
            return ""

        def get_max_workers(self):
            return 6

    monkeypatch.setattr(scoring_router, "_get_scoring", lambda: _StubScoringService())

    with TestClient(app) as client:
        response = client.get("/api/scoring/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is True
    assert payload["max_workers"] == 6


def test_batch_conversation_defaults_scoring_model_to_default_scoring_model():
    with TestClient(app) as client:
        create_response = client.post(
            "/api/conversations",
            json={
                "preset_id": "xiaoJingYan",
                "model_id": "doubao-pro",
                "dry_run": True,
                "turns": ["默认评分模型回退校验"],
            },
        )

        assert create_response.status_code == 200, create_response.text
        conv_id = create_response.json()["id"]

        detail_response = client.get(f"/api/conversations/{conv_id}")
        assert detail_response.status_code == 200, detail_response.text
        payload = detail_response.json()
        assert payload["model_id"] == "doubao-pro"
        assert payload["scoring_model_id"] == config_module.DEFAULT_SCORING_MODEL


def test_interactive_conversation_defaults_scoring_model_to_default_scoring_model():
    with TestClient(app) as client:
        create_response = client.post(
            "/api/conversations/interactive",
            json={
                "model_id": "doubao-pro",
                "character": {
                    "Role_Nickname": "默认评分模型角色",
                    "personality": "冷静",
                },
                "context": {
                    "relationship": "朋友",
                    "scene": "书房",
                    "time_period": "下午",
                    "user_nickname": "测试用户",
                },
                "modules": {},
            },
        )

        assert create_response.status_code == 200, create_response.text
        conv_id = create_response.json()["id"]

        detail_response = client.get(f"/api/conversations/{conv_id}")
        assert detail_response.status_code == 200, detail_response.text
        payload = detail_response.json()
        assert payload["model_id"] == "doubao-pro"
        assert payload["scoring_model_id"] == config_module.DEFAULT_SCORING_MODEL


def test_conversation_detail_exposes_score_avg_after_turn_scoring():
    with TestClient(app) as client:
        create_response = client.post(
            "/api/conversations",
            json={
                "preset_id": "xiaoJingYan",
                "model_id": "doubao-pro",
                "dry_run": True,
                "turns": ["明细分数回填校验"],
            },
        )

        assert create_response.status_code == 200, create_response.text
        conv_id = create_response.json()["id"]
        db.insert_turn_result(
            conv_id,
            {
                "turn": 1,
                "user_input": "明细分数回填校验",
                "ai_output": "测试输出",
                "word_count": 4,
                "messages_snapshot": [],
                "request_payload_snapshot": {},
                "model_id": "doubao-pro",
            },
        )

        score_response = client.post(
            f"/api/conversations/{conv_id}/turns/1/scores",
            json={
                "scores": {
                    "persona_fidelity": 5,
                    "narrative_immersion": 4,
                    "emotional_tension": 4,
                    "boundary_memory": 4,
                    "format_compliance": 4,
                },
                "mapped_total": 8.4,
                "reasoning": "测试回写",
                "success": True,
            },
        )
        assert score_response.status_code == 200, score_response.text

        detail_response = client.get(f"/api/conversations/{conv_id}")
        assert detail_response.status_code == 200, detail_response.text
        payload = detail_response.json()
        assert payload["score_avg"] == 8.4
        assert payload["results"][0]["score_status"] == "scored"


def test_scoring_config_route_updates_max_workers(monkeypatch):
    class _StubScoringService:
        def __init__(self):
            self.max_workers = 6

        def set_max_workers(self, value):
            self.max_workers = value
            return value

        def get_max_workers(self):
            return self.max_workers

    stub = _StubScoringService()
    monkeypatch.setattr(scoring_router, "_get_scoring", lambda: stub)

    with TestClient(app) as client:
        response = client.post("/api/scoring/config", json={"max_workers": 12})

    assert response.status_code == 200, response.text
    assert response.json()["max_workers"] == 12


def test_scoring_results_summary_counts_skipped_turns():
    with TestClient(app) as client:
        create_response = client.post(
            "/api/conversations",
            json={
                "preset_id": "xiaoJingYan",
                "model_id": "doubao-pro",
                "dry_run": True,
                "turns": ["skip 统计校验"],
            },
        )
        assert create_response.status_code == 200, create_response.text
        conv_id = create_response.json()["id"]
        db.insert_turn_result(
            conv_id,
            {
                "turn": 1,
                "user_input": "skip 统计校验",
                "ai_output": "",
                "word_count": 0,
                "messages_snapshot": [],
                "request_payload_snapshot": {},
                "model_id": "doubao-pro",
            },
        )
        db.update_turn_scores(
            conv_id,
            1,
            {
                "mapped_total": 0,
                "reasoning": "[跳过] ai_output 为空",
                "success": False,
                "score_status": "skipped",
            },
        )

        response = client.get(f"/api/scoring/{conv_id}/results")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["summary"]["skipped_count"] == 1
    assert payload["summary"]["failed_count"] == 0
    assert payload["summary"]["total_count"] == 1


def test_conversation_list_exposes_zero_score_for_skipped_only_conversation():
    with TestClient(app) as client:
        create_response = client.post(
            "/api/conversations",
            json={
                "preset_id": "xiaoJingYan",
                "model_id": "doubao-pro",
                "dry_run": True,
                "turns": ["skip 列表均分回填校验"],
            },
        )
        assert create_response.status_code == 200, create_response.text
        conv_id = create_response.json()["id"]
        db.insert_turn_result(
            conv_id,
            {
                "turn": 1,
                "user_input": "skip 列表均分回填校验",
                "ai_output": "",
                "word_count": 0,
                "messages_snapshot": [],
                "request_payload_snapshot": {},
                "model_id": "doubao-pro",
            },
        )
        db.update_turn_scores(
            conv_id,
            1,
            {
                "mapped_total": 0,
                "reasoning": "[跳过] ai_output 为空",
                "success": False,
                "score_status": "skipped",
            },
        )

        detail_response = client.get(f"/api/conversations/{conv_id}")
        assert detail_response.status_code == 200, detail_response.text
        detail_payload = detail_response.json()

        list_response = client.get("/api/conversations")
        assert list_response.status_code == 200, list_response.text
        list_payload = list_response.json()

    target = next(item for item in list_payload["conversations"] if item["id"] == conv_id)
    assert detail_payload["score_avg"] == 0.0
    assert detail_payload["skipped_turns"] == 1
    assert target["score_avg"] == 0.0
    assert target["skipped_turns"] == 1
