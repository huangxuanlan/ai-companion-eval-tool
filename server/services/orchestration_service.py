from __future__ import annotations

import asyncio
from copy import deepcopy

import database as db
from models import ConversationCreate, OrchestrationRunCreate, TaskControlRequest
from routers import conversations as conversations_router
from services import task_control


ACTIVE_RUN_STATUSES = {"pending", "queued", "running", "paused", "interrupted", "cancelling"}
ACTIVE_CONVERSATION_STATUSES = {"queued", "running", "paused"}
GENERATION_ACTIVE_ITEM_STATUSES = ACTIVE_CONVERSATION_STATUSES | {"cancelling"}
ACTIVE_ORCHESTRATION_ITEM_STATUSES = GENERATION_ACTIVE_ITEM_STATUSES | {"scoring"}
RESUMABLE_CONVERSATION_STATUSES = {"interrupted", "cancelled"}
TERMINAL_ITEM_STATUSES = {"completed", "failed", "cancelled"}
RUNNER_PREFIX = "orchestration:"

_runner_tasks: dict[str, asyncio.Task] = {}


def _runner_task_id(run_id: str) -> str:
    return f"{RUNNER_PREFIX}{run_id}"


def _compute_turn_metrics(conversation: dict | None) -> dict:
    results = list((conversation or {}).get("results", []) or [])
    turn_count = len(results)
    char_lengths = [
        len(str(item.get("ai_output", "") or "").strip())
        for item in results
        if str(item.get("ai_output", "") or "").strip()
    ]
    avg_chars = round(sum(char_lengths) / len(char_lengths)) if char_lengths else 0
    return {
        "turn_count": turn_count,
        "avg_chars": avg_chars,
        "avg_score": conversation.get("score_avg") if conversation else None,
        "scored_turns": int((conversation or {}).get("scored_turns") or 0),
        "failed_turns": int((conversation or {}).get("failed_turns") or 0),
        "skipped_turns": int((conversation or {}).get("skipped_turns") or 0),
        "updated_at": (conversation or {}).get("updated_at") or (conversation or {}).get("created_at"),
    }


def _get_generation_progress(conversation: dict | None, *, planned_turns: int = 0) -> tuple[int, int]:
    conversation = conversation or {}
    runtime = ((conversation.get("config", {}) or {}).get("runtime", {}) or {})
    results_count = len(list(conversation.get("results", []) or []))
    total_turns = int(runtime.get("total_turns") or planned_turns or results_count or 0)
    total_turns = max(total_turns, planned_turns, results_count)
    next_turn_index = int(runtime.get("next_turn_index") or results_count or 0)
    next_turn_index = max(next_turn_index, results_count)
    if total_turns > 0:
        next_turn_index = min(next_turn_index, total_turns)
    return next_turn_index, total_turns


def _has_pending_auto_scoring(
    conversation: dict | None,
    *,
    metrics: dict | None = None,
    planned_turns: int = 0,
    auto_scoring_enabled: bool = False,
) -> bool:
    if not auto_scoring_enabled or not conversation:
        return False
    metrics = metrics or _compute_turn_metrics(conversation)
    turn_count = int(metrics.get("turn_count", 0) or 0)
    if turn_count <= 0:
        return False
    settled_score_turns = (
        int(metrics.get("scored_turns", 0) or 0)
        + int(metrics.get("failed_turns", 0) or 0)
        + int(metrics.get("skipped_turns", 0) or 0)
    )
    return settled_score_turns < turn_count


def _is_auto_scoring_enabled(
    *,
    payload: dict | None = None,
    conversation: dict | None = None,
) -> bool:
    payload = payload or {}
    if not bool(payload.get("auto_scoring")):
        return False
    if bool(payload.get("dry_run")):
        return False
    runtime = ((conversation or {}).get("config", {}) or {}).get("runtime", {}) or {}
    if bool(runtime.get("dry_run", False)):
        return False
    return True


def _make_item_key(group_key: str, item_index: int, fallback: str = "") -> str:
    explicit = str(fallback or "").strip()
    if explicit:
        return explicit
    return f"{group_key or 'group'}:item:{item_index + 1}"


def _make_group_key(group_index: int, fallback: str = "") -> str:
    explicit = str(fallback or "").strip()
    if explicit:
        return explicit
    return f"group:{group_index + 1}"


