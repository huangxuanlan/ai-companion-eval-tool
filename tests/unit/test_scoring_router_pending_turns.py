from __future__ import annotations

import asyncio
from copy import deepcopy

from routers import scoring as scoring_router_module


def test_select_pending_scoring_results_only_keeps_unscored_and_failed():
    results = [
        {"turn": 1, "score_status": "scored", "score_total": 6.8},
        {"turn": 2, "score_status": "unscored", "score_total": 0},
        {"turn": 3, "score_status": "failed", "score_total": 0},
        {"turn": 4, "score_status": "skipped", "score_total": 0},
    ]

    pending = scoring_router_module._select_pending_scoring_results(results)

    assert [item["turn"] for item in pending] == [2, 3]


def test_build_scoring_detail_diagnostics_uses_existing_scores_and_reasoning():
    conversation = {
        "id": "conv-diagnostics",
        "results": [
            {
                "turn": 1,
                "score_status": "scored",
                "score_total": 7.2,
                "score_persona_fidelity": 3.2,
                "score_narrative_immersion": 4.2,
                "score_emotional_tension": 4.0,
                "score_boundary_memory": 4.1,
                "score_format_compliance": 4.3,
                "score_context_coherence": 3.4,
                "score_reasoning": "人设和上下文衔接偏弱",
            },
            {
                "turn": 2,
                "score_status": "failed",
                "score_total": 0,
                "score_reasoning": "[打分失败] timeout",
            },
            {
                "turn": 3,
                "score_status": "unscored",
                "score_total": 0,
                "score_reasoning": "",
            },
        ],
    }

    diagnostics = scoring_router_module._build_scoring_detail_diagnostics(conversation)

    assert set(diagnostics.keys()) == {
        "evidence_chain",
        "failure_diagnostics",
        "low_score_clusters",
    }
    assert diagnostics["evidence_chain"][0]["turn"] == 1
    assert diagnostics["evidence_chain"][0]["weakest_dimensions"][0]["dimension"] == "persona_fidelity"
    assert diagnostics["evidence_chain"][1]["failure_type"] == "timeout"
    assert diagnostics["failure_diagnostics"]["status_counts"] == {
        "scored": 1,
        "failed": 1,
        "unscored": 1,
    }
    assert diagnostics["failure_diagnostics"]["failure_types"][0]["type"] == "pending_scoring"
    cluster_names = {item["cluster"] for item in diagnostics["low_score_clusters"]}
    assert {"persona_fidelity", "context_coherence"}.issubset(cluster_names)


def test_get_scoring_results_payload_includes_diagnostics(monkeypatch):
    conversation = {
        "id": "conv-preview",
        "model_id": "qwen-plus",
        "config": {},
        "results": [
            {
                "turn": 1,
                "score_status": "scored",
                "score_total": 7.0,
                "score_persona_fidelity": 3.0,
                "score_narrative_immersion": 4.0,
                "score_emotional_tension": 4.0,
                "score_boundary_memory": 4.0,
                "score_format_compliance": 4.0,
                "score_context_coherence": 4.0,
                "score_reasoning": "人设偏弱",
            },
            {
                "turn": 2,
                "score_status": "failed",
                "score_total": 0,
                "score_reasoning": "[JSON解析失败] bad payload",
            },
        ],
    }

    monkeypatch.setattr(
        scoring_router_module,
        "_get_visible_conversation_or_404",
        lambda conv_id: deepcopy(conversation) if conv_id == "conv-preview" else None,
    )
    monkeypatch.setattr(
        scoring_router_module,
        "_build_scoring_state_view",
        lambda _conv_id, _conversation: {
            "summary": {"scored_count": 1, "failed_count": 1},
            "meta": {"scoring_model_id": "qwen-plus"},
            "action": {"recommended_action": "retry_failed_turns"},
        },
    )

    payload = asyncio.run(scoring_router_module.get_scoring_results("conv-preview"))

    assert "evidence_chain" in payload
    assert "failure_diagnostics" in payload
    assert "low_score_clusters" in payload
    assert payload["evidence_chain"][1]["failure_type"] == "parse_error"
    assert payload["low_score_clusters"][0]["cluster"] == "persona_fidelity"


