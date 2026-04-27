from __future__ import annotations

from config import DEFAULT_PROFILE_MODEL, DEFAULT_SCORING_MODEL, DEFAULT_SUMMARY_MODEL
from routers import conversations as conversations_router
from services.model_adapter import ModelAdapter


class _FakeConversationService:
    def infer_conversation_channel(self, config: dict, prompt_ref: str = "") -> str:
        return "电话聊天沟通"

    def get_latest_conversation_channel(
        self,
        *,
        role_name: str = "",
        exclude_conv_id: str = "",
    ) -> str:
        return "文字聊天沟通"


def test_apply_conversation_channel_context_preserves_tested_helper_contract():
    original = conversations_router._conv_service
    conversations_router._conv_service = _FakeConversationService()
    try:
        config = {
            "character": {"Role_Nickname": "模板角色"},
            "context": {},
            "runtime": {},
        }
        conversations_router._apply_conversation_channel_context(
            config,
            prompt_ref="dummy_prompt.md",
        )
        assert config["runtime"]["conversation_channel"] == "电话聊天沟通"
        assert config["context"]["last_cst_type"] == "上一次在文字聊天沟通"
    finally:
        conversations_router._conv_service = original


def test_prepare_batch_runtime_sets_resume_fields():
    config = {"runtime": {}}
    runtime, normalized_turns = conversations_router._prepare_batch_runtime(
        config=config,
        turns=["你好", "在吗"],
        model_ids=["doubao-pro"],
        compare_mode="",
        model_id="doubao-pro",
        dry_run=False,
    )
    assert normalized_turns == ["你好", "在吗"]
    assert runtime["conversation_mode"] == "batch"
    assert runtime["resume_supported"] is True


def test_build_runtime_config_normalizes_legacy_model_name_aliases():
    config = {"runtime": {}}
    _, resolved_model_mini = conversations_router._build_runtime_config(
        config=config,
        model_id="gemma4-31b-local",
        model_mini="doubao-seed-2-0-lite-260215",
        scoring_model_id=DEFAULT_SCORING_MODEL,
        profile_model_id="doubao-seed-2-0-lite-260215",
    )

    runtime = config["runtime"]
    assert resolved_model_mini == DEFAULT_SUMMARY_MODEL
    assert runtime["model_mini"] == DEFAULT_SUMMARY_MODEL
    assert runtime["profile_model_id"] == DEFAULT_PROFILE_MODEL


def test_model_adapter_normalizes_builtin_api_model_name_to_internal_id():
    assert (
        ModelAdapter.normalize_model_id("doubao-seed-2-0-lite-260215")
        == "doubao-lite"
    )
