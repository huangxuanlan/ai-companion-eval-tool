from __future__ import annotations

from services import conversation_service as conversation_service_module


def test_conversation_service_reexports_required_constants():
    required_constants = [
        "CORE_CONSTRAINTS_TEMPLATE",
        "LONGFORM_WORD_RANGE",
        "SEPARATOR_MSG",
        "STYLE_ISOLATION_MSG",
        "SUMMARY_INJECT_TEMPLATE",
        "MEMORY_WAIT_TIMEOUT_S",
    ]
    for name in required_constants:
        assert hasattr(conversation_service_module, name), f"缺少常量导出: {name}"


def test_conversation_service_compat_surface_has_required_methods():
    service = conversation_service_module.ConversationService()
    try:
        required_methods = [
            "build_config_from_preset",
            "_prepare_runtime_bundle",
            "_execute_single_turn",
            "generate_interactive_turn",
            "generate_summary",
            "generate_user_profile",
            "run_conversation",
        ]
        for name in required_methods:
            assert hasattr(service, name), f"缺少兼容方法: {name}"
    finally:
        service._background_executor.shutdown(wait=False, cancel_futures=True)
