"""
前端交互链路与批量链路等价性回归测试。
"""
from __future__ import annotations

import asyncio
import os
import sys
from copy import deepcopy
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
SERVER_DIR = PROJECT_DIR / "server"
DB_DIR = PROJECT_DIR / "output" / "test_runtime"
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / "frontend_batch_equivalence.db"

for suffix in ("", "-wal", "-shm"):
    target = Path(str(DB_PATH) + suffix)
    if target.exists():
        target.unlink()

os.environ["LONGFORM_DB_PATH"] = str(DB_PATH)

if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import database as db  # noqa: E402
from routers.conversations import (  # noqa: E402
    _apply_conversation_channel_context,
    _build_runtime_config,
    _prepare_batch_runtime,
)
from services.conversation_service import ConversationService  # noqa: E402
from services.model_adapter import ChatResult  # noqa: E402
from services.prompt_service import PromptService  # noqa: E402

db.init_db()


class DeterministicAdapter:
    def __init__(self):
        self.calls: list[dict] = []
        self._models = {
            "doubao-pro": {"parameters": {}},
            "doubao-mini": {"parameters": {}},
        }

    def chat(self, model_id, messages, **kwargs):
        self.calls.append(
            {
                "model_id": model_id,
                "messages": [dict(item) for item in messages],
                "kwargs": dict(kwargs),
            }
        )
        if model_id == "doubao-mini":
            return ChatResult(
                content="=== 之前剧情摘要 ===\n- 场景：图书馆\n- 剧情：继续推进\n- 悬念：晚点是否见面\n- 角色情绪：克制\n- 用户情绪：期待\n- 关系动态：升温\n- 用户画像信号：怕冷\n=== 摘要结束 ===",
                success=True,
                input_tokens=8,
                output_tokens=8,
                latency_s=0.01,
            )
        turn_index = len([item for item in self.calls if item["model_id"] == "doubao-pro"])
        return ChatResult(
            content=f"第{turn_index}轮固定回复",
            success=True,
            input_tokens=16,
            output_tokens=12,
            latency_s=0.02,
        )

    def resolve_thinking_effort(
        self,
        model_id,
        thinking_enabled=None,
        thinking_effort="disabled",
    ):
        text = str(thinking_effort or "").strip().lower() or "disabled"
        if thinking_enabled is False:
            return "disabled"
        if thinking_enabled is True and text == "disabled":
            return "high"
        return text


def clear_db():
    conn = db.get_connection()
    conn.execute("DELETE FROM turn_results")
    conn.execute("DELETE FROM conversations")
    conn.commit()
    conn.close()


def make_prompt(tmp_path: Path) -> Path:
    prompt = tmp_path / "equivalence_prompt.md"
    prompt.write_text(
        (
            "你是{{Role_Nickname}}，关系{{relationship}}，场景{{current_scene}}。\n"
            "完整时间：{{完整时间信息}}\n"
            "上次沟通：{{last_cst_type}}\n"
            "称呼规则：{{relation_calling}}\n"
            "亲密边界：{{intimacy_boundary}}\n"
            "角色画像：{{longform_persona}}\n"
            "叙事策略：{{longform_narrative_style}}\n"
            "Few-shot：{{longform_few_shot}}\n"
            "朋友圈：{{moments}}\n"
            "月度安排：{{monthly_schedule}}\n"
            "禁用语气：{{voice_forbidden}}\n"
        ),
        encoding="utf-8",
    )
    return prompt


def build_base_config() -> dict:
    return {
        "character": {
            "Role_Nickname": "模板角色",
            "personality": "霸道腹黑",
            "personal_type": "霸道腹黑型女性",
            "gender": "女",
            "age": 28,
            "occupation": "总裁",
            "speaking_style": "冷静克制",
        },
        "context": {
            "relationship": "恋人",
            "scene": "厨房",
            "time_period": "夜晚",
            "season": "春季",
            "user_nickname": "小鹿",
            "user_gender": "男",
            "user_identity": "恋人",
            "last_cst_type": "上一次在文字聊天沟通",
            "currentTime": "2026-04-15 21:30",
            "weekDay": "星期三",
            "timeperiod": "夜晚",
            "完整时间信息": "2026-04-15 21:30 / 星期三 / 夜晚 / 春季",
            "relation_calling": "对用户可用亲昵称呼，但不得越界支配",
            "relation_info": "已确立恋人关系",
            "intimacy_boundary": "可以表达关心和轻微肢体照料，但不能直接推进露骨亲密行为",
        },
        "modules": {
            "longform_persona": "高压、克制、嘴硬但会照顾人",
            "longform_narrative_style": "压迫感外壳下的细节照料",
            "longform_few_shot": "## 【霸道腹黑型女性 - 恋人阶段 - 日常场景】",
            "dialogueStartPrompt": "用户怕冷",
            "voice_forbidden": "禁止英译中翻译腔",
        },
        "custom_variables": {
            "moments": "她今天发了做饭照片",
            "monthly_schedule": "月底前都在准备发布会",
        },
    }


