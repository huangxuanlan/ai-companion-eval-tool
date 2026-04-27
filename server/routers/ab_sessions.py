from __future__ import annotations

import asyncio
from copy import deepcopy
import uuid

from fastapi import APIRouter, HTTPException

import database as db
from models import (
    ABSessionCreateRequest,
    ABSessionResponse,
    ABSessionStatusResponse,
    ABSessionTurnRequest,
    InteractiveConversationCreate,
    InteractiveGenerateRequest,
)
from routers import conversations as conversations_router

router = APIRouter(prefix="/api/ab-sessions", tags=["ab-sessions"])


def _normalize_ab_session_payload(session: dict) -> ABSessionStatusResponse:
    config = dict(session.get("config", {}) or {})
    base_conv = db.get_conversation(str(session.get("base_conversation_id", "") or "").strip()) or {}
    compare_conv = db.get_conversation(str(session.get("compare_conversation_id", "") or "").strip()) or {}
    return ABSessionStatusResponse(
        id=str(session.get("id", "") or "").strip(),
        status=str(session.get("status", "active") or "active").strip(),
        base_conversation_id=str(session.get("base_conversation_id", "") or "").strip(),
        compare_conversation_id=str(session.get("compare_conversation_id", "") or "").strip(),
        current_turn=int(session.get("current_turn", 0) or 0),
        created_at=session.get("created_at"),
        updated_at=session.get("updated_at"),
        shared_config=dict(config.get("shared_config", {}) or {}),
        base_config=dict(config.get("base_config", {}) or {}),
        compare_config=dict(config.get("compare_config", {}) or {}),
        base_status=str(base_conv.get("status", "") or "").strip(),
        compare_status=str(compare_conv.get("status", "") or "").strip(),
    )


def _get_ab_session_or_404(session_id: str) -> dict:
    session = db.get_ab_session(str(session_id or "").strip())
    if not session:
        raise HTTPException(status_code=404, detail="A/B 实验不存在")
    return session


async def _launch_ab_generation(
    session_id: str,
    turn: int,
    *,
    base_conversation_id: str,
    compare_conversation_id: str,
    request: ABSessionTurnRequest,
) -> None:
    payload = InteractiveGenerateRequest(
        user_input=request.user_input,
        web_search=bool(request.web_search),
        thinking_enabled=request.thinking_enabled,
        thinking_effort=request.thinking_effort or "",
        temperature=request.temperature,
        top_p=request.top_p,
    )

    async def _run_one(conv_id: str) -> dict:
        try:
            return await conversations_router.generate_interactive_turn(conv_id, payload)
        except Exception as exc:
            return {"success": False, "error": str(exc), "conversation_id": conv_id}

    results = await asyncio.gather(
        _run_one(base_conversation_id),
        _run_one(compare_conversation_id),
        return_exceptions=False,
    )
    session = db.get_ab_session(session_id)
    if not session:
        return
    session_status = str(session.get("status", "") or "").strip().lower()
    if session_status != "running":
        return
    if int(session.get("current_turn", 0) or 0) != int(turn or 0):
        return
    next_config = dict(session.get("config", {}) or {})
    next_config["last_turn_result"] = {
        "turn": int(turn or 0),
        "base": results[0],
        "compare": results[1],
    }
    next_status = "active"
    if not bool(results[0].get("success")) or not bool(results[1].get("success")):
        next_status = "failed"
    db.update_ab_session(
        session_id,
        status=next_status,
        current_turn=int(turn or 0),
        config=next_config,
    )


@router.get("/active", response_model=ABSessionStatusResponse | None)
async def get_active_ab_session():
    session = db.get_latest_active_ab_session()
    if not session:
        return None
    return _normalize_ab_session_payload(session)


@router.post("", response_model=ABSessionResponse)
async def create_ab_session(data: ABSessionCreateRequest):
    for existing in db.list_ab_sessions(statuses=["running", "active"], limit=20):
        db.update_ab_session(existing["id"], status="completed")

    session_id = str(uuid.uuid4())[:12]
    base_request = data.base.model_copy(
        update={
            "auto_scoring": True,
            "ab_session_id": session_id,
            "ab_variant": "base",
        }
    )
    compare_request = data.compare.model_copy(
        update={
            "auto_scoring": True,
            "ab_session_id": session_id,
            "ab_variant": "compare",
        }
    )
    base_conversation = await conversations_router.create_interactive_conversation(base_request)
    compare_conversation = await conversations_router.create_interactive_conversation(compare_request)
    session = db.create_ab_session(
        session_id=session_id,
        status="active",
        base_conversation_id=str(base_conversation.get("id", "") or "").strip(),
        compare_conversation_id=str(compare_conversation.get("id", "") or "").strip(),
        current_turn=0,
        config={
            "shared_config": deepcopy(data.shared_config or {}),
            "base_config": base_request.model_dump(mode="python"),
            "compare_config": compare_request.model_dump(mode="python"),
        },
    )
    normalized = _normalize_ab_session_payload(session)
    return ABSessionResponse(
        id=normalized.id,
        status=normalized.status,
        base_conversation_id=normalized.base_conversation_id,
        compare_conversation_id=normalized.compare_conversation_id,
        current_turn=normalized.current_turn,
        created_at=normalized.created_at,
        updated_at=normalized.updated_at,
        shared_config=normalized.shared_config,
        base_config=normalized.base_config,
        compare_config=normalized.compare_config,
    )


@router.get("/{session_id}", response_model=ABSessionStatusResponse)
async def get_ab_session(session_id: str):
    return _normalize_ab_session_payload(_get_ab_session_or_404(session_id))


@router.post("/{session_id}/turns", response_model=ABSessionStatusResponse)
async def create_ab_session_turn(session_id: str, data: ABSessionTurnRequest):
    session = _get_ab_session_or_404(session_id)
    session_status = str(session.get("status", "") or "").strip().lower()
    if session_status == "running":
        raise HTTPException(status_code=409, detail="当前 A/B 实验仍在生成上一轮")
    if session_status != "active":
        raise HTTPException(status_code=409, detail="当前 A/B 实验已结束，不能继续写入")
    user_input = str(data.user_input or "").strip()
    if not user_input:
        raise HTTPException(status_code=400, detail="user_input 不能为空")

    next_turn = int(session.get("current_turn", 0) or 0) + 1
    running_session = db.update_ab_session(
        session_id,
        status="running",
        current_turn=next_turn,
    ) or session
    asyncio.create_task(
        _launch_ab_generation(
            session_id,
            next_turn,
            base_conversation_id=str(session.get("base_conversation_id", "") or "").strip(),
            compare_conversation_id=str(session.get("compare_conversation_id", "") or "").strip(),
            request=data,
        )
    )
    return _normalize_ab_session_payload(running_session)
