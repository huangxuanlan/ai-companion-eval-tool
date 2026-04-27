from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

PROJECT_DIR = Path(__file__).resolve().parent
SERVER_DIR = PROJECT_DIR / "server"

if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from main import app  # noqa: E402
from routers import compare  # noqa: E402


def test_compare_ai_summary_endpoint_returns_markdown(monkeypatch):
    report = {
        "id": "cmp001",
        "groups": [
            {"conv_id": "a1", "label": "A"},
            {"conv_id": "b1", "label": "B"},
        ],
        "group_results": [
            {
                "conv_id": "a1",
                "label": "A",
                "status": "completed",
                "model_id": "model-a",
                "prompt_version": "prompt-a",
                "avg_scores": {"total": 8.1, "persona_fidelity": 4.1},
                "per_turn": [
                    {
                        "turn": 1,
                        "total": 8.1,
                        "status": "scored",
                        "manual_star_score": 8,
                        "input_tokens": 60,
                        "output_tokens": 20,
                        "latency_s": 8.2,
                        "reasoning": "A 稳定",
                        "ai_output": "A 的输出",
                        "dimension_scores": {"persona_fidelity": 4.0},
                    }
                ],
                "turn_count": 1,
                "scored_count": 1,
                "failed_count": 0,
                "pending_count": 0,
                "manual_avg": 8.0,
                "pass_count": 1,
                "total_input_tokens": 60,
                "total_output_tokens": 20,
                "avg_latency_s": 8.2,
            },
            {
                "conv_id": "b1",
                "label": "B",
                "status": "completed",
                "model_id": "model-b",
                "prompt_version": "prompt-b",
                "avg_scores": {"total": 8.4, "persona_fidelity": 4.4},
                "per_turn": [
                    {
                        "turn": 1,
                        "total": 8.4,
                        "status": "scored",
                        "manual_star_score": 9,
                        "input_tokens": 58,
                        "output_tokens": 22,
                        "latency_s": 7.4,
                        "reasoning": "B 更好",
                        "ai_output": "B 的输出",
                        "dimension_scores": {"persona_fidelity": 5.0},
                    }
                ],
                "turn_count": 1,
                "scored_count": 1,
                "failed_count": 0,
                "pending_count": 0,
                "manual_avg": 9.0,
                "pass_count": 1,
                "total_input_tokens": 58,
                "total_output_tokens": 22,
                "avg_latency_s": 7.4,
            },
        ],
        "winners": {"persona_fidelity": "B", "total": "B"},
        "created_at": "2026-04-20 10:00:00",
    }

    monkeypatch.setattr(compare.db, "get_compare_report", lambda report_id: report if report_id == "cmp001" else None)

    class _FakeScoringService:
        async def generate_compare_report(self, augmented_report, model_id=None, prompt_version=None):
            assert augmented_report["group_results"][0]["total_input_tokens"] == 60
            assert augmented_report["per_turn_comparison"][0]["groups"][0]["reasoning"] == "A 稳定"
            assert augmented_report["per_turn_comparison"][0]["groups"][1]["dimension_scores"]["persona_fidelity"] == 5.0
            return {
                "markdown": "============================================================\n  A/B 对比摘要 | cmp001\n============================================================\n\n维度分析\n概括性结论\n逐条对比",
                "model_id": model_id or "qwen-plus",
                "prompt_version": prompt_version or "长文模式对比摘要报告提示词_v1.0_20260420.md",
                "report_title": "MODEL 对比报告",
                "group_count": 2,
                "cached": False,
            }

    monkeypatch.setattr(compare, "_get_scoring_service", lambda: _FakeScoringService())

    with TestClient(app) as client:
        response = client.post("/api/reports/compare/cmp001/ai-summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["report_id"] == "cmp001"
    assert payload["summary"]["model_id"] == "qwen-plus"
    assert "A/B 对比摘要" in payload["summary"]["markdown"]
