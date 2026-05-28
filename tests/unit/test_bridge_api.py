from __future__ import annotations

import os
import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

import database as db
from main import app
from services.model_adapter import ModelAdapter
from services.scoring_service import ScoringService
from services.conversation_summary import generate_summary

# Ensure DB is redirected
DB_DIR = Path(__file__).resolve().parent.parent / "output" / "test_runtime"
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / "bridge_unit_test.db"
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
        conn.execute("DELETE FROM mode_switches")
        conn.execute("DELETE FROM turn_results")
        conn.execute("DELETE FROM conversations")
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.close()
    yield


@pytest.fixture
def mock_adapters(monkeypatch):
    class FakeResult:
        def __init__(self, content, success=True, error="", input_tokens=10, output_tokens=20, latency=0.1):
            self.content = content
            self.success = success
            self.error = error
            self.input_tokens = input_tokens
            self.output_tokens = output_tokens
            self.latency = latency
            self.latency_s = latency

    # Mock ModelAdapter
    def fake_chat(self, model_id: str, messages: list[dict], **kwargs):
        # Return a response with parenthetical actions and dialogue (>= 300 CJK chars, >= 3 full-width parentheses pairs)
        content_parts = [
            "（他悄悄地拉开身前的雕花木椅，带着一丝微不可察的拘谨坐下，那双清亮而深邃的黑眸专注且温柔地凝视着你的眼睛，仿佛要在这一刻将你所有的神情都细细描摹、刻印在心底最柔软的角落）",
            "「你终于来了，我还以为你今天会因为临时有事而迟到呢，看到你出现的那一刻，我悬着的心总算是彻底落了下来。」",
            "（他说话时的声音压得很轻很柔，低沉的磁性嗓音里夹杂着一丝微颤的喜悦，如同初春里拂过湖面的微风一般，在寂静的图书馆里悄然回荡着，带起一阵阵细腻的涟漪）",
            "（他有些不好意思地微微移开了视线，修长的手指下意识地轻轻摩挲着粗糙的实木桌面，耳根在昏黄的灯光照射下悄悄染上了一抹淡淡的绯红，显露出他此时此刻内心深处的不平静）",
            "其实我今天提前了半个小时就坐在这里等你了，就是为了能第一时间看到你走进来。"
        ]
        return FakeResult(content="".join(content_parts))
    monkeypatch.setattr(ModelAdapter, "chat", fake_chat)

    # Mock ScoringService
    async def fake_score_turn(self, turn_data, **kwargs):
        return {
            "success": True,
            "scores": {
                "persona_fidelity": 9.0,
                "narrative_immersion": 8.5,
                "emotional_tension": 8.0,
                "boundary_memory": 9.0,
                "format_compliance": 9.5,
                "context_coherence": 9.0,
            },
            "mapped_total": 8.8,
            "reasoning": "Mocked test scoring result.",
        }
    monkeypatch.setattr(ScoringService, "score_turn", fake_score_turn)

    # Mock generate_summary
    def fake_generate_summary(messages: list[dict], **kwargs):
        return "*(测试用剧情摘要：他们坐在图书馆。)*"
    monkeypatch.setattr("services.conversation_summary.generate_summary", fake_generate_summary)

    # Mock ThreadPoolExecutor.submit to run synchronously
    from services.bridge_service import _summary_executor
    def fake_submit(fn, *args, **kwargs):
        fn(*args, **kwargs)
    monkeypatch.setattr(_summary_executor, "submit", fake_submit)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_bridge_session_lifecycle(client, mock_adapters):
    # 1. Prepare a source conversation with some turns
    conv_config = {
        "prompt_file": "星朋友长文模式_提示词_v5.1.md",
        "character": {
            "Role_Nickname": "萧逸",
            "gender": "男",
            "personality": "冷静",
        },
        "context": {"relationship": "暧昧"},
        "modules": {"user_Nickname": "女主角"},
        "runtime": {"model_ids": ["doubao-lite"], "summary_interval": 10},
    }
    source_conv_id = db.create_conversation("doubao-lite", conv_config)
    db.update_conversation_mode(source_conv_id, "short")

    # Insert 3 turns
    for turn in range(1, 4):
        db.insert_turn_result(
            source_conv_id,
            {
                "turn": turn,
                "user_input": f"短文输入 {turn}",
                "ai_output": f"短文AI接话 {turn}",
                "dialogue_summary": "",
                "model_id": "doubao-lite",
            },
        )
        db.update_turn_mode(source_conv_id, turn, "short")

    # 2. Create mode switch session: short -> long
    payload = {
        "from_mode": "shortform",
        "to_mode": "longform",
        "source_conversation_id": source_conv_id,
        "target_model": "deepseek-v4-pro",
        "bridge_turns": 2,
        "summary_interval": 10,
        "scenario_name": "S5",
        "triggered_by": "user_click",
    }
    response = client.post("/api/bridge/sessions", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "session_id" in data
    assert data["status"] == "created"
    
    session_id = data["session_id"]

    # 3. Retrieve session details
    response = client.get(f"/api/bridge/sessions/{session_id}")
    assert response.status_code == 200
    details = response.json()
    assert details["session_id"] == session_id
    assert details["bridge_meta"]["source_message_counts"]["shortform"] == 4  # 2 turns * 2 messages
    assert details["status"] == "pending_summary"

    # 4. Generate story summary
    response = client.post(f"/api/bridge/sessions/{session_id}/summary", json={"summary_model": "deepseek-v4-flash"})
    assert response.status_code == 200
    summary_data = response.json()
    assert summary_data["summary_status"] == "generating"

    # Fetch summary status
    response = client.get(f"/api/bridge/sessions/{session_id}/summary")
    assert response.status_code == 200
    summary_status = response.json()
    assert summary_status["summary_status"] == "completed"
    assert "测试用剧情摘要" in summary_status["switch_summary"]

    # Check updated session status
    response = client.get(f"/api/bridge/sessions/{session_id}")
    assert response.json()["status"] == "pending_first_response"

    # 5. Generate first response
    response = client.post(
        f"/api/bridge/sessions/{session_id}/first-response",
        json={"user_input": "你好啊，萧逸。", "thinking_level": "high"}
    )
    assert response.status_code == 200
    first_res = response.json()
    assert "target_conversation_id" in first_res
    assert first_res["ai_output"].startswith("（他悄悄地拉开身前的雕花木椅")
    assert first_res["scoring"]["score_total"] == 8.8
    assert len(first_res["metrics"]["first_response_format_issues"]) == 0
    assert first_res["metrics"]["first_response_paren_pairs"] > 0

    # Check session is now completed
    response = client.get(f"/api/bridge/sessions/{session_id}")
    assert response.json()["status"] == "completed"


def test_verify_runs_endpoints(client):
    # Start dry-run verification
    payload = {
        "scripts": ["mece_main"],
        "dry_run": True,
    }
    response = client.post("/api/bridge/verify-runs", json=payload)
    assert response.status_code == 201
    run = response.json()
    assert "run_id" in run
    assert run["status"] in {"queued", "running"}
    run_id = run["run_id"]

    # Get details
    response = client.get(f"/api/bridge/verify-runs/{run_id}")
    assert response.status_code == 200
    assert response.json()["run_id"] == run_id

    # List verify runs
    response = client.get("/api/bridge/verify-runs")
    assert response.status_code == 200
    runs = response.json()
    assert any(r["run_id"] == run_id for r in runs)

    # Delete verify run
    response = client.delete(f"/api/bridge/verify-runs/{run_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # Get details should fail (404)
    response = client.get(f"/api/bridge/verify-runs/{run_id}")
    assert response.status_code == 404


# ── F3 Scenarios endpoint（v6.0 补齐 / 桥接 API v0.1 §2.6）──────

def test_get_scenarios_default_params():
    """GET /api/bridge/scenarios 默认参数返回 MECE 场景 + AB 配置"""
    client = TestClient(app)
    resp = client.get("/api/bridge/scenarios")
    assert resp.status_code == 200
    body = resp.json()
    assert "scenarios" in body and isinstance(body["scenarios"], list)
    assert len(body["scenarios"]) >= 3, "至少应有 S4/S5/S6 三个场景"
    # 每个场景必须含 name 和 phases
    for sc in body["scenarios"]:
        assert "name" in sc
        assert "phases" in sc and isinstance(sc["phases"], list)
        for ph in sc["phases"]:
            assert "mode" in ph and ph["mode"] in {"long", "short"}
            assert "turns" in ph and isinstance(ph["turns"], int)
    # ab_configs 必须含 baseline + optimized
    assert "ab_configs" in body
    ab = body["ab_configs"]
    assert "baseline" in ab and ab["baseline"]["bridge_turns"] == 20
    assert "optimized" in ab and ab["optimized"]["bridge_turns"] == 10


def test_get_scenarios_custom_params():
    """GET /api/bridge/scenarios?sf_turns=8&lf_turns=20 自定义参数生效"""
    client = TestClient(app)
    resp = client.get("/api/bridge/scenarios?sf_turns=8&lf_turns=20")
    assert resp.status_code == 200
    body = resp.json()
    assert body["params"]["sf_turns"] == 8
    assert body["params"]["lf_turns"] == 20


def test_get_scenarios_validation():
    """GET /api/bridge/scenarios 参数越界返回 422"""
    client = TestClient(app)
    # sf_turns 超 20 应被拒
    resp = client.get("/api/bridge/scenarios?sf_turns=99")
    assert resp.status_code == 422
    # lf_turns 超 40 应被拒
    resp = client.get("/api/bridge/scenarios?lf_turns=999")
    assert resp.status_code == 422


def test_get_scenarios_includes_tags():
    """D7: GET /api/bridge/scenarios 每个场景必须含 tags 字段（PRD §2.6 schema）"""
    client = TestClient(app)
    resp = client.get("/api/bridge/scenarios")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["scenarios"]) >= 3
    for sc in body["scenarios"]:
        assert "tags" in sc, f"场景 {sc.get('name')} 缺少 tags 字段"
        assert isinstance(sc["tags"], list), f"tags 必须是列表，实际: {type(sc['tags'])}"
        assert len(sc["tags"]) >= 1, f"场景 {sc.get('name')} tags 不能为空"
        for tag in sc["tags"]:
            assert isinstance(tag, str) and tag.strip(), f"tag 必须是非空字符串，实际: {tag!r}"
    # 关键场景应有「核心路径」标签
    core_path_scenarios = [sc for sc in body["scenarios"] if "核心路径" in sc.get("tags", [])]
    assert len(core_path_scenarios) >= 3, "至少应有 3 个核心路径场景（S4/S5/S6）"
