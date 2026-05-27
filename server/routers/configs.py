"""
配置路由: /api/configs
"""
from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from datetime import datetime

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse

import database as db
from config import (
    DEFAULT_PRIMARY_MODEL,
    DEFAULT_INJECTION_DEPTH,
    DEFAULT_SUMMARY_INTERVAL,
    PRESET_CHARACTERS,
    PROJECT_DIR,
    RELATIONSHIP_PRESETS,
    extract_preset_module_defaults,
)
from models import ConfigSaveRequest
from services.export_service import ExportService
from services.prompt_service import PromptService
from services.runtime_config import (
    build_longform_variable_bundle,
    normalize_longform_config_contract,
)
from services.public_demo import is_public_demo_mode, raise_if_demo_write_blocked

router = APIRouter(prefix="/api/configs", tags=["configs"])

TEMP_DIR = PROJECT_DIR / "output"
TEMP_DIR.mkdir(exist_ok=True)
_export_service = ExportService()
_LONGFORM_MULTI_TURN_MODULE_NAME = "_longform_multi_turn_bridge"

CHAR_KEYS = {
    "Role_Nickname",
    "gender",
    "age",
    "occupation",
    "personality",
    "speaking_style",
    "personal_type",
    "Role_info_works",
    "background",
    "hobby",
}
CHAR_FIELDS = [
    "Role_Nickname",
    "gender",
    "age",
    "occupation",
    "personality",
    "speaking_style",
    "personal_type",
    "Role_info_works",
    "hobby",
    "background",
]
CTX_KEYS = {
    "relationship",
    "relation_info",
    "intimacy_boundary",
    "relation_calling",
    "currentTime",
    "weekDay",
    "timeperiod",
    "season",
    "current_scene",
    "last_cst_type",
    "完整时间信息",
}
CTX_FIELDS = [
    "relationship",
    "relation_info",
    "intimacy_boundary",
    "relation_calling",
    "currentTime",
    "weekDay",
    "timeperiod",
    "season",
    "current_scene",
    "last_cst_type",
    "完整时间信息",
]
MODULE_KEYS = {
    "user_Nickname",
    "user_gender",
    "user_identity",
    "longform_persona",
    "longform_narrative_style",
    "longform_dialogue_guideline",
    "longform_few_shot",
    "dialogueStartPrompt",
    "moments",
    "weekly_schedule",
    "monthly_schedule",
    "system_module8",
    "system_Role_acting",
    "voice_forbidden",
}
MODULE_FIELDS = [
    "user_Nickname",
    "user_gender",
    "user_identity",
    "longform_persona",
    "longform_narrative_style",
    "longform_dialogue_guideline",
    "longform_few_shot",
    "dialogueStartPrompt",
    "moments",
    "weekly_schedule",
    "monthly_schedule",
    "system_module8",
    "system_Role_acting",
    "voice_forbidden",
]
EXPORT_HEADERS = [
    "session_id",
    "turn_order",
    "user_message",
    *CHAR_FIELDS,
    *CTX_FIELDS,
    *MODULE_FIELDS,
    "prompt_file",
    "few_shot_file",
]
VARIABLE_TEMPLATE_ROWS = (
    [{"group": "character", "name": name, "value": ""} for name in CHAR_FIELDS]
    + [{"group": "context", "name": name, "value": ""} for name in CTX_FIELDS]
    + [{"group": "modules/runtime", "name": name, "value": ""} for name in MODULE_FIELDS]
)


def _load_configs_from_excel(file_path: str) -> list[dict]:
    module = sys.modules.get(_LONGFORM_MULTI_TURN_MODULE_NAME)
    if module is None:
        module_path = PROJECT_DIR / "longform_multi_turn.py"
        spec = importlib.util.spec_from_file_location(
            _LONGFORM_MULTI_TURN_MODULE_NAME,
            module_path,
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"无法加载 longform_multi_turn 模块: {module_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[_LONGFORM_MULTI_TURN_MODULE_NAME] = module
        spec.loader.exec_module(module)

    return module.load_config_from_excel(file_path)


def _build_builtin_preset_config(preset_id: str) -> dict:
    prompt_service = PromptService()
    preset = PRESET_CHARACTERS[preset_id]
    relationship = preset.get("default_relationship", "暧昧")
    gender = preset.get("gender", "")
    personal_type = preset.get("type", "")
    defaults = preset.get("character_defaults", {})
    variable_bundle = build_longform_variable_bundle(
        personality=personal_type,
        relationship=relationship,
        gender=gender,
        persona_file=preset.get("persona_file", ""),
        few_shot_file=preset.get("few_shot_file", ""),
        preset_characters=PRESET_CHARACTERS,
        relationship_presets=RELATIONSHIP_PRESETS,
        prompt_service=prompt_service,
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
        },
        "runtime": {
            "model_ids": [DEFAULT_PRIMARY_MODEL],
            "summary_interval": DEFAULT_SUMMARY_INTERVAL,
            "injection_depth": DEFAULT_INJECTION_DEPTH,
        },
    }


