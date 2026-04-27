from __future__ import annotations

import asyncio
from types import SimpleNamespace

from services import conversation_service as conversation_service_module


def _build_service():
    service = conversation_service_module.ConversationService(
        model_adapter=object(),
        prompt_service=object(),
    )
    return service


def test_run_conversation_retries_transient_turn_error(monkeypatch):
    service = _build_service()
    calls = {"count": 0}
    inserted_turns: list[dict] = []
    status_updates: list[tuple[str, str]] = []

    async def _fake_sleep(_delay):
        return None

    monkeypatch.setattr(conversation_service_module.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(service, "_prepare_runtime_bundle", lambda config: SimpleNamespace())
    monkeypatch.setattr(service, "get_conversation", lambda conv_id: {})
    monkeypatch.setattr(service, "_ensure_runtime_state", lambda config, bundle, results: {})
    monkeypatch.setattr(service, "_await_memory_jobs", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_refresh_runtime_bundle_memory", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        service,
        "_resolve_dialogue_summary_for_next_turn",
        lambda config, results, runtime_bundle: ("", ""),
    )
    monkeypatch.setattr(
        service,
        "insert_turn_result",
        lambda conv_id, turn_data: inserted_turns.append(turn_data),
    )
    monkeypatch.setattr(service, "_schedule_summary_job_if_needed", lambda **kwargs: None)
    monkeypatch.setattr(service, "_schedule_profile_job_if_needed", lambda **kwargs: None)
    monkeypatch.setattr(
        service,
        "update_conversation_status",
        lambda conv_id, status: status_updates.append((conv_id, status)),
    )

    def _fake_execute(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("Connection error.")
        return {
            "turn": 1,
            "user_input": "你好",
            "ai_output": "ok",
            "dialogue_summary": "",
        }

    monkeypatch.setattr(service, "_execute_single_turn", _fake_execute)

    try:
        results = asyncio.run(
            service.run_conversation(
                conv_id="conv-retry",
                config={"runtime": {}},
                turns=["你好"],
                model_id="gemma4-26b",
                model_mini="doubao-lite",
                dry_run=False,
            )
        )
    finally:
        service._background_executor.shutdown(wait=False, cancel_futures=True)

    assert calls["count"] == 2
    assert len(results) == 1
    assert inserted_turns == [results[0]]
    assert status_updates[-1] == ("conv-retry", "completed")


def test_run_conversation_does_not_retry_non_transient_turn_error(monkeypatch):
    service = _build_service()
    calls = {"count": 0}

    monkeypatch.setattr(service, "_prepare_runtime_bundle", lambda config: SimpleNamespace())
    monkeypatch.setattr(service, "get_conversation", lambda conv_id: {})
    monkeypatch.setattr(service, "_ensure_runtime_state", lambda config, bundle, results: {})
    monkeypatch.setattr(service, "_await_memory_jobs", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_refresh_runtime_bundle_memory", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        service,
        "_resolve_dialogue_summary_for_next_turn",
        lambda config, results, runtime_bundle: ("", ""),
    )
    monkeypatch.setattr(service, "insert_turn_result", lambda conv_id, turn_data: None)
    monkeypatch.setattr(service, "_schedule_summary_job_if_needed", lambda **kwargs: None)
    monkeypatch.setattr(service, "_schedule_profile_job_if_needed", lambda **kwargs: None)
    monkeypatch.setattr(service, "update_conversation_status", lambda conv_id, status: None)

    def _fake_execute(*args, **kwargs):
        calls["count"] += 1
        raise RuntimeError("模型 gemma4-26b 返回空内容")

    monkeypatch.setattr(service, "_execute_single_turn", _fake_execute)

    try:
        try:
            asyncio.run(
                service.run_conversation(
                    conv_id="conv-no-retry",
                    config={"runtime": {}},
                    turns=["你好"],
                    model_id="gemma4-26b",
                    model_mini="doubao-lite",
                    dry_run=False,
                )
            )
        except RuntimeError as exc:
            assert "返回空内容" in str(exc)
        else:
            raise AssertionError("预期应抛出非瞬时错误")
    finally:
        service._background_executor.shutdown(wait=False, cancel_futures=True)

    assert calls["count"] == 1
