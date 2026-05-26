from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
SERVER_DIR = PROJECT_DIR / "server"

if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services.runtime_config import (  # noqa: E402
    build_longform_variable_bundle,
    apply_relationship_defaults,
    apply_runtime_defaults,
    apply_temporal_defaults,
    normalize_longform_config_contract,
    normalize_frontend_aliases,
)


class _PromptServiceStub:
    @staticmethod
    def load_intimacy_boundary(relationship: str) -> str:
        return f"{relationship}-边界"

    @staticmethod
    def load_persona_block(persona_file: str, gender: str, relationship: str, personal_type: str = "") -> str:
        return f"persona:{persona_file}:{gender}:{relationship}:{personal_type}"

    @staticmethod
    def load_narrative_style(personality: str) -> str:
        return f"style:{personality}"

    @staticmethod
    def resolve_few_shot_reference(
        few_shot_path: str,
        personal_type: str = "",
        gender: str = "",
        relationship: str = "",
    ) -> tuple[None, str]:
        return None, few_shot_path


def test_request_config_helpers_fill_aliases_temporal_and_relationship_defaults():
    config = {
        "character": {"personality": "理性沉稳"},
        "context": {
            "relationship": "暧昧",
            "scene": "客厅",
            "time_period": "深夜",
            "user_nickname": "小鹿",
            "user_gender": "女",
            "user_identity": "测试身份",
        },
        "modules": {"longform_few_shot": "few-shot.md"},
    }

    normalize_frontend_aliases(config)
    apply_temporal_defaults(config, now=datetime(2026, 3, 25, 20, 15))
    apply_relationship_defaults(
        config,
        relationship_presets={
            "暧昧": {
                "relation_calling": "直呼名字",
                "relation_info": "暧昧关系说明",
            }
        },
        prompt_service=_PromptServiceStub(),
    )

    assert config["character"]["personal_type"] == "理性沉稳"
    assert config["context"]["current_scene"] == "客厅"
    assert config["context"]["timeperiod"] == "深夜"
    assert config["modules"]["user_Nickname"] == "小鹿"
    assert config["modules"]["user_gender"] == "女"
    assert config["modules"]["user_identity"] == "测试身份"
    assert config["few_shot_file"] == "few-shot.md"
    assert config["context"]["currentTime"] == "2026-03-25 20:15"
    assert config["context"]["weekDay"] == "星期三"
    assert config["context"]["season"] == "春季"
    assert config["context"]["完整时间信息"] == "2026-03-25 20:15 / 星期三 / 深夜 / 春季"
    assert config["context"]["intimacy_boundary"] == "暧昧-边界"
    assert config["context"]["relation_calling"] == "直呼名字"
    assert config["context"]["relation_info"] == "暧昧关系说明"


def test_apply_runtime_defaults_sets_prompt_and_runtime_fields():
    config = {}

    apply_runtime_defaults(
        config,
        model_id="doubao-pro",
        summary_interval=0,
        injection_depth=0,
        temperature=0.8,
        top_p=0.9,
        prompt_file="星朋友长文模式_提示词_v2.4_20260325.md",
    )

    assert config["prompt_file"] == "星朋友长文模式_提示词_v2.4_20260325.md"
    assert config["runtime"]["summary_interval"] == 5
    assert config["runtime"]["injection_depth"] == 4
    assert config["runtime"]["model_ids"] == ["doubao-pro"]
    assert config["runtime"]["temperature"] == 0.8
    assert config["runtime"]["top_p"] == 0.9
    assert config["runtime"]["schema_version"] == "2026-05-22"
    assert config["runtime_schema_version"] == "2026-05-22"


