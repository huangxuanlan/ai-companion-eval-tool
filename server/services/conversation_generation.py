from __future__ import annotations

import logging

from config import DEFAULT_SCORING_MODEL
from services.model_adapter import ModelAdapter
from services.quality_guard import QualityGuard

logger = logging.getLogger(__name__)


def build_request_payload_snapshot(
    service,
    *,
    config: dict,
    runtime_bundle,
    messages: list[dict],
    model_id: str,
    memory_context_snapshot: dict | None = None,
    summary_source: str = "",
    web_search: bool = False,
    thinking_enabled: bool | None = None,
    thinking_effort: str = "disabled",
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
) -> dict:
    runtime = dict(config.get("runtime", {}) or {})
    character = dict(config.get("character", {}) or {})
    model_meta = dict(getattr(service.model, "_models", {}).get(model_id, {}) or {})
    parameters = dict(model_meta.get("parameters", {}) or {})
    if max_tokens is not None:
        if "max_tokens" in parameters:
            parameters["max_tokens"] = max_tokens
        elif "max_completion_tokens" in parameters:
            parameters["max_completion_tokens"] = max_tokens
        else:
            parameters["max_tokens"] = max_tokens
    if temperature is not None:
        parameters["temperature"] = temperature
    elif runtime.get("temperature") is not None:
        parameters["temperature"] = runtime.get("temperature")
    if top_p is not None:
        parameters["top_p"] = top_p
    elif runtime.get("top_p") is not None:
        parameters["top_p"] = runtime.get("top_p")
    effective_max_tokens = parameters.get("max_tokens")
    if effective_max_tokens is None:
        effective_max_tokens = parameters.get("max_completion_tokens")

    effective_thinking_effort = str(thinking_effort or "").strip().lower() or "disabled"
    return {
        "model_id": model_id,
        "messages": [dict(item) for item in (messages or [])],
        "web_search": bool(web_search),
        "thinking_enabled": (
            bool(thinking_enabled)
            if thinking_enabled is not None
            else effective_thinking_effort != "disabled"
        ),
        "thinking_effort": effective_thinking_effort,
        "temperature": parameters.get("temperature"),
        "top_p": parameters.get("top_p"),
        "max_tokens": effective_max_tokens,
        "prompt_version": str(config.get("prompt_file", "")).strip(),
        "summary_prompt_version": str(
            runtime.get("summary_prompt_version", "")
        ).strip(),
        "scoring_prompt_version": str(
            runtime.get("scoring_prompt_version", "")
        ).strip(),
        "scoring_model_id": str(
            runtime.get("scoring_model_id", DEFAULT_SCORING_MODEL)
        ).strip(),
        "scoring_thinking_enabled": runtime.get("scoring_thinking_enabled", None),
        "scoring_thinking_effort": str(
            runtime.get("scoring_thinking_effort", "")
        ).strip(),
        "summary_interval": runtime.get("summary_interval"),
        "injection_depth": runtime.get(
            "injection_depth", runtime_bundle.injection_depth
        ),
        "role_name": runtime_bundle.role_name,
        "relationship": runtime_bundle.relationship,
        "personality": runtime_bundle.personality,
        "system_prompt": runtime_bundle.rendered_system,
        "system_after": runtime_bundle.rendered_after,
        "memory_context_snapshot": dict(memory_context_snapshot or {}),
        "summary_source": str(summary_source or "").strip(),
        "custom_variables": dict(config.get("custom_variables", {}) or {}),
        "character": {
            "Role_Nickname": character.get(
                "Role_Nickname", runtime_bundle.role_name
            ),
            "personality": character.get(
                "personality", runtime_bundle.personality
            ),
        },
    }


def build_memory_context_block(
    profile: str,
    moments: str,
    dialogue_summary: str,
) -> tuple[str, dict]:
    sections: list[str] = []
    snapshot = {
        "dialogueStartPrompt": str(profile or "").strip(),
        "moments": str(moments or "").strip(),
        "dialogue_summary": str(dialogue_summary or "").strip(),
    }
    if snapshot["dialogueStartPrompt"]:
        sections.append(f"【长期记忆用户画像】\n{snapshot['dialogueStartPrompt']}")
    if snapshot["moments"]:
        sections.append(f"【朋友圈记忆】\n{snapshot['moments']}")
    if snapshot["dialogue_summary"]:
        sections.append(f"【历史对话摘要】\n{snapshot['dialogue_summary']}")
    return "\n\n".join(sections), snapshot


