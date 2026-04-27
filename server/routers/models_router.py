"""
模型路由 — /api/models
"""
import re
import yaml
from fastapi import APIRouter, HTTPException, Query

from config import MODELS_CONFIG_DIR
from models import ModelConfigRequest
from services.model_adapter import ModelAdapter
from services.public_demo import raise_if_demo_write_blocked

router = APIRouter(prefix="/api/models", tags=["models"])

_adapter = None

_MINI_TOKEN_RE = re.compile(r"(^|[-_\s])(mini|flash|lite|haiku)(?=$|[-_\s])", re.IGNORECASE)


def _get_adapter():
    global _adapter
    if _adapter is None:
        _adapter = ModelAdapter()
    return _adapter


def _is_mini(m: dict) -> bool:
    labels = [
        str(m.get("id", "") or ""),
        str(m.get("name", "") or ""),
        str(m.get("display_name", "") or ""),
    ]
    return any(_MINI_TOKEN_RE.search(label) for label in labels if label)


@router.get("")
async def list_models(tier: str = Query(None, description="pro 或 mini")):
    """获取可用模型列表，可按 tier 筛选"""
    models = _get_adapter().list_models()
    if tier == "mini":
        models = [m for m in models if _is_mini(m)]
    elif tier == "pro":
        models = [m for m in models if not _is_mini(m)]
    return {"models": models}


@router.get("/{model_id}")
async def get_model_info(model_id: str):
    """获取单个模型信息"""
    models = _get_adapter().list_models(include_hidden=True)
    for m in models:
        if m["id"] == model_id:
            return m
    return {"error": f"模型不存在: {model_id}"}


@router.post("")
async def save_model_config(data: ModelConfigRequest):
    """新增或更新模型配置（后端管理接口）。"""
    raise_if_demo_write_blocked("演示模式下禁止修改模型配置")
    if data.id in ModelAdapter.BUILTIN_MODELS:
        raise HTTPException(status_code=400, detail="内置模型不可覆盖")

    MODELS_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config = {
        "name": data.name,
        "display_name": data.display_name or data.name,
        "provider": data.provider,
        "api": data.api,
        "parameters": data.parameters,
    }
    output_path = MODELS_CONFIG_DIR / f"{data.id}.yaml"
    output_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    global _adapter
    _adapter = None
    return {
        "message": "模型配置已保存",
        "id": data.id,
        "path": str(output_path),
    }
