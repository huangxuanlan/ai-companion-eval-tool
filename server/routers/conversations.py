"""
对话路由 — /api/conversations + WebSocket

REST 端点 + WebSocket 实时推送。
"""
import asyncio
from copy import deepcopy
import inspect
import json
from datetime import datetime
from fastapi import APIRouter, Body, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

import database as db
from models import (
    ConversationCreate,
    InteractiveConversationCreate,
    InteractiveGenerateRequest,
    InteractiveRegenerateRequest,
    TaskControlRequest,
    InteractiveTurnCreate,
    InteractiveTurnScoreCreate,
)
from services.conversation_service import ConversationService
from services.model_adapter import ModelAdapter
from services.prompt_service import PromptService
from services.runtime_config import (
    apply_relationship_defaults as apply_runtime_relationship_defaults,
    apply_runtime_defaults,
    apply_temporal_defaults as apply_runtime_temporal_defaults,
    normalize_frontend_aliases as normalize_runtime_aliases,
)
from services.export_service import ExportService
from services.prompt_version_service import VersionedPromptStore
from services.public_demo import (
    ensure_visible_conversation,
    filter_visible_conversations,
    is_public_demo_mode,
)
from services import task_control
from config import (
    DEFAULT_INJECTION_DEPTH,
    DEFAULT_PROFILE_MODEL,
    DEFAULT_SCORING_MODEL,
    DEFAULT_SUMMARY_MODEL,
    DEFAULT_SUMMARY_INTERVAL,
    MAX_COMPARE_MODELS,
    MAX_CONCURRENT_CONVERSATIONS,
    PRESET_CHARACTERS,
    RELATIONSHIP_PRESETS,
    build_prompt_alias_map,
    get_latest_prompt_file,
)

router = APIRouter(tags=["conversations"])

# 共享 Service 实例（懒加载，避免模块导入时的网络相关 import 阻塞）
_conv_service = None
_export_service = ExportService()
_MAX_CONCURRENT_CONVERSATIONS = MAX_CONCURRENT_CONVERSATIONS
_queue_lock = asyncio.Lock()
_running_conversations: set[str] = set()
_queued_conversations: list[str] = []


def _get_conv_service():
    global _conv_service
    if _conv_service is None:
        _conv_service = ConversationService(ModelAdapter(), PromptService())
    return _conv_service


def _call_conv_service(method_name: str, fallback, *args, **kwargs):
    service = _get_conv_service()
    method = getattr(service, method_name, None)
    if callable(method):
        return method(*args, **kwargs)
    return fallback(*args, **kwargs)


def _load_conversation(conv_id: str) -> dict | None:
    return _call_conv_service("get_conversation", db.get_conversation, conv_id)


def _list_conversation_records(**filters) -> list[dict]:
    return _call_conv_service("list_conversations", db.list_conversations, **filters)


def _update_conversation_status(conv_id: str, status: str) -> None:
    _call_conv_service(
        "update_conversation_status",
        db.update_conversation_status,
        conv_id,
        status,
    )


def _update_conversation_config(conv_id: str, config: dict) -> bool:
    return _call_conv_service(
        "update_conversation_config",
        db.update_conversation_config,
        conv_id,
        config,
    )


def _create_conversation_record(
    *,
    model_id: str,
    config: dict,
    preset_id: str | None = None,
    model_mini: str | None = None,
    prompt_version: str = "",
) -> str:
    return _call_conv_service(
        "create_conversation",
        db.create_conversation,
        model_id=model_id,
        config=config,
        preset_id=preset_id,
        model_mini=model_mini,
        prompt_version=prompt_version,
    )


def _insert_turn_result(conv_id: str, turn_data: dict) -> int:
    return _call_conv_service(
        "insert_turn_result",
        db.insert_turn_result,
        conv_id,
        turn_data,
    )


def _delete_turn_result(conv_id: str, turn: int) -> int:
    return _call_conv_service(
        "delete_turn_result",
        db.delete_turn_result,
        conv_id,
        turn,
    )


def _delete_turn_results(conv_id: str) -> int:
    return _call_conv_service(
        "delete_turn_results",
        db.delete_turn_results,
        conv_id,
    )


def _update_turn_scores(conv_id: str, turn: int, scores: dict) -> None:
    _call_conv_service(
        "update_turn_scores",
        db.update_turn_scores,
        conv_id,
        turn,
        scores,
    )


def _delete_conversation_record(conv_id: str) -> bool:
    return _call_conv_service(
        "delete_conversation",
        db.delete_conversation,
        conv_id,
    )


def _set_conversation_pinned(conv_id: str, pinned: bool) -> bool:
    return _call_conv_service(
        "set_conversation_pinned",
        db.set_conversation_pinned,
        conv_id,
        pinned,
    )


def _infer_conversation_channel(config: dict | None, prompt_ref: str = "") -> str:
    return _call_conv_service(
        "infer_conversation_channel",
        db.infer_conversation_channel,
        config,
        prompt_ref,
    )


def _get_latest_conversation_channel(
    *,
    role_name: str = "",
    exclude_conv_id: str = "",
) -> str:
    return _call_conv_service(
        "get_latest_conversation_channel",
        db.get_latest_conversation_channel,
        role_name=role_name,
        exclude_conv_id=exclude_conv_id,
    )


def _get_visible_conversation_or_404(conv_id: str) -> dict:
    return ensure_visible_conversation(_load_conversation(conv_id), conv_id)


def _record_conversation_event(
    conv_id: str,
    event_type: str,
    *,
    scope: str = "generation",
    level: str = "info",
    detail: dict | None = None,
) -> None:
    try:
        db.log_conversation_event(
            conv_id,
            scope=scope,
            level=level,
            event_type=event_type,
            detail=detail or {},
        )
    except Exception as exc:
        print(f"[WARN] conversation event log failed: {conv_id} {event_type}: {exc}")


async def _push_generation_status(
    conv_id: str,
    status: str,
    *,
    event_type: str | None = None,
    message: str = "",
    **extra,
):
    payload = {
        "type": "task_status",
        "scope": "generation",
        "conversation_id": conv_id,
        "status": status,
        **extra,
    }
    if message:
        payload["message"] = message
    await _push_ws_message(conv_id, payload)
    if event_type:
        event_payload = {
            "type": event_type,
            "conversation_id": conv_id,
            **extra,
        }
        if message:
            event_payload["message"] = message
        await _push_ws_message(conv_id, event_payload)


