from __future__ import annotations

import logging
from typing import Any
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field

import database as db
from services.bridge_service import BridgeService, map_db_mode_to_api
from services.verify_run_service import VerifyRunService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bridge", tags=["bridge"])
bridge_service = BridgeService()
verify_service = VerifyRunService()


# ── Pydantic Request Models ───────────────────────────────────────

class CreateSessionRequest(BaseModel):
    from_mode: str = Field(..., description="源模式 (shortform | longform)")
    to_mode: str = Field(..., description="目标模式 (shortform | longform)")
    source_conversation_id: str = Field(..., description="源会话 ID")
    target_model: str | None = Field(None, description="目标模型ID")
    bridge_turns: int = Field(20, description="桥接历史最大轮数")
    summary_interval: int = Field(10, description="摘要间隔轮数")
    scenario_name: str | None = Field(None, description="场景名称")
    triggered_by: str = Field("user_click", description="触发源 (user_click | api)")


class GenerateSummaryRequest(BaseModel):
    summary_model: str = Field("deepseek-v4-flash", description="生成摘要的轻量模型")
    delay_until_turn: int = Field(0, description="延迟生成直至指定轮数 (0表示即时)")


class FirstResponseRequest(BaseModel):
    user_input: str = Field(..., description="首轮用户输入内容")
    thinking_level: str = Field("high", description="深度思考层级 (high | disabled)")


class StartVerifyRunRequest(BaseModel):
    scripts: list[str] = Field(..., description="执行的验证脚本键列表 (mece_main | log_replay | short_model_matrix)")
    ab_config: list[str] | None = Field(None, description="AB配置过滤列表 (baseline | optimized)")
    scenarios: list[str] | None = Field(None, description="场景过滤列表 (S4 | S5 | S6 | S7 | S8 | S9 | S14)")
    dry_run: bool = Field(False, description="是否以 dry-run 模式运行")
    repeat: int = Field(1, description="重复次数 (仅适用于 mece_main)")


# ── HTTP Endpoints ────────────────────────────────────────────────

@router.post("/sessions", status_code=201)
def create_session(req: CreateSessionRequest):
    try:
        return bridge_service.create_bridge_session(
            from_mode=req.from_mode,
            to_mode=req.to_mode,
            source_conversation_id=req.source_conversation_id,
            target_model=req.target_model,
            bridge_turns=req.bridge_turns,
            summary_interval=req.summary_interval,
            scenario_name=req.scenario_name,
            triggered_by=req.triggered_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("创建切换会话接口异常: %s", e)
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")


@router.get("/sessions")
def list_sessions(
    from_mode: str | None = None,
    to_mode: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    try:
        # 在数据库查询中处理模式的转换
        db_from = None
        if from_mode:
            if from_mode.lower() in {"shortform", "short"}:
                db_from = "short"
            elif from_mode.lower() in {"longform", "long"}:
                db_from = "long"
        
        db_to = None
        if to_mode:
            if to_mode.lower() in {"shortform", "short"}:
                db_to = "short"
            elif to_mode.lower() in {"longform", "long"}:
                db_to = "long"

        rows = db.list_mode_switches(from_mode=db_from, to_mode=db_to, limit=limit, offset=offset)
        results = []
        for r in rows:
            mapped = bridge_service.get_bridge_session(f"br_{r['switch_id']}")
            if mapped:
                results.append(mapped)
        return results
    except Exception as e:
        logger.exception("查询切换会话列表接口异常: %s", e)
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")


@router.get("/sessions/{session_id}")
def get_session(session_id: str):
    session = bridge_service.get_bridge_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"切换会话不存在: {session_id}")
    return session


@router.post("/sessions/{session_id}/summary")
def generate_summary_endpoint(session_id: str, req: GenerateSummaryRequest):
    try:
        return bridge_service.trigger_async_summary(
            session_id=session_id,
            summary_model=req.summary_model,
            delay_until_turn=req.delay_until_turn,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("生成剧情摘要接口异常: %s", e)
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")


@router.get("/sessions/{session_id}/summary")
def get_summary_endpoint(session_id: str):
    try:
        return bridge_service.get_summary_status(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("查询剧情摘要接口异常: %s", e)
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")


@router.post("/sessions/{session_id}/first-response")
async def generate_first_response_endpoint(session_id: str, req: FirstResponseRequest):
    try:
        return await bridge_service.generate_first_response_and_score(
            session_id=session_id,
            user_input=req.user_input,
            thinking_level=req.thinking_level,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("生成首轮接话接口异常: %s", e)
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")


# ── Scenarios Endpoint（v6.0 F3 补齐，桥接 API v0.1 §2.6）──────────

@router.get("/scenarios")
def list_scenarios(
    sf_turns: int = Query(5, ge=1, le=20, description="短文阶段轮数"),
    lf_turns: int = Query(12, ge=1, le=40, description="长文阶段轮数"),
):
    """列出 MECE 测试场景定义 + A/B 配置（直接复用 verify_mode_switching.define_scenarios）"""
    import sys as _sys
    from pathlib import Path as _Path

    project_root = _Path(__file__).resolve().parent.parent.parent
    if str(project_root) not in _sys.path:
        _sys.path.insert(0, str(project_root))

    try:
        from scripts.verify_mode_switching import define_scenarios as _define
        scenarios = _define(sf_turns=sf_turns, lf_turns=lf_turns)
    except Exception as e:
        logger.warning("加载 verify_mode_switching.define_scenarios 失败，使用 fallback: %s", e)
        scenarios = [
            {"name": "S4_纯长文", "tags": ["核心路径", "纯长文"], "phases": [{"mode": "long", "turns": lf_turns}]},
            {"name": "S5_短→长", "tags": ["核心路径", "正向切换"], "phases": [{"mode": "short", "turns": sf_turns}, {"mode": "long", "turns": lf_turns}]},
            {"name": "S6_长→短", "tags": ["核心路径", "反向切换"], "phases": [{"mode": "long", "turns": lf_turns}, {"mode": "short", "turns": sf_turns}]},
        ]

    return {
        "scenarios": scenarios,
        "ab_configs": {
            "baseline": {"label": "线上基线", "bridge_turns": 20, "summary_interval": 10},
            "optimized": {"label": "优化方案", "bridge_turns": 10, "summary_interval": 5},
        },
        "params": {"sf_turns": sf_turns, "lf_turns": lf_turns},
    }


# ── Verify Runs Endpoints ──────────────────────────────────────────

@router.get("/verify-runs")
def list_verify_runs_endpoint(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    try:
        return verify_service.list_verify_runs(limit=limit, offset=offset)
    except Exception as e:
        logger.exception("列出验证运行历史接口异常: %s", e)
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")


@router.get("/verify-runs/{run_id}")
def get_verify_run_endpoint(run_id: str):
    run = verify_service.get_verify_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"未找到验证任务: {run_id}")
    return run


@router.delete("/verify-runs/{run_id}")
def delete_verify_run_endpoint(run_id: str):
    success = verify_service.delete_verify_run(run_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"未找到验证任务: {run_id}")
    return {"status": "success", "message": f"任务已删除: {run_id}"}


@router.post("/verify-runs", status_code=201)
async def start_verify_run_endpoint(req: StartVerifyRunRequest):
    try:
        return await verify_service.start_verification(
            scripts=req.scripts,
            ab_config=req.ab_config,
            scenarios=req.scenarios,
            dry_run=req.dry_run,
            repeat=req.repeat,
        )
    except Exception as e:
        logger.exception("启动验证运行接口异常: %s", e)
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")
