from __future__ import annotations

import asyncio
import os
import sys
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_DIR = Path(__file__).resolve().parent
SERVER_DIR = PROJECT_DIR / "server"
os.environ.setdefault(
    "LONGFORM_DB_PATH",
    str(PROJECT_DIR / "output" / "test_runtime" / "narrative_var_dual_read.db"),
)

if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import config  # noqa: E402
import database as db  # noqa: E402
from main import app  # noqa: E402
from routers import chat as chat_router  # noqa: E402
from routers import configs as configs_router  # noqa: E402
from routers import conversations as conversations_router  # noqa: E402
from routers import presets as presets_router  # noqa: E402
from services import conversation_service as conversation_service_module  # noqa: E402
from services import prompt_service as prompt_service_module  # noqa: E402
from services import scoring_service as scoring_service_module  # noqa: E402
from services.conversation_service import ConversationService  # noqa: E402
from services.prompt_service import PromptService  # noqa: E402


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


@pytest.fixture(autouse=True)
def reset_chat_router_singletons():
    chat_router._adapter = None
    chat_router._scoring_service = None
    yield
    chat_router._adapter = None
    chat_router._scoring_service = None


@pytest.fixture
def prompt_sources(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    variable_dir = tmp_path / "variables"
    narrative_dir = variable_dir / "长文模式叙事变量"
    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
    narrative_dir.mkdir(parents=True, exist_ok=True)

    relationship_presets = {
        "暧昧": {
            "intimacy_boundary": "硬编码-暧昧边界",
            "relation_calling": "暧昧称呼",
            "relation_info": "暧昧关系信息",
        },
        "恋人": {
            "intimacy_boundary": "硬编码-恋人边界",
            "relation_calling": "恋人称呼",
            "relation_info": "恋人关系信息",
        },
    }
    preset_characters = {
        "demo": {
            "id": "demo",
            "name": "测试角色",
            "type": "理性沉稳",
            "gender": "男",
            "default_relationship": "暧昧",
            "persona_file": "old_persona.md",
            "few_shot_file": "fewshot.md",
            "character_defaults": {
                "personality": "理性沉稳",
                "speaking_style": "克制",
                "user_nickname": "小鹿",
                "user_gender": "女",
                "user_identity": "产品经理",
                "sys_startprompt": "长期记忆-测试",
                "weekly_schedule": "周三晚上健身",
                "sys_module8": "咖啡、展览、爵士乐",
                "sys_role_acting": "名人角色隔离说明",
            },
        }
    }

    monkeypatch.setattr(prompt_service_module, "VARIABLE_DIR", variable_dir)
    monkeypatch.setattr(prompt_service_module, "NARRATIVE_VAR_DIR", narrative_dir)
    monkeypatch.setattr(prompt_service_module, "PROJECT_DIR", project_dir)
    monkeypatch.setattr(
        prompt_service_module,
        "RELATIONSHIP_PRESETS",
        relationship_presets,
    )
    monkeypatch.setattr(
        PromptService,
        "NARRATIVE_STYLE_DOC",
        variable_dir / "长文模式核心变量定义_v2.3.md",
    )
    monkeypatch.setattr(
        PromptService,
        "AGGREGATED_PERSONA_DOC",
        narrative_dir / "longform_persona.md",
    )
    monkeypatch.setattr(
        PromptService,
        "INTIMACY_BOUNDARY_DOC",
        narrative_dir / "intimacy_boundary.md",
    )
    few_shot_root = narrative_dir / "示例——长文模式"
    latest_few_shot_dir = few_shot_root / "最新版本"
    monkeypatch.setattr(PromptService, "FEW_SHOT_LATEST_DIR", latest_few_shot_dir)
    monkeypatch.setattr(PromptService, "FEW_SHOT_SOURCE_ROOTS", [latest_few_shot_dir])
    monkeypatch.setattr(
        PromptService,
        "FEW_SHOT_SEARCH_PATHS",
        [latest_few_shot_dir, few_shot_root, project_dir],
    )

    monkeypatch.setattr(config, "RELATIONSHIP_PRESETS", relationship_presets)
    monkeypatch.setattr(config, "PRESET_CHARACTERS", preset_characters)
    monkeypatch.setattr(
        conversation_service_module,
        "RELATIONSHIP_PRESETS",
        relationship_presets,
    )
    monkeypatch.setattr(
        conversation_service_module,
        "PRESET_CHARACTERS",
        preset_characters,
    )
    monkeypatch.setattr(configs_router, "RELATIONSHIP_PRESETS", relationship_presets)
    monkeypatch.setattr(configs_router, "PRESET_CHARACTERS", preset_characters)
    monkeypatch.setattr(presets_router, "PRESET_CHARACTERS", preset_characters)
    monkeypatch.setattr(presets_router, "RELATIONSHIP_PRESETS", relationship_presets)
    monkeypatch.setattr(conversations_router, "RELATIONSHIP_PRESETS", relationship_presets)
    conversations_router._conv_service = None

    return {
        "variable_dir": variable_dir,
        "narrative_dir": narrative_dir,
        "few_shot_dir": latest_few_shot_dir,
        "project_dir": project_dir,
        "relationship_presets": relationship_presets,
        "preset_characters": preset_characters,
    }


@pytest.fixture
def isolated_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    db_path = tmp_path / "longform_test.db"
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(db, "DB_PATH", db_path)
    conversations_router._conv_service = None
    return db_path


def test_load_persona_block_falls_back_when_new_doc_empty(
    prompt_sources,
):
    variable_dir = prompt_sources["variable_dir"]
    narrative_dir = prompt_sources["narrative_dir"]

    _write(
        variable_dir / "old_persona.md",
        """
        ## 理性沉稳 × 男

        ### 暧昧阶段
        ```yaml
        tone: old-persona
        ```
        """,
    )
    (narrative_dir / "longform_persona.md").write_text("", encoding="utf-8")

    block = PromptService().load_persona_block(
        "old_persona.md",
        "男",
        "暧昧",
        personal_type="理性沉稳",
    )

    assert block == "tone: old-persona"


def test_load_narrative_style_prefers_new_doc(prompt_sources):
    variable_dir = prompt_sources["variable_dir"]
    narrative_dir = prompt_sources["narrative_dir"]

    _write(
        narrative_dir / "longform_narrative_style.md",
        """
        ## 理性沉稳型
        ```yaml
        style: new-style
        ```
        """,
    )
    _write(
        variable_dir / "长文模式核心变量定义_v2.3.md",
        """
        ### 理性沉稳型
        ```yaml
        style: old-style
        ```
        """,
    )

    block = PromptService().load_narrative_style("理性沉稳")

    assert block == "style: new-style"


def test_load_intimacy_boundary_prefers_new_doc_and_falls_back(prompt_sources):
    narrative_dir = prompt_sources["narrative_dir"]

    _write(
        narrative_dir / "intimacy_boundary.md",
        """
        ## 暧昧阶段
        ```yaml
        intimacy_boundary:
          - 允许试探性靠近
          - 禁止越级承诺
        ```
        """,
    )

    service = PromptService()
    assert service.load_intimacy_boundary("暧昧") == (
        "- 允许试探性靠近\n- 禁止越级承诺"
    )
    assert service.load_intimacy_boundary("恋人") == "硬编码-恋人边界"


def test_load_few_shot_examples_filters_by_relationship_and_limits_pairs(prompt_sources):
    narrative_dir = prompt_sources["narrative_dir"]
    few_shot_dir = prompt_sources["few_shot_dir"]

    _write(
        few_shot_dir / "霸道腹黑型男性 Few-shot 示例.md",
        """
        ## 【霸道腹黑型 - 熟人阶段 - 日常场景】
        [User]
        *熟人日常*
        [Assistant]
        *熟人日常回复*
        ---

        ## 【霸道腹黑型 - 暧昧阶段 - 日常场景】
        [User]
        *暧昧日常*
        [Assistant]
        *暧昧日常回复*
        ---

        ## 【霸道腹黑型 - 暧昧阶段 - 亲密场景】
        [User]
        *暧昧亲密*
        [Assistant]
        *暧昧亲密回复*
        ---

        ## 【霸道腹黑型 - 暧昧阶段 - 冲突场景】
        [User]
        *暧昧冲突*
        [Assistant]
        *暧昧冲突回复*
        ---
        """,
    )
    few_shot_path = str(few_shot_dir / "霸道腹黑型男性 Few-shot 示例.md")

    messages = PromptService().load_few_shot_examples(
        few_shot_path,
        relationship="暧昧",
        personal_type="霸道腹黑",
        gender="男",
    )

    assert len(messages) == 4
    assert messages[0]["content"] == "*暧昧日常*"
    assert messages[1]["content"] == "*暧昧日常回复*"
    assert messages[2]["content"] == "*暧昧亲密*"
    assert messages[3]["content"] == "*暧昧亲密回复*"


def test_few_shot_candidate_archive_filter_matches_named_archive_dirs():
    service = PromptService()

    assert service._is_archived_few_shot_candidate(
        Path(r"E:\工作资料\产品资料\提示词资料\长文模式\提示词\长文模式提示词归档\理性沉稳型男性 Few-shot 示例.md")
    )
    assert service._is_archived_few_shot_candidate(
        Path(r"E:\提效工具\长文模式生成\优化文档\历史归档_20260421\温暖陪伴型女性 Few-shot 示例.md")
    )
    assert not service._is_archived_few_shot_candidate(
        Path(r"E:\工作资料\产品资料\提示词资料\长文模式\变量\长文模式叙事变量\示例——长文模式\温暖陪伴型女性 Few-shot 示例（精选版）_v17.md")
    )


def test_resolve_few_shot_reference_prefers_latest_file_with_relationship_match(
    prompt_sources,
    monkeypatch: pytest.MonkeyPatch,
):
    narrative_dir = prompt_sources["narrative_dir"]
    few_shot_dir = prompt_sources["few_shot_dir"]

    _write(
        few_shot_dir / "霸道腹黑型女性 Few-shot 示例（精选版）_v9_20260414.md",
        """
        ## 【霸道腹黑型 - 恋人阶段 - 日常场景】
        [User]
        *v9 恋人日常*
        [Assistant]
        *v9 恋人回复*
        ---
        """,
    )
    _write(
        few_shot_dir / "霸道腹黑型女性 Few-shot 示例（精选版）_v10_20260414.md",
        """
        ## 【霸道腹黑型 - 暧昧阶段 - 日常场景】
        [User]
        *v10 暧昧日常*
        [Assistant]
        *v10 暧昧回复*
        ---
        """,
    )

    monkeypatch.setattr(PromptService, "FEW_SHOT_SOURCE_ROOTS", [few_shot_dir])
    monkeypatch.setattr(PromptService, "FEW_SHOT_SEARCH_PATHS", [few_shot_dir])

    service = PromptService()
    _, lover_path = service.resolve_few_shot_reference(
        "",
        personal_type="霸道腹黑",
        gender="女",
        relationship="恋人",
    )
    _, ambiguous_path = service.resolve_few_shot_reference(
        "",
        personal_type="霸道腹黑",
        gender="女",
        relationship="暧昧",
    )

    assert lover_path.endswith("霸道腹黑型女性 Few-shot 示例（精选版）_v9_20260414.md")
    assert ambiguous_path.endswith("霸道腹黑型女性 Few-shot 示例（精选版）_v10_20260414.md")


def test_resolve_few_shot_reference_excludes_archive_from_auto_selection(
    prompt_sources,
    monkeypatch: pytest.MonkeyPatch,
):
    narrative_dir = prompt_sources["narrative_dir"]
    few_shot_dir = prompt_sources["few_shot_dir"]
    archive_dir = few_shot_dir / "归档"

    active_path = few_shot_dir / "温暖陪伴型男性 Few-shot 示例（精选版）_v15.md"
    archived_path = archive_dir / "温暖陪伴型男性 Few-shot 示例（精选版）_v20_20260428.md"
    _write(
        active_path,
        """
        ## 【温暖陪伴型 - 暧昧阶段 - 日常场景】
        [User]
        *active user*
        [Assistant]
        *active reply*
        ---
        """,
    )
    _write(
        archived_path,
        """
        ## 【温暖陪伴型 - 暧昧阶段 - 日常场景】
        [User]
        *archived user*
        [Assistant]
        *archived reply*
        ---
        """,
    )

    monkeypatch.setattr(PromptService, "FEW_SHOT_SOURCE_ROOTS", [few_shot_dir])
    monkeypatch.setattr(PromptService, "FEW_SHOT_SEARCH_PATHS", [few_shot_dir])

    service = PromptService()
    resolved, display_path = service.resolve_few_shot_reference(
        "",
        personal_type="温暖陪伴",
        gender="男",
        relationship="暧昧",
    )
    auto_messages = service.load_few_shot_examples(
        "",
        relationship="暧昧",
        personal_type="温暖陪伴",
        gender="男",
    )
    explicit_messages = service.load_few_shot_examples(
        str(archived_path),
        relationship="暧昧",
        personal_type="温暖陪伴",
        gender="男",
    )

    assert resolved == active_path
    assert "归档" not in display_path
    assert auto_messages[0]["content"] == "*active user*"
    assert explicit_messages[0]["content"] == "*active user*"


def test_prepare_runtime_bundle_routes_few_shot_with_scene_preference(prompt_sources):
    narrative_dir = prompt_sources["narrative_dir"]
    few_shot_dir = prompt_sources["few_shot_dir"]

    _write(
        prompt_sources["project_dir"] / "prompt.md",
        """
        system prompt body
        """,
    )
    prompt_path = str(prompt_sources["project_dir"] / "prompt.md")
    _write(
        few_shot_dir / "霸道腹黑型男性 Few-shot 示例.md",
        """
        ## 【霸道腹黑型 - 暧昧阶段 - 日常场景】
        [User]
        *暧昧日常*
        [Assistant]
        *暧昧日常回复*
        ---

        ## 【霸道腹黑型 - 暧昧阶段 - 亲密场景】
        [User]
        *暧昧亲密*
        [Assistant]
        *暧昧亲密回复*
        ---

        ## 【霸道腹黑型 - 暧昧阶段 - 冲突场景】
        [User]
        *暧昧冲突*
        [Assistant]
        *暧昧冲突回复*
        ---
        """,
    )
    few_shot_path = str(few_shot_dir / "霸道腹黑型男性 Few-shot 示例.md")

    bundle = ConversationService()._prepare_runtime_bundle(
        {
            "prompt_file": prompt_path,
            "few_shot_file": few_shot_path,
            "character": {
                "Role_Nickname": "萧璟言",
                "gender": "男",
                "personal_type": "霸道腹黑",
                "personality": "霸道腹黑",
            },
            "context": {
                "relationship": "暧昧",
                "current_scene": "深夜客厅沙发上等他回来",
            },
            "modules": {},
            "runtime": {},
        }
    )

    assert len(bundle.few_shot_messages) == 4
    assert bundle.few_shot_messages[0]["content"] == "*暧昧亲密*"
    assert bundle.few_shot_messages[1]["content"] == "*暧昧亲密回复*"


def test_prepare_runtime_bundle_renders_few_shot_role_alias(prompt_sources):
    narrative_dir = prompt_sources["narrative_dir"]
    few_shot_dir = prompt_sources["few_shot_dir"]

    _write(
        prompt_sources["project_dir"] / "prompt.md",
        """
        system prompt body
        """,
    )
    prompt_path = str(prompt_sources["project_dir"] / "prompt.md")
    _write(
        few_shot_dir / "温暖陪伴型男性 Few-shot 示例.md",
        """
        ## 【温暖陪伴型 - 熟人阶段 - 日常场景】
        [User]
        （抬头看向他）
        [Assistant]
        {{角色名}}把声音放得很轻。
        ---
        """,
    )
    few_shot_path = str(few_shot_dir / "温暖陪伴型男性 Few-shot 示例.md")

    bundle = ConversationService()._prepare_runtime_bundle(
        {
            "prompt_file": prompt_path,
            "few_shot_file": few_shot_path,
            "character": {
                "Role_Nickname": "玉奴",
                "gender": "男",
                "personal_type": "温暖陪伴",
                "personality": "温暖陪伴",
            },
            "context": {
                "relationship": "熟人",
                "current_scene": "偏院门口",
            },
            "modules": {},
            "runtime": {},
        }
    )

    assert bundle.few_shot_messages[1]["content"] == "玉奴把声音放得很轻。"
    assert "{{角色名}}" not in bundle.few_shot_messages[1]["content"]


def test_preset_builders_share_same_three_core_variables(prompt_sources):
    variable_dir = prompt_sources["variable_dir"]
    narrative_dir = prompt_sources["narrative_dir"]

    _write(
        variable_dir / "old_persona.md",
        """
        ## 理性沉稳 × 男

        ### 暧昧阶段
        ```yaml
        tone: old-persona
        ```
        """,
    )
    _write(
        narrative_dir / "longform_persona_理性沉稳.md",
        """
        ## 理性沉稳 × 男

        ### 暧昧阶段
        ```yaml
        tone: new-persona
        ```
        """,
    )
    _write(
        narrative_dir / "longform_narrative_style.md",
        """
        ## 理性沉稳型
        ```yaml
        style: unified-style
        ```
        """,
    )
    _write(
        narrative_dir / "intimacy_boundary.md",
        """
        ## 暧昧阶段
        ```yaml
        intimacy_boundary:
          - 文件边界一
          - 文件边界二
        ```
        """,
    )

    preset_vars = presets_router._build_longform_variables("理性沉稳", "暧昧", "男")
    conv_config = ConversationService().build_config_from_preset("demo")
    builtin_config = configs_router._build_builtin_preset_config("demo")

    expected_boundary = "- 文件边界一\n- 文件边界二"
    assert preset_vars["longform_persona"] == "tone: new-persona"
    assert conv_config["modules"]["longform_persona"] == "tone: new-persona"
    assert builtin_config["modules"]["longform_persona"] == "tone: new-persona"
    assert preset_vars["longform_narrative_style"] == "style: unified-style"
    assert conv_config["modules"]["longform_narrative_style"] == "style: unified-style"
    assert builtin_config["modules"]["longform_narrative_style"] == "style: unified-style"
    assert preset_vars["longform_few_shot"]
    assert conv_config["modules"]["longform_few_shot"] == "fewshot.md"
    assert builtin_config["modules"]["longform_few_shot"] == "fewshot.md"
    assert preset_vars["intimacy_boundary"] == expected_boundary
    assert conv_config["context"]["intimacy_boundary"] == expected_boundary
    assert builtin_config["context"]["intimacy_boundary"] == expected_boundary
    assert conv_config["context"]["relation_calling"] == preset_vars["relation_calling"]
    assert builtin_config["context"]["relation_calling"] == preset_vars["relation_calling"]
    assert conv_config["context"]["relation_info"] == preset_vars["relation_info"]
    assert builtin_config["context"]["relation_info"] == preset_vars["relation_info"]


def test_build_config_from_preset_prefers_explicit_preset_files_when_type_duplicates(
    prompt_sources,
):
    variable_dir = prompt_sources["variable_dir"]
    narrative_dir = prompt_sources["narrative_dir"]
    preset_characters = prompt_sources["preset_characters"]

    preset_characters["other"] = {
        "id": "other",
        "name": "另一角色",
        "type": "理性沉稳",
        "gender": "男",
        "default_relationship": "暧昧",
        "persona_file": "other_persona.md",
        "few_shot_file": "other_fewshot.md",
        "character_defaults": {
            "personality": "理性沉稳",
        },
    }
    preset_characters["demo"]["persona_file"] = "demo_persona.md"
    preset_characters["demo"]["few_shot_file"] = "demo_fewshot.md"

    _write(
        variable_dir / "demo_persona.md",
        """
        ## 理性沉稳 × 男

        ### 暧昧阶段
        ```yaml
        tone: demo-persona
        ```
        """,
    )
    _write(
        variable_dir / "other_persona.md",
        """
        ## 理性沉稳 × 男

        ### 暧昧阶段
        ```yaml
        tone: other-persona
        ```
        """,
    )
    _write(
        narrative_dir / "longform_narrative_style.md",
        """
        ## 理性沉稳型
        ```yaml
        style: shared-style
        ```
        """,
    )

    config = ConversationService().build_config_from_preset("demo")

    assert config["modules"]["longform_persona"] == "tone: demo-persona"
    assert config["modules"]["longform_few_shot"] == "demo_fewshot.md"
    assert config["few_shot_file"] == "demo_fewshot.md"


def test_preset_builders_include_default_module_fields(prompt_sources):
    conv_config = ConversationService().build_config_from_preset("demo")
    builtin_config = configs_router._build_builtin_preset_config("demo")

    for config in (conv_config, builtin_config):
        modules = config["modules"]
        assert modules["user_Nickname"] == "小鹿"
        assert modules["user_gender"] == "女"
        assert modules["user_identity"] == "产品经理"
        assert modules["dialogueStartPrompt"] == "长期记忆-测试"
        assert modules["weekly_schedule"] == "周三晚上健身"
        assert modules["system_module8"] == "咖啡、展览、爵士乐"
        assert modules["system_Role_acting"] == "名人角色隔离说明"


def test_conversation_routes_fill_intimacy_boundary_from_loader(
    prompt_sources,
    isolated_db,
    monkeypatch: pytest.MonkeyPatch,
):
    def fake_create_task(coro):
        coro.close()
        return None

    monkeypatch.setattr(conversations_router.asyncio, "create_task", fake_create_task)
    monkeypatch.setattr(
        conversations_router.PromptService,
        "load_intimacy_boundary",
        lambda self, relationship: "文件边界-测试",
    )

    with TestClient(app) as client:
        interactive_response = client.post(
            "/api/conversations/interactive",
            json={
                "prompt_version": "",
                "character": {
                    "Role_Nickname": "交互角色",
                    "personality": "理性沉稳",
                },
                "context": {"relationship": "暧昧"},
                "modules": {"longform_few_shot": "narrative/fewshot.md"},
            },
        )
        assert interactive_response.status_code == 200, interactive_response.text
        interactive_id = interactive_response.json()["id"]
        interactive = db.get_conversation(interactive_id)
        assert interactive["config"]["context"]["intimacy_boundary"] == "文件边界-测试"
        assert interactive["config"]["context"]["relation_calling"] == "暧昧称呼"
        assert interactive["config"]["context"]["relation_info"] == "暧昧关系信息"
        assert interactive["config"]["context"]["currentTime"]
        assert interactive["config"]["context"]["weekDay"]
        assert interactive["config"]["context"]["timeperiod"]
        assert interactive["config"]["context"]["season"]
        assert interactive["config"]["few_shot_file"] == "narrative/fewshot.md"

        batch_response = client.post(
            "/api/conversations",
            json={
                "prompt_version": "",
                "dry_run": True,
                "turns": ["第一轮输入"],
                "character": {
                    "Role_Nickname": "批量角色",
                    "personality": "理性沉稳",
                },
                "context": {"relationship": "暧昧"},
                "modules": {"longform_few_shot": "narrative/fewshot.md"},
            },
        )
        assert batch_response.status_code == 200, batch_response.text
        batch_id = batch_response.json()["id"]
        batch = db.get_conversation(batch_id)
        assert batch["config"]["context"]["intimacy_boundary"] == "文件边界-测试"
        assert batch["config"]["context"]["relation_calling"] == "暧昧称呼"
        assert batch["config"]["context"]["relation_info"] == "暧昧关系信息"
        assert batch["config"]["context"]["currentTime"]
        assert batch["config"]["context"]["weekDay"]
        assert batch["config"]["context"]["timeperiod"]
        assert batch["config"]["context"]["season"]
        assert batch["config"]["few_shot_file"] == "narrative/fewshot.md"


def test_seed_dialogue_summary_injected_before_generated_summary(prompt_sources):
    _write(
        prompt_sources["project_dir"] / "prompt.md",
        """
        system prompt body
        """,
    )
    bundle = ConversationService()._prepare_runtime_bundle(
        {
            "prompt_file": str(prompt_sources["project_dir"] / "prompt.md"),
            "character": {
                "Role_Nickname": "测试角色",
                "gender": "男",
                "personal_type": "理性沉稳",
                "personality": "理性沉稳",
            },
            "context": {"relationship": "暧昧"},
            "modules": {"dialogue_summary": "手填摘要-测试"},
            "runtime": {},
        }
    )

    result = ConversationService()._execute_single_turn(
        runtime_bundle=bundle,
        conversation_history=[],
        dialogue_summary=bundle.seed_dialogue_summary,
        current_input="你好",
        turn_num=1,
        model_id="doubao-pro",
        dry_run=True,
    )

    summary_messages = [
        message for message in result["messages_snapshot"]
        if message["role"] == "system" and message["content"] == "手填摘要-测试"
    ]
    assert len(summary_messages) == 1



def test_save_config_copies_few_shot_file_from_modules(
    prompt_sources,
):
    name, type_, config = configs_router._normalize_save_payload(
        configs_router.ConfigSaveRequest(
            name="测试配置",
            type="quick_chat",
            config={
                "character": {"Role_Nickname": "测试角色"},
                "context": {"relationship": "暧昧"},
                "modules": {"longform_few_shot": "narrative/fewshot.md"},
            },
        )
    )

    assert name == "测试配置"
    assert type_ == "quick_chat"
    assert config["few_shot_file"] == "narrative/fewshot.md"


def test_interactive_generate_route_returns_real_message_snapshot(
    prompt_sources,
    isolated_db,
):
    calls = []

    class FakeConvService:
        def generate_interactive_turn(
            self,
            conv_id,
            conversation,
            user_input,
            model_id="",
            model_mini="",
            dry_run=False,
            web_search=False,
            thinking_effort="disabled",
        ):
            calls.append(
                {
                    "conv_id": conv_id,
                    "user_input": user_input,
                    "model_id": model_id,
                    "web_search": web_search,
                    "thinking_effort": thinking_effort,
                    "few_shot_file": conversation["config"].get("few_shot_file", ""),
                }
            )
            turn_data = {
                "turn": 1,
                "user_input": user_input,
                "ai_output": "后端生成回复",
                "word_count": 6,
                "dialogue_summary": "",
                "msg_count": 4,
                "input_tokens": 120,
                "output_tokens": 80,
                "latency_s": 1.5,
                "has_deep_injection": False,
                "has_style_isolation": True,
                "has_cooldown_reinject": False,
                "token_trim_level": 0,
                "quality_retries": 0,
                "messages_snapshot": [
                    {"role": "system", "content": "完整 system"},
                    {"role": "user", "content": "few-shot user"},
                    {"role": "assistant", "content": "few-shot assistant"},
                    {"role": "user", "content": "<user_input>你好</user_input>"},
                ],
                "model_id": model_id or "doubao-pro",
            }
            db.insert_turn_result(conv_id, turn_data)
            return turn_data

    with TestClient(app) as client:
        create_response = client.post(
            "/api/conversations/interactive",
            json={
                "prompt_version": "",
                "character": {
                    "Role_Nickname": "交互角色",
                    "personality": "理性沉稳",
                },
                "context": {"relationship": "暧昧"},
                "modules": {"longform_few_shot": "narrative/fewshot.md"},
            },
        )
        assert create_response.status_code == 200, create_response.text
        conv_id = create_response.json()["id"]

        conversations_router._conv_service = FakeConvService()
        generate_response = client.post(
            f"/api/conversations/{conv_id}/generate",
            json={
                "user_input": "你好",
                "model_id": "doubao-character",
                "web_search": True,
                "thinking_effort": "high",
            },
        )
        assert generate_response.status_code == 200, generate_response.text
        body = generate_response.json()
        assert body["success"] is True
        assert body["turn"] == 1
        assert body["messages_snapshot"][0]["content"] == "完整 system"
        assert body["messages_snapshot"][-1]["content"] == "<user_input>你好</user_input>"

        saved = db.get_conversation(conv_id)
        assert len(saved["results"]) == 1
        assert saved["results"][0]["messages_snapshot"][0]["content"] == "完整 system"

    assert calls == [
        {
            "conv_id": conv_id,
            "user_input": "你好",
            "model_id": "doubao-character",
            "web_search": True,
            "thinking_effort": "high",
            "few_shot_file": "narrative/fewshot.md",
        }
    ]


def test_interactive_regenerate_route_replaces_last_turn(
    prompt_sources,
    isolated_db,
):
    calls = []

    class FakeConvService:
        def generate_interactive_turn(
            self,
            conv_id,
            conversation,
            user_input,
            model_id="",
            model_mini="",
            dry_run=False,
            web_search=False,
            thinking_effort="disabled",
        ):
            calls.append(
                {
                    "existing_turns": len(conversation.get("results", [])),
                    "user_input": user_input,
                    "model_id": model_id,
                    "web_search": web_search,
                    "thinking_effort": thinking_effort,
                }
            )
            turn_data = {
                "turn": 1,
                "user_input": user_input,
                "ai_output": "重生成回复",
                "word_count": 5,
                "dialogue_summary": "",
                "msg_count": 3,
                "input_tokens": 99,
                "output_tokens": 66,
                "latency_s": 1.1,
                "has_deep_injection": False,
                "has_style_isolation": True,
                "has_cooldown_reinject": False,
                "token_trim_level": 0,
                "quality_retries": 0,
                "messages_snapshot": [
                    {"role": "system", "content": "完整 system"},
                    {"role": "user", "content": "<user_input>你好</user_input>"},
                    {"role": "assistant", "content": "重生成回复"},
                ],
                "model_id": model_id or "doubao-pro",
            }
            db.insert_turn_result(conv_id, turn_data)
            return turn_data

    with TestClient(app) as client:
        create_response = client.post(
            "/api/conversations/interactive",
            json={
                "prompt_version": "",
                "character": {
                    "Role_Nickname": "交互角色",
                    "personality": "理性沉稳",
                },
                "context": {"relationship": "暧昧"},
                "modules": {"longform_few_shot": "narrative/fewshot.md"},
            },
        )
        assert create_response.status_code == 200, create_response.text
        conv_id = create_response.json()["id"]

        db.insert_turn_result(
            conv_id,
            {
                "turn": 1,
                "user_input": "你好",
                "ai_output": "旧回复",
                "word_count": 3,
                "dialogue_summary": "",
                "msg_count": 2,
                "input_tokens": 10,
                "output_tokens": 10,
                "latency_s": 0.5,
                "has_deep_injection": False,
                "has_style_isolation": False,
                "has_cooldown_reinject": False,
                "token_trim_level": 0,
                "quality_retries": 0,
                "messages_snapshot": [
                    {"role": "system", "content": "旧 system"},
                    {"role": "user", "content": "<user_input>你好</user_input>"},
                ],
                "model_id": "doubao-pro",
            },
        )

        conversations_router._conv_service = FakeConvService()
        regenerate_response = client.post(
            f"/api/conversations/{conv_id}/turns/1/regenerate",
            json={
                "model_id": "doubao-character",
                "web_search": True,
                "thinking_effort": "high",
            },
        )
        assert regenerate_response.status_code == 200, regenerate_response.text
        body = regenerate_response.json()
        assert body["success"] is True
        assert body["ai_output"] == "重生成回复"

        saved = db.get_conversation(conv_id)
        assert len(saved["results"]) == 1
        assert saved["results"][0]["ai_output"] == "重生成回复"
        assert saved["results"][0]["messages_snapshot"][0]["content"] == "完整 system"

    assert calls == [
        {
            "existing_turns": 0,
            "user_input": "你好",
            "model_id": "doubao-character",
            "web_search": True,
            "thinking_effort": "high",
        }
    ]


def test_chat_score_route_uses_short_timeout(monkeypatch: pytest.MonkeyPatch):
    calls = {}

    class FakeScoringService:
        def is_available(self):
            return True

        def get_last_error(self):
            return ""

        async def score_turn(self, turn_data, timeout_s=None, retry_delays=None):
            calls["turn_data"] = dict(turn_data)
            calls["timeout_s"] = timeout_s
            calls["retry_delays"] = retry_delays
            return {
                "success": True,
                "scores": {"persona_fidelity": 5},
                "mapped_total": 8.8,
                "reasoning": "ok",
            }

    monkeypatch.setattr(scoring_service_module, "ScoringService", FakeScoringService)

    with TestClient(app) as client:
        response = client.post(
            "/api/chat/score",
            json={
                "user_input": "你好",
                "ai_output": "你好。",
                "config": {
                    "prompt_file": "prompt.md",
                    "character": {
                        "Role_Nickname": "阿言",
                        "personality": "霸道腹黑",
                    },
                    "context": {"relationship": "暧昧"},
                },
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["mapped_total"] == 8.8
    assert calls["timeout_s"] == chat_router.CHAT_SCORE_TIMEOUT_S
    assert calls["retry_delays"] == chat_router.CHAT_SCORE_RETRY_DELAYS
    assert calls["turn_data"]["role_name"] == "阿言"
    assert calls["turn_data"]["relationship"] == "暧昧"


def test_chat_score_route_reuses_scoring_service(monkeypatch: pytest.MonkeyPatch):
    calls = {"init_count": 0, "score_count": 0}

    class FakeScoringService:
        def __init__(self):
            calls["init_count"] += 1

        def is_available(self):
            return True

        def get_last_error(self):
            return ""

        async def score_turn(self, turn_data, timeout_s=None, retry_delays=None):
            calls["score_count"] += 1
            return {
                "success": True,
                "scores": {"persona_fidelity": 5},
                "mapped_total": 8.8,
                "reasoning": f"ok-{turn_data.get('turn', 1)}",
            }

    monkeypatch.setattr(scoring_service_module, "ScoringService", FakeScoringService)

    with TestClient(app) as client:
        payload = {
            "user_input": "你好",
            "ai_output": "你好。",
            "config": {
                "prompt_file": "prompt.md",
                "character": {
                    "Role_Nickname": "阿言",
                    "personality": "霸道腹黑",
                },
                "context": {"relationship": "暧昧"},
            },
        }
        response1 = client.post("/api/chat/score", json=payload)
        response2 = client.post("/api/chat/score", json=payload)

    assert response1.status_code == 200
    assert response2.status_code == 200
    assert response1.json()["success"] is True
    assert response2.json()["success"] is True
    assert calls["init_count"] == 1
    assert calls["score_count"] == 2


def test_chat_score_route_returns_soft_timeout(monkeypatch: pytest.MonkeyPatch):
    class SlowScoringService:
        def is_available(self):
            return True

        def get_last_error(self):
            return ""

        async def score_turn(self, turn_data, timeout_s=None, retry_delays=None):
            await asyncio.sleep(1.2)
            return {
                "success": True,
                "scores": {"persona_fidelity": 5},
                "mapped_total": 9.0,
                "reasoning": "too slow",
            }

    monkeypatch.setattr(scoring_service_module, "ScoringService", SlowScoringService)
    monkeypatch.setattr(chat_router, "CHAT_SCORE_TIMEOUT_S", 0.01)

    with TestClient(app) as client:
        response = client.post(
            "/api/chat/score",
            json={
                "user_input": "你好",
                "ai_output": "你好。",
                "config": {"character": {}, "context": {}},
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert "超时" in body["error"]