async def _push_ws_message(conv_id: str, payload: dict):
    if conv_id not in _ws_connections:
        return
    message = json.dumps(payload, ensure_ascii=False, default=str)
    dead = []
    for ws in _ws_connections[conv_id]:
        try:
            await ws.send_text(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_connections[conv_id].remove(ws)
    if conv_id in _ws_connections and not _ws_connections[conv_id]:
        del _ws_connections[conv_id]


async def _broadcast_turn_result(conv_id: str, turn_data: dict) -> None:
    push_data = {
        key: value for key, value in (turn_data or {}).items()
        if key != "messages_snapshot"
    }
    for payload in (
        {"type": "turn_complete", "data": push_data},
        {**push_data, "type": "turn_result"},
    ):
        await _push_ws_message(conv_id, payload)


async def _maybe_enqueue_live_scoring(
    conv_id: str,
    turn: int,
    *,
    config: dict | None,
    dry_run: bool = False,
) -> bool:
    runtime = ((config or {}).get("runtime", {}) or {})
    if dry_run or not bool(runtime.get("auto_scoring", True)):
        return False
    from routers import scoring as scoring_router

    try:
        return await scoring_router.enqueue_live_score_turn(
            conv_id,
            turn,
            config=config,
        )
    except Exception as exc:
        print(f"[WARN] live scoring enqueue failed for {conv_id} turn {turn}: {exc}")
        return False


async def _reserve_conversation_slot(conv_id: str) -> tuple[str, int, bool]:
    async with _queue_lock:
        if conv_id in _running_conversations:
            return "running", 0, True
        if conv_id in _queued_conversations:
            return "queued", _queued_conversations.index(conv_id) + 1, True
        if len(_running_conversations) < _MAX_CONCURRENT_CONVERSATIONS and not _queued_conversations:
            _running_conversations.add(conv_id)
            return "pending", 0, False
        _queued_conversations.append(conv_id)
        return "queued", len(_queued_conversations), False


async def _wait_for_conversation_slot(conv_id: str) -> tuple[bool, int]:
    queued_notice_sent = False
    queue_position = 0
    while True:
        ctrl = task_control.get(conv_id)
        if ctrl and ctrl.is_cancelled:
            raise asyncio.CancelledError(f"对话任务已取消: {conv_id}")
        async with _queue_lock:
            if conv_id in _running_conversations:
                return queued_notice_sent, queue_position
            if (
                ctrl
                and ctrl.is_paused
                and conv_id in _queued_conversations
            ):
                queue_position = _queued_conversations.index(conv_id) + 1
            elif _queued_conversations and _queued_conversations[0] == conv_id and len(_running_conversations) < _MAX_CONCURRENT_CONVERSATIONS:
                _queued_conversations.pop(0)
                _running_conversations.add(conv_id)
                return True, 1 if queue_position == 0 else queue_position
            if conv_id in _queued_conversations:
                queue_position = _queued_conversations.index(conv_id) + 1
        if queue_position > 0 and not queued_notice_sent:
            await _push_generation_status(
                conv_id,
                "queued",
                event_type="queued",
                queue_position=queue_position,
                message=f"当前并发任务已满，已进入队列（前方 {queue_position - 1} 个）",
            )
            queued_notice_sent = True
        await asyncio.sleep(0.2)


async def _release_conversation_slot(conv_id: str):
    async with _queue_lock:
        _running_conversations.discard(conv_id)
        if _queued_conversations and len(_running_conversations) < _MAX_CONCURRENT_CONVERSATIONS:
            next_conv_id = _queued_conversations.pop(0)
            _running_conversations.add(next_conv_id)


def _resolve_requested_prompt(prompt_version: str) -> str:
    requested = (prompt_version or "").strip()
    if not requested:
        return ""

    lowered = requested.lower()
    if lowered in {"latest", "auto"}:
        return get_latest_prompt_file()

    alias_map = build_prompt_alias_map()
    normalized = alias_map.get(lowered, requested)

    try:
        PromptService().load_prompt_template(normalized)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"提示词版本不存在: {requested}",
        ) from exc
    return normalized


def _build_runtime_config(
    config: dict,
    model_id: str,
    model_mini: str,
    prompt_version: str = "",
    summary_prompt_version: str = "",
    scoring_prompt_version: str = "",
    scoring_model_id: str = "",
    profile_model_id: str = "",
    profile_prompt_version: str = "",
    summary_interval: int = DEFAULT_SUMMARY_INTERVAL,
    injection_depth: int = DEFAULT_INJECTION_DEPTH,
    temperature: float | None = None,
    top_p: float | None = None,
    thinking_enabled: bool | None = None,
    thinking_effort: str = "",
    scoring_thinking_enabled: bool | None = None,
    scoring_thinking_effort: str = "",
    scoring_max_workers: int | None = None,
    scoring_retry_count: int | None = None,
):
    model_id = ModelAdapter.normalize_model_id(model_id) or model_id
    model_mini = ModelAdapter.normalize_model_id(model_mini or DEFAULT_SUMMARY_MODEL)
    scoring_model_id = ModelAdapter.normalize_model_id(
        scoring_model_id or DEFAULT_SCORING_MODEL
    )
    profile_model_id = ModelAdapter.normalize_model_id(
        profile_model_id or DEFAULT_PROFILE_MODEL
    )
    requested_prompt = _resolve_requested_prompt(prompt_version)
    selected_prompt = requested_prompt or config.get("prompt_file") or get_latest_prompt_file()
    summary_store = VersionedPromptStore(kind="summary")
    scoring_store = VersionedPromptStore(kind="scoring")
    profile_store = VersionedPromptStore(kind="profile")
    resolved_summary_prompt = summary_store.resolve_filename(summary_prompt_version or "latest")
    resolved_scoring_prompt = scoring_store.resolve_filename(scoring_prompt_version or "latest")
    resolved_profile_prompt = profile_store.resolve_filename(profile_prompt_version or "latest")
    apply_runtime_defaults(
        config,
        model_id=model_id,
        model_mini=model_mini,
        summary_interval=summary_interval,
        injection_depth=injection_depth,
        temperature=temperature,
        top_p=top_p,
        prompt_file=selected_prompt,
        summary_prompt_version=resolved_summary_prompt,
        scoring_prompt_version=resolved_scoring_prompt,
        scoring_model_id=scoring_model_id,
        profile_model_id=profile_model_id,
        profile_prompt_version=resolved_profile_prompt,
        thinking_enabled=thinking_enabled,
        thinking_effort=thinking_effort,
        scoring_thinking_enabled=scoring_thinking_enabled,
        scoring_thinking_effort=scoring_thinking_effort,
        scoring_max_workers=scoring_max_workers,
        scoring_retry_count=scoring_retry_count,
    )
    return requested_prompt or prompt_version or config["prompt_file"], model_mini