def prepare_runtime_config(config: dict, prompt_path: Path):
    requested_prompt, model_mini = _build_runtime_config(
        config=config,
        model_id="doubao-pro",
        model_mini="doubao-mini",
        prompt_version=str(prompt_path),
        summary_prompt_version="",
        scoring_prompt_version="",
        scoring_model_id="",
        thinking_enabled=True,
        thinking_effort="high",
        scoring_thinking_enabled=True,
        scoring_thinking_effort="high",
        summary_interval=5,
        injection_depth=4,
        temperature=0.55,
        top_p=0.75,
    )
    _apply_conversation_channel_context(
        config,
        prompt_ref=requested_prompt or config.get("prompt_file", ""),
    )
    return requested_prompt, model_mini


def run_interactive_sequence(service: ConversationService, prompt_path: Path, turns: list[str]):
    clear_db()
    config = deepcopy(build_base_config())
    requested_prompt, model_mini = prepare_runtime_config(config, prompt_path)
    conv_id = db.create_conversation(
        model_id="doubao-pro",
        config=config,
        model_mini=model_mini,
        prompt_version=requested_prompt,
    )
    results = []
    for turn in turns:
        conversation = db.get_conversation(conv_id)
        results.append(
            service.generate_interactive_turn(
                conv_id,
                conversation,
                turn,
                model_id="doubao-pro",
                thinking_enabled=True,
                thinking_effort="high",
                temperature=0.55,
                top_p=0.75,
            )
        )
    return db.get_conversation(conv_id), results


def run_batch_sequence(service: ConversationService, prompt_path: Path, turns: list[str]):
    clear_db()
    config = deepcopy(build_base_config())
    requested_prompt, model_mini = prepare_runtime_config(config, prompt_path)
    runtime, normalized_turns = _prepare_batch_runtime(
        config=config,
        turns=turns,
        model_ids=["doubao-pro"],
        compare_mode="",
        model_id="doubao-pro",
        dry_run=False,
    )
    conv_id = db.create_conversation(
        model_id="doubao-pro",
        config=config,
        model_mini=model_mini,
        prompt_version=requested_prompt,
    )
    results = asyncio.run(
        service.run_conversation(
            conv_id=conv_id,
            config=config,
            turns=normalized_turns,
            model_id="doubao-pro",
            model_mini=model_mini,
            summary_interval=runtime["summary_interval"],
            dry_run=False,
        )
    )
    return db.get_conversation(conv_id), results


def test_interactive_payload_builder_delegates_to_batch_builder():
    js_path = SERVER_DIR / "static" / "js" / "legacy_bundle.js"
    source = js_path.read_text(encoding="utf-8")
    marker = "function buildInteractiveConversationPayload()"
    start = source.index(marker)
    end = source.index("function buildConfigSnapshotRequest", start)
    body = source[start:end]
    assert "const payload = buildConversationRunPayload();" in body


def test_batch_payload_builder_reads_nested_memory_variables():
    js_path = SERVER_DIR / "static" / "js" / "legacy_bundle.js"
    source = js_path.read_text(encoding="utf-8")

    modules_start = source.index("function buildSystemModulesPayload")
    modules_end = source.index("function getMergedCustomVariables", modules_start)
    modules_body = source[modules_start:modules_end]
    assert "source.modules?.[key]" in modules_body
    assert "source.custom_variables?.[key]" in modules_body
    assert "source.prompt_base_values?.[key]" in modules_body

    payload_start = source.index("function buildConversationRunPayload")
    payload_end = source.index("function buildConfigSnapshotRequest", payload_start)
    payload_body = source[payload_start:payload_end]
    assert "source.custom_variables?.[key]" in payload_body
    assert "source.prompt_base_values?.[key]" in payload_body
    assert "source.modules?.[key]" in payload_body
    assert "const formCustomVariables = cfg ? {} : getMergedCustomVariables();" in payload_body


def test_interactive_session_auto_rotates_when_prompt_config_changes():
    js_path = SERVER_DIR / "static" / "js" / "legacy_bundle.js"
    source = js_path.read_text(encoding="utf-8")

    assert "function buildInteractiveConfigSignature(payload = buildInteractiveConversationPayload())" in source
    assert "state.interactiveConfigSignature = buildInteractiveConfigSignature(payload);" in source
    assert "state.interactiveConfigSignature === nextSignature" in source
    assert "ensureInteractiveConversationSession({ resetOnConfigChange: true })" in source
    assert "已自动切换到新会话" in source


def test_scoring_defaults_controls_expose_save_feedback():
    js_path = SERVER_DIR / "static" / "js" / "legacy_bundle.js"
    html_path = SERVER_DIR / "static" / "index.html"
    js_source = js_path.read_text(encoding="utf-8")
    html_source = html_path.read_text(encoding="utf-8")

    assert "const DEFAULT_SCORING_CONCURRENCY = 24;" in js_source
    assert "const DEFAULT_SCORING_THINKING_ENABLED = true;" in js_source
    assert "function saveScoringDefaults()" in js_source
    assert "function resetScoringDefaults()" in js_source
    assert "当前修改未保存；本次运行会生效，刷新页面后会丢失" in js_source
    assert 'id="tc-scoring-save-defaults"' in html_source
    assert 'id="tc-scoring-reset-defaults"' in html_source
    assert 'id="tc-scoring-default-status"' in html_source
    assert 'id="tc-scoring-concurrency-display"' in html_source and ">24<" in html_source


