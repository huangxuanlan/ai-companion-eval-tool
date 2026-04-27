from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query

from models import OrchestrationRunCreate, TaskControlRequest
from services import orchestration_service

router = APIRouter(prefix="/api/orchestrations", tags=["orchestrations"])


@router.post("")
async def create_orchestration_run(data: OrchestrationRunCreate):
    if not data.groups:
        raise HTTPException(status_code=400, detail="groups 不能为空")
    if any(not group.items for group in data.groups):
        raise HTTPException(status_code=400, detail="每个 group 至少要有 1 个任务")
    return await orchestration_service.create_run(data)


@router.get("/active")
async def get_active_orchestration(kind: str = Query(default="")):
    normalized_kind = str(kind or "").strip().lower()
    if normalized_kind not in {"batch", "compare", "ab"}:
        raise HTTPException(status_code=400, detail="kind 仅支持 batch、compare 或 ab")
    run = await orchestration_service.get_latest_recoverable_run(normalized_kind)
    return {"run": run}


@router.get("/latest")
async def get_latest_orchestration(kind: str = Query(default="")):
    normalized_kind = str(kind or "").strip().lower()
    if normalized_kind not in {"batch", "compare", "ab"}:
        raise HTTPException(status_code=400, detail="kind 仅支持 batch、compare 或 ab")
    run = await orchestration_service.get_latest_run(normalized_kind)
    return {"run": run}


@router.get("/{run_id}")
async def get_orchestration_run(run_id: str):
    run = await orchestration_service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"编排任务不存在: {run_id}")
    return run


@router.post("/{run_id}/control")
async def control_orchestration_run(run_id: str, data: TaskControlRequest = Body(...)):
    try:
        run = await orchestration_service.control_run(run_id, data.action)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return run
