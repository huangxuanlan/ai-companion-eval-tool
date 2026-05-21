"""
预设角色路由 — /api/presets
"""
from fastapi import APIRouter, HTTPException, Query

from config import (
    DEFAULT_PRIMARY_MODEL,
    PRESET_CHARACTERS,
    RELATIONSHIP_PRESETS,
    extract_preset_module_defaults,
)
import database as db
from models import PresetCreate, PresetResponse
from services.prompt_service import PromptService
from services.runtime_config import build_longform_variable_bundle

router = APIRouter(prefix="/api/presets", tags=["presets"])


def _build_longform_variables(
    personality: str = "",
    relationship: str = "暧昧",
    gender: str = "男",
    persona_file: str = "",
    few_shot_file: str = "",
):
    return build_longform_variable_bundle(
        personality=personality,
        relationship=relationship,
        gender=gender,
        persona_file=persona_file,
        few_shot_file=few_shot_file,
        preset_characters=PRESET_CHARACTERS,
        relationship_presets=RELATIONSHIP_PRESETS,
        prompt_service=PromptService(),
    )


def _build_builtin_config(preset_id: str) -> dict:
    preset = PRESET_CHARACTERS[preset_id]
    relationship = preset.get("default_relationship", "暧昧")
    gender = preset.get("gender", "")
    personal_type = preset.get("type", "")
    defaults = preset.get("character_defaults", {})
    variable_bundle = _build_longform_variables(
        personality=personal_type,
        relationship=relationship,
        gender=gender,
    )
    return {
        "prompt_file": preset.get("prompt_file", ""),
        "few_shot_file": variable_bundle["longform_few_shot"],
        "character": {
            "Role_Nickname": preset.get("name", ""),
            "gender": gender,
            "personal_type": personal_type,
            "personality": defaults.get("personality", personal_type),
            "speaking_style": defaults.get("speaking_style", ""),
            "background": defaults.get("background", ""),
            "age": defaults.get("age", ""),
            "occupation": defaults.get("occupation", ""),
            "Role_info_works": defaults.get(
                "Role_info_works",
                defaults.get("role_info_works", defaults.get("works", "")),
            ),
            "hobby": defaults.get("hobby", ""),
        },
        "context": {
            "relationship": relationship,
            "intimacy_boundary": variable_bundle["intimacy_boundary"],
            "relation_calling": variable_bundle["relation_calling"],
            "relation_info": variable_bundle["relation_info"],
        },
        "modules": {
            **extract_preset_module_defaults(preset),
            "longform_persona": variable_bundle["longform_persona"],
            "longform_narrative_style": variable_bundle["longform_narrative_style"],
            "longform_dialogue_guideline": variable_bundle.get("longform_dialogue_guideline", ""),
            "longform_few_shot": variable_bundle["longform_few_shot"],
            "voice_forbidden": variable_bundle["voice_forbidden"],
        },
        "runtime": {
            "model_ids": [DEFAULT_PRIMARY_MODEL],
            "summary_interval": 5,
            "injection_depth": 4,
        },
    }


@router.get("")
async def list_presets():
    """获取所有预设角色（内置 + 用户自定义）"""
    # 内置预设
    builtins = []
    for pid, preset in PRESET_CHARACTERS.items():
        builtins.append({
            "id": pid,
            "name": preset["name"],
            "nickname": preset["name"],
            "type": preset["type"],
            "personality_type": preset["type"],
            "default_relationship": preset.get("default_relationship", "暧昧"),
            "source": "builtin",
            "gender": preset.get("gender", ""),
            "is_builtin": True,
        })

    # 数据库自定义预设
    custom = db.list_presets()
    for c in custom:
        c["source"] = "custom"
        c["is_builtin"] = False

    return {"presets": builtins + custom}


@router.get("/variables")
async def get_longform_variables(
    personality: str = "",
    relationship: str = "暧昧",
    gender: str = "男",
):
    """根据性格+关系+性别 返回长文专属变量（persona/narrative_style/关系联动）"""
    return _build_longform_variables(personality, relationship, gender)


@router.get("/{preset_type}/variables")
async def get_preset_type_variables(
    preset_type: str,
    gender: str = Query("男"),
    relationship: str = Query("暧昧"),
):
    """前端联动接口：按性格类型返回变量块。"""
    return _build_longform_variables(preset_type, relationship, gender)


@router.get("/{preset_id}")
async def get_preset(preset_id: str):
    """获取预设角色详情（含完整变量配置）"""
    # 先查内置
    if preset_id in PRESET_CHARACTERS:
        preset = PRESET_CHARACTERS[preset_id]
        return {
            "id": preset_id,
            "name": preset["name"],
            "type": preset["type"],
            "source": "builtin",
            "is_builtin": True,
            "config": _build_builtin_config(preset_id),
        }

    # 再查数据库
    custom = db.get_preset(preset_id)
    if not custom:
        raise HTTPException(status_code=404, detail=f"预设不存在: {preset_id}")
    custom["source"] = "custom"
    custom["is_builtin"] = False
    return custom


@router.post("")
async def create_preset(data: PresetCreate):
    """创建自定义预设"""
    preset_id = db.create_preset(data.name, data.type, data.config)
    return {"id": preset_id, "message": "预设已创建"}


@router.post("/save")
async def save_as_preset(data: PresetCreate):
    """保存当前配置为角色模板（v5.0 Phase 1）"""
    preset_id = db.create_preset(data.name, data.type, data.config)
    return {
        "id": preset_id,
        "message": f"已保存为角色模板: {data.name}",
    }


@router.delete("/{preset_id}")
async def delete_preset(preset_id: str):
    """删除自定义预设。"""
    if preset_id in PRESET_CHARACTERS:
        raise HTTPException(status_code=403, detail="内置模板不可删除")
    if not db.delete_preset(preset_id):
        raise HTTPException(status_code=404, detail=f"预设不存在: {preset_id}")
    return {"id": preset_id, "message": "预设已删除"}


@router.post("/configs/import", tags=["configs"])
async def import_config_excel():
    """导入 Excel 配置文件（v5.0）"""
    from fastapi import UploadFile, File
    # 占位——实际实现需要 UploadFile 参数
    # 完整实现将在前端对接时补全
    return {"message": "配置导入 API 已就绪（待前端对接）"}


