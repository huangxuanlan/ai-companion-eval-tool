"""
普通聊天路由 — POST /api/chat（v5.1）

支持多模型并行调用，返回各模型独立结果。
"""
import asyncio
import inspect
from fastapi import APIRouter, HTTPException

from models import ChatRequest, ChatScoreRequest
from config import MAX_COMPARE_MODELS
from services.model_adapter import ModelAdapter

router = APIRouter(tags=["chat"])

_adapter = None
_scoring_service = None
CHAT_SCORE_TIMEOUT_S = 180
CHAT_SCORE_RETRY_DELAYS: tuple[float, ...] = ()


def _get_adapter():
    global _adapter
    if _adapter is None:
        _adapter = ModelAdapter()
    return _adapter


def _get_scoring_service():
    global _scoring_service
    if _scoring_service is None:
        from services.scoring_service import ScoringService

        _scoring_service = ScoringService()
    return _scoring_service


def _is_scoring_service_available(service, model_id: str) -> bool:
    checker = getattr(service, "is_available", None)
    if not callable(checker):
        return False
    try:
        signature = inspect.signature(checker)
        if not signature.parameters:
            return bool(checker())
    except (TypeError, ValueError):
        pass
    try:
        return bool(checker(model_id))
    except TypeError:
        return bool(checker())


@router.post("/api/chat")
async def chat(data: ChatRequest):
    """普通聊天 — 支持多模型并行输出"""
    if not data.messages:
        raise HTTPException(400, "messages 不能为空")
    if len(data.model_ids) > MAX_COMPARE_MODELS:
        raise HTTPException(400, f"最多支持 {MAX_COMPARE_MODELS} 个模型并行")

    adapter = _get_adapter()

    async def _call_model(model_id: str) -> dict:
        try:
            thinking_effort = adapter.resolve_thinking_effort(
                model_id,
                data.thinking_enabled,
                data.thinking_effort,
            )
            # 根据每个模型的独立配置，复制并组装专有消息体
            model_messages = list(data.messages)
            if data.model_prompts and model_id in data.model_prompts:
                custom_sys = data.model_prompts[model_id].strip()
                if custom_sys:
                    if model_messages and model_messages[0].get("role") == "system":
                        model_messages[0] = {
                            "role": "system",
                            "content": custom_sys,
                        }
                    else:
                        model_messages.insert(
                            0, {"role": "system", "content": custom_sys}
                        )
            
            result = await asyncio.to_thread(
                adapter.chat, model_id, model_messages,
                web_search=data.web_search,
                thinking_effort=thinking_effort,
                temperature=data.temperature,
                top_p=data.top_p,
            )
            return {
                "model_id": model_id,
                "content": result.content,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "latency_s": result.latency_s,
                "success": result.success,
                "error": result.error if not result.success else "",
            }
        except Exception as e:
            return {
                "model_id": model_id,
                "content": "",
                "error": str(e),
                "success": False,
            }

    # 并行调用所有模型
    tasks = [_call_model(mid) for mid in data.model_ids]
    results = await asyncio.gather(*tasks)

    return {"results": list(results)}


@router.post("/api/chat/score")
async def chat_score(data: ChatScoreRequest):
    """对话体验页单轮AI评分 — 无需创建conversation"""
    if not data.ai_output:
        raise HTTPException(400, "ai_output 不能为空")

    from services.scoring_service import invoke_score_turn_compat

    service = _get_scoring_service()
    runtime = data.config.get("runtime", {})
    scoring_model_id = (
        data.scoring_model_id
        or runtime.get("scoring_model_id", "")
    )
    if not _is_scoring_service_available(service, scoring_model_id):
        return {"success": False, "error": service.get_last_error() or "评分服务不可用"}

    resolver = getattr(service, "resolve_scoring_thinking_effort", None)
    if callable(resolver):
        scoring_thinking_effort = resolver(
            scoring_model_id,
            data.scoring_thinking_enabled,
            data.scoring_thinking_effort or runtime.get("scoring_thinking_effort", ""),
            runtime.get("scoring_thinking_enabled", None),
        )
    else:
        scoring_thinking_effort = ModelAdapter.resolve_thinking_effort(
            scoring_model_id,
            (
                data.scoring_thinking_enabled
                if data.scoring_thinking_enabled is not None
                else runtime.get("scoring_thinking_enabled", None)
            ),
            data.scoring_thinking_effort or runtime.get("scoring_thinking_effort", ""),
        )

    character = data.config.get("character", {})
    context = data.config.get("context", {})
    modules = dict(data.config.get("modules", {}) or {})
    turn_payload = {
        "turn": 1,
        "user_input": data.user_input,
        "ai_output": data.ai_output,
        "role_name": character.get("Role_Nickname", ""),
        "personality": character.get("personality", ""),
        "relationship": context.get("relationship", ""),
        "prompt_name": data.config.get("prompt_file", ""),
        "dialogueStartPrompt": modules.get("dialogueStartPrompt", ""),
        "moments": modules.get("moments", ""),
        "dialogue_summary": runtime.get("latest_dialogue_summary", ""),
    }

    try:
        result = await asyncio.wait_for(
            invoke_score_turn_compat(
                service,
                turn_payload,
                timeout_s=CHAT_SCORE_TIMEOUT_S,
                retry_delays=CHAT_SCORE_RETRY_DELAYS,
                prompt_version=(
                    data.scoring_prompt_version
                    or runtime.get("scoring_prompt_version", "")
                ),
                model_id=scoring_model_id,
                thinking_effort=scoring_thinking_effort,
            ),
            timeout=CHAT_SCORE_TIMEOUT_S + 1,
        )
        return {"success": True, **result}
    except asyncio.TimeoutError:
        return {
            "success": False,
            "error": f"AI打分超时（>{CHAT_SCORE_TIMEOUT_S}s），已切换为手动重试",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
