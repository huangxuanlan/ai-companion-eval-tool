"""
运行时配置模型。

仅约束长文消息生成链路内部真正需要的字段，避免继续在 service 内部
用裸 dict 传递关键运行时状态。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from config import (
    DEFAULT_INJECTION_DEPTH,
    DEFAULT_PRIMARY_MODEL,
    DEFAULT_SCORING_MODEL,
    DEFAULT_SUMMARY_INTERVAL,
    PUBLIC_DEMO_MODE,
    DEFAULT_VOICE_FORBIDDEN,
)

RUNTIME_CONFIG_SCHEMA_VERSION = "2026-05-22"
THINKING_EFFORT_VALUES = {"disabled", "low", "medium", "high", "max"}
CHARACTER_CONTRACT_KEYS = (
    "Role_Nickname", "gender", "age", "occupation", "personality",
    "personal_type", "Role_info_works", "speaking_style", "background", "hobby",
)
CONTEXT_CONTRACT_KEYS = (
    "relationship", "scene", "current_scene", "time_period", "timeperiod",
    "season", "currentTime", "weekDay", "完整时间信息", "last_cst_type",
    "intimacy_boundary", "relation_calling", "relation_info", "user_nickname",
    "user_gender", "user_identity", "relation_rule4", "system_module11",
)
MODULE_CONTRACT_KEYS = (
    "longform_persona", "longform_narrative_style",
    "longform_dialogue_guideline", "longform_few_shot", "dialogueStartPrompt",
    "dialogue_summary", "moments", "monthly_schedule", "weekly_schedule",
    "system_module8", "system_Role_acting", "voice_forbidden", "system_prompt",
    "user_Nickname", "user_gender", "user_identity",
)


def _clean_mapping(value: Any, keys: tuple[str, ...] | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    if keys is None:
        return dict(value)
    return {key: value[key] for key in keys if key in value}


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "开启"}:
        return True
    if text in {"0", "false", "no", "n", "off", "关闭"}:
        return False
    return None


def _bounded_int(
    value: Any,
    default: int,
    *,
    minimum: int,
    maximum: int | None = None,
) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


def _optional_float(value: Any, *, minimum: float, maximum: float) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return max(minimum, min(maximum, number))


def _thinking_effort(value: Any, default: str = "disabled") -> str:
    text = str(value or "").strip().lower()
    return text if text in THINKING_EFFORT_VALUES else default


def normalize_longform_config_contract(config: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize Web, CLI, and fixture configs to the same longform contract."""
    source = dict(config or {})
    runtime_source = _clean_mapping(source.get("runtime"))
    character = _clean_mapping(source.get("character"), CHARACTER_CONTRACT_KEYS)
    context = _clean_mapping(source.get("context"), CONTEXT_CONTRACT_KEYS)
    modules = _clean_mapping(source.get("modules"), MODULE_CONTRACT_KEYS)
    custom_variables = _clean_mapping(source.get("custom_variables"))

    if context.get("current_scene") and not context.get("scene"):
        context["scene"] = context["current_scene"]
    if context.get("scene") and not context.get("current_scene"):
        context["current_scene"] = context["scene"]
    if context.get("timeperiod") and not context.get("time_period"):
        context["time_period"] = context["timeperiod"]
    if context.get("time_period") and not context.get("timeperiod"):
        context["timeperiod"] = context["time_period"]
    if context.get("user_nickname") and not modules.get("user_Nickname"):
        modules["user_Nickname"] = context["user_nickname"]
    if context.get("user_gender") and not modules.get("user_gender"):
        modules["user_gender"] = context["user_gender"]
    if context.get("user_identity") and not modules.get("user_identity"):
        modules["user_identity"] = context["user_identity"]
    if character.get("personality") and not character.get("personal_type"):
        character["personal_type"] = character["personality"]
    if modules.get("longform_few_shot") and not source.get("few_shot_file"):
        source["few_shot_file"] = modules["longform_few_shot"]
    modules.setdefault("voice_forbidden", DEFAULT_VOICE_FORBIDDEN)

    model_ids = source.get("model_ids") or runtime_source.get("model_ids") or []
    if not isinstance(model_ids, list):
        model_ids = [model_ids]
    model_ids = [str(item).strip() for item in model_ids if str(item or "").strip()]
    model_id = str(
        source.get("model_id")
        or runtime_source.get("model_id")
        or (model_ids[0] if model_ids else "")
        or DEFAULT_PRIMARY_MODEL
        or ""
    ).strip()
    if model_id and model_id not in model_ids:
        model_ids.insert(0, model_id)

    scoring_model_id = str(
        source.get("scoring_model_id")
        or runtime_source.get("scoring_model_id")
        or DEFAULT_SCORING_MODEL
        or model_id
        or ""
    ).strip()
    summary_interval = _bounded_int(
        source.get("summary_interval", runtime_source.get("summary_interval")),
        DEFAULT_SUMMARY_INTERVAL,
        minimum=1,
    )
    injection_depth = _bounded_int(
        source.get("injection_depth", runtime_source.get("injection_depth")),
        DEFAULT_INJECTION_DEPTH,
        minimum=1,
    )
    scoring_max_workers = _bounded_int(
        source.get("scoring_max_workers", runtime_source.get("scoring_max_workers")),
        2,
        minimum=1,
        maximum=24,
    )
    scoring_retry_count = _bounded_int(
        source.get("scoring_retry_count", runtime_source.get("scoring_retry_count")),
        3,
        minimum=0,
        maximum=10,
    )

    thinking_enabled = _optional_bool(
        source.get("thinking_enabled", runtime_source.get("thinking_enabled"))
    )
    scoring_thinking_enabled = _optional_bool(
        source.get(
            "scoring_thinking_enabled",
            runtime_source.get("scoring_thinking_enabled"),
        )
    )
    runtime = {
        "schema_version": RUNTIME_CONFIG_SCHEMA_VERSION,
        "model_ids": model_ids,
        "compare_mode": str(
            source.get("compare_mode") or runtime_source.get("compare_mode") or ""
        ).strip(),
        "model_mini": str(
            source.get("model_mini") or runtime_source.get("model_mini") or ""
        ).strip(),
        "scoring_model_id": scoring_model_id,
        "profile_model_id": str(
            source.get("profile_model_id")
            or runtime_source.get("profile_model_id")
            or ""
        ).strip(),
        "prompt_version": str(
            source.get("prompt_version") or runtime_source.get("prompt_version") or ""
        ).strip(),
        "summary_prompt_version": str(
            source.get("summary_prompt_version")
            or runtime_source.get("summary_prompt_version")
            or ""
        ).strip(),
        "scoring_prompt_version": str(
            source.get("scoring_prompt_version")
            or runtime_source.get("scoring_prompt_version")
            or ""
        ).strip(),
        "profile_prompt_version": str(
            source.get("profile_prompt_version")
            or runtime_source.get("profile_prompt_version")
            or ""
        ).strip(),
        "summary_interval": summary_interval,
        "injection_depth": injection_depth,
        "thinking_effort": _thinking_effort(
            source.get("thinking_effort", runtime_source.get("thinking_effort")),
        ),
        "scoring_thinking_effort": _thinking_effort(
            source.get(
                "scoring_thinking_effort",
                runtime_source.get("scoring_thinking_effort"),
            ),
        ),
        "scoring_max_workers": scoring_max_workers,
        "scoring_retry_count": scoring_retry_count,
    }
    if thinking_enabled is not None:
        runtime["thinking_enabled"] = thinking_enabled
    if scoring_thinking_enabled is not None:
        runtime["scoring_thinking_enabled"] = scoring_thinking_enabled
    temperature = _optional_float(
        source.get("temperature", runtime_source.get("temperature")),
        minimum=0.0,
        maximum=2.0,
    )
    if temperature is not None:
        runtime["temperature"] = temperature
    top_p = _optional_float(
        source.get("top_p", runtime_source.get("top_p")),
        minimum=0.0,
        maximum=1.0,
    )
    if top_p is not None:
        runtime["top_p"] = top_p
    for key in ("dry_run", "auto_scoring"):
        value = _optional_bool(source.get(key, runtime_source.get(key)))
        if value is not None:
            runtime[key] = value

    turns = source.get("turns", [])
    if isinstance(turns, str):
        turns = [line for line in turns.splitlines() if line.strip()]
    elif not isinstance(turns, list):
        turns = []

    return {
        "runtime_schema_version": RUNTIME_CONFIG_SCHEMA_VERSION,
        "model_id": model_id,
        "model_ids": model_ids,
        "compare_mode": runtime["compare_mode"],
        "model_mini": runtime["model_mini"],
        "scoring_model_id": scoring_model_id,
        "profile_model_id": runtime["profile_model_id"],
        "prompt_version": runtime["prompt_version"],
        "summary_prompt_version": runtime["summary_prompt_version"],
        "scoring_prompt_version": runtime["scoring_prompt_version"],
        "profile_prompt_version": runtime["profile_prompt_version"],
        "summary_interval": runtime["summary_interval"],
        "injection_depth": runtime["injection_depth"],
        "thinking_enabled": runtime.get("thinking_enabled"),
        "thinking_effort": runtime["thinking_effort"],
        "scoring_thinking_enabled": runtime.get("scoring_thinking_enabled"),
        "scoring_thinking_effort": runtime["scoring_thinking_effort"],
        "scoring_max_workers": runtime["scoring_max_workers"],
        "scoring_retry_count": runtime["scoring_retry_count"],
        "temperature": runtime.get("temperature"),
        "top_p": runtime.get("top_p"),
        "dry_run": runtime.get("dry_run", False),
        "auto_scoring": runtime.get("auto_scoring", True),
        "prompt_file": str(
            source.get("prompt_file")
            or runtime.get("prompt_version")
            or ""
        ).strip(),
        "few_shot_file": str(source.get("few_shot_file") or "").strip(),
        "turns": turns,
        "character": character,
        "context": context,
        "modules": modules,
        "custom_variables": custom_variables,
        "runtime": runtime,
    }