def _build_initial_run_payload(data: OrchestrationRunCreate) -> tuple[dict, dict]:
    manifest_groups = []
    state_groups = []
    for group_index, group in enumerate(data.groups):
        group_key = _make_group_key(group_index, group.key)
        manifest_items = []
        state_items = []
        for item_index, item in enumerate(group.items):
            item_key = _make_item_key(group_key, item_index, item.key)
            manifest_items.append(
                {
                    "key": item_key,
                    "label": str(item.label or "").strip(),
                    "relationship": str(item.relationship or group.relationship or "").strip(),
                    "model_id": str(item.model_id or "").strip(),
                    "planned_turns": int(item.planned_turns or group.planned_turns or 0),
                    "payload": deepcopy(item.payload or {}),
                }
            )
            state_items.append(
                {
                    "key": item_key,
                    "label": str(item.label or "").strip(),
                    "relationship": str(item.relationship or group.relationship or "").strip(),
                    "model_id": str(item.model_id or "").strip(),
                    "planned_turns": int(item.planned_turns or group.planned_turns or 0),
                    "conversation_id": "",
                    "status": "pending",
                    "turn_count": 0,
                    "avg_chars": 0,
                    "avg_score": None,
                    "resume_supported": False,
                    "error": "",
                }
            )
        manifest_groups.append(
            {
                "key": group_key,
                "label": str(group.label or "").strip(),
                "relationship": str(group.relationship or "").strip(),
                "planned_turns": int(group.planned_turns or 0),
                "items": manifest_items,
            }
        )
        state_groups.append(
            {
                "key": group_key,
                "label": str(group.label or "").strip(),
                "relationship": str(group.relationship or "").strip(),
                "planned_turns": int(group.planned_turns or 0),
                "status": "pending",
                "items": state_items,
            }
        )
    manifest = {
        "kind": data.kind,
        "title": str(data.title or "").strip(),
        "concurrency": int(data.concurrency or 1),
        "config_snapshot": deepcopy(data.config_snapshot or {}),
        "groups": manifest_groups,
    }
    state = {
        "kind": data.kind,
        "title": str(data.title or "").strip(),
        "groups": state_groups,
        "summary": {},
    }
    return manifest, state


def _summarize_state(state: dict | None) -> dict:
    groups = list((state or {}).get("groups", []) or [])
    total_items = 0
    counts = {
        "pending_items": 0,
        "queued_items": 0,
        "running_items": 0,
        "scoring_items": 0,
        "pending_scoring_items": 0,
        "paused_items": 0,
        "interrupted_items": 0,
        "completed_items": 0,
        "failed_items": 0,
        "cancelled_items": 0,
    }
    for group in groups:
        for item in group.get("items", []) or []:
            total_items += 1
            status = str(item.get("status", "pending") or "pending").strip().lower()
            if status == "scoring":
                if bool(item.get("scoring_active")):
                    counts["scoring_items"] += 1
                else:
                    counts["pending_scoring_items"] += 1
                continue
            key = f"{status}_items"
            if key in counts:
                counts[key] += 1
            else:
                counts["pending_items"] += 1
    counts["total_items"] = total_items
    counts["terminal_items"] = (
        counts["completed_items"] + counts["failed_items"] + counts["cancelled_items"]
    )
    return counts


def _derive_group_status(items: list[dict]) -> str:
    statuses = {str(item.get("status", "pending") or "pending").strip().lower() for item in items}
    if not statuses:
        return "pending"
    if statuses & {"running"}:
        return "running"
    if statuses & {"scoring"}:
        return "running"
    if statuses & {"queued"}:
        return "queued"
    if statuses & {"paused"}:
        return "paused"
    if statuses & {"interrupted"}:
        return "interrupted"
    if statuses == {"completed"}:
        return "completed"
    if statuses <= {"cancelled"}:
        return "cancelled"
    if statuses & {"pending"}:
        return "pending"
    if statuses & {"failed"}:
        return "failed"
    return sorted(statuses)[0]


def _derive_run_status(current_status: str, state: dict) -> str:
    summary = _summarize_state(state)
    total_items = summary.get("total_items", 0)
    if total_items and summary.get("terminal_items", 0) >= total_items:
        if current_status in {"cancelled", "cancelling"} or summary.get("cancelled_items", 0) > 0:
            return "cancelled"
        return "completed"
    if current_status in {"paused", "cancelled", "interrupted", "cancelling"}:
        return current_status
    if summary.get("running_items", 0) > 0:
        return "running"
    if summary.get("scoring_items", 0) > 0:
        return "running"
    if summary.get("pending_scoring_items", 0) > 0:
        return "running"
    if summary.get("queued_items", 0) > 0:
        return "queued"
    if summary.get("pending_items", 0) > 0:
        return "pending"
    if summary.get("interrupted_items", 0) > 0:
        return "interrupted"
    return current_status or "pending"