def _merge_runtime_sampling_config(config: dict, *, temperature=None, top_p=None) -> dict:
    runtime = config.setdefault("runtime", {})
    if temperature is not None:
        runtime["temperature"] = float(temperature)
    if top_p is not None:
        runtime["top_p"] = float(top_p)
    return config


def _invoke_interactive_turn_generation(
    service,
    *,
    conv_id: str,
    conversation: dict,
    user_input: str,
    model_id: str,
    model_mini: str,
    dry_run: bool,
    web_search: bool,
    thinking_enabled: bool | None,
    thinking_effort: str,
    temperature: float | None,
    top_p: float | None,
):
    """按 service 实际签名做兼容调用，避免 mock/旧实现被新增参数打爆。"""
    method = service.generate_interactive_turn
    supported = inspect.signature(method).parameters
    kwargs = {}
    optional_args = {
        "model_id": model_id,
        "model_mini": model_mini,
        "dry_run": dry_run,
        "web_search": web_search,
        "thinking_enabled": thinking_enabled,
        "thinking_effort": thinking_effort,
        "temperature": temperature,
        "top_p": top_p,
    }
    for name, value in optional_args.items():
        if name in supported:
            kwargs[name] = value
    return method(conv_id, conversation, user_input, **kwargs)


def _format_last_conversation_type(channel: str) -> str:
    text = str(channel or "").strip()
    if not text:
        return ""
    return text if text.startswith("上一次在") else f"上一次在{text}"


def _apply_conversation_channel_context(
    config: dict,
    *,
    prompt_ref: str,
    exclude_conv_id: str = "",
) -> None:
    context = config.setdefault("context", {})
    runtime = config.setdefault("runtime", {})
    role_name = str(dict(config.get("character", {}) or {}).get("Role_Nickname", "")).strip()

    current_channel = _infer_conversation_channel(config, prompt_ref)
    if current_channel:
        runtime["conversation_channel"] = current_channel

    if is_public_demo_mode():
        return

    if not str(context.get("last_cst_type", "")).strip():
        previous_channel = _get_latest_conversation_channel(
            role_name=role_name,
            exclude_conv_id=exclude_conv_id,
        )
        context["last_cst_type"] = _format_last_conversation_type(previous_channel)


def _normalize_runtime_turns(turns: list[str] | None) -> list[str]:
    return [str(item) for item in (turns or [])]


def _prepare_batch_runtime(
    *,
    config: dict,
    turns: list[str],
    model_ids: list[str],
    compare_mode: str,
    model_id: str,
    dry_run: bool,
) -> tuple[dict, list[str]]:
    runtime = config.setdefault("runtime", {})
    normalized_turns = _normalize_runtime_turns(turns)
    runtime["conversation_mode"] = "batch"
    runtime["turns"] = normalized_turns
    runtime["total_turns"] = len(normalized_turns)
    runtime["next_turn_index"] = 0
    runtime["resume_supported"] = bool(normalized_turns)
    runtime["dry_run"] = bool(dry_run)
    runtime["model_ids"] = list(model_ids or [model_id])
    runtime["compare_mode"] = compare_mode or ""
    runtime["active_model_id"] = model_id
    return runtime, normalized_turns


def _read_batch_runtime_state(conversation: dict) -> tuple[dict, dict, list[str], int, int]:
    config = conversation.get("config", {})
    runtime = config.setdefault("runtime", {})
    stored_turns = runtime.get("turns")
    turns = _normalize_runtime_turns(stored_turns if isinstance(stored_turns, list) else [])
    total_turns = len(turns)
    runtime["total_turns"] = total_turns
    results_count = len(conversation.get("results", []))
    next_turn_index = max(int(runtime.get("next_turn_index", 0) or 0), results_count)
    next_turn_index = min(next_turn_index, total_turns)
    runtime["next_turn_index"] = next_turn_index
    runtime["resume_supported"] = bool(turns)
    return config, runtime, turns, total_turns, next_turn_index


def _persist_conversation_runtime(conv_id: str, config: dict, **runtime_fields):
    runtime = config.setdefault("runtime", {})
    for key, value in runtime_fields.items():
        runtime[key] = value
    _update_conversation_config(conv_id, config)
    return runtime


async def _start_conversation_run(
    *,
    conv_id: str,
    config: dict,
    turns: list[str],
    model_id: str,
    model_mini: str,
    summary_interval: int,
    dry_run: bool,
) -> tuple[str, int]:
    status, queue_position, already_scheduled = await _reserve_conversation_slot(conv_id)
    if status == "queued":
        _update_conversation_status(conv_id, "queued")
        _record_conversation_event(
            conv_id,
            "queued",
            detail={"queue_position": queue_position},
        )
    elif status == "pending":
        _update_conversation_status(conv_id, "pending")
    if not already_scheduled:
        task_control.remove(conv_id)
        task_control.get_or_create(conv_id)
        asyncio.create_task(
            _run_in_background(
                conv_id,
                config,
                turns,
                model_id,
                model_mini,
                summary_interval,
                dry_run,
            )
        )
    return status, queue_position


async def _schedule_conversation_run(
    *,
    config: dict,
    preset_ref: str | None,
    turns: list[str],
    model_id: str,
    model_ids: list[str],
    model_mini: str,
    prompt_version: str,
    summary_prompt_version: str,
    scoring_prompt_version: str,
    scoring_model_id: str | None,
    summary_interval: int,
    injection_depth: int,
    temperature: float | None,
    top_p: float | None,
    thinking_enabled: bool | None = None,
    thinking_effort: str = "",
    scoring_thinking_enabled: bool | None = None,
    scoring_thinking_effort: str = "",
    scoring_max_workers: int | None = None,
    scoring_retry_count: int | None = None,
    dry_run: bool,
    compare_mode: str,
) -> dict:
    requested_prompt, resolved_model_mini = _build_runtime_config(
        config=config,
        model_id=model_id,
        model_mini=model_mini,
        prompt_version=prompt_version,
        summary_prompt_version=summary_prompt_version or "",
        scoring_prompt_version=scoring_prompt_version or "",
        scoring_model_id=scoring_model_id or "",
        profile_model_id=config.get("runtime", {}).get("profile_model_id", ""),
        profile_prompt_version=config.get("runtime", {}).get("profile_prompt_version", ""),
        summary_interval=summary_interval,
        injection_depth=injection_depth,
        temperature=temperature,
        top_p=top_p,
        thinking_enabled=thinking_enabled,
        thinking_effort=thinking_effort,
        scoring_thinking_enabled=scoring_thinking_enabled,
        scoring_thinking_effort=scoring_thinking_effort,
        scoring_max_workers=scoring_max_workers,
        scoring_retry_count=scoring_retry_count,
    )
    _apply_conversation_channel_context(
        config,
        prompt_ref=requested_prompt or config.get("prompt_file", ""),
    )
    runtime, normalized_turns = _prepare_batch_runtime(
        config=config,
        turns=turns,
        model_ids=model_ids,
        compare_mode=compare_mode,
        model_id=model_id,
        dry_run=dry_run,
    )

    conv_id = _create_conversation_record(
        model_id=model_id,
        config=config,
        preset_id=preset_ref,
        model_mini=resolved_model_mini,
        prompt_version=requested_prompt,
    )
    status, queue_position = await _start_conversation_run(
        conv_id=conv_id,
        config=config,
        turns=normalized_turns,
        model_id=model_id,
        model_mini=resolved_model_mini,
        summary_interval=runtime["summary_interval"],
        dry_run=dry_run,
    )
    return {
        "id": conv_id,
        "model_id": model_id,
        "status": status,
        "queue_position": queue_position if status == "queued" else 0,
        "prompt_version": requested_prompt,
        "model_mini": resolved_model_mini,
    }


