from __future__ import annotations

import asyncio
from copy import deepcopy

from routers import conversations as conversations_router_module
from routers import scoring as scoring_router_module
from services import orchestration_service as orchestration_service_module
from services import task_control as task_control_module


def test_compare_run_stays_running_while_auto_scoring_is_still_pending(monkeypatch):
    run = {
        "id": "run-progress",
        "kind": "compare",
        "title": "模型对比",
        "status": "running",
        "concurrency": 1,
        "created_at": "2026-04-21 11:43:14",
        "updated_at": "2026-04-21 11:43:14",
        "manifest": {
            "groups": [
                {
                    "items": [
                        {
                            "payload": {"auto_scoring": True},
                            "planned_turns": 16,
                        }
                    ]
                }
            ]
        },
        "state": {
            "groups": [
                {
                    "key": "group:1",
                    "label": "玉奴",
                    "relationship": "熟人",
                    "planned_turns": 16,
                    "status": "running",
                    "items": [
                        {
                            "key": "group:1:model:1",
                            "label": "qwen3.5-plus",
                            "relationship": "熟人",
                            "model_id": "qwen3.5-plus",
                            "planned_turns": 16,
                            "conversation_id": "conv-progress",
                            "status": "completed",
                            "turn_count": 16,
                            "avg_chars": 446,
                            "avg_score": None,
                            "resume_supported": False,
                            "error": "",
                        }
                    ],
                }
            ],
            "summary": {},
        },
    }
    conversation = {
        "status": "completed",
        "updated_at": "2026-04-21 11:50:00",
        "results": [{"ai_output": "ok"} for _ in range(16)],
        "score_avg": None,
        "scored_turns": 4,
        "failed_turns": 1,
        "skipped_turns": 0,
        "resume_supported": False,
    }

    monkeypatch.setattr(
        orchestration_service_module.db,
        "get_orchestration_run",
        lambda _run_id: deepcopy(run),
    )
    monkeypatch.setattr(
        orchestration_service_module.db,
        "get_conversation",
        lambda _conv_id: deepcopy(conversation),
    )

    def _fake_update_orchestration_run(run_id: str, *, status: str | None = None, state: dict | None = None):
        updated = deepcopy(run)
        updated["id"] = run_id
        updated["status"] = status or updated["status"]
        updated["state"] = deepcopy(state or updated["state"])
        return updated

    monkeypatch.setattr(
        orchestration_service_module.db,
        "update_orchestration_run",
        _fake_update_orchestration_run,
    )
    monkeypatch.setattr(
        orchestration_service_module,
        "_get_live_scoring_state",
        lambda _conv_id: {"active": False, "queued_jobs": 0, "has_activity": False},
    )

    public_run = asyncio.run(orchestration_service_module.get_run("run-progress"))

    item = public_run["groups"][0]["items"][0]
    assert public_run["status"] == "running"
    assert public_run["summary"]["completed_items"] == 0
    assert public_run["summary"]["scoring_items"] == 0
    assert public_run["summary"]["pending_scoring_items"] == 1
    assert item["status"] == "scoring"
    assert item["scoring_active"] is False
    assert item["pending_scoring_turns"] == 11
    assert item["scored_turns"] == 4
    assert item["failed_turns"] == 1
    assert item["updated_at"] == "2026-04-21 11:50:00"


def test_start_or_resume_item_recovers_pending_auto_scoring(monkeypatch):
    run = {
        "state": {
            "groups": [
                {
                    "items": [
                        {
                            "conversation_id": "conv-score",
                            "planned_turns": 16,
                            "status": "completed",
                            "error": "old",
                        }
                    ]
                }
            ]
        },
        "manifest": {
            "groups": [
                {
                    "items": [
                        {
                            "payload": {"auto_scoring": True},
                        }
                    ]
                }
            ]
        },
    }
    conversation = {
        "status": "completed",
        "config": {"runtime": {"total_turns": 16, "next_turn_index": 16}},
        "results": [{"turn": i + 1, "ai_output": "ok"} for i in range(16)],
        "scored_turns": 3,
        "failed_turns": 0,
        "skipped_turns": 0,
    }
    calls = {"scoring": 0}

    async def _fake_enqueue_pending_scores(conv_id: str, config=None):
        assert conv_id == "conv-score"
        calls["scoring"] += 1
        return 13

    monkeypatch.setattr(
        orchestration_service_module.db,
        "get_conversation",
        lambda conv_id: deepcopy(conversation) if conv_id == "conv-score" else None,
    )
    monkeypatch.setattr(scoring_router_module, "enqueue_pending_live_scores", _fake_enqueue_pending_scores)

    state_item = asyncio.run(orchestration_service_module._start_or_resume_item(run, 0, 0))

    assert calls["scoring"] == 1
    assert state_item["status"] == "scoring"
    assert state_item["error"] == ""