def _public_group(group: dict) -> dict:
    return {
        "key": group.get("key", ""),
        "label": group.get("label", ""),
        "relationship": group.get("relationship", ""),
        "planned_turns": int(group.get("planned_turns", 0) or 0),
        "status": group.get("status", "pending"),
        "items": [
            {
                "key": item.get("key", ""),
                "label": item.get("label", ""),
                "relationship": item.get("relationship", ""),
                "model_id": item.get("model_id", ""),
                "planned_turns": int(item.get("planned_turns", 0) or 0),
                "conversation_id": item.get("conversation_id", ""),
                "status": item.get("status", "pending"),
                "turn_count": int(item.get("turn_count", 0) or 0),
                "avg_chars": int(item.get("avg_chars", 0) or 0),
                "avg_score": item.get("avg_score", None),
                "scored_turns": int(item.get("scored_turns", 0) or 0),
                "failed_turns": int(item.get("failed_turns", 0) or 0),
                "skipped_turns": int(item.get("skipped_turns", 0) or 0),
                "pending_scoring_turns": int(item.get("pending_scoring_turns", 0) or 0),
                "has_pending_scores": bool(item.get("has_pending_scores")),
                "scoring_active": bool(item.get("scoring_active")),
                "updated_at": item.get("updated_at"),
                "resume_supported": bool(item.get("resume_supported")),
                "error": item.get("error", ""),
            }
            for item in group.get("items", []) or []
        ],
    }


def _public_run(run: dict | None) -> dict | None:
    if not run:
        return None
    state = run.get("state", {}) or {}
    manifest = deepcopy(run.get("manifest", {}) or {})
    groups = [_public_group(group) for group in state.get("groups", []) or []]
    summary = _summarize_state({"groups": groups})
    return {
        "id": run.get("id", ""),
        "kind": run.get("kind", ""),
        "title": run.get("title", ""),
        "status": run.get("status", "pending"),
        "concurrency": int(run.get("concurrency", 1) or 1),
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
        "config_snapshot": deepcopy(manifest.get("config_snapshot", {}) or {}),
        "manifest": manifest,
        "groups": groups,
        "summary": summary,
    }


def _iter_positions(run: dict) -> list[tuple[int, int]]:
    positions: list[tuple[int, int]] = []
    for group_index, group in enumerate(run.get("state", {}).get("groups", []) or []):
        items = list(group.get("items", []) or [])
        for item_index, _ in enumerate(items):
            positions.append((group_index, item_index))
    return positions


def _has_live_scoring_activity(conv_id: str) -> bool:
    return bool(_get_live_scoring_state(conv_id).get("active"))


def _get_live_scoring_state(conv_id: str) -> dict:
    normalized = str(conv_id or "").strip()
    if not normalized:
        return {"active": False, "queued_jobs": 0, "has_activity": False}
    try:
        from routers import scoring as scoring_router

        dispatcher = scoring_router.get_live_scoring_dispatcher()
        active = bool(dispatcher.is_conversation_active(normalized))
        queued_jobs = int(dispatcher.get_queue_size(normalized) or 0)
        return {
            "active": active,
            "queued_jobs": queued_jobs,
            "has_activity": bool(active or queued_jobs > 0),
        }
    except Exception:
        return {"active": False, "queued_jobs": 0, "has_activity": False}


def _is_active_item(item: dict) -> bool:
    status = str(item.get("status", "") or "").strip().lower()
    if status != "scoring":
        return status in ACTIVE_ORCHESTRATION_ITEM_STATUSES
    return _has_live_scoring_activity(item.get("conversation_id", ""))


def _is_generation_active_item(item: dict) -> bool:
    status = str(item.get("status", "") or "").strip().lower()
    return status in GENERATION_ACTIVE_ITEM_STATUSES


def _is_schedulable_item(item: dict) -> bool:
    status = str(item.get("status", "pending") or "pending").strip().lower()
    if status in {"pending", "interrupted", "cancelled"}:
        return True
    if status == "scoring":
        return not _has_live_scoring_activity(item.get("conversation_id", ""))
    return False