# WebSocket 连接管理
_ws_connections: dict[str, list[WebSocket]] = {}


@router.post("/api/conversations")
async def create_conversation(data: ConversationCreate):
    """创建对话任务"""
    # 构建配置
    preset_ref = None
    unique_model_ids = [m for m in dict.fromkeys(data.model_ids or []) if m]
    if not unique_model_ids and data.model_id:
        unique_model_ids = [data.model_id]
    if len(unique_model_ids) > MAX_COMPARE_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"model_ids 最多支持 {MAX_COMPARE_MODELS} 个模型",
        )
    if unique_model_ids:
        data.model_ids = unique_model_ids
        data.model_id = unique_model_ids[0]

    if data.preset_id and data.preset_id in PRESET_CHARACTERS:
        config = _get_conv_service().build_config_from_preset(data.preset_id)
    elif data.preset_id:
        preset = db.get_preset(data.preset_id)
        if not preset:
            raise HTTPException(
                status_code=404,
                detail=f"预设不存在: {data.preset_id}",
            )
        config = dict(preset.get("config", {}))
        preset_ref = data.preset_id
    elif data.character:
        config = {
            "character": data.character or {},
            "context": data.context or {},
            "modules": data.modules or {},
            "custom_variables": data.custom_variables or {},
        }
    else:
        raise HTTPException(
            status_code=400,
            detail="需要提供 preset_id 或 character 配置",
        )

    config["custom_variables"] = {
        **dict(config.get("custom_variables", {}) or {}),
        **dict(data.custom_variables or {}),
    }

    normalize_runtime_aliases(config)
    apply_runtime_temporal_defaults(config)
    apply_runtime_relationship_defaults(
        config,
        relationship_presets=RELATIONSHIP_PRESETS,
        prompt_service=PromptService(),
    )
    config.setdefault("runtime", {})["auto_scoring"] = bool(data.auto_scoring)

    if not data.turns:
        raise HTTPException(status_code=400, detail="turns 不能为空")

    if data.compare_mode == "model" and len(unique_model_ids) > 1:
        conversations = []
        for model_id in unique_model_ids:
            conversations.append(
                await _schedule_conversation_run(
                    config=deepcopy(config),
                    preset_ref=preset_ref,
                    turns=data.turns,
                    model_id=model_id,
                    model_ids=unique_model_ids,
                    model_mini=data.model_mini,
                    prompt_version=data.prompt_version or "",
                    summary_prompt_version=data.summary_prompt_version or "",
                    scoring_prompt_version=data.scoring_prompt_version or "",
                    scoring_model_id=data.scoring_model_id or "",
                    thinking_enabled=data.thinking_enabled,
                    thinking_effort=data.thinking_effort or "",
                    scoring_thinking_enabled=data.scoring_thinking_enabled,
                    scoring_thinking_effort=data.scoring_thinking_effort or "",
                    scoring_max_workers=data.scoring_max_workers,
                    scoring_retry_count=data.scoring_retry_count,
                    summary_interval=data.summary_interval,
                    injection_depth=data.injection_depth,
                    temperature=data.temperature,
                    top_p=data.top_p,
                    dry_run=data.dry_run,
                    compare_mode=data.compare_mode or "",
                )
            )
        overall_status = "queued" if any(item["status"] == "queued" for item in conversations) else "pending"
        return {
            "id": conversations[0]["id"],
            "status": overall_status,
            "turns_count": len(data.turns),
            "queue_position": min(
                [item["queue_position"] for item in conversations if item["queue_position"] > 0] or [0]
            ),
            "compare_mode": data.compare_mode or "",
            "conversation_ids": [item["id"] for item in conversations],
            "conversations": conversations,
        }

    conversation = await _schedule_conversation_run(
        config=config,
        preset_ref=preset_ref,
        turns=data.turns,
        model_id=data.model_id,
        model_ids=list(data.model_ids or [data.model_id]),
        model_mini=data.model_mini,
        prompt_version=data.prompt_version or "",
        summary_prompt_version=data.summary_prompt_version or "",
        scoring_prompt_version=data.scoring_prompt_version or "",
        scoring_model_id=data.scoring_model_id or "",
        thinking_enabled=data.thinking_enabled,
        thinking_effort=data.thinking_effort or "",
        scoring_thinking_enabled=data.scoring_thinking_enabled,
        scoring_thinking_effort=data.scoring_thinking_effort or "",
        scoring_max_workers=data.scoring_max_workers,
        scoring_retry_count=data.scoring_retry_count,
        summary_interval=data.summary_interval,
        injection_depth=data.injection_depth,
        temperature=data.temperature,
        top_p=data.top_p,
        dry_run=data.dry_run,
        compare_mode=data.compare_mode or "",
    )

    return {
        "id": conversation["id"],
        "status": conversation["status"],
        "turns_count": len(data.turns),
        "queue_position": conversation["queue_position"],
        "compare_mode": data.compare_mode or "",
    }