def normalize_frontend_aliases(config: dict[str, Any]) -> None:
    """兼容旧前端字段命名，统一为核心链路使用的 key。"""
    context = config.setdefault("context", {})
    modules = config.setdefault("modules", {})
    character = config.setdefault("character", {})

    if context.get("scene") and not context.get("current_scene"):
        context["current_scene"] = context["scene"]
    if context.get("time_period") and not context.get("timeperiod"):
        context["timeperiod"] = context["time_period"]
    if context.get("user_nickname") and not modules.get("user_Nickname"):
        modules["user_Nickname"] = context["user_nickname"]
    if context.get("user_gender") and not modules.get("user_gender"):
        modules["user_gender"] = context["user_gender"]
    if context.get("user_identity") and not modules.get("user_identity"):
        modules["user_identity"] = context["user_identity"]
    if character.get("personality") and not character.get("personal_type"):
        character["personal_type"] = character["personality"]
    if modules.get("longform_few_shot") and not config.get("few_shot_file"):
        config["few_shot_file"] = modules["longform_few_shot"]
    if not modules.get("voice_forbidden"):
        modules["voice_forbidden"] = DEFAULT_VOICE_FORBIDDEN


def apply_relationship_defaults(
    config: dict[str, Any],
    relationship_presets: dict[str, dict[str, str]],
    prompt_service: Any,
) -> None:
    """统一补齐关系阶段默认变量，避免不同入口读取来源分叉。"""
    context = config.setdefault("context", {})
    relationship = context.get("relationship", "暧昧")
    rel_info = relationship_presets.get(relationship, {})

    if not context.get("intimacy_boundary"):
        context["intimacy_boundary"] = prompt_service.load_intimacy_boundary(
            relationship
        )
    if rel_info:
        context.setdefault("relation_calling", rel_info.get("relation_calling", ""))
        context.setdefault("relation_info", rel_info.get("relation_info", ""))