def test_compare_run_dry_run_does_not_wait_for_scoring(monkeypatch):
    run = {
        "id": "run-dry-progress",
        "kind": "compare",
        "title": "模型对比 dry-run",
        "status": "running",
        "concurrency": 1,
        "created_at": "2026-04-22 10:00:00",
        "updated_at": "2026-04-22 10:00:00",
        "manifest": {
            "groups": [
                {
                    "items": [
                        {
                            "payload": {"auto_scoring": True, "dry_run": True},
                            "planned_turns": 3,
                        }
                    ]
                }
            ]
        },
        "state": {
            "groups": [
                {
                    "key": "group:1",
                    "label": "玉奴",
                    "relationship": "熟人",
                    "planned_turns": 3,
                    "status": "running",
                    "items": [
                        {
                            "key": "group:1:model:1",
                            "label": "gemma4-31b-local",
                            "relationship": "熟人",
                            "model_id": "gemma4-31b-local",
                            "planned_turns": 3,
                            "conversation_id": "conv-dry-progress",
                            "status": "completed",
                            "turn_count": 3,
                            "avg_chars": 120,
                            "avg_score": None,
                            "resume_supported": False,
                            "error": "",
                        }
                    ],
                }
            ],
            "summary": {},
        },
    }
    conversation = {
        "status": "completed",
        "updated_at": "2026-04-22 10:02:00",
        "config": {"runtime": {"dry_run": True}},
        "results": [{"turn": i + 1, "ai_output": "ok"} for i in range(3)],
        "score_avg": None,
        "scored_turns": 0,
        "failed_turns": 0,
        "skipped_turns": 0,
        "resume_supported": False,
    }

    monkeypatch.setattr(
        orchestration_service_module.db,
        "get_orchestration_run",
        lambda _run_id: deepcopy(run),
    )
    monkeypatch.setattr(
        orchestration_service_module.db,
        "get_conversation",
        lambda _conv_id: deepcopy(conversation),
    )
    monkeypatch.setattr(
        orchestration_service_module.db,
        "update_orchestration_run",
        lambda run_id, *, status=None, state=None: {
            **deepcopy(run),
            "id": run_id,
            "status": status or run["status"],
            "state": deepcopy(state or run["state"]),
        },
    )
    monkeypatch.setattr(
        orchestration_service_module,
        "_get_live_scoring_state",
        lambda _conv_id: {"active": False, "queued_jobs": 0, "has_activity": False},
    )

    public_run = asyncio.run(orchestration_service_module.get_run("run-dry-progress"))

    item = public_run["groups"][0]["items"][0]
    assert public_run["status"] == "completed"
    assert public_run["summary"]["completed_items"] == 1
    assert public_run["summary"]["scoring_items"] == 0
    assert public_run["summary"]["pending_scoring_items"] == 0
    assert item["status"] == "completed"
    assert item["pending_scoring_turns"] == 0


def test_start_or_resume_item_skips_pending_scoring_for_dry_run(monkeypatch):
    run = {
        "state": {
            "groups": [
                {
                    "items": [
                        {
                            "conversation_id": "conv-dry-score",
                            "planned_turns": 3,
                            "status": "completed",
                            "error": "old",
                        }
                    ]
                }
            ]
        },
        "manifest": {
            "groups": [
                {
                    "items": [
                        {
                            "payload": {"auto_scoring": True, "dry_run": True},
                        }
                    ]
                }
            ]
        },
    }
    conversation = {
        "status": "completed",
        "config": {"runtime": {"total_turns": 3, "next_turn_index": 3, "dry_run": True}},
        "results": [{"turn": i + 1, "ai_output": "ok"} for i in range(3)],
        "scored_turns": 0,
        "failed_turns": 0,
        "skipped_turns": 0,
    }
    calls = {"scoring": 0}

    async def _fake_enqueue_pending_scores(conv_id: str, config=None):
        calls["scoring"] += 1
        return 3

    monkeypatch.setattr(
        orchestration_service_module.db,
        "get_conversation",
        lambda conv_id: deepcopy(conversation) if conv_id == "conv-dry-score" else None,
    )
    monkeypatch.setattr(scoring_router_module, "enqueue_pending_live_scores", _fake_enqueue_pending_scores)

    state_item = asyncio.run(orchestration_service_module._start_or_resume_item(run, 0, 0))

    assert calls["scoring"] == 0
    assert state_item["status"] == "completed"
    assert state_item["error"] == "old"