@router.post("/api/conversations/interactive")
async def create_interactive_conversation(data: InteractiveConversationCreate):
    """创建交互式聊天会话，仅建立会话壳，不批量执行 turns。"""
    config = {
        "character": data.character or {},
        "context": data.context or {},
        "modules": data.modules or {},
        "custom_variables": data.custom_variables or {},
    }
    normalize_runtime_aliases(config)
    apply_runtime_temporal_defaults(config)
    apply_runtime_relationship_defaults(
        config,
        relationship_presets=RELATIONSHIP_PRESETS,
        prompt_service=PromptService(),
    )
    requested_prompt, model_mini = _build_runtime_config(
        config=config,
        model_id=data.model_id,
        model_mini=data.model_mini,
        prompt_version=data.prompt_version,
        summary_prompt_version=data.summary_prompt_version or "",
        scoring_prompt_version=data.scoring_prompt_version or "",
        scoring_model_id=data.scoring_model_id or "",
        profile_model_id=data.profile_model_id or "",
        profile_prompt_version=data.profile_prompt_version or "",
        thinking_enabled=data.thinking_enabled,
        thinking_effort=data.thinking_effort or "",
        scoring_thinking_enabled=data.scoring_thinking_enabled,
        scoring_thinking_effort=data.scoring_thinking_effort or "",
        scoring_max_workers=data.scoring_max_workers,
        scoring_retry_count=data.scoring_retry_count,
        summary_interval=data.summary_interval,
        injection_depth=data.injection_depth,
        temperature=data.temperature,
        top_p=data.top_p,
    )
    _apply_conversation_channel_context(
        config,
        prompt_ref=requested_prompt or config.get("prompt_file", ""),
    )
    runtime = config.setdefault("runtime", {})
    runtime["conversation_mode"] = "interactive"
    runtime["model_ids"] = [data.model_id]
    runtime["compare_mode"] = ""
    runtime["active_model_id"] = data.model_id
    runtime["auto_scoring"] = bool(data.auto_scoring)
    if data.ab_session_id:
        runtime["ab_session_id"] = str(data.ab_session_id).strip()
    if data.ab_variant:
        runtime["ab_variant"] = str(data.ab_variant).strip()
    conv_id = _create_conversation_record(
        model_id=data.model_id,
        config=config,
        model_mini=model_mini,
        prompt_version=requested_prompt,
    )
    _update_conversation_status(conv_id, "running")
    return {"id": conv_id, "status": "running"}


@router.post("/api/conversations/{conv_id}/turns")
async def append_interactive_turn(conv_id: str, data: InteractiveTurnCreate):
    """向交互式聊天会话追加一轮结果，并尝试自动评分。"""
    conversation = _get_visible_conversation_or_404(conv_id)

    next_turn = len(conversation.get("results", [])) + 1
    ai_output = data.ai_output or ""
    turn_data = {
        "turn": next_turn,
        "user_input": data.user_input,
        "ai_output": ai_output,
        "word_count": data.word_count or len(ai_output),
        "dialogue_summary": data.dialogue_summary,
        "msg_count": data.msg_count or len(data.messages_snapshot or []),
        "input_tokens": data.input_tokens,
        "output_tokens": data.output_tokens,
        "latency_s": data.latency_s,
        "has_deep_injection": data.has_deep_injection,
        "has_style_isolation": data.has_style_isolation,
        "has_cooldown_reinject": data.has_cooldown_reinject,
        "token_trim_level": data.token_trim_level,
        "quality_retries": data.quality_retries,
        "messages_snapshot": data.messages_snapshot,
        "request_payload_snapshot": data.request_payload_snapshot,
        "model_id": data.model_id or conversation.get("model_id", ""),
    }
    _insert_turn_result(conv_id, turn_data)
    _update_conversation_status(conv_id, "running")
    return {
        "id": conv_id,
        "turn": next_turn,
        "score_status": "unscored",
    }