def infer_timeperiod(hour: int) -> str:
    if 5 <= hour < 11:
        return "早晨"
    if 11 <= hour < 14:
        return "中午"
    if 14 <= hour < 18:
        return "下午"
    if 18 <= hour < 23:
        return "傍晚"
    return "深夜"


def infer_season(month: int) -> str:
    if month in (3, 4, 5):
        return "春季"
    if month in (6, 7, 8):
        return "夏季"
    if month in (9, 10, 11):
        return "秋季"
    return "冬季"


def _parse_current_time(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def compose_complete_time_info(
    current_time: str,
    week_day: str,
    timeperiod: str,
    season: str,
) -> str:
    parts = [str(current_time or "").strip(), str(week_day or "").strip()]
    trailing = [str(timeperiod or "").strip(), str(season or "").strip()]
    parts.extend(item for item in trailing if item)
    return " / ".join(item for item in parts if item)


def apply_temporal_defaults(
    config: dict[str, Any],
    now: datetime | None = None,
) -> None:
    """补齐模板强依赖的时空变量，避免 currentTime/weekDay 留空。"""
    context = config.setdefault("context", {})
    current_time = (
        _parse_current_time(context.get("currentTime", ""))
        or now
        or datetime.now()
    )
    weekday_labels = [
        "星期一", "星期二", "星期三", "星期四",
        "星期五", "星期六", "星期日",
    ]

    context.setdefault("currentTime", current_time.strftime("%Y-%m-%d %H:%M"))
    context.setdefault("weekDay", weekday_labels[current_time.weekday()])
    context.setdefault("timeperiod", infer_timeperiod(current_time.hour))
    context.setdefault("season", infer_season(current_time.month))
    context.setdefault(
        "完整时间信息",
        compose_complete_time_info(
            context.get("currentTime", ""),
            context.get("weekDay", ""),
            context.get("timeperiod", ""),
            context.get("season", ""),
        ),
    )


def apply_runtime_defaults(
    config: dict[str, Any],
    *,
    model_id: str,
    model_mini: str = "",
    summary_interval: int,
    injection_depth: int,
    temperature: float | None = None,
    top_p: float | None = None,
    prompt_file: str,
    summary_prompt_version: str = "",
    scoring_prompt_version: str = "",
    scoring_model_id: str = "",
    profile_model_id: str = "",
    profile_prompt_version: str = "",
    thinking_enabled: bool | None = None,
    thinking_effort: str = "",
    scoring_thinking_enabled: bool | None = None,
    scoring_thinking_effort: str = "",
    scoring_max_workers: int | None = None,
    scoring_retry_count: int | None = None,
) -> None:
    """统一补齐运行时字段，避免路由层各自写默认值。"""
    if prompt_file:
        config["prompt_file"] = prompt_file
    modules = config.setdefault("modules", {})
    modules.setdefault("voice_forbidden", DEFAULT_VOICE_FORBIDDEN)
    config.setdefault("runtime", {})
    config["runtime"]["schema_version"] = RUNTIME_CONFIG_SCHEMA_VERSION
    config["runtime_schema_version"] = RUNTIME_CONFIG_SCHEMA_VERSION
    config["runtime"]["summary_interval"] = max(
        1,
        int(summary_interval or DEFAULT_SUMMARY_INTERVAL),
    )
    config["runtime"]["injection_depth"] = int(
        injection_depth or DEFAULT_INJECTION_DEPTH
    )
    config["runtime"]["model_ids"] = [model_id]
    config["runtime"]["model_mini"] = model_mini or ""
    if temperature is not None:
        config["runtime"]["temperature"] = float(temperature)
    if top_p is not None:
        config["runtime"]["top_p"] = float(top_p)
    config["runtime"]["summary_prompt_version"] = str(summary_prompt_version or "").strip()
    config["runtime"]["scoring_prompt_version"] = str(scoring_prompt_version or "").strip()
    config["runtime"]["scoring_model_id"] = str(
        scoring_model_id or DEFAULT_SCORING_MODEL or model_id or DEFAULT_PRIMARY_MODEL or ""
    ).strip()
    if thinking_enabled is not None:
        config["runtime"]["thinking_enabled"] = bool(thinking_enabled)
    if str(thinking_effort or "").strip():
        config["runtime"]["thinking_effort"] = str(thinking_effort).strip()
    if scoring_thinking_enabled is not None:
        config["runtime"]["scoring_thinking_enabled"] = bool(scoring_thinking_enabled)
    if str(scoring_thinking_effort or "").strip():
        config["runtime"]["scoring_thinking_effort"] = str(scoring_thinking_effort).strip()
    if scoring_max_workers is not None:
        config["runtime"]["scoring_max_workers"] = max(
            1,
            min(int(scoring_max_workers), 24),
        )
    if scoring_retry_count is not None:
        config["runtime"]["scoring_retry_count"] = max(
            0,
            min(int(scoring_retry_count), 10),
        )
    config["runtime"]["profile_model_id"] = str(profile_model_id or "").strip()
    config["runtime"]["profile_prompt_version"] = str(profile_prompt_version or "").strip()
    config["runtime"]["public_demo_mode"] = bool(PUBLIC_DEMO_MODE)


def build_longform_variable_bundle(
    *,
    personality: str,
    relationship: str,
    gender: str,
    persona_file: str = "",
    few_shot_file: str = "",
    preset_characters: dict[str, dict[str, Any]],
    relationship_presets: dict[str, dict[str, str]],
    prompt_service: Any,
) -> dict[str, str]:
    """统一构建长文变量块，避免 routes 各自手工拼装。"""
    resolved_persona_file = str(persona_file or "").strip()
    resolved_few_shot_file = str(few_shot_file or "").strip()
    explicit_few_shot_file = resolved_few_shot_file
    if not resolved_persona_file or not resolved_few_shot_file:
        for preset in preset_characters.values():
            if preset.get("type") != personality:
                continue
            if not resolved_persona_file:
                resolved_persona_file = str(preset.get("persona_file", "")).strip()
            if not resolved_few_shot_file:
                resolved_few_shot_file = str(preset.get("few_shot_file", "")).strip()
            if resolved_persona_file and resolved_few_shot_file:
                break
    resolved_few_shot_display = resolved_few_shot_file
    if not explicit_few_shot_file and resolved_few_shot_file and hasattr(
        prompt_service, "resolve_few_shot_reference"
    ):
        _, resolved_few_shot_display = prompt_service.resolve_few_shot_reference(
            resolved_few_shot_file,
            personal_type=personality,
            gender=gender,
            relationship=relationship,
        )
        resolved_few_shot_display = (
            str(resolved_few_shot_display or "").strip() or resolved_few_shot_file
        )

    context = {"relationship": relationship}
    apply_relationship_defaults(
        {"context": context},
        relationship_presets=relationship_presets,
        prompt_service=prompt_service,
    )

    result = {
        "longform_persona": "",
        "longform_narrative_style": "",
        "longform_few_shot": resolved_few_shot_display,
        "intimacy_boundary": context.get("intimacy_boundary", ""),
        "relation_calling": context.get("relation_calling", ""),
        "relation_info": context.get("relation_info", ""),
        "voice_forbidden": DEFAULT_VOICE_FORBIDDEN,
    }
    if resolved_persona_file:
        result["longform_persona"] = prompt_service.load_persona_block(
            resolved_persona_file,
            gender,
            relationship,
            personal_type=personality,
        )
    result["longform_narrative_style"] = prompt_service.load_narrative_style(
        personality
    )
    if hasattr(prompt_service, "load_dialogue_guideline"):
        result["longform_dialogue_guideline"] = prompt_service.load_dialogue_guideline(
            personality
        )
    return result


@dataclass(slots=True)
class LongformRuntimeConfig:
    prompt_file: str
    few_shot_file: str
    role_name: str
    relationship: str
    personal_type: str
    personality: str
    gender: str
    current_scene: str
    injection_depth: int | str
    modules: dict[str, str] = field(default_factory=dict)
    seed_dialogue_summary: str = ""

    @classmethod
    def from_dict(
        cls,
        config: dict[str, Any],
        web_search: bool = False,
    ) -> "LongformRuntimeConfig":
        character = dict(config.get("character", {}) or {})
        context = dict(config.get("context", {}) or {})
        runtime = dict(config.get("runtime", {}) or {})
        modules = dict(config.get("modules", {}) or {})

        if not web_search:
            modules["system_Role_acting"] = ""

        return cls(
            prompt_file=str(config.get("prompt_file", "")).strip(),
            few_shot_file=str(
                config.get("few_shot_file", "") or modules.get("longform_few_shot", "")
            ).strip(),
            role_name=str(character.get("Role_Nickname", "unknown")).strip() or "unknown",
            relationship=str(context.get("relationship", "暧昧")).strip() or "暧昧",
            personal_type=str(
                character.get("personal_type", "") or character.get("personality", "")
            ).strip(),
            personality=str(character.get("personality", "")).strip(),
            gender=str(character.get("gender", "")).strip(),
            current_scene=str(
                context.get("current_scene", "") or context.get("scene", "")
            ).strip(),
            injection_depth=runtime.get(
                "injection_depth",
                DEFAULT_INJECTION_DEPTH,
            ),
            modules=modules,
            seed_dialogue_summary=str(
                modules.get("dialogue_summary", "") or config.get("dialogue_summary", "")
            ).strip(),
        )


@dataclass(slots=True)
class RuntimeBundle:
    few_shot_messages: list[dict]
    rendered_system: str
    rendered_after: str
    relationship: str
    role_name: str
    personal_type: str
    personality: str
    injection_depth: int | str
    memory_profile: str
    memory_moments: str
    seed_dialogue_summary: str