def _derive_config_name(config: dict) -> str:
    role_name = config.get("character", {}).get("Role_Nickname", "").strip()
    if role_name:
        return role_name
    return f"config_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def _has_snapshot_content(config: dict) -> bool:
    if config.get("prompt_file") or config.get("few_shot_file"):
        return True
    for section in ("character", "context", "modules", "runtime"):
        if config.get(section):
            return True
    return False


def _normalize_save_payload(data: ConfigSaveRequest) -> tuple[str, str, dict]:
    config = data.config.copy() if isinstance(data.config, dict) else {}
    if not config:
        config = {
            "character": data.character or {},
            "context": data.context or {},
            "modules": data.modules or {},
            "runtime": data.runtime or {},
        }
        if data.prompt_file:
            config["prompt_file"] = data.prompt_file
        if data.few_shot_file:
            config["few_shot_file"] = data.few_shot_file

    if not isinstance(config, dict) or not config:
        raise HTTPException(status_code=400, detail="缺少 config 配置快照")

    config.setdefault("character", {})
    config.setdefault("context", {})
    config.setdefault("modules", {})
    if data.runtime is not None:
        config["runtime"] = data.runtime
    else:
        config.setdefault("runtime", {})

    if data.prompt_file and not config.get("prompt_file"):
        config["prompt_file"] = data.prompt_file
    if data.few_shot_file and not config.get("few_shot_file"):
        config["few_shot_file"] = data.few_shot_file
    if not config.get("few_shot_file"):
        modules = config.get("modules", {})
        if isinstance(modules, dict) and modules.get("longform_few_shot"):
            config["few_shot_file"] = modules["longform_few_shot"]

    if not _has_snapshot_content(config):
        raise HTTPException(status_code=400, detail="config 不能为空")

    config = normalize_longform_config_contract(config)
    name = (data.name or _derive_config_name(config)).strip()
    type_ = (data.type or "").strip() or "custom_config"
    return name, type_, config


def _resolve_config_snapshot(config_id: str) -> tuple[dict, list[str], str]:
    saved_config = db.get_saved_config(config_id)
    if saved_config:
        return saved_config.get("config", {}), [], "saved_config"

    conversation = db.get_conversation(config_id)
    if conversation:
        turns = [row.get("user_input", "") for row in conversation.get("results", [])]
        return conversation.get("config", {}), turns, "conversation"

    if config_id in PRESET_CHARACTERS:
        return _build_builtin_preset_config(config_id), [], "builtin_preset"

    preset = db.get_preset(config_id)
    if preset:
        return preset.get("config", {}), [], "custom_preset"

    raise HTTPException(status_code=404, detail=f"配置不存在: {config_id}")


def _flatten_variables(config: dict) -> list[dict]:
    variables = PromptService.build_variables(config)
    rows = []
    for key, value in variables.items():
        if key in CHAR_KEYS:
            group = "character"
        elif key in CTX_KEYS:
            group = "context"
        else:
            group = "modules/runtime"
        rows.append({"group": group, "name": key, "value": value})
    rows.sort(key=lambda item: (item["group"], item["name"]))
    return rows