@router.post("/api/conversations/{conv_id}/generate")
async def generate_interactive_turn(conv_id: str, data: InteractiveGenerateRequest):
    """按当前会话配置生成一轮交互式回复，并保存真实消息拼接快照。"""
    conversation = _get_visible_conversation_or_404(conv_id)

    user_input = (data.user_input or "").strip()
    if not user_input:
        raise HTTPException(status_code=400, detail="user_input 不能为空")

    config = dict(conversation.get("config", {}) or {})
    _merge_runtime_sampling_config(
        config,
        temperature=data.temperature,
        top_p=data.top_p,
    )
    if config != conversation.get("config", {}):
        _update_conversation_config(conv_id, config)
        conversation = {**conversation, "config": config}

    try:
        service = _get_conv_service()
        turn_data = await asyncio.to_thread(
            _invoke_interactive_turn_generation,
            service,
            conv_id=conv_id,
            conversation=conversation,
            user_input=user_input,
            model_id=data.model_id or conversation.get("model_id", ""),
            model_mini=conversation.get("model_mini", ""),
            dry_run=False,
            web_search=data.web_search,
            thinking_enabled=data.thinking_enabled,
            thinking_effort=data.thinking_effort,
            temperature=data.temperature,
            top_p=data.top_p,
        )
    except Exception as exc:
        _update_conversation_status(conv_id, "failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    _update_conversation_status(conv_id, "running")
    await _broadcast_turn_result(conv_id, turn_data)
    await _maybe_enqueue_live_scoring(
        conv_id,
        int(turn_data.get("turn", 0) or 0),
        config=config,
        dry_run=False,
    )
    return {"id": conv_id, "success": True, **turn_data}


@router.post("/api/conversations/{conv_id}/turns/{turn}/regenerate")
async def regenerate_interactive_turn(
    conv_id: str,
    turn: int,
    data: InteractiveRegenerateRequest,
):
    """删除最后一轮并按同一用户输入重新生成，避免伪“追加一轮”。"""
    conversation = _get_visible_conversation_or_404(conv_id)

    results = conversation.get("results", [])
    if not results:
        raise HTTPException(status_code=400, detail="当前会话暂无可重生成轮次")

    latest_turn = results[-1]
    latest_turn_num = int(latest_turn.get("turn", 0))
    if turn != latest_turn_num:
        raise HTTPException(
            status_code=400,
            detail="仅支持重生成最后一轮，避免破坏后续上下文",
        )

    user_input = str(latest_turn.get("user_input", "")).strip()
    if not user_input:
        raise HTTPException(status_code=400, detail="最后一轮缺少 user_input，无法重生成")

    deleted = _delete_turn_result(conv_id, turn)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"轮次不存在: {turn}")

    refreshed = _get_visible_conversation_or_404(conv_id)
    refreshed_config = dict(refreshed.get("config", {}) or {})
    _merge_runtime_sampling_config(
        refreshed_config,
        temperature=data.temperature,
        top_p=data.top_p,
    )
    if refreshed_config != refreshed.get("config", {}):
        _update_conversation_config(conv_id, refreshed_config)
        refreshed = {**refreshed, "config": refreshed_config}
    try:
        service = _get_conv_service()
        turn_data = await asyncio.to_thread(
            _invoke_interactive_turn_generation,
            service,
            conv_id=conv_id,
            conversation=refreshed,
            user_input=user_input,
            model_id=data.model_id or conversation.get("model_id", ""),
            model_mini=conversation.get("model_mini", ""),
            dry_run=False,
            web_search=data.web_search,
            thinking_enabled=data.thinking_enabled,
            thinking_effort=data.thinking_effort,
            temperature=data.temperature,
            top_p=data.top_p,
        )
    except Exception as exc:
        _update_conversation_status(conv_id, "failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    _update_conversation_status(conv_id, "running")
    await _broadcast_turn_result(conv_id, turn_data)
    await _maybe_enqueue_live_scoring(
        conv_id,
        int(turn_data.get("turn", 0) or 0),
        config=refreshed.get("config", {}),
        dry_run=False,
    )
    return {
        "id": conv_id,
        "success": True,
        "regenerated_from_turn": turn,
        **turn_data,
    }


@router.post("/api/conversations/{conv_id}/turns/{turn}/scores")
async def save_interactive_turn_score(
    conv_id: str,
    turn: int,
    data: InteractiveTurnScoreCreate,
):
    """回写交互式聊天单轮评分结果。"""
    conversation = _get_visible_conversation_or_404(conv_id)
    target = next((item for item in conversation.get("results", []) if item.get("turn") == turn), None)
    if not target:
        raise HTTPException(status_code=404, detail=f"轮次不存在: {turn}")
    _update_turn_scores(
        conv_id,
        turn,
        {
            **(data.scores or {}),
            "mapped_total": data.mapped_total,
            "reasoning": data.reasoning,
            "success": data.success,
        },
    )
    return {"id": conv_id, "turn": turn, "score_status": "scored" if data.success else "failed"}


@router.delete("/api/conversations/{conv_id}/turns")
async def clear_conversation_turns(conv_id: str):
    """清空会话内的所有轮次结果，但保留会话配置。"""
    conversation = _get_visible_conversation_or_404(conv_id)
    deleted = _delete_turn_results(conv_id)
    config = conversation.get("config", {})
    runtime = config.setdefault("runtime", {})
    if runtime.get("conversation_mode") == "batch" and isinstance(runtime.get("turns"), list):
        runtime["next_turn_index"] = 0
        runtime["total_turns"] = len(runtime.get("turns", []))
        runtime["resume_supported"] = bool(runtime.get("turns"))
        _update_conversation_config(conv_id, config)
    _update_conversation_status(conv_id, "pending")
    return {"id": conv_id, "deleted_turns": deleted, "status": "pending"}


@router.post("/api/conversations/{conv_id}/complete")
async def complete_conversation(conv_id: str):
    """标记交互式聊天会话完成。"""
    _get_visible_conversation_or_404(conv_id)
    _update_conversation_status(conv_id, "completed")
    return {"id": conv_id, "status": "completed"}


@router.post("/api/conversations/{conv_id}/resume")
async def resume_conversation(conv_id: str):
    """恢复被中断的批量任务，只续跑剩余轮次。"""
    conversation = _get_visible_conversation_or_404(conv_id)

    config, runtime, turns, total_turns, next_turn_index = _read_batch_runtime_state(conversation)
    if runtime.get("conversation_mode") != "batch" or not turns:
        raise HTTPException(status_code=400, detail="当前会话不支持恢复")
    if conversation.get("status") in {"running", "queued"}:
        queue_position = 0
        if conversation.get("status") == "queued":
            async with _queue_lock:
                queue_position = (
                    _queued_conversations.index(conv_id) + 1
                    if conv_id in _queued_conversations
                    else 1
                )
        return {
            "id": conv_id,
            "status": conversation.get("status"),
            "queue_position": queue_position,
            "turns_count": total_turns,
            "compare_mode": runtime.get("compare_mode", ""),
        }
    if next_turn_index >= total_turns:
        raise HTTPException(status_code=400, detail="当前会话已完成，无需恢复")

    _persist_conversation_runtime(
        conv_id,
        config,
        total_turns=total_turns,
        next_turn_index=next_turn_index,
        resume_supported=True,
    )
    remaining_turns = turns[next_turn_index:]
    status, queue_position = await _start_conversation_run(
        conv_id=conv_id,
        config=config,
        turns=remaining_turns,
        model_id=runtime.get("active_model_id") or conversation.get("model_id", ""),
        model_mini=conversation.get("model_mini", ""),
        summary_interval=runtime.get("summary_interval", DEFAULT_SUMMARY_INTERVAL),
        dry_run=bool(runtime.get("dry_run", False)),
    )
    return {
        "id": conv_id,
        "status": status,
        "queue_position": queue_position if status == "queued" else 0,
        "turns_count": total_turns,
        "compare_mode": runtime.get("compare_mode", ""),
    }


async def _run_in_background(
    conv_id: str, config: dict, turns: list[str],
    model_id: str, model_mini: str, summary_interval: int, dry_run: bool,
):
    """后台执行对话链并推送结果"""
    total_turns = int(config.get("runtime", {}).get("total_turns", len(turns)) or len(turns))
    ctrl = task_control.get_or_create(conv_id)

    async def on_turn_start(turn_num: int, total: int, user_input: str):
        """推送轮次开始事件，让前端知道当前在跑第几轮。"""
        if conv_id in _ws_connections:
            payload = {
                "type": "turn_started",
                "conversation_id": conv_id,
                "turn": turn_num,
                "total_turns": total,
                "user_input_preview": (user_input or "")[:80],
            }
            dead = []
            for ws in _ws_connections[conv_id]:
                try:
                    await ws.send_text(
                        json.dumps(payload, ensure_ascii=False, default=str)
                    )
                except Exception:
                    dead.append(ws)
            for ws in dead:
                _ws_connections[conv_id].remove(ws)

    async def on_turn(turn_data: dict):
        try:
            _persist_conversation_runtime(
                conv_id,
                config,
                next_turn_index=int(turn_data.get("turn", 0) or 0),
                total_turns=total_turns,
                resume_supported=bool(total_turns),
            )
            await _broadcast_turn_result(conv_id, turn_data)
            await _maybe_enqueue_live_scoring(
                conv_id,
                int(turn_data.get("turn", 0) or 0),
                config=config,
                dry_run=dry_run,
            )
        except Exception as exc:
            print(f"[WARN] on_turn callback error for {conv_id}: {exc}")

    try:
        queued_notice_sent, queue_position = await _wait_for_conversation_slot(conv_id)
        _update_conversation_status(conv_id, "running")
        _record_conversation_event(
            conv_id,
            "started",
            detail={"queue_position": queue_position, "total_turns": total_turns},
        )
        await _push_generation_status(
            conv_id,
            "running",
            event_type="started",
            queue_position=queue_position if queued_notice_sent else 0,
            message="排队结束，任务开始执行" if queued_notice_sent else "任务开始执行",
        )
        await _get_conv_service().run_conversation(
            conv_id=conv_id,
            config=config,
            turns=turns,
            model_id=model_id,
            model_mini=model_mini,
            summary_interval=summary_interval,
            dry_run=dry_run,
            on_turn_complete=on_turn,
            on_turn_start=on_turn_start,
        )
        _persist_conversation_runtime(
            conv_id,
            config,
            next_turn_index=total_turns,
            total_turns=total_turns,
            resume_supported=bool(total_turns),
        )
        ctrl.complete()
        _record_conversation_event(
            conv_id,
            "completed",
            detail={"completed_turns": total_turns, "total_turns": total_turns},
        )
        await _push_generation_status(
            conv_id,
            "completed",
            event_type="completed",
        )
    except asyncio.CancelledError:
        _update_conversation_status(conv_id, "cancelled")
        _record_conversation_event(conv_id, "cancelled")
        await _push_generation_status(
            conv_id,
            "cancelled",
            event_type="cancelled",
            message="任务已取消",
        )
    except Exception as e:
        import traceback
        print(f"[ERROR] 对话 {conv_id} 执行失败: {e}")
        traceback.print_exc()
        _update_conversation_status(conv_id, "failed")
        _record_conversation_event(
            conv_id,
            "failed",
            level="error",
            detail={"error": str(e)},
        )
        await _push_generation_status(
            conv_id,
            "failed",
            event_type="error",
            error=str(e),
        )
    finally:
        task_control.remove(conv_id)
        await _release_conversation_slot(conv_id)


async def reconcile_conversation_runtime_state():
    """服务启动时收敛上次异常退出留下的会话状态。"""
    async with _queue_lock:
        _running_conversations.clear()
        _queued_conversations.clear()

    for item in _list_conversation_records():
        status = item.get("status")
        if status not in {"running", "queued", "paused"}:
            continue
        conversation = _load_conversation(item.get("id", ""))
        if not conversation:
            continue
        _reconcile_stale_conversation_status(conversation["id"], conversation)


@router.get("/api/conversations")
async def list_conversations(
    model_id: str = Query(default=""),
    date_from: str = Query(default=""),
    date_to: str = Query(default=""),
    status: str = Query(default=""),
    min_score: float | None = Query(default=None),
    max_score: float | None = Query(default=None),
    archived: bool | None = Query(default=None),
    include_archived: bool = Query(default=False),
):
    """获取对话列表"""
    return {
        "conversations": filter_visible_conversations(
            _list_conversation_records(
                model_id=model_id,
                date_from=date_from,
                date_to=date_to,
                status=status,
                min_score=min_score,
                max_score=max_score,
                archived=archived,
                include_archived=include_archived,
            )
        )
    }


@router.get("/api/conversations/{conv_id}")
async def get_conversation(conv_id: str):
    """获取对话详情（含所有轮次结果）"""
    conv = _get_visible_conversation_or_404(conv_id)
    runtime = conv.get("config", {}).get("runtime", {})
    if runtime:
        conv["summary_interval"] = runtime.get(
            "summary_interval",
            DEFAULT_SUMMARY_INTERVAL,
        )
        conv["model_ids"] = runtime.get("model_ids", [conv.get("model_id")])
        conv["compare_mode"] = runtime.get("compare_mode", "")
        conv["summary_prompt_version"] = runtime.get("summary_prompt_version", "")
        conv["scoring_prompt_version"] = runtime.get("scoring_prompt_version", "")
        conv["scoring_model_id"] = runtime.get("scoring_model_id", DEFAULT_SCORING_MODEL)
        conv["total_turns"] = runtime.get("total_turns", len(conv.get("results", [])))
        conv["next_turn_index"] = runtime.get("next_turn_index", len(conv.get("results", [])))
        conv["resume_supported"] = bool(runtime.get("resume_supported"))
    return conv


@router.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: str):
    """删除对话"""
    _get_visible_conversation_or_404(conv_id)
    if not _delete_conversation_record(conv_id):
        raise HTTPException(status_code=404, detail=f"对话不存在: {conv_id}")
    return {"message": "已删除"}