def _active_positions(run: dict) -> list[tuple[int, int]]:
    positions = []
    for group_index, item_index in _iter_positions(run):
        item = run["state"]["groups"][group_index]["items"][item_index]
        if _is_active_item(item):
            positions.append((group_index, item_index))
    return positions


def _generation_active_positions(run: dict) -> list[tuple[int, int]]:
    positions = []
    for group_index, item_index in _iter_positions(run):
        item = run["state"]["groups"][group_index]["items"][item_index]
        if _is_generation_active_item(item):
            positions.append((group_index, item_index))
    return positions


def _schedulable_positions(run: dict) -> list[tuple[int, int]]:
    positions: list[tuple[int, int]] = []
    groups = list(run.get("state", {}).get("groups", []) or [])
    if run.get("kind") == "compare":
        target_group = None
        for group_index, group in enumerate(groups):
            statuses = {
                str(item.get("status", "pending") or "pending").strip().lower()
                for item in group.get("items", []) or []
            }
            if statuses - TERMINAL_ITEM_STATUSES:
                target_group = group_index
                break
        if target_group is None:
            return positions
        groups = [groups[target_group]]
        offset = target_group
        for item_index, item in enumerate(groups[0].get("items", []) or []):
            if _is_schedulable_item(item):
                positions.append((offset, item_index))
        return positions

    for group_index, group in enumerate(groups):
        for item_index, item in enumerate(group.get("items", []) or []):
            if _is_schedulable_item(item):
                positions.append((group_index, item_index))
    return positions


def _select_schedulable_positions(run: dict, available_slots: int) -> list[tuple[int, int]]:
    if available_slots <= 0:
        return []
    schedulable = _schedulable_positions(run)
    if run.get("kind") != "ab":
        return schedulable[:available_slots]

    selected: list[tuple[int, int]] = []
    remaining_slots = available_slots
    groups = list(run.get("state", {}).get("groups", []) or [])
    for group_index, group in enumerate(groups):
        group_positions = [
            (group_index, item_index)
            for item_index, item in enumerate(group.get("items", []) or [])
            if _is_schedulable_item(item)
        ]
        if not group_positions:
            continue
        group_has_generation_activity = any(
            _is_generation_active_item(item)
            for item in group.get("items", []) or []
        )
        if not group_has_generation_activity and len(group_positions) > 1 and len(group_positions) > remaining_slots:
            continue
        take = group_positions[:remaining_slots]
        if not take:
            continue
        selected.extend(take)
        remaining_slots -= len(take)
        if remaining_slots <= 0:
            break
    return selected