def test_compare_run_counts_active_live_scoring_separately(monkeypatch):
    run = {
        "id": "run-active-score",
        "kind": "compare",
        "title": "模型对比",
        "status": "running",
        "concurrency": 1,
        "created_at": "2026-04-22 05:30:00",
        "updated_at": "2026-04-22 05:30:00",
        "manifest": {
            "groups": [
                {
                    "items": [
                        {
                            "payload": {"auto_scoring": True},
                            "planned_turns": 10,
                        }
                    ]
                }
            ]
        },
        "state": {
            "groups": [
                {
                    "key": "group:1",
                    "label": "玉奴",
                    "relationship": "熟人",
                    "planned_turns": 10,
                    "status": "running",
                    "items": [
                        {
                            "key": "group:1:model:1",
                            "label": "qwen-plus",
                            "relationship": "熟人",
                            "model_id": "qwen-plus",
                            "planned_turns": 10,
                            "conversation_id": "conv-active-score",
                            "status": "completed",
                            "turn_count": 10,
                            "avg_chars": 420,
                            "avg_score": 6.1,
                            "resume_supported": False,
                            "error": "",
                        }
                    ],
                }
            ],
            "summary": {},
        },
    }
    conversation = {
        "status": "completed",
        "updated_at": "2026-04-22 05:31:00",
        "results": [{"ai_output": "ok"} for _ in range(10)],
        "score_avg": 6.1,
        "scored_turns": 6,
        "failed_turns": 0,
        "skipped_turns": 0,
        "resume_supported": False,
    }

    monkeypatch.setattr(
        orchestration_service_module.db,
        "get_orchestration_run",
        lambda _run_id: deepcopy(run),
    )
    monkeypatch.setattr(
        orchestration_service_module.db,
        "get_conversation",
        lambda _conv_id: deepcopy(conversation),
    )
    monkeypatch.setattr(
        orchestration_service_module.db,
        "update_orchestration_run",
        lambda run_id, *, status=None, state=None: {
            **deepcopy(run),
            "id": run_id,
            "status": status or run["status"],
            "state": deepcopy(state or run["state"]),
        },
    )
    monkeypatch.setattr(
        orchestration_service_module,
        "_get_live_scoring_state",
        lambda _conv_id: {"active": True, "queued_jobs": 0, "has_activity": True},
    )

    public_run = asyncio.run(orchestration_service_module.get_run("run-active-score"))

    item = public_run["groups"][0]["items"][0]
    assert public_run["summary"]["scoring_items"] == 1
    assert public_run["summary"]["pending_scoring_items"] == 0
    assert item["status"] == "scoring"
    assert item["scoring_active"] is True


def test_control_child_conversations_routes_scoring_items_to_scoring_controller(monkeypatch):
    run = {
        "state": {
            "groups": [
                {
                    "items": [
                        {"conversation_id": "conv-running", "status": "running"},
                        {"conversation_id": "conv-scoring", "status": "scoring"},
                        {"conversation_id": "conv-paused", "status": "paused"},
                        {"conversation_id": "conv-done", "status": "completed"},
                    ]
                }
            ]
        }
    }
    generation_calls: list[tuple[str, str]] = []
    scoring_calls: list[tuple[str, str]] = []

    async def _fake_control_conversation(conv_id: str, request):
        generation_calls.append((conv_id, request.action))
        return {"id": conv_id, "status": request.action}

    async def _fake_control_scoring(conv_id: str, request):
        scoring_calls.append((conv_id, request.action))
        return {"conversation_id": conv_id, "status": request.action}

    monkeypatch.setattr(conversations_router_module, "control_conversation", _fake_control_conversation)
    monkeypatch.setattr(scoring_router_module, "control_scoring", _fake_control_scoring)

    asyncio.run(orchestration_service_module._control_child_conversations(run, "pause"))

    assert generation_calls == [("conv-running", "pause"), ("conv-paused", "pause")]
    assert scoring_calls == [("conv-scoring", "pause")]