@router.put("/api/conversations/{conv_id}/pin")
async def pin_conversation(conv_id: str, pinned: bool = True):
    """置顶/取消置顶对话"""
    _get_visible_conversation_or_404(conv_id)
    if not _set_conversation_pinned(conv_id, pinned):
        raise HTTPException(status_code=404, detail=f"对话不存在: {conv_id}")
    return {"message": "已更新置顶状态", "pinned": pinned}


@router.post("/api/conversations/{conv_id}/control")
async def control_conversation(conv_id: str, data: TaskControlRequest = Body(...)):
    conversation = _get_visible_conversation_or_404(conv_id)
    ctrl = task_control.get(conv_id)
    if ctrl is None:
        raise HTTPException(status_code=400, detail="当前会话没有可控制的运行任务")
    from routers import scoring as scoring_router

    live_dispatcher = scoring_router.get_live_scoring_dispatcher()

    action = data.action
    if action == "pause":
        ctrl.pause()
        await live_dispatcher.pause_conversation(conv_id)
        _update_conversation_status(conv_id, "paused")
        _record_conversation_event(conv_id, "paused")
        await _push_generation_status(
            conv_id,
            "paused",
            event_type="paused",
            message="任务已暂停",
        )
        return {"id": conv_id, "status": "paused"}

    if action == "resume":
        ctrl.resume()
        await live_dispatcher.resume_conversation(conv_id)
        async with _queue_lock:
            resumed_status = "running" if conv_id in _running_conversations else "queued"
        _update_conversation_status(conv_id, resumed_status)
        _record_conversation_event(conv_id, "resumed", detail={"status": resumed_status})
        await _push_generation_status(
            conv_id,
            resumed_status,
            event_type="resumed",
            message="任务已恢复" if resumed_status == "running" else "任务已恢复排队",
        )
        return {"id": conv_id, "status": resumed_status}

    ctrl.cancel()
    await live_dispatcher.cancel_conversation(conv_id)
    async with _queue_lock:
        if conv_id in _queued_conversations:
            _queued_conversations.remove(conv_id)
    _record_conversation_event(
        conv_id,
        "cancel_requested",
        detail={"from_status": conversation.get("status", "")},
    )
    return {"id": conv_id, "status": "cancelling"}