def test_compare_models_expose_per_model_thinking_controls():
    js_path = SERVER_DIR / "static" / "js" / "legacy_bundle.js"
    html_path = SERVER_DIR / "static" / "index.html"
    js_source = js_path.read_text(encoding="utf-8")
    html_source = html_path.read_text(encoding="utf-8")

    assert "let compareThinkingByModel = {};" in js_source
    assert "function getCompareThinkingState" in js_source
    assert "function applyCompareThinkingToSelected" in js_source
    assert "compare-thinking-select" in js_source
    assert "getCompareThinkingState(model.id)" in js_source
    assert "payload.thinking_enabled = thinking.enabled;" in js_source
    assert "payload.thinking_effort = thinking.thinking_effort;" in js_source
    assert "模型思考:" in js_source
    assert "思考全关" in html_source
    assert "思考高" in html_source
    assert "思考Max" in html_source
    assert "legacy_bundle.js?v=96" in html_source


def test_prompt_ab_batch_caps_auto_scoring_concurrency():
    js_path = SERVER_DIR / "static" / "js" / "legacy_bundle.js"
    source = js_path.read_text(encoding="utf-8")

    assert "const DEFAULT_AB_BATCH_SCORING_CONCURRENCY = 2;" in source
    marker = "function buildABBatchBranchItem"
    start = source.index(marker)
    end = source.index("function buildABBatchOrchestrationPayload", start)
    body = source[start:end]

    assert "payload.auto_scoring = !dryRun;" in body
    assert "payload.scoring_max_workers = Math.min(" in body
    assert "DEFAULT_AB_BATCH_SCORING_CONCURRENCY" in body


def test_interactive_and_batch_match_for_ten_turns(tmp_path: Path):
    prompt_path = make_prompt(tmp_path)
    turns = [
        "今天下班早一点吗？",
        "你刚刚是不是又没吃晚饭。",
        "厨房里有点冷，要不要我来帮你。",
        "你今天心情看起来不太好。",
        "如果忙完了我们就一起吃宵夜吧。",
        "你别一直站着，先把手擦干。",
        "我去把汤碗拿过来。",
        "那你现在到底是累还是饿。",
        "我听你的，先回沙发等你。",
        "所以今晚最后怎么安排？",
    ]

    interactive_service = ConversationService(
        model_adapter=DeterministicAdapter(),
        prompt_service=PromptService(),
    )
    batch_service = ConversationService(
        model_adapter=DeterministicAdapter(),
        prompt_service=PromptService(),
    )

    interactive_conv, interactive_results = run_interactive_sequence(
        interactive_service,
        prompt_path,
        turns,
    )
    batch_conv, batch_results = run_batch_sequence(
        batch_service,
        prompt_path,
        turns,
    )

    assert len(interactive_results) == len(batch_results) == 10
    for index, (interactive_turn, batch_turn) in enumerate(
        zip(interactive_results, batch_results, strict=True),
        start=1,
    ):
        assert interactive_turn["ai_output"] == batch_turn["ai_output"], f"第 {index} 轮 ai_output 不一致"
        assert interactive_turn["dialogue_summary"] == batch_turn["dialogue_summary"], f"第 {index} 轮摘要不一致"
        assert interactive_turn["summary_source"] == batch_turn["summary_source"], f"第 {index} 轮 summary_source 不一致"
        assert interactive_turn["memory_context_snapshot"] == batch_turn["memory_context_snapshot"], f"第 {index} 轮 memory_context_snapshot 不一致"
        assert interactive_turn["messages_snapshot"] == batch_turn["messages_snapshot"], f"第 {index} 轮 messages_snapshot 不一致"
        assert interactive_turn["request_payload_snapshot"] == batch_turn["request_payload_snapshot"], f"第 {index} 轮 request_payload_snapshot 不一致"
        assert interactive_turn["token_trim_level"] == batch_turn["token_trim_level"], f"第 {index} 轮 token_trim_level 不一致"
        assert interactive_turn["has_deep_injection"] == batch_turn["has_deep_injection"], f"第 {index} 轮 has_deep_injection 不一致"
        assert interactive_turn["has_style_isolation"] == batch_turn["has_style_isolation"], f"第 {index} 轮 has_style_isolation 不一致"
        assert interactive_turn["model_id"] == batch_turn["model_id"], f"第 {index} 轮 model_id 不一致"

    interactive_runtime = interactive_conv["config"].get("runtime", {})
    batch_runtime = batch_conv["config"].get("runtime", {})
    assert interactive_runtime["thinking_effort"] == batch_runtime["thinking_effort"] == "high"
    assert interactive_runtime["scoring_thinking_effort"] == batch_runtime["scoring_thinking_effort"] == "high"