def test_normalize_longform_config_contract_aligns_web_and_cli_payloads():
    web_payload = {
        "model_id": "deepseek-v4-pro",
        "model_ids": ["deepseek-v4-pro", "qwen-plus"],
        "compare_mode": "model",
        "model_mini": "doubao-lite",
        "scoring_model_id": "qwen-plus",
        "profile_model_id": "deepseek-profile",
        "profile_prompt_version": "profile-latest",
        "thinking_enabled": True,
        "thinking_effort": "max",
        "scoring_thinking_enabled": False,
        "scoring_thinking_effort": "disabled",
        "summary_interval": "0",
        "injection_depth": "0",
        "temperature": "0.8",
        "top_p": "0.9",
        "prompt_version": "latest",
        "few_shot_file": "fewshot.md",
        "turns": "第一轮\n第二轮",
        "character": {"Role_Nickname": "阿衡", "personality": "理性沉稳"},
        "context": {"scene": "雨夜", "time_period": "深夜", "user_nickname": "小鹿"},
        "modules": {"longform_few_shot": "fewshot.md", "monthly_schedule": "周末约会"},
        "custom_variables": {"moments": "刚发了朋友圈", "monthly_schedule": "周末约会"},
    }
    cli_config = {
        "prompt_file": "latest",
        "few_shot_file": "fewshot.md",
        "turns": ["第一轮", "第二轮"],
        "character": {"Role_Nickname": "阿衡", "personal_type": "理性沉稳"},
        "context": {
            "current_scene": "雨夜",
            "timeperiod": "深夜",
            "user_nickname": "小鹿",
        },
        "modules": {"longform_few_shot": "fewshot.md", "monthly_schedule": "周末约会"},
        "custom_variables": {"moments": "刚发了朋友圈", "monthly_schedule": "周末约会"},
        "runtime": {
            "model_ids": ["deepseek-v4-pro", "qwen-plus"],
            "compare_mode": "model",
            "model_mini": "doubao-lite",
            "scoring_model_id": "qwen-plus",
            "profile_model_id": "deepseek-profile",
            "profile_prompt_version": "profile-latest",
            "thinking_enabled": True,
            "thinking_effort": "max",
            "scoring_thinking_enabled": False,
            "scoring_thinking_effort": "disabled",
            "summary_interval": 1,
            "injection_depth": 1,
            "temperature": 0.8,
            "top_p": 0.9,
        },
    }

    normalized_web = normalize_longform_config_contract(web_payload)
    normalized_cli = normalize_longform_config_contract(cli_config)

    assert normalized_web["runtime_schema_version"] == "2026-05-22"
    assert normalized_web["runtime"]["schema_version"] == "2026-05-22"
    assert normalized_web["turns"] == normalized_cli["turns"] == ["第一轮", "第二轮"]
    assert normalized_web["runtime"]["model_ids"] == normalized_cli["runtime"]["model_ids"]
    assert normalized_web["runtime"]["compare_mode"] == normalized_cli["runtime"]["compare_mode"] == "model"
    assert normalized_web["runtime"]["profile_model_id"] == normalized_cli["runtime"]["profile_model_id"] == "deepseek-profile"
    assert normalized_web["runtime"]["profile_prompt_version"] == normalized_cli["runtime"]["profile_prompt_version"] == "profile-latest"
    assert normalized_web["runtime"]["thinking_effort"] == "max"
    assert normalized_web["runtime"]["scoring_thinking_enabled"] is False
    assert normalized_web["runtime"]["summary_interval"] == 1
    assert normalized_web["runtime"]["injection_depth"] == 1
    assert normalized_web["context"]["current_scene"] == normalized_cli["context"]["current_scene"]
    assert normalized_web["context"]["timeperiod"] == normalized_cli["context"]["timeperiod"]
    assert normalized_web["modules"]["user_Nickname"] == normalized_cli["modules"]["user_Nickname"]
    assert normalized_web["custom_variables"] == normalized_cli["custom_variables"]


def test_build_longform_variable_bundle_reuses_same_prompt_and_relationship_logic():
    bundle = build_longform_variable_bundle(
        personality="理性沉稳",
        relationship="暧昧",
        gender="男",
        preset_characters={
            "demo": {
                "type": "理性沉稳",
                "persona_file": "persona-demo.md",
                "few_shot_file": "few-shot-demo.md",
            }
        },
        relationship_presets={
            "暧昧": {
                "relation_calling": "直呼名字",
                "relation_info": "暧昧关系说明",
            }
        },
        prompt_service=_PromptServiceStub(),
    )

    assert bundle["longform_persona"] == "persona:persona-demo.md:男:暧昧:理性沉稳"
    assert bundle["longform_narrative_style"] == "style:理性沉稳"
    assert bundle["longform_few_shot"] == "few-shot-demo.md"
    assert bundle["intimacy_boundary"] == "暧昧-边界"
    assert bundle["relation_calling"] == "直呼名字"
    assert bundle["relation_info"] == "暧昧关系说明"


def test_build_longform_variable_bundle_passes_relationship_to_few_shot_resolution():
    class _RelationshipAwarePromptService(_PromptServiceStub):
        def __init__(self):
            self.relationship_calls = []

        def resolve_few_shot_reference(
            self,
            few_shot_path: str,
            personal_type: str = "",
            gender: str = "",
            relationship: str = "",
        ) -> tuple[None, str]:
            self.relationship_calls.append(relationship)
            return None, f"{few_shot_path}:{relationship}"

    prompt_service = _RelationshipAwarePromptService()
    bundle = build_longform_variable_bundle(
        personality="理性沉稳",
        relationship="恋人",
        gender="男",
        preset_characters={
            "demo": {
                "type": "理性沉稳",
                "persona_file": "persona-demo.md",
                "few_shot_file": "few-shot-demo.md",
            }
        },
        relationship_presets={
            "恋人": {
                "relation_calling": "专属昵称",
                "relation_info": "恋人关系说明",
            }
        },
        prompt_service=prompt_service,
    )

    assert prompt_service.relationship_calls == ["恋人"]
    assert bundle["longform_few_shot"] == "few-shot-demo.md:恋人"