@router.put("/api/conversations/{conv_id}/archive")
async def archive_conversation(conv_id: str, archived: bool = Query(default=True)):
    _get_visible_conversation_or_404(conv_id)
    if not db.set_conversation_archived(conv_id, archived):
        raise HTTPException(status_code=404, detail=f"对话不存在: {conv_id}")
    _record_conversation_event(
        conv_id,
        "archived" if archived else "unarchived",
        detail={"archived": bool(archived)},
    )
    return {"id": conv_id, "archived": bool(archived)}


@router.get("/api/conversations/{conv_id}/events")
async def get_conversation_events(
    conv_id: str,
    scope: str = Query(default=""),
    level: str = Query(default=""),
):
    _get_visible_conversation_or_404(conv_id)
    return {"events": db.get_conversation_events(conv_id, scope=scope, level=level)}


def _reconcile_stale_conversation_status(conv_id: str, conversation: dict) -> dict:
    config, runtime, turns, total_turns, next_turn_index = _read_batch_runtime_state(conversation)
    results_count = len(conversation.get("results", []))
    previous_status = str(conversation.get("status", "pending") or "pending")
    status = previous_status
    if turns:
        _persist_conversation_runtime(
            conv_id,
            config,
            total_turns=total_turns,
            next_turn_index=next_turn_index,
            resume_supported=True,
        )
        status = "completed" if next_turn_index >= total_turns else "interrupted"
    elif results_count == 0:
        status = "pending"
    _update_conversation_status(conv_id, status)
    if status == "interrupted" and previous_status != "interrupted":
        _record_conversation_event(
            conv_id,
            "interrupted",
            level="warn",
            detail={
                "reason": "service_restart_recovery",
                "previous_status": previous_status,
                "completed_turns": next_turn_index,
                "total_turns": total_turns,
            },
        )
    refreshed = _load_conversation(conv_id) or conversation
    refreshed["status"] = status
    return refreshed


@router.get("/api/conversations/{conv_id}/export")
async def export_conversation_alias(conv_id: str):
    """兼容 PRD 路径：导出对话结果 Excel"""
    from config import PROJECT_DIR

    conv = _get_visible_conversation_or_404(conv_id)

    results = conv.get("results", [])
    if not results:
        raise HTTPException(status_code=400, detail="对话无结果数据")

    output_dir = PROJECT_DIR / "output"
    output_dir.mkdir(exist_ok=True)
    role_name = conv.get("config", {}).get("character", {}).get("Role_Nickname", "unknown")
    safe_name = _export_service.safe_filename_part(role_name, fallback="conversation")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    # P2: 根据实际打分状态决定文件名后缀
    scored_count = sum(1 for r in results if r.get("score_status") == "scored")
    suffix = "已打分" if scored_count > 0 else "待打分"
    filename = f"{safe_name}_{ts}_{suffix}.xlsx"
    output_path = output_dir / filename

    _export_service.export_to_excel(results, conv.get("config", {}), str(output_path))
    return FileResponse(
        path=str(output_path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.websocket("/ws/conversations/{conv_id}")
async def websocket_conversation(websocket: WebSocket, conv_id: str):
    """WebSocket：实时接收对话轮次结果"""
    await websocket.accept()

    # 注册连接
    if conv_id not in _ws_connections:
        _ws_connections[conv_id] = []
    _ws_connections[conv_id].append(websocket)

    try:
        conversation = _get_visible_conversation_or_404(conv_id)
        if conversation:
            status = conversation.get("status")
            for turn in conversation.get("results", []):
                push_data = {
                    k: v for k, v in turn.items() if k != "messages_snapshot"
                }
                for payload in (
                    {"type": "turn_complete", "data": push_data},
                    {**push_data, "type": "turn_result"},
                ):
                    await websocket.send_text(
                        json.dumps(payload, ensure_ascii=False, default=str)
                    )
            if status == "queued":
                async with _queue_lock:
                    queue_position = (
                        _queued_conversations.index(conv_id) + 1
                        if conv_id in _queued_conversations
                        else 1
                    )
                for payload in (
                    {
                        "type": "queued",
                        "conversation_id": conv_id,
                        "queue_position": queue_position,
                        "message": f"当前并发任务已满，已进入队列（前方 {queue_position - 1} 个）",
                    },
                    {
                        "type": "task_status",
                        "scope": "generation",
                        "conversation_id": conv_id,
                        "status": "queued",
                        "queue_position": queue_position,
                    },
                ):
                    await websocket.send_text(json.dumps(payload, ensure_ascii=False))
            else:
                if status == "running":
                    for payload in (
                        {
                            "type": "started",
                            "conversation_id": conv_id,
                            "message": "任务正在执行",
                        },
                        {
                            "type": "task_status",
                            "scope": "generation",
                            "conversation_id": conv_id,
                            "status": "running",
                        },
                    ):
                        await websocket.send_text(json.dumps(payload, ensure_ascii=False))
                elif status == "paused":
                    for payload in (
                        {
                            "type": "paused",
                            "conversation_id": conv_id,
                            "message": "任务已暂停",
                        },
                        {
                            "type": "task_status",
                            "scope": "generation",
                            "conversation_id": conv_id,
                            "status": "paused",
                        },
                    ):
                        await websocket.send_text(json.dumps(payload, ensure_ascii=False))
                elif status == "cancelled":
                    for payload in (
                        {
                            "type": "cancelled",
                            "conversation_id": conv_id,
                            "message": "任务已取消",
                        },
                        {
                            "type": "task_status",
                            "scope": "generation",
                            "conversation_id": conv_id,
                            "status": "cancelled",
                        },
                    ):
                        await websocket.send_text(json.dumps(payload, ensure_ascii=False))
                elif status == "completed":
                    for payload in (
                        {"type": "completed", "conversation_id": conv_id},
                        {
                            "type": "task_status",
                            "scope": "generation",
                            "conversation_id": conv_id,
                            "status": "completed",
                        },
                    ):
                        await websocket.send_text(json.dumps(payload, ensure_ascii=False))
                elif status == "failed":
                    for payload in (
                        {
                            "type": "error",
                            "conversation_id": conv_id,
                            "error": "任务执行失败",
                        },
                        {
                            "type": "task_status",
                            "scope": "generation",
                            "conversation_id": conv_id,
                            "status": "failed",
                        },
                    ):
                        await websocket.send_text(json.dumps(payload, ensure_ascii=False))
        # 保持连接直到客户端断开
        while True:
            data = await websocket.receive_text()
            # 可接收客户端控制指令（如暂停/取消）
            try:
                cmd = json.loads(data)
                if cmd.get("action") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        if conv_id in _ws_connections:
            _ws_connections[conv_id].remove(websocket)
            if not _ws_connections[conv_id]:
                del _ws_connections[conv_id]