def test_scoring_item_without_live_dispatcher_activity_is_reschedulable(monkeypatch):
    run = {
        "kind": "compare",
        "state": {
            "groups": [
                {
                    "items": [
                        {"conversation_id": "conv-score", "status": "scoring"},
                        {"conversation_id": "conv-done", "status": "completed"},
                    ]
                }
            ]
        },
    }

    monkeypatch.setattr(
        orchestration_service_module,
        "_has_live_scoring_activity",
        lambda conv_id: False,
    )

    assert orchestration_service_module._active_positions(run) == []
    assert orchestration_service_module._schedulable_positions(run) == [(0, 0)]


def test_scoring_item_with_live_dispatcher_activity_stays_active(monkeypatch):
    run = {
        "kind": "compare",
        "state": {
            "groups": [
                {
                    "items": [
                        {"conversation_id": "conv-score", "status": "scoring"},
                        {"conversation_id": "conv-done", "status": "completed"},
                    ]
                }
            ]
        },
    }

    monkeypatch.setattr(
        orchestration_service_module,
        "_has_live_scoring_activity",
        lambda conv_id: conv_id == "conv-score",
    )

    assert orchestration_service_module._active_positions(run) == [(0, 0)]
    assert orchestration_service_module._schedulable_positions(run) == []


def test_live_scoring_activity_does_not_consume_generation_concurrency(monkeypatch):
    run = {
        "kind": "batch",
        "state": {
            "groups": [
                {
                    "items": [
                        {"conversation_id": "conv-score", "status": "scoring"},
                        {"conversation_id": "", "status": "pending"},
                    ]
                }
            ]
        },
    }

    monkeypatch.setattr(
        orchestration_service_module,
        "_has_live_scoring_activity",
        lambda conv_id: conv_id == "conv-score",
    )

    assert orchestration_service_module._active_positions(run) == [(0, 0)]
    assert orchestration_service_module._generation_active_positions(run) == []
    assert orchestration_service_module._schedulable_positions(run) == [(0, 1)]


def test_cancelling_item_stays_active_until_terminal():
    run = {
        "kind": "batch",
        "state": {
            "groups": [
                {
                    "items": [
                        {"conversation_id": "conv-cancelling", "status": "cancelling"},
                    ]
                }
            ]
        },
    }

    assert orchestration_service_module._active_positions(run) == [(0, 0)]
    assert orchestration_service_module._generation_active_positions(run) == [(0, 0)]
    assert orchestration_service_module._schedulable_positions(run) == []


def test_ab_run_allows_cross_group_scheduling_in_group_order(monkeypatch):
    run = {
        "kind": "ab",
        "state": {
            "groups": [
                {
                    "items": [
                        {"conversation_id": "", "status": "completed"},
                        {"conversation_id": "", "status": "completed"},
                    ]
                },
                {
                    "items": [
                        {"conversation_id": "", "status": "pending"},
                        {"conversation_id": "", "status": "pending"},
                    ]
                },
                {
                    "items": [
                        {"conversation_id": "", "status": "pending"},
                    ]
                },
            ]
        },
    }

    monkeypatch.setattr(
        orchestration_service_module,
        "_has_live_scoring_activity",
        lambda _conv_id: False,
    )

    assert orchestration_service_module._schedulable_positions(run) == [(1, 0), (1, 1), (2, 0)]


def test_ab_scheduler_keeps_new_groups_atomic_when_slots_are_limited(monkeypatch):
    run = {
        "kind": "ab",
        "state": {
            "groups": [
                {
                    "items": [
                        {"conversation_id": "", "status": "completed"},
                        {"conversation_id": "", "status": "pending"},
                    ]
                },
                {
                    "items": [
                        {"conversation_id": "", "status": "pending"},
                        {"conversation_id": "", "status": "pending"},
                    ]
                },
                {
                    "items": [
                        {"conversation_id": "", "status": "pending"},
                        {"conversation_id": "", "status": "pending"},
                    ]
                },
            ]
        },
    }

    monkeypatch.setattr(
        orchestration_service_module,
        "_has_live_scoring_activity",
        lambda _conv_id: False,
    )

    assert orchestration_service_module._select_schedulable_positions(run, 2) == [(0, 1)]
    assert orchestration_service_module._select_schedulable_positions(run, 4) == [(0, 1), (1, 0), (1, 1)]