def execute_single_turn(
    service,
    *,
    runtime_bundle,
    conversation_history: list[dict],
    dialogue_summary: str,
    summary_source: str,
    current_input: str,
    turn_num: int,
    model_id: str,
    config: dict | None = None,
    dry_run: bool = False,
    web_search: bool = False,
    thinking_enabled: bool | None = None,
    thinking_effort: str = "disabled",
    temperature: float | None = None,
    top_p: float | None = None,
) -> dict:
    config = config or {}
    runtime = dict(config.get("runtime", {}) or {})
    effective_summary_source = str(summary_source or "").strip()
    if not effective_summary_source and turn_num <= 1 and str(dialogue_summary or "").strip():
        effective_summary_source = "seed"
    resolver = getattr(service.model, "resolve_thinking_effort", None)
    if callable(resolver):
        effective_thinking_effort = resolver(
            model_id,
            thinking_enabled,
            thinking_effort,
        )
    else:
        effective_thinking_effort = ModelAdapter.resolve_thinking_effort(
            model_id,
            thinking_enabled,
            thinking_effort,
        )
    if ModelAdapter.is_gemma_model(model_id) and thinking_enabled is False:
        effective_thinking_effort = "disabled"

    def _parse_optional_float(value):
        text = str(value).strip()
        if text == "":
            return None
        try:
            return float(text)
        except (TypeError, ValueError):
            return None

    effective_temperature = (
        _parse_optional_float(temperature)
        if temperature is not None
        else _parse_optional_float(runtime.get("temperature"))
    )
    effective_top_p = (
        _parse_optional_float(top_p)
        if top_p is not None
        else _parse_optional_float(runtime.get("top_p"))
    )
    history_window = list(conversation_history or [])[-20:]
    memory_context, memory_context_snapshot = build_memory_context_block(
        runtime_bundle.memory_profile,
        runtime_bundle.memory_moments,
        dialogue_summary,
    )
    use_raw_seed_summary = (
        effective_summary_source == "seed"
        and not str(runtime_bundle.memory_profile or "").strip()
        and not str(runtime_bundle.memory_moments or "").strip()
    )
    if use_raw_seed_summary:
        memory_context = ""
    messages = service._build_messages_internal(
        rendered_system=runtime_bundle.rendered_system,
        system_after=runtime_bundle.rendered_after,
        few_shot_messages=runtime_bundle.few_shot_messages,
        conversation_history=history_window,
        dialogue_summary=dialogue_summary,
        memory_context=memory_context,
        current_input=current_input,
        relationship=runtime_bundle.relationship,
        role_name=runtime_bundle.role_name,
        personality=runtime_bundle.personality,
        turn_num=turn_num,
        injection_depth=runtime_bundle.injection_depth,
        model_id=model_id,
    )

    total_tokens = service.trimmer.count_messages_tokens(messages)
    token_trim_level = 0
    internal_trim_level = 0
    if total_tokens > service.trimmer.max_tokens:
        messages, internal_trim_level = service.trimmer.trim_messages(
            messages=messages,
            few_shot_messages=runtime_bundle.few_shot_messages,
            conversation_history=history_window,
            dialogue_summary=dialogue_summary,
            memory_profile=runtime_bundle.memory_profile,
            memory_moments=runtime_bundle.memory_moments,
            system_prompt=runtime_bundle.rendered_system,
            system_after=runtime_bundle.rendered_after,
            current_input=current_input,
            relationship=runtime_bundle.relationship,
            role_name=runtime_bundle.role_name,
            personality=runtime_bundle.personality,
            turn_num=turn_num,
            injection_depth=runtime_bundle.injection_depth,
            model_id=model_id,
        )
        memory_context, memory_context_snapshot = build_memory_context_block(
            runtime_bundle.memory_profile,
            runtime_bundle.memory_moments,
            dialogue_summary,
        )
        if use_raw_seed_summary:
            memory_context = ""
        token_trim_level = 1 if internal_trim_level == 1 else 2

    has_style_isolation = any("遵循System Prompt" in m.get("content", "") for m in messages)
    has_deep_injection = any("请记住：你是" in m.get("content", "") for m in messages)
    has_cooldown_reinject = (
        turn_num >= 16
        and len(runtime_bundle.few_shot_messages) > 0
        and internal_trim_level < 2
    )
    request_payload_snapshot = build_request_payload_snapshot(
        service,
        config=config,
        runtime_bundle=runtime_bundle,
        messages=messages,
        model_id=model_id,
        memory_context_snapshot=memory_context_snapshot,
        summary_source=effective_summary_source,
        web_search=web_search,
        thinking_enabled=thinking_enabled,
        thinking_effort=effective_thinking_effort,
        temperature=effective_temperature,
        top_p=effective_top_p,
    )

    if dry_run:
        return {
            "turn": turn_num,
            "user_input": current_input,
            "ai_output": f"[dry-run] Turn {turn_num} 模拟回复",
            "word_count": 0,
            "dialogue_summary": dialogue_summary,
            "msg_count": len(messages),
            "input_tokens": 0,
            "output_tokens": 0,
            "latency_s": 0,
            "has_deep_injection": has_deep_injection,
            "has_style_isolation": has_style_isolation,
            "has_cooldown_reinject": has_cooldown_reinject,
            "token_trim_level": token_trim_level,
            "quality_retries": 0,
            "messages_snapshot": messages,
            "request_payload_snapshot": request_payload_snapshot,
            "memory_context_snapshot": memory_context_snapshot,
            "summary_source": effective_summary_source,
            "model_id": model_id,
        }

    qa = QualityGuard()
    quality_retries = 0
    total_input_tokens = 0
    total_output_tokens = 0
    total_latency = 0.0

    for attempt in range(qa.MAX_RETRIES + 1):
        request_payload_snapshot = build_request_payload_snapshot(
            service,
            config=config,
            runtime_bundle=runtime_bundle,
                messages=messages,
                model_id=model_id,
                memory_context_snapshot=memory_context_snapshot,
                summary_source=effective_summary_source,
                web_search=web_search,
                thinking_enabled=thinking_enabled,
                thinking_effort=effective_thinking_effort,
                temperature=effective_temperature,
                top_p=effective_top_p,
        )
        result = service.model.chat(
            model_id,
            messages,
            web_search=web_search,
            thinking_effort=effective_thinking_effort,
            temperature=effective_temperature,
            top_p=effective_top_p,
        )
        if not result.success:
            raise RuntimeError(result.error or f"模型 {model_id} 调用失败")

        ai_output = str(result.content or "").strip()
        if not ai_output:
            raise RuntimeError(f"模型 {model_id} 返回空内容")
        logger.info(
            "主生成完成 model=%s turn=%s latency=%.2fs input_tokens=%s output_tokens=%s",
            model_id,
            turn_num,
            result.latency_s,
            result.input_tokens,
            result.output_tokens,
        )
        total_input_tokens += result.input_tokens
        total_output_tokens += result.output_tokens
        total_latency += result.latency_s

        qa_result = qa.check(ai_output)
        ai_output = qa_result["processed_text"]

        if not qa_result["needs_retry"]:
            break
        if attempt < qa.MAX_RETRIES:
            quality_retries += 1
            retry_msg = qa.get_retry_prompt(qa_result["retry_reason"])
            messages.append({"role": "system", "content": retry_msg})

    return {
        "turn": turn_num,
        "user_input": current_input,
        "ai_output": ai_output,
        "word_count": len(ai_output),
        "dialogue_summary": dialogue_summary,
        "msg_count": len(messages),
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "latency_s": round(total_latency, 2),
        "has_deep_injection": has_deep_injection,
        "has_style_isolation": has_style_isolation,
        "has_cooldown_reinject": has_cooldown_reinject,
        "token_trim_level": token_trim_level,
        "quality_retries": quality_retries,
        "messages_snapshot": messages,
        "request_payload_snapshot": request_payload_snapshot,
        "memory_context_snapshot": memory_context_snapshot,
        "summary_source": effective_summary_source,
        "model_id": model_id,
    }