async def _refresh_run_state(run_id: str, *, persist: bool = True) -> dict | None:
    run = db.get_orchestration_run(run_id)
    if not run:
        return None
    state = deepcopy(run.get("state", {}) or {})
    manifest_groups = list((run.get("manifest", {}) or {}).get("groups", []) or [])
    groups = list(state.get("groups", []) or [])
    for group_index, group in enumerate(groups):
        items = list(group.get("items", []) or [])
        manifest_group = manifest_groups[group_index] if group_index < len(manifest_groups) else {}
        manifest_items = list(manifest_group.get("items", []) or [])
        for item_index, item in enumerate(items):
            conv_id = str(item.get("conversation_id", "") or "").strip()
            if not conv_id:
                item.setdefault("status", "pending")
                item.setdefault("turn_count", 0)
                item.setdefault("avg_chars", 0)
                item.setdefault("avg_score", None)
                item.setdefault("scored_turns", 0)
                item.setdefault("failed_turns", 0)
                item.setdefault("skipped_turns", 0)
                item.setdefault("updated_at", None)
                continue
            conversation = db.get_conversation(conv_id)
            if not conversation:
                if str(item.get("status", "")).strip().lower() not in TERMINAL_ITEM_STATUSES:
                    item["status"] = "failed"
                    item["error"] = item.get("error") or "关联会话不存在"
                continue
            metrics = _compute_turn_metrics(conversation)
            manifest_item = manifest_items[item_index] if item_index < len(manifest_items) else {}
            payload = manifest_item.get("payload", {}) or {}
            auto_scoring_enabled = _is_auto_scoring_enabled(
                payload=payload,
                conversation=conversation,
            )
            settled_score_turns = (
                metrics["scored_turns"] + metrics["failed_turns"] + metrics["skipped_turns"]
            )
            live_scoring_state = _get_live_scoring_state(conv_id)
            conversation_status = str(
                conversation.get("status", item.get("status", "pending")) or "pending"
            ).strip().lower()
            has_pending_scores = (
                conversation_status not in {"failed", "cancelled"}
                and _has_pending_auto_scoring(
                    conversation,
                    metrics=metrics,
                    planned_turns=int(item.get("planned_turns", 0) or 0),
                    auto_scoring_enabled=auto_scoring_enabled,
                )
            )
            pending_scoring_turns = max(
                0,
                int(metrics["turn_count"] or 0) - int(settled_score_turns or 0),
            ) if auto_scoring_enabled else 0
            if has_pending_scores and conversation_status == "completed":
                item["status"] = "scoring"
            else:
                item["status"] = conversation_status
            item["turn_count"] = metrics["turn_count"]
            item["avg_chars"] = metrics["avg_chars"]
            item["avg_score"] = metrics["avg_score"]
            item["scored_turns"] = metrics["scored_turns"]
            item["failed_turns"] = metrics["failed_turns"]
            item["skipped_turns"] = metrics["skipped_turns"]
            item["pending_scoring_turns"] = pending_scoring_turns
            item["has_pending_scores"] = bool(has_pending_scores)
            item["scoring_active"] = bool(live_scoring_state.get("active"))
            item["updated_at"] = metrics["updated_at"]
            item["resume_supported"] = bool(conversation.get("resume_supported"))
        group["status"] = _derive_group_status(items)
    state["groups"] = groups
    state["summary"] = _summarize_state(state)
    next_status = _derive_run_status(str(run.get("status", "pending") or "pending"), state)
    if persist:
        updated = db.update_orchestration_run(run_id, status=next_status, state=state)
        return updated
    run["state"] = state
    run["status"] = next_status
    return run


async def get_run(run_id: str) -> dict | None:
    return _public_run(await _refresh_run_state(run_id))


async def get_latest_recoverable_run(kind: str) -> dict | None:
    candidates = db.list_orchestration_runs(
        kind=kind,
        statuses=["running", "queued", "paused", "interrupted", "cancelling"],
        limit=5,
    )
    for item in candidates:
        refreshed = await _refresh_run_state(item["id"])
        if refreshed and refreshed.get("status") in {"running", "queued", "paused", "interrupted", "cancelling"}:
            return _public_run(refreshed)
    return None


async def get_latest_run(kind: str) -> dict | None:
    active_run = await get_latest_recoverable_run(kind)
    if active_run:
        return active_run
    candidates = db.list_orchestration_runs(kind=kind, limit=5)
    for item in candidates:
        refreshed = await _refresh_run_state(item["id"])
        if refreshed:
            return _public_run(refreshed)
    return None


async def list_runs(
    kind: str = "",
    status: str = "",
    limit: int = 20,
) -> list[dict]:
    normalized_kind = str(kind or "").strip().lower()
    normalized_status = str(status or "").strip().lower()
    statuses = [normalized_status] if normalized_status else None
    candidates = db.list_orchestration_runs(
        kind=normalized_kind or None,
        statuses=statuses,
        limit=max(1, min(int(limit or 20), 100)),
    )
    runs: list[dict] = []
    for item in candidates:
        refreshed = await _refresh_run_state(item["id"], persist=False)
        public = _public_run(refreshed or item)
        if public:
            runs.append(public)
    return runs