def test_generate_ai_summary_payload_includes_diagnostics_without_model_call(monkeypatch):
    conversation = {
        "id": "conv-report",
        "config": {},
        "results": [
            {
                "turn": 1,
                "score_status": "scored",
                "score_total": 7.4,
                "score_persona_fidelity": 3.2,
                "score_narrative_immersion": 4.1,
                "score_emotional_tension": 4.0,
                "score_boundary_memory": 4.0,
                "score_format_compliance": 4.0,
                "score_context_coherence": 3.3,
                "score_reasoning": "证据显示人设和上下文衔接较弱",
            },
            {
                "turn": 2,
                "score_status": "failed",
                "score_total": 0,
                "score_reasoning": "[打分失败] 上游打分服务 500 错误",
            },
        ],
    }
    calls = {"generate_ai_summary": 0}

    class _FakeService:
        async def generate_ai_summary(self, scored_items, config, model_id=None, prompt_version=None, conversation_id=""):
            calls["generate_ai_summary"] += 1
            assert conversation_id == "conv-report"
            assert scored_items[0]["mapped_total"] == 7.4
            return {"markdown": "cached report", "cached": True}

    monkeypatch.setattr(
        scoring_router_module,
        "_get_visible_conversation_or_404",
        lambda conv_id: deepcopy(conversation) if conv_id == "conv-report" else None,
    )
    monkeypatch.setattr(scoring_router_module, "_get_scoring", lambda: _FakeService())

    payload = asyncio.run(scoring_router_module.generate_ai_summary("conv-report", "", ""))

    assert calls["generate_ai_summary"] == 1
    assert payload["summary"]["markdown"] == "cached report"
    assert payload["summary"]["evidence_chain"][0]["turn"] == 1
    assert payload["summary"]["failure_diagnostics"]["failure_types"][0]["type"] == "upstream_error"
    assert {item["cluster"] for item in payload["summary"]["low_score_clusters"]} == {
        "context_coherence",
        "persona_fidelity",
    }


def test_live_scoring_default_global_capacity_is_capped(monkeypatch):
    monkeypatch.delenv(scoring_router_module.LIVE_SCORING_MAX_WORKERS_ENV, raising=False)

    assert scoring_router_module._resolve_live_scoring_max_workers() == 6


def test_enqueue_live_score_turn_does_not_mutate_global_worker_limit(monkeypatch):
    calls: list[int] = []

    class _FakeService:
        def set_max_workers(self, value):
            calls.append(value)

    class _FakeDispatcher:
        async def notify_capacity_changed(self):
            calls.append(-1)

        async def enqueue(self, conv_id, turn, config=None):
            assert conv_id == "conv-live"
            assert turn == 2
            return True

    monkeypatch.setattr(scoring_router_module, "_get_scoring", lambda: _FakeService())
    monkeypatch.setattr(scoring_router_module, "get_live_scoring_dispatcher", lambda: _FakeDispatcher())
    monkeypatch.setattr(scoring_router_module, "_record_scoring_event", lambda *_args, **_kwargs: None)

    async def _fake_push_live_score_event(*_args, **_kwargs):
        return None

    monkeypatch.setattr(scoring_router_module, "_push_live_score_event", _fake_push_live_score_event)

    result = asyncio.run(
        scoring_router_module.enqueue_live_score_turn(
            "conv-live",
            2,
            config={"runtime": {"scoring_max_workers": 2}},
        )
    )

    assert result is True
    assert calls == []


def test_trigger_scoring_returns_already_scored_when_no_pending_results(monkeypatch):
    conversation = {
        "id": "conv-scored",
        "config": {"runtime": {"scoring_model_id": "qwen-plus"}},
        "status": "completed",
        "results": [
            {"turn": 1, "score_status": "scored", "score_total": 7.2},
            {"turn": 2, "score_status": "skipped", "score_total": 0},
        ],
    }

    monkeypatch.setattr(
        scoring_router_module,
        "_get_visible_conversation_or_404",
        lambda conv_id: deepcopy(conversation) if conv_id == "conv-scored" else None,
    )
    monkeypatch.setattr(
        scoring_router_module,
        "_build_scoring_summary",
        lambda _conversation: {
            "avg_total": 7.2,
            "scored_count": 1,
            "failed_count": 0,
            "skipped_count": 1,
            "total_count": 2,
        },
    )
    monkeypatch.setattr(
        scoring_router_module,
        "_build_ai_report_meta",
        lambda *_args, **_kwargs: {
            "ai_report_status": "pending",
            "ai_report_label": "等待生成报告",
            "ai_report_ready": False,
            "ai_report_updated_at": "",
        },
    )
    monkeypatch.setattr(scoring_router_module.task_control, "get", lambda _key: None)
    monkeypatch.setattr(
        scoring_router_module.get_live_scoring_dispatcher(),
        "has_activity",
        lambda _conv_id: False,
    )

    result = asyncio.run(scoring_router_module.trigger_scoring("conv-scored", None))

    assert result["status"] == "already_scored"
    assert result["turns_to_score"] == 0
    assert result["summary"]["scored_count"] == 1
    assert result["summary"]["skipped_count"] == 1
    assert result["summary"]["recommended_action"] == "repair_summary"
    assert result["action"]["recommended_action_label"] == "汇总评分"


