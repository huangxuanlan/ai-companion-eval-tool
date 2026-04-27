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