def _rows_from_config(config_id: str, config: dict, turns: list[str]) -> list[dict]:
    character = config.get("character", {})
    context = config.get("context", {})
    modules = config.get("modules", {})
    if not turns:
        turns = [""]

    rows = []
    for idx, user_message in enumerate(turns, start=1):
        rows.append(
            {
                "session_id": config_id,
                "turn_order": idx,
                "user_message": user_message,
                "Role_Nickname": character.get("Role_Nickname", ""),
                "gender": character.get("gender", ""),
                "age": character.get("age", ""),
                "occupation": character.get("occupation", ""),
                "personality": character.get("personality", ""),
                "speaking_style": character.get("speaking_style", ""),
                "personal_type": character.get("personal_type", ""),
                "Role_info_works": character.get("Role_info_works", ""),
                "hobby": character.get("hobby", ""),
                "background": character.get("background", ""),
                "user_Nickname": modules.get("user_Nickname", ""),
                "user_gender": modules.get("user_gender", ""),
                "user_identity": modules.get("user_identity", ""),
                "relationship": context.get("relationship", ""),
                "relation_info": context.get("relation_info", ""),
                "intimacy_boundary": context.get("intimacy_boundary", ""),
                "relation_calling": context.get("relation_calling", ""),
                "currentTime": context.get("currentTime", ""),
                "weekDay": context.get("weekDay", ""),
                "timeperiod": context.get("timeperiod", ""),
                "season": context.get("season", ""),
                "current_scene": context.get("current_scene", ""),
                "last_cst_type": context.get("last_cst_type", ""),
                "完整时间信息": context.get("完整时间信息", ""),
                "longform_narrative_style": modules.get(
                    "longform_narrative_style",
                    "",
                ),
                "longform_persona": modules.get("longform_persona", ""),
                "longform_dialogue_guideline": modules.get("longform_dialogue_guideline", ""),
                "longform_few_shot": modules.get("longform_few_shot", ""),
                "dialogueStartPrompt": modules.get("dialogueStartPrompt", ""),
                "moments": modules.get("moments", ""),
                "system_module8": modules.get("system_module8", ""),
                "weekly_schedule": modules.get("weekly_schedule", ""),
                "monthly_schedule": modules.get("monthly_schedule", ""),
                "system_Role_acting": modules.get("system_Role_acting", ""),
                "voice_forbidden": modules.get("voice_forbidden", ""),
                "prompt_file": config.get("prompt_file", ""),
                "few_shot_file": config.get("few_shot_file", ""),
            }
        )
    return rows


def _blank_row(headers: list[str]) -> dict[str, str]:
    return {header: "" for header in headers}


def _parse_variable_payload(filename: str, content: bytes) -> dict[str, str]:
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix == "json":
        raw = json.loads(content.decode("utf-8"))
        if isinstance(raw, dict):
            return {str(k): str(v) for k, v in raw.items()}
        if isinstance(raw, list):
            parsed = {}
            for item in raw:
                if not isinstance(item, dict):
                    continue
                name = item.get("name") or item.get("变量名")
                if not name:
                    continue
                parsed[str(name)] = str(item.get("value") or item.get("变量值") or "")
            return parsed
        raise HTTPException(status_code=400, detail="JSON 变量格式不支持")

    if suffix not in {"xlsx", "xls"}:
        raise HTTPException(status_code=400, detail="仅支持 .xlsx/.xls/.json 文件")

    temp_path = TEMP_DIR / f"variables_{uuid.uuid4().hex}.{suffix}"
    temp_path.write_bytes(content)
    try:
        rows = _export_service.import_from_excel(str(temp_path))
    finally:
        if temp_path.exists():
            temp_path.unlink()

    variables = {}
    for row in rows:
        name = row.get("变量名") or row.get("name") or next(iter(row.values()), "")
        value = row.get("变量值") or row.get("value") or (
            list(row.values())[1] if len(row) > 1 else ""
        )
        if name:
            variables[str(name)] = str(value or "")
    return variables


def _variables_to_config(variables: dict[str, str]) -> dict:
    config = {
        "character": {},
        "context": {},
        "modules": {},
    }
    for key, value in variables.items():
        if key in CHAR_KEYS:
            config["character"][key] = value
        elif key in CTX_KEYS:
            config["context"][key] = value
        else:
            config["modules"][key] = value
    return config


@router.post("")
async def save_config(data: ConfigSaveRequest):
    """保存自定义配置快照。"""
    name, type_, config = _normalize_save_payload(data)
    if is_public_demo_mode():
        return {
            "id": f"demo-config-{uuid.uuid4().hex[:8]}",
            "name": name,
            "type": type_,
            "message": "演示模式下未持久保存，仅用于本次会话",
            "ephemeral": True,
            "config": config,
        }
    config_id = db.create_saved_config(name, config, type_, mode=data.mode or "long")
    return {
        "id": config_id,
        "name": name,
        "type": type_,
        "message": "配置已保存",
    }


@router.get("")
async def list_configs(mode: str = Query(default="long")):
    """列出当前可复用的配置快照。"""
    items = []

    if not is_public_demo_mode():
        for saved in db.list_saved_configs(mode=mode):
            config = saved.get("config", {})
            items.append(
                {
                    "id": saved["id"],
                    "source": "saved_config",
                    "name": saved.get("name", saved["id"]),
                    "type": saved.get("type", ""),
                    "relationship": config.get("context", {}).get("relationship", ""),
                    "prompt_file": config.get("prompt_file", ""),
                    "turns_count": 0,
                    "created_at": saved.get("created_at"),
                }
            )

    if mode == "long":
        for preset_id, preset in PRESET_CHARACTERS.items():
            items.append(
                {
                    "id": preset_id,
                    "source": "builtin_preset",
                    "name": preset.get("name", preset_id),
                    "type": preset.get("type", ""),
                    "relationship": preset.get("default_relationship", "暧昧"),
                    "prompt_file": preset.get("prompt_file", ""),
                    "turns_count": 0,
                }
            )

    if not is_public_demo_mode():
        for preset in db.list_presets(mode=mode):
            items.append(
                {
                    "id": preset["id"],
                    "source": "custom_preset",
                    "name": preset.get("name", preset["id"]),
                    "type": preset.get("type", ""),
                    "relationship": "",
                    "prompt_file": "",
                    "turns_count": 0,
                    "created_at": preset.get("created_at"),
                }
            )

        for conversation in db.list_conversations(mode=mode):
            items.append(
                {
                    "id": conversation["id"],
                    "source": "conversation",
                    "name": conversation.get("nickname", conversation["id"]),
                    "type": "",
                    "relationship": conversation.get("relationship", ""),
                    "prompt_file": "",
                    "turns_count": conversation.get("total_turns", 0),
                    "created_at": conversation.get("created_at"),
                }
            )

    return {"configs": items}