def test_trigger_scoring_only_schedules_pending_turns(monkeypatch):
    conversation = {
        "id": "conv-pending",
        "config": {"runtime": {"scoring_model_id": "qwen-plus"}},
        "results": [
            {"turn": 1, "score_status": "scored", "score_total": 7.6},
            {"turn": 2, "score_status": "unscored", "score_total": 0},
            {"turn": 3, "score_status": "failed", "score_total": 0},
            {"turn": 4, "score_status": "skipped", "score_total": 0},
        ],
    }
    captured: dict[str, object] = {}

    class _FakeService:
        def set_max_workers(self, _value):
            return None

        def is_available(self, _model_id):
            return True

        def get_last_error(self):
            return ""

    monkeypatch.setattr(
        scoring_router_module,
        "_get_visible_conversation_or_404",
        lambda conv_id: deepcopy(conversation) if conv_id == "conv-pending" else None,
    )
    monkeypatch.setattr(scoring_router_module, "_get_scoring", lambda: _FakeService())
    monkeypatch.setattr(
        scoring_router_module,
        "_merge_scoring_runtime",
        lambda config, _data: deepcopy(config),
    )
    monkeypatch.setattr(scoring_router_module, "_persist_scoring_runtime", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(scoring_router_module, "_invalidate_conversation_scoring_summary", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(scoring_router_module, "_record_scoring_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(scoring_router_module.task_control, "get", lambda _key: None)
    monkeypatch.setattr(scoring_router_module.task_control, "remove", lambda _key: None)
    monkeypatch.setattr(scoring_router_module.task_control, "get_or_create", lambda _key: object())

    async def _fake_run_scoring(conv_id: str, results: list[dict], config: dict, service):
        captured["conv_id"] = conv_id
        captured["results"] = results
        captured["config"] = config
        captured["service"] = service

    def _fake_create_task(coro):
        frame = getattr(coro, "cr_frame", None)
        if frame is not None:
            captured["results"] = frame.f_locals.get("results")
            captured["conv_id"] = frame.f_locals.get("conv_id")
        coro.close()
        return object()

    monkeypatch.setattr(scoring_router_module, "_run_scoring", _fake_run_scoring)
    monkeypatch.setattr(scoring_router_module.asyncio, "create_task", _fake_create_task)

    result = asyncio.run(scoring_router_module.trigger_scoring("conv-pending", None))

    assert result["status"] == "scoring_started"
    assert result["turns_to_score"] == 2
    assert [item["turn"] for item in captured["results"]] == [2, 3]


def test_trigger_scoring_with_changed_model_schedules_full_rescore(monkeypatch):
    conversation = {
        "id": "conv-scored",
        "config": {"runtime": {"scoring_model_id": "qwen-plus"}},
        "scoring_model_id": "qwen-plus",
        "results": [
            {"turn": 1, "score_status": "scored", "score_total": 8.1},
            {"turn": 2, "score_status": "scored", "score_total": 8.3},
        ],
    }
    captured: dict[str, object] = {}

    class _FakeService:
        def set_max_workers(self, _value):
            return None

        def is_available(self, _model_id):
            return True

        def get_last_error(self):
            return ""

    monkeypatch.setattr(
        scoring_router_module,
        "_get_visible_conversation_or_404",
        lambda conv_id: deepcopy(conversation) if conv_id == "conv-scored" else None,
    )
    monkeypatch.setattr(scoring_router_module, "_get_scoring", lambda: _FakeService())
    monkeypatch.setattr(
        scoring_router_module,
        "_merge_scoring_runtime",
        lambda config, _data: deepcopy(config),
    )
    monkeypatch.setattr(scoring_router_module, "_persist_scoring_runtime", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(scoring_router_module.db, "reset_conversation_scores", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(scoring_router_module, "_invalidate_conversation_scoring_summary", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(scoring_router_module, "_record_scoring_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(scoring_router_module.task_control, "get", lambda _key: None)
    monkeypatch.setattr(scoring_router_module.task_control, "remove", lambda _key: None)
    monkeypatch.setattr(scoring_router_module.task_control, "get_or_create", lambda _key: object())

    async def _fake_run_scoring(conv_id: str, results: list[dict], config: dict, service):
        captured["conv_id"] = conv_id
        captured["results"] = results
        captured["config"] = config
        captured["service"] = service

    def _fake_create_task(coro):
        frame = getattr(coro, "cr_frame", None)
        if frame is not None:
            captured["results"] = frame.f_locals.get("results")
            captured["conv_id"] = frame.f_locals.get("conv_id")
        coro.close()
        return object()

    monkeypatch.setattr(scoring_router_module, "_run_scoring", _fake_run_scoring)
    monkeypatch.setattr(scoring_router_module.asyncio, "create_task", _fake_create_task)

    result = asyncio.run(
        scoring_router_module.trigger_scoring(
            "conv-scored",
            scoring_router_module.TriggerScoringRequest(
                scoring_model_id="qwen3.6-plus",
                max_workers=4,
            ),
        )
    )

    assert result["status"] == "rescore_started"
    assert result["turns_to_score"] == 2
    assert captured["conv_id"] == "conv-scored"
    assert [item["turn"] for item in captured["results"]] == [1, 2]


def test_trigger_scoring_with_explicit_model_rescores_legacy_conversation(monkeypatch):
    conversation = {
        "id": "conv-legacy",
        "config": {"runtime": {}},
        "results": [
            {"turn": 1, "score_status": "scored", "score_total": 8.1},
            {"turn": 2, "score_status": "scored", "score_total": 8.3},
        ],
    }
    captured: dict[str, object] = {}

    class _FakeService:
        def set_max_workers(self, _value):
            return None

        def is_available(self, _model_id):
            return True

        def get_last_error(self):
            return ""

    monkeypatch.setattr(
        scoring_router_module,
        "_get_visible_conversation_or_404",
        lambda conv_id: deepcopy(conversation) if conv_id == "conv-legacy" else None,
    )
    monkeypatch.setattr(scoring_router_module, "_get_scoring", lambda: _FakeService())
    monkeypatch.setattr(
        scoring_router_module,
        "_merge_scoring_runtime",
        lambda config, _data: deepcopy(config),
    )
    monkeypatch.setattr(scoring_router_module, "_persist_scoring_runtime", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(scoring_router_module.db, "reset_conversation_scores", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(scoring_router_module, "_invalidate_conversation_scoring_summary", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(scoring_router_module, "_record_scoring_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(scoring_router_module.task_control, "get", lambda _key: None)
    monkeypatch.setattr(scoring_router_module.task_control, "remove", lambda _key: None)
    monkeypatch.setattr(scoring_router_module.task_control, "get_or_create", lambda _key: object())

    async def _fake_run_scoring(conv_id: str, results: list[dict], config: dict, service):
        captured["conv_id"] = conv_id
        captured["results"] = results

    def _fake_create_task(coro):
        frame = getattr(coro, "cr_frame", None)
        if frame is not None:
            captured["results"] = frame.f_locals.get("results")
            captured["conv_id"] = frame.f_locals.get("conv_id")
        coro.close()
        return object()

    monkeypatch.setattr(scoring_router_module, "_run_scoring", _fake_run_scoring)
    monkeypatch.setattr(scoring_router_module.asyncio, "create_task", _fake_create_task)

    result = asyncio.run(
        scoring_router_module.trigger_scoring(
            "conv-legacy",
            scoring_router_module.TriggerScoringRequest(scoring_model_id="qwen3.6-plus"),
        )
    )

    assert result["status"] == "rescore_started"
    assert result["turns_to_score"] == 2
    assert captured["conv_id"] == "conv-legacy"
    assert [item["turn"] for item in captured["results"]] == [1, 2]


def test_build_scoring_action_state_prefers_retry_failed_when_partial_scores_exist(monkeypatch):
    conversation = {"id": "conv-partial", "status": "completed", "results": []}
    summary = {
        "avg_total": 6.6,
        "scored_count": 2,
        "failed_count": 1,
        "skipped_count": 0,
        "total_count": 4,
    }
    report_meta = {
        "ai_report_status": "waiting_scoring",
        "ai_report_label": "待评分完成",
        "ai_report_ready": False,
        "ai_report_updated_at": "",
    }

    monkeypatch.setattr(scoring_router_module.task_control, "get", lambda _key: None)
    monkeypatch.setattr(
        scoring_router_module.get_live_scoring_dispatcher(),
        "has_activity",
        lambda _conv_id: False,
    )

    action_state = scoring_router_module._build_scoring_action_state(
        "conv-partial",
        conversation,
        summary,
        report_meta,
    )

    assert action_state["recommended_action"] == "retry_failed_turns"
    assert action_state["has_scored_turns"] is True
    assert action_state["has_pending_turns"] is True


def test_build_scoring_action_state_retries_failed_even_when_all_turns_settled(monkeypatch):
    conversation = {"id": "conv-settled-failed", "status": "completed", "results": []}
    summary = {
        "avg_total": 6.6,
        "scored_count": 2,
        "failed_count": 1,
        "skipped_count": 0,
        "total_count": 3,
    }
    report_meta = {
        "ai_report_status": "pending",
        "ai_report_label": "等待生成报告",
        "ai_report_ready": False,
        "ai_report_updated_at": "",
    }

    monkeypatch.setattr(scoring_router_module.task_control, "get", lambda _key: None)
    monkeypatch.setattr(
        scoring_router_module.get_live_scoring_dispatcher(),
        "has_activity",
        lambda _conv_id: False,
    )

    action_state = scoring_router_module._build_scoring_action_state(
        "conv-settled-failed",
        conversation,
        summary,
        report_meta,
    )

    assert action_state["recommended_action"] == "retry_failed_turns"
    assert action_state["all_turns_settled"] is True
    assert action_state["repair_summary_needed"] is True


def test_build_scoring_action_state_retries_failed_without_scored_turns(monkeypatch):
    conversation = {"id": "conv-failed-first", "status": "completed", "results": []}
    summary = {
        "avg_total": None,
        "scored_count": 0,
        "failed_count": 1,
        "skipped_count": 0,
        "total_count": 3,
    }
    report_meta = {
        "ai_report_status": "waiting_scoring",
        "ai_report_label": "待评分完成",
        "ai_report_ready": False,
        "ai_report_updated_at": "",
    }

    monkeypatch.setattr(scoring_router_module.task_control, "get", lambda _key: None)
    monkeypatch.setattr(
        scoring_router_module.get_live_scoring_dispatcher(),
        "has_activity",
        lambda _conv_id: False,
    )

    action_state = scoring_router_module._build_scoring_action_state(
        "conv-failed-first",
        conversation,
        summary,
        report_meta,
    )

    assert action_state["recommended_action"] == "retry_failed_turns"
    assert action_state["has_scored_turns"] is False
    assert action_state["has_pending_turns"] is True


def test_build_scoring_action_state_prefers_resume_sync_when_runtime_is_active(monkeypatch):
    conversation = {"id": "conv-active", "status": "completed", "results": []}
    summary = {
        "avg_total": 6.6,
        "scored_count": 1,
        "failed_count": 0,
        "skipped_count": 0,
        "total_count": 4,
    }
    report_meta = {
        "ai_report_status": "waiting_scoring",
        "ai_report_label": "待评分完成",
        "ai_report_ready": False,
        "ai_report_updated_at": "",
    }

    class _FakeCtrl:
        status = "running"

    monkeypatch.setattr(scoring_router_module.task_control, "get", lambda _key: _FakeCtrl())
    monkeypatch.setattr(
        scoring_router_module.get_live_scoring_dispatcher(),
        "has_activity",
        lambda _conv_id: True,
    )

    action_state = scoring_router_module._build_scoring_action_state(
        "conv-active",
        conversation,
        summary,
        report_meta,
    )

    assert action_state["recommended_action"] == "resume_sync"
    assert action_state["scoring_active"] is True