async def _start_or_resume_item(run: dict, group_index: int, item_index: int) -> dict:
    state_item = run["state"]["groups"][group_index]["items"][item_index]
    manifest_item = run["manifest"]["groups"][group_index]["items"][item_index]
    conv_id = str(state_item.get("conversation_id", "") or "").strip()
    if conv_id:
        conversation = db.get_conversation(conv_id)
        if conversation:
            status = str(conversation.get("status", "") or "").strip().lower()
            payload = manifest_item.get("payload", {}) or {}
            auto_scoring_enabled = _is_auto_scoring_enabled(
                payload=payload,
                conversation=conversation,
            )
            has_pending_scores = (
                status not in {"failed", "cancelled"}
                and _has_pending_auto_scoring(
                    conversation,
                    planned_turns=int(state_item.get("planned_turns", 0) or 0),
                    auto_scoring_enabled=auto_scoring_enabled,
                )
            )
            if has_pending_scores:
                from routers import scoring as scoring_router

                try:
                    await scoring_router.enqueue_pending_live_scores(
                        conv_id,
                        config=conversation.get("config", {}),
                    )
                    state_item["error"] = ""
                except Exception as exc:
                    state_item["status"] = "failed"
                    state_item["error"] = f"恢复评分失败: {exc}"
                    return state_item
            if status in ACTIVE_CONVERSATION_STATUSES | TERMINAL_ITEM_STATUSES:
                if status == "completed" and has_pending_scores:
                    state_item["status"] = "scoring"
                else:
                    state_item["status"] = status
                return state_item
            if status in RESUMABLE_CONVERSATION_STATUSES:
                try:
                    result = await conversations_router.resume_conversation(conv_id)
                    state_item["status"] = str(result.get("status", "queued") or "queued").strip().lower()
                    state_item["error"] = ""
                    return state_item
                except Exception as exc:  # pragma: no cover - 失败通过状态同步暴露
                    state_item["status"] = "failed"
                    state_item["error"] = f"恢复失败: {exc}"
                    return state_item
        else:
            state_item["conversation_id"] = ""

    try:
        payload = ConversationCreate(**deepcopy(manifest_item.get("payload", {}) or {}))
        result = await conversations_router.create_conversation(payload)
        state_item["conversation_id"] = str(result.get("id", "") or result.get("conversation_id", "")).strip()
        state_item["status"] = str(result.get("status", "queued") or "queued").strip().lower()
        state_item["error"] = ""
    except Exception as exc:
        state_item["status"] = "failed"
        state_item["error"] = str(exc)
    return state_item


async def _control_child_conversations(run: dict, action: str) -> None:
    request = TaskControlRequest(action=action)
    for group in run.get("state", {}).get("groups", []) or []:
        for item in group.get("items", []) or []:
            conv_id = str(item.get("conversation_id", "") or "").strip()
            if not conv_id:
                continue
            status = str(item.get("status", "") or "").strip().lower()
            if status == "scoring":
                from routers import scoring as scoring_router

                try:
                    await scoring_router.control_scoring(conv_id, request)
                except Exception:
                    continue
                continue
            if status not in ACTIVE_CONVERSATION_STATUSES:
                continue
            try:
                await conversations_router.control_conversation(conv_id, request)
            except Exception:
                continue


def _mark_pending_items_cancelled(state: dict) -> dict:
    next_state = deepcopy(state or {})
    for group in next_state.get("groups", []) or []:
        for item in group.get("items", []) or []:
            if str(item.get("status", "pending") or "pending").strip().lower() in {"pending", "interrupted"}:
                item["status"] = "cancelled"
                item["error"] = item.get("error") or "任务已取消"
        group["status"] = _derive_group_status(group.get("items", []) or [])
    next_state["summary"] = _summarize_state(next_state)
    return next_state


def _persist_run_state(run_id: str, run: dict, *, status: str | None = None) -> dict | None:
    return db.update_orchestration_run(
        run_id,
        status=status or str(run.get("status", "pending") or "pending"),
        state=run.get("state", {}) or {},
    )


def _spawn_runner(run_id: str) -> None:
    existing = _runner_tasks.get(run_id)
    if existing and not existing.done():
        return
    _runner_tasks[run_id] = asyncio.create_task(_run_loop(run_id))


async def create_run(data: OrchestrationRunCreate) -> dict:
    manifest, state = _build_initial_run_payload(data)
    created = db.create_orchestration_run(
        data.kind,
        title=data.title,
        concurrency=data.concurrency,
        manifest=manifest,
        state=state,
        status="pending",
    )
    task_control.remove(_runner_task_id(created["id"]))
    task_control.get_or_create(_runner_task_id(created["id"]))
    _spawn_runner(created["id"])
    return _public_run(await _refresh_run_state(created["id"])) or {}