@router.post("/import")
async def import_configs(file: UploadFile = File(...)):
    """导入批量测试配置 Excel。"""
    filename = file.filename or ""
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix not in {"xlsx", "xls"}:
        raise HTTPException(status_code=400, detail="仅支持 .xlsx/.xls 文件")

    temp_path = TEMP_DIR / f"configs_{uuid.uuid4().hex}.{suffix}"
    with temp_path.open("wb") as handle:
        handle.write(await file.read())

    try:
        configs = _load_configs_from_excel(str(temp_path))
        preview = []
        for config in configs[:5]:
            preview.append(
                {
                    "mode": config.get("_mode", ""),
                    "session_id": config.get("_session_id", ""),
                    "turns_count": len(config.get("turns", [])),
                    "role_name": config.get("character", {}).get("Role_Nickname", ""),
                    "relationship": config.get("context", {}).get("relationship", ""),
                    "prompt_file": config.get("prompt_file", ""),
                }
            )
        return {"count": len(configs), "preview": preview}
    finally:
        if temp_path.exists():
            temp_path.unlink()


@router.post("/variables/import")
async def import_variables(file: UploadFile = File(...)):
    """导入变量表并转换为标准 config 结构。"""
    filename = file.filename or ""
    content = await file.read()
    variables = _parse_variable_payload(filename, content)
    config = _variables_to_config(variables)
    return {
        "count": len(variables),
        "variables": variables,
        "config": config,
    }


@router.get("/export-template")
async def export_config_template():
    """下载空白批量测试对话模板。"""
    filename = "长文模式_对话模板.xlsx"
    output_path = TEMP_DIR / filename
    rows = [_blank_row(EXPORT_HEADERS)]
    _export_service.export_rows_to_excel(rows, str(output_path), sheet_name="对话模板")
    return FileResponse(
        path=str(output_path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/export")
async def export_config_template_legacy():
    """兼容旧前端路径：/api/configs/export -> 模板下载。"""
    return await export_config_template()


@router.get("/variables/template/export")
async def export_variable_template():
    """下载空白变量表模板。"""
    filename = "长文模式_变量表模板.xlsx"
    output_path = TEMP_DIR / filename
    rows = VARIABLE_TEMPLATE_ROWS
    _export_service.export_rows_to_excel(rows, str(output_path), sheet_name="变量模板")
    return FileResponse(
        path=str(output_path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/{config_id}/export")
async def export_config(config_id: str):
    """导出指定配置为 Excel。"""
    raise_if_demo_write_blocked("演示模式下禁止导出历史配置快照")
    config, turns, _ = _resolve_config_snapshot(config_id)
    rows = _rows_from_config(config_id, config, turns)

    timestamp = uuid.uuid4().hex[:8]
    filename = f"config_{config_id}_{timestamp}.xlsx"
    output_path = TEMP_DIR / filename
    _export_service.export_rows_to_excel(rows, str(output_path), sheet_name="配置导出")
    return FileResponse(
        path=str(output_path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/{config_id}/variables/export")
async def export_config_variables(
    config_id: str,
    format: str = Query("xlsx", pattern="^(xlsx|json)$"),
):
    """导出指定配置的全部变量。"""
    raise_if_demo_write_blocked("演示模式下禁止导出历史配置变量")
    config, _, _ = _resolve_config_snapshot(config_id)
    rows = _flatten_variables(config)

    if format == "json":
        return JSONResponse({"config_id": config_id, "variables": rows})

    timestamp = uuid.uuid4().hex[:8]
    filename = f"variables_{config_id}_{timestamp}.xlsx"
    output_path = TEMP_DIR / filename
    _export_service.export_rows_to_excel(rows, str(output_path), sheet_name="变量表")
    return FileResponse(
        path=str(output_path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