def test_control_run_cancel_keeps_runner_alive_for_cancelling_settlement(monkeypatch):
    run = {
        "id": "run-cancel-control",
        "kind": "batch",
        "title": "批量取消任务",
        "status": "running",
        "concurrency": 1,
        "state": {
            "groups": [
                {
                    "items": [
                        {"conversation_id": "conv-running", "status": "running", "error": ""},
                    ]
                }
            ]
        },
    }
    updated: list[tuple[str, str]] = []
    spawned: list[str] = []
    task_id = orchestration_service_module._runner_task_id(run["id"])
    ctrl = task_control_module.get_or_create(task_id)
    ctrl.pause()

    async def _fake_refresh_run_state(run_id: str, *, persist: bool = True):
        assert run_id == run["id"]
        assert persist is True
        return deepcopy(run)

    async def _fake_control_child_conversations(run_arg: dict, action: str):
        assert run_arg["id"] == run["id"]
        assert action == "cancel"

    monkeypatch.setattr(orchestration_service_module, "_refresh_run_state", _fake_refresh_run_state)
    monkeypatch.setattr(
        orchestration_service_module,
        "_control_child_conversations",
        _fake_control_child_conversations,
    )
    monkeypatch.setattr(
        orchestration_service_module,
        "_active_positions",
        lambda _run: [(0, 0)],
    )
    monkeypatch.setattr(
        orchestration_service_module.db,
        "update_orchestration_run",
        lambda run_id, status, state: updated.append((run_id, status)) or {
            **deepcopy(run),
            "id": run_id,
            "status": status,
            "state": deepcopy(state),
        },
    )
    monkeypatch.setattr(orchestration_service_module, "_spawn_runner", lambda run_id: spawned.append(run_id))

    try:
        payload = asyncio.run(orchestration_service_module.control_run(run["id"], "cancel"))
    finally:
        task_control_module.remove(task_id)

    assert payload["status"] == "cancelling"
    assert updated == [(run["id"], "cancelling")]
    assert spawned == [run["id"]]
    assert ctrl.status == "running"


def test_reconcile_runtime_state_respawns_interrupted_recoverable_runs(monkeypatch):
    spawned: list[str] = []
    updated: list[tuple[str, str]] = []

    async def _fake_refresh_run_state(run_id: str, *, persist: bool = True):
        assert persist is False
        return {"id": run_id, "status": "interrupted", "state": {"groups": []}}

    monkeypatch.setattr(
        orchestration_service_module.db,
        "list_orchestration_runs",
        lambda statuses, limit: [{"id": "run-recover", "status": "running"}],
    )
    monkeypatch.setattr(orchestration_service_module, "_refresh_run_state", _fake_refresh_run_state)
    monkeypatch.setattr(
        orchestration_service_module.db,
        "update_orchestration_run",
        lambda run_id, status, state: updated.append((run_id, status)) or {"id": run_id, "status": status, "state": state},
    )
    monkeypatch.setattr(orchestration_service_module, "_spawn_runner", lambda run_id: spawned.append(run_id))
    monkeypatch.setattr(task_control_module, "list_active", lambda: {"orchestration:stale": "running"})
    monkeypatch.setattr(task_control_module, "remove", lambda _task_id: None)
    monkeypatch.setattr(task_control_module, "get_or_create", lambda task_id: task_id)

    asyncio.run(orchestration_service_module.reconcile_runtime_state())

    assert updated == [("run-recover", "interrupted")]
    assert spawned == ["run-recover"]


def test_reconcile_runtime_state_keeps_settled_cancelling_runs_cancelled(monkeypatch):
    updated: list[tuple[str, str]] = []
    spawned: list[str] = []

    async def _fake_refresh_run_state(run_id: str, *, persist: bool = True):
        assert persist is False
        return {"id": run_id, "status": "cancelled", "state": {"groups": []}}

    monkeypatch.setattr(
        orchestration_service_module.db,
        "list_orchestration_runs",
        lambda statuses, limit: [{"id": "run-cancelled", "status": "cancelling"}],
    )
    monkeypatch.setattr(orchestration_service_module, "_refresh_run_state", _fake_refresh_run_state)
    monkeypatch.setattr(
        orchestration_service_module.db,
        "update_orchestration_run",
        lambda run_id, status, state: updated.append((run_id, status)) or {"id": run_id, "status": status, "state": state},
    )
    monkeypatch.setattr(orchestration_service_module, "_spawn_runner", lambda run_id: spawned.append(run_id))
    monkeypatch.setattr(task_control_module, "list_active", lambda: {"orchestration:stale": "running"})
    monkeypatch.setattr(task_control_module, "remove", lambda _task_id: None)
    monkeypatch.setattr(task_control_module, "get_or_create", lambda task_id: task_id)

    asyncio.run(orchestration_service_module.reconcile_runtime_state())

    assert updated == [("run-cancelled", "cancelled")]
    assert spawned == []