async def control_run(run_id: str, action: str) -> dict:
    run = await _refresh_run_state(run_id)
    if not run:
        raise ValueError(f"编排任务不存在: {run_id}")
    normalized_status = str(run.get("status", "") or "").strip().lower()
    if normalized_status in {"completed", "cancelled"}:
        raise RuntimeError(f"编排任务已结束，不能再执行 {action}")
    task_id = _runner_task_id(run_id)
    ctrl = task_control.get(task_id)

    if action == "pause":
        ctrl = ctrl or task_control.get_or_create(task_id)
        ctrl.pause()
        await _control_child_conversations(run, "pause")
        updated = db.update_orchestration_run(run_id, status="paused", state=run.get("state", {}))
        return _public_run(updated) or {}

    if action == "resume":
        ctrl = ctrl or task_control.get_or_create(task_id)
        ctrl.resume()
        await _control_child_conversations(run, "resume")
        updated = db.update_orchestration_run(run_id, status="running", state=run.get("state", {}))
        _spawn_runner(run_id)
        return _public_run(updated) or {}

    ctrl = ctrl or task_control.get_or_create(task_id)
    ctrl.resume()
    await _control_child_conversations(run, "cancel")
    state = _mark_pending_items_cancelled(run.get("state", {}))
    next_status = "cancelling" if _active_positions(run) else "cancelled"
    updated = db.update_orchestration_run(run_id, status=next_status, state=state)
    if next_status == "cancelling":
        _spawn_runner(run_id)
    else:
        task_control.remove(task_id)
    return _public_run(updated) or {}


async def reconcile_runtime_state() -> None:
    for task_id in list(task_control.list_active().keys()):
        if task_id.startswith(RUNNER_PREFIX):
            task_control.remove(task_id)
    for run in db.list_orchestration_runs(
        statuses=["running", "queued", "paused", "pending", "cancelling"],
        limit=100,
    ):
        refreshed = await _refresh_run_state(run["id"], persist=False)
        if not refreshed:
            continue
        original_status = str(run.get("status", "") or "").strip().lower()
        refreshed_status = str(refreshed.get("status", "") or "").strip().lower()
        if refreshed_status in {"completed", "cancelled"}:
            next_status = refreshed_status
        elif original_status == "paused":
            next_status = "paused"
        elif original_status == "cancelling":
            next_status = "cancelling"
        else:
            next_status = "interrupted"
        db.update_orchestration_run(
            run["id"],
            status=next_status,
            state=refreshed.get("state", {}),
        )
        if next_status in {"interrupted", "cancelling"}:
            task_control.remove(_runner_task_id(run["id"]))
            task_control.get_or_create(_runner_task_id(run["id"]))
            _spawn_runner(run["id"])


async def _run_loop(run_id: str) -> None:
    task_id = _runner_task_id(run_id)
    ctrl = task_control.get_or_create(task_id)
    try:
        while True:
            run = await _refresh_run_state(run_id)
            if not run:
                return
            await ctrl.checkpoint()

            summary = dict((run.get("state", {}) or {}).get("summary", {}) or {})
            total_items = int(summary.get("total_items", 0) or 0)
            active = _active_positions(run)
            schedulable = _schedulable_positions(run)

            if total_items and not active and not schedulable:
                final_status = _derive_run_status(str(run.get("status", "pending") or "pending"), run.get("state", {}) or {})
                if final_status not in {"completed", "cancelled"}:
                    final_status = "completed"
                db.update_orchestration_run(run_id, status=final_status, state=run.get("state", {}) or {})
                return

            concurrency = max(1, int(run.get("concurrency", 1) or 1))
            available_slots = max(0, concurrency - len(_generation_active_positions(run)))
            if available_slots > 0 and schedulable:
                scheduled_any = False
                for group_index, item_index in _select_schedulable_positions(run, available_slots):
                    await _start_or_resume_item(run, group_index, item_index)
                    scheduled_any = True
                if scheduled_any:
                    _persist_run_state(run_id, run)
                refreshed = await _refresh_run_state(run_id)
                if refreshed and refreshed.get("status") not in {"paused", "cancelled", "completed"}:
                    next_status = "running" if _active_positions(refreshed) else "queued"
                    db.update_orchestration_run(
                        run_id,
                        status=next_status,
                        state=refreshed.get("state", {}) or {},
                    )

            await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        refreshed = await _refresh_run_state(run_id)
        if refreshed:
            refreshed_status = str(refreshed.get("status", "") or "").strip().lower()
            if refreshed_status not in {"completed", "cancelled", "paused", "cancelling"}:
                db.update_orchestration_run(
                    run_id,
                    status="interrupted",
                    state=refreshed.get("state", {}) or {},
                )
        raise
    finally:
        task_control.remove(task_id)
        _runner_tasks.pop(run_id, None)
