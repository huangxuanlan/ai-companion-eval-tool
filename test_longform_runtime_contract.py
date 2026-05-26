from __future__ import annotations

import asyncio
import importlib
import os
import sqlite3
import sys
from concurrent.futures import Future
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parent
SERVER_DIR = PROJECT_DIR / "server"
os.environ.setdefault(
    "LONGFORM_DB_PATH",
    str(PROJECT_DIR / "output" / "test_runtime" / "longform_runtime_contract.db"),
)

if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import config  # noqa: E402
import database as db  # noqa: E402
from config import (  # noqa: E402
    CELEBRITY_ROLE_ACTING_BOUNDARY,
    DEFAULT_INJECTION_DEPTH,
    DEFAULT_VOICE_FORBIDDEN,
    NON_CELEBRITY_ROLE_ACTING_PLACEHOLDER,
    PRESET_CHARACTERS,
    RELATIONSHIP_PRESETS,
    extract_preset_module_defaults,
    get_latest_prompt_file,
)


TARGET_PRESET_MODULE_KEYS = [
    "user_Nickname",
    "user_gender",
    "user_identity",
    "dialogueStartPrompt",
    "weekly_schedule",
    "system_module8",
    "system_Role_acting",
    "voice_forbidden",
]


def _import_runtime_modules():
    conversation_service_module = importlib.import_module("services.conversation_service")
    prompt_service_module = importlib.import_module("services.prompt_service")
    server_dir = str(SERVER_DIR)
    if server_dir in sys.path:
        sys.path.remove(server_dir)
    sys.path.insert(0, server_dir)
    return conversation_service_module, prompt_service_module


def _build_service():
    conversation_service_module, prompt_service_module = _import_runtime_modules()

    class _DryRunModelAdapter:
        """dry-run 合同测试不触发真实模型调用。"""

    return conversation_service_module.ConversationService(
        model_adapter=_DryRunModelAdapter(),
        prompt_service=prompt_service_module.PromptService(),
    )


def _resolve_latest_curated_few_shot(personality: str, gender: str) -> str:
    _, prompt_service_module = _import_runtime_modules()
    _, display_path = prompt_service_module.PromptService().resolve_few_shot_reference(
        "",
        personal_type=personality,
        gender=gender,
    )
    assert display_path, f"未解析到 {personality}/{gender} 的最新 few-shot 路径"
    return display_path


def _build_runtime_config(service, preset_id: str) -> dict:
    config_data = service.build_config_from_preset(preset_id)
    config_data["prompt_file"] = get_latest_prompt_file()
    return config_data


@pytest.fixture
def isolated_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    db_path = tmp_path / "longform_runtime_contract.db"
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()
    db.migrate_add_score_columns()
    return db_path


def test_word_range_constraints_are_consistent(monkeypatch: pytest.MonkeyPatch):
    conversation_service_module, _ = _import_runtime_modules()
    service = _build_service()
    monkeypatch.setattr(service, "_resolve_injection_policy", lambda: (1, 1))

    messages = service._build_messages_internal(
        rendered_system="system prompt",
        system_after="",
        few_shot_messages=[],
        conversation_history=[
            {"role": "user", "content": "上一轮用户输入"},
            {"role": "assistant", "content": "上一轮 AI 回复"},
        ],
        dialogue_summary="=== 之前剧情摘要 ===\n- 场景：测试\n=== 摘要结束 ===",
        memory_context="【历史对话摘要】\n=== 之前剧情摘要 ===\n- 场景：测试\n=== 摘要结束 ===",
        current_input="这一轮继续",
        relationship="暧昧",
        role_name="萧璟言",
        personality="霸道腹黑",
        turn_num=2,
        injection_depth=2,
    )

    deep_injection = next(
        msg["content"]
        for msg in messages
        if msg["role"] == "system" and "请记住：你是" in msg["content"]
    )

    assert conversation_service_module.LONGFORM_WORD_RANGE == "300-500字"
    assert "600-800字" not in conversation_service_module.CORE_CONSTRAINTS_TEMPLATE
    assert (
        f"- 长度：{conversation_service_module.LONGFORM_WORD_RANGE}完整叙事"
        in conversation_service_module.CORE_CONSTRAINTS_TEMPLATE
    )
    assert "旁白用（）包裹" in conversation_service_module.CORE_CONSTRAINTS_TEMPLATE
    assert "对白为纯文本不带任何标记" in conversation_service_module.CORE_CONSTRAINTS_TEMPLATE
    assert "*包裹" not in conversation_service_module.CORE_CONSTRAINTS_TEMPLATE
    assert "「」" not in conversation_service_module.CORE_CONSTRAINTS_TEMPLATE
    assert f"输出{conversation_service_module.LONGFORM_WORD_RANGE}" in deep_injection
    assert "旁白用（）包裹" in deep_injection
    assert "对白为纯文本不带任何标记" in deep_injection
    assert '**""**' not in deep_injection
    assert "旁白*" not in deep_injection
    assert "对白「」" not in deep_injection


def test_runtime_bundle_prefers_custom_system_prompt(monkeypatch: pytest.MonkeyPatch):
    service = _build_service()
    preset_id = next(iter(PRESET_CHARACTERS))
    config_data = _build_runtime_config(service, preset_id)
    config_data.setdefault("modules", {})["system_prompt"] = "## 自定义主提示词\n你只能输出测试文本。"

    bundle = service._prepare_runtime_bundle(config_data)

    assert bundle.rendered_system.startswith("## 自定义主提示词")
    assert "你只能输出测试文本。" in bundle.rendered_system


def test_runtime_bundle_strips_memory_shells_from_custom_system_prompt():
    service = _build_service()
    preset_id = next(iter(PRESET_CHARACTERS))
    config_data = _build_runtime_config(service, preset_id)
    modules = config_data.setdefault("modules", {})
    modules["dialogueStartPrompt"] = "PROFILE_CUSTOM_ONCE_123"
    modules["moments"] = "MOMENTS_CUSTOM_ONCE_123"
    modules["dialogue_summary"] = "SUMMARY_CUSTOM_ONCE_123"
    modules["system_prompt"] = "\n".join(
        [
            "你是测试角色。",
            "【长期记忆用户画像】",
            "{{dialogueStartPrompt}}",
            "",
            "【朋友圈记忆】",
            "{{moments}}",
            "",
            "【历史对话摘要】",
            "{{dialogue_summary}}",
            "",
            "---L5 Few-shot 示例注入区---",
            "{{longform_few_shot}}",
            "---",
            "## 最终指令",
            "请自然回复用户。",
        ]
    )

    bundle = service._prepare_runtime_bundle(config_data)
    rendered_text = "\n".join(
        part for part in [bundle.rendered_system, bundle.rendered_after] if part
    )

    assert "你是测试角色。" in bundle.rendered_system
    assert "请自然回复用户。" in rendered_text
    assert "PROFILE_CUSTOM_ONCE_123" not in rendered_text
    assert "MOMENTS_CUSTOM_ONCE_123" not in rendered_text
    assert "SUMMARY_CUSTOM_ONCE_123" not in rendered_text
    assert "【长期记忆用户画像】" not in rendered_text
    assert "【朋友圈记忆】" not in rendered_text
    assert "【历史对话摘要】" not in rendered_text


def test_runtime_bundle_strips_memory_from_main_system_prompt():
    service = _build_service()
    preset_id = next(iter(PRESET_CHARACTERS))
    config_data = _build_runtime_config(service, preset_id)
    modules = config_data.setdefault("modules", {})
    modules["dialogueStartPrompt"] = "PROFILE_ONLY_ONCE_123"
    modules["moments"] = "MOMENTS_ONLY_ONCE_123"
    modules["dialogue_summary"] = "SUMMARY_ONLY_ONCE_123"

    bundle = service._prepare_runtime_bundle(config_data)
    rendered_text = "\n".join(
        part for part in [bundle.rendered_system, bundle.rendered_after] if part
    )

    assert "PROFILE_ONLY_ONCE_123" not in rendered_text
    assert "MOMENTS_ONLY_ONCE_123" not in rendered_text
    assert "SUMMARY_ONLY_ONCE_123" not in rendered_text
    assert "【长期记忆用户画像】" not in rendered_text
    assert "【朋友圈记忆】" not in rendered_text
    assert "【历史对话摘要】" not in rendered_text
    assert bundle.memory_profile == "PROFILE_ONLY_ONCE_123"
    assert bundle.memory_moments == "MOMENTS_ONLY_ONCE_123"
    assert bundle.seed_dialogue_summary == "SUMMARY_ONLY_ONCE_123"


def test_runtime_messages_keep_memory_single_injection_across_model_branches():
    service = _build_service()
    preset_id = next(iter(PRESET_CHARACTERS))
    config_data = _build_runtime_config(service, preset_id)
    modules = config_data.setdefault("modules", {})
    modules["dialogueStartPrompt"] = "PROFILE_ONLY_ONCE_456"
    modules["moments"] = "MOMENTS_ONLY_ONCE_456"
    modules["dialogue_summary"] = "SUMMARY_ONLY_ONCE_456"

    bundle = service._prepare_runtime_bundle(config_data)
    memory_context, memory_snapshot = service._build_memory_context_block(
        bundle.memory_profile,
        bundle.memory_moments,
        bundle.seed_dialogue_summary,
    )
    history = [
        {"role": "user", "content": "上一轮用户输入"},
        {"role": "assistant", "content": "上一轮角色回复"},
    ]
    expected_tokens = [
        "PROFILE_ONLY_ONCE_456",
        "MOMENTS_ONLY_ONCE_456",
        "SUMMARY_ONLY_ONCE_456",
    ]

    assert memory_snapshot == {
        "dialogueStartPrompt": "PROFILE_ONLY_ONCE_456",
        "moments": "MOMENTS_ONLY_ONCE_456",
        "dialogue_summary": "SUMMARY_ONLY_ONCE_456",
        "switch_state": "",
    }

    for model_id in ("doubao-pro-32k", "qwen3.6-plus", "gemma4-31b"):
        messages = service._build_messages_internal(
            rendered_system=bundle.rendered_system,
            system_after=bundle.rendered_after,
            few_shot_messages=[],
            conversation_history=history,
            dialogue_summary=bundle.seed_dialogue_summary,
            memory_context=memory_context,
            current_input="这一轮继续",
            relationship=bundle.relationship,
            role_name=bundle.role_name,
            personality=bundle.personality,
            turn_num=2,
            injection_depth=bundle.injection_depth,
            model_id=model_id,
        )

        assert messages[0]["role"] == "system"
        assert "PROFILE_ONLY_ONCE_456" not in messages[0]["content"]

        carrier_messages = [
            msg for msg in messages
            if any(token in str(msg.get("content", "")) for token in expected_tokens)
        ]
        assert len(carrier_messages) == 1, f"{model_id} 的记忆内容应只落在 1 条消息里"

        merged_text = "\n".join(str(msg.get("content", "")) for msg in messages)
        for token in expected_tokens:
            assert merged_text.count(token) == 1, f"{model_id} 中 {token} 被重复注入"


def test_summary_job_gracefully_ignores_late_missing_turn_results_table():
    service = _build_service()
    try:
        future: Future[str] = Future()
        future.set_result("LATE_SUMMARY_TOKEN")
        service.store.update_conversation_config = lambda *args, **kwargs: True

        def _raise_missing_table(*args, **kwargs):
            raise sqlite3.OperationalError("no such table: turn_results")

        service.store.update_turn_dialogue_summary = _raise_missing_table
        config_data = {
            "runtime": {
                "latest_dialogue_summary": "",
                "last_summary_turn": 0,
            }
        }
        service._summary_jobs[("conv-late", 1)] = {
            "future": future,
            "config": config_data,
            "consumed": False,
        }

        result = service._consume_summary_job("conv-late", 1)

        assert result == "LATE_SUMMARY_TOKEN"
        assert ("conv-late", 1) not in service._summary_jobs
        assert config_data["runtime"]["latest_dialogue_summary"] == "LATE_SUMMARY_TOKEN"
        assert config_data["runtime"]["last_summary_turn"] == 1
    finally:
        service._background_executor.shutdown(wait=False, cancel_futures=True)


@pytest.mark.parametrize("model_id", ["doubao-pro-32k", "qwen3.6-plus", "gemma4-31b"])
def test_run_conversation_preserves_seed_summary_single_injection_across_model_branches(
    isolated_db: Path,
    model_id: str,
):
    service = _build_service()
    preset_id = next(iter(PRESET_CHARACTERS))
    config_data = _build_runtime_config(service, preset_id)
    modules = config_data.setdefault("modules", {})
    modules["dialogueStartPrompt"] = "PROFILE_RUNTIME_ONCE_789"
    modules["moments"] = "MOMENTS_RUNTIME_ONCE_789"
    modules["dialogue_summary"] = "SUMMARY_RUNTIME_ONCE_789"
    conv_id = db.create_conversation(
        model_id=model_id,
        config=config_data,
        model_mini="dry-run-mini",
        prompt_version=config_data["prompt_file"],
    )

    results = asyncio.run(
        service.run_conversation(
            conv_id=conv_id,
            config=config_data,
            turns=["第一轮测试输入", "第二轮测试输入"],
            model_id=model_id,
            model_mini="dry-run-mini",
            summary_interval=10,
            dry_run=True,
        )
    )

    expected_snapshot = {
        "dialogueStartPrompt": "PROFILE_RUNTIME_ONCE_789",
        "moments": "MOMENTS_RUNTIME_ONCE_789",
        "dialogue_summary": "SUMMARY_RUNTIME_ONCE_789",
        "switch_state": "",
    }
    first_turn_text = "\n".join(
        str(msg.get("content", ""))
        for msg in results[0]["request_payload_snapshot"]["messages"]
    )
    assert (
        "【写作风格示例开始】" in first_turn_text
        or "<writing_style_example>" in first_turn_text
    )

    second_snapshot = results[1]["request_payload_snapshot"]
    assert results[0]["request_payload_snapshot"]["memory_context_snapshot"] == expected_snapshot
    assert second_snapshot["memory_context_snapshot"] == expected_snapshot
    assert "PROFILE_RUNTIME_ONCE_789" not in second_snapshot["messages"][0]["content"]
    merged_text = "\n".join(
        str(msg.get("content", ""))
        for msg in second_snapshot["messages"]
    )
    for token in expected_snapshot.values():
        if not token:
            continue
        assert merged_text.count(token) == 1, f"{model_id} 中 {token} 被重复注入"


def test_quality_guard_normalizes_legacy_output_to_v49_format():
    quality_guard_module = importlib.import_module("services.quality_guard")
    guard = quality_guard_module.QualityGuard()
    legacy_output = (
        "*灯光沿着落地窗慢慢铺开，他把西装外套搭在臂弯，视线沉沉压过来，"
        "像是早就替今晚的节奏做完了所有安排。空气里有红酒和雪松木混在一起的冷甜味，"
        "呼吸靠近时连距离都显得暧昧起来。*\n"
        "「今晚别想躲开我。」\n\n"
        "*他抬手轻敲桌面，指节落下的节奏很稳，像是在给你留思考的时间，"
        "可那种不动声色的笃定又把退路悄悄收紧，只剩下顺着他的话往前走这一种可能。*\n"
        "「先陪我去吃饭，剩下的安排路上慢慢说。」\n\n"
        "*他垂眼看着你时，眸色被灯影压得更深，唇角没明显上扬，"
        "却偏偏有种克制过头的纵容。那枚车钥匙在掌心里转了一圈，金属反光晃了一下，"
        "又安安稳稳停住，像是在等你把最后一句犹豫亲手递给他。*\n"
        "「你要是还拿不定主意，我就当你默认跟我走。」\n\n"
        "*他最后往前逼近半步，留出的距离刚好够你听清他压低的呼吸，"
        "也刚好够你意识到，这场暧昧从来不是毫无方向地飘着，而是被他耐心又强势地牵着往前。*\n"
        "「现在告诉我，你想让我先带你去哪里？」"
    )

    result = guard.check(legacy_output)

    assert result["needs_retry"] is False
    assert '**"' not in result["processed_text"]
    assert "「" not in result["processed_text"]
    assert "」" not in result["processed_text"]
    assert "*灯光" not in result["processed_text"]
    assert "*他抬手" not in result["processed_text"]
    assert "（灯光" in result["processed_text"]
    assert "今晚别想躲开我。" in result["processed_text"]


def test_quality_guard_normalizes_misaligned_bold_quote_dialogue():
    quality_guard_module = importlib.import_module("services.quality_guard")
    guard = quality_guard_module.QualityGuard()
    malformed_output = (
        "萧璟言指尖捏着刚斟了半杯的波尔多，暗红木纹桌面在暖黄的落地灯里浸出深琥珀色的光。"
        "他抬眼扫过来的时候，喉结动了动，领口两颗扣子没扣，露出一点锁骨的轮廓。\n\n"
        '**"我怎么安排，你就肯照做？**"**\n\n'
        "他把酒杯往你这边推了半寸，杯壁磕碰桌面的声音轻得像落在耳边的呼吸。"
        "指节划过杯沿的弧度很慢，目光落在你握着手机的手指上，顿了两秒才移开。\n\n"
        '**"**之前给你发的私人行程，你看都没看？**"**\n\n'
        "他抬手松了松领带结，动作漫不经心，眼神却带着点不容错辨的侵略性。"
        "手机屏幕亮了一下，是秘书发来的下周红酒品鉴会的邀请函，他随手按灭了，目光没从你脸上移开。"
        "窗外的街灯透过百叶窗漏进来，在他下颌线落下一道浅影。酒气混着雪松调的冷香飘过来，"
        "他往后靠在椅背上，胳膊搭着扶手，指尖轻轻敲了敲扶手的雕花。"
    )

    result = guard.check(malformed_output)

    assert result["needs_retry"] is True
    assert result["retry_reason"] == "格式错误(缺少（旁白）括号包裹)"
    assert "我怎么安排，你就肯照做？" in result["processed_text"]
    assert "之前给你发的私人行程，你看都没看？" in result["processed_text"]
    assert '**"**' not in result["processed_text"]
    assert '**"我怎么安排，你就肯照做？**"**' not in result["processed_text"]


def test_quality_guard_strips_pseudo_xml_dialogue_prefix_without_losing_quote():
    quality_guard_module = importlib.import_module("services.quality_guard")
    guard = quality_guard_module.QualityGuard()
    malformed_output = (
        "窗外的阳光被写字楼的玻璃幕墙折射得有些刺眼，金色的光斑在深褐色的办公桌上缓慢地挪动。"
        "他向后靠在人体工学椅上，指尖轻轻敲击着扶手，眼神落在屏幕上的时间跳到17:51时停顿了一下。"
        "手机屏幕亮起，简单的两个字在通知栏跳出。\n\n"
        '"dialogue">"这么客气？怎么，还没下班啊。"\n\n'
        "他轻笑一声，身体微微前倾，右手习惯性地抚平西装袖口的一道细小褶皱。"
        "想起对方之前抱怨加班到深夜的疲惫模样，他敲击键盘的速度放慢了些，眼神在屏幕上停留了几秒。\n\n"
        '"dialogue">"记得之前说这周末得补回来，想好想吃什么了吗。"\n\n'
        "他看向窗外渐浓的暮色，街上的行人都显得有些急匆匆的。"
        "他想起几家安静且评价不错的私房菜，指尖在屏幕上缓慢地滑动，嘴角勾起一个若有若无的弧度。\n\n"
        '"dialogue">"还是说，累得现在还没主意？"'
    )

    result = guard.check(malformed_output)

    assert result["needs_retry"] is True
    assert result["retry_reason"] == "格式错误(缺少（旁白）括号包裹)"
    assert '"dialogue">' not in result["processed_text"]
    assert "这么客气？怎么，还没下班啊。" in result["processed_text"]
    assert "记得之前说这周末得补回来，想好想吃什么了吗。" in result["processed_text"]
    assert "还是说，累得现在还没主意？" in result["processed_text"]


def test_quality_guard_truncates_single_newline_output_within_v29_range():
    quality_guard_module = importlib.import_module("services.quality_guard")
    guard = quality_guard_module.QualityGuard()
    single_newline_output = "\n".join(
        [
            "落地窗外的霓虹在二十九层玻璃上晕开模糊的光斑，萧璟言指尖转着钢笔，刚签完最后一份项目合同。衬衫袖口挽到小臂，腕间那只古董表在台灯下泛着冷光。听到你声音时，笔尖顿了半秒，墨点落在纸角。",
            '**"刚结束。"**',
            "他把文件推到一边，拿起桌角温着的柠檬水喝了一口，喉结动了动。手机屏幕亮着，是下午部门提交的会议纪要，你的名字在参会人列表里排第三，旁边标注了负责整理的待办项。",
            '**"哪个会开这么久？下午的渠道对接会？我让他们压缩到两小时，结果又拖了三个小时？"**',
            "他翻了翻会议记录的最后一页，看到你标注的三个待解决问题，字迹比平时潦草些，末尾的句号都带着点飘。指尖在你名字旁边敲了敲，指腹蹭过纸面上的墨痕。",
            '**"会议室空调开得低，你今天穿的那件针织衫薄，没冻着吧？"**',
            "助理敲门进来拿文件，他抬了抬手示意先放着，目光没离开手机屏幕。听见你说累，眉头微不可察地皱了一下，钢笔在指节间转了个圈停住。",
            '**"我让司机去接你，二十分钟到你楼下。别自己打车，晚高峰不安全。"**',
            "他站起身走到窗边，指尖擦过冰凉的玻璃，下面的车流像一条缓慢流动的光河。停顿了两秒，嗓音比刚才低了些，带着点漫不经心的懒。",
            '**"我让厨房熬了桃胶羹，你上次说想吃的。现在过来，还热着。"**',
        ]
    )

    assert len(single_newline_output) > 500
    assert "\n\n" not in single_newline_output

    result = guard.check(single_newline_output)

    assert result["needs_retry"] is True
    assert result["retry_reason"] == "格式错误(缺少（旁白）括号包裹)"
    assert any(fix.startswith("字数截断(") for fix in result["fixes_applied"])
    assert '**"' not in result["processed_text"]


def test_quality_guard_closes_dangling_dialogue_line_without_retry():
    quality_guard_module = importlib.import_module("services.quality_guard")
    guard = quality_guard_module.QualityGuard()
    malformed_output = (
        "办公室的百叶窗半拉着，金色夕阳漏进半格，落在萧璟言面前的红木办公桌上。"
        "他刚结束下午的考察回来，袖口挽到小臂，腕间的古董表在光里转了转冷银色的边。"
        "抬眼扫过你手里皱巴巴的会议记录本，指尖在桌面敲了两下。\n\n"
        '"放我这。"\n\n'
        "他伸手接过你递过来的本子，指节擦过你冰凉的手背，顿了半秒才收回去。"
        "翻到最后一页潦草的字迹处，从笔筒里抽了支钢笔，笔尖划过纸面的声音很轻。"
        "你站在桌前晃了晃，后颈还有点僵。\n\n"
        '"早上给你泡的洋甘菊茶喝了？"\n\n'
        "他头都没抬，钢笔在你写错的数字上圈了个圈，旁边补了两行工整的批注。"
        "办公室里只剩笔尖划纸的声响，墙角的落地钟滴答走了三下。"
        "他把改了小半的纪要推回你面前，指腹按在你没写全的备注那行。\n\n"
        '"下午董事会的决议不用记太细，过两天我让助理把最终版发你。"\n\n'
        "他靠回椅背，抬眼看向你，喉结动了动。桌上刚温好的普洱冒着浅白的热气，"
        "飘过来一点陈香。他伸手把茶杯往你那边推了推，杯底磕在桌面发出轻响。\n\n"
        '**"周五晚上我约了人试新开的火锅店，你跟我一起去。'
    )

    result = guard.check(malformed_output)

    assert result["needs_retry"] is True
    assert result["retry_reason"] == "格式错误(缺少（旁白）括号包裹)"
    assert "周五晚上我约了人试新开的火锅店，你跟我一起去。" in result["processed_text"]
    assert '**"' not in result["processed_text"]


def test_prompt_service_build_variables_supports_v26_fields():
    _, prompt_service_module = _import_runtime_modules()
    variables = prompt_service_module.PromptService.build_variables(
        {
            "character": {
                "Role_Nickname": "萧璟言",
                "personality": "理性沉稳",
                "gender": "男",
                "Role_info_works": "代表作A",
            },
            "context": {
                "relationship": "暧昧",
                "currentTime": "2026-03-25 20:15",
                "weekDay": "星期三",
                "timeperiod": "傍晚",
                "season": "春季",
                "last_cst_type": "文本对话",
            },
            "modules": {
                "moments": "朋友圈近况",
                "monthly_schedule": "月底出差安排",
                "voice_forbidden": "禁止语音条",
            },
        }
    )

    assert variables["personal_type"] == "理性沉稳"
    assert variables["Role_info_works"] == "代表作A"
    assert variables["moments"] == "朋友圈近况"
    assert variables["monthly_schedule"] == "月底出差安排"
    assert variables["voice_forbidden"] == "禁止语音条"
    assert variables["last_cst_type"] == "文本对话"
    assert variables["完整时间信息"] == "2026-03-25 20:15 / 星期三 / 傍晚 / 春季"


def test_extract_preset_module_defaults_includes_voice_forbidden():
    modules = extract_preset_module_defaults(PRESET_CHARACTERS["xiaoJingYan"])

    assert modules["voice_forbidden"] == DEFAULT_VOICE_FORBIDDEN


def test_build_longform_variable_bundle_prefers_latest_curated_few_shot():
    runtime_config_module = importlib.import_module("services.runtime_config")
    _, prompt_service_module = _import_runtime_modules()

    bundle = runtime_config_module.build_longform_variable_bundle(
        personality="霸道腹黑",
        relationship="暧昧",
        gender="男",
        preset_characters=PRESET_CHARACTERS,
        relationship_presets=RELATIONSHIP_PRESETS,
        prompt_service=prompt_service_module.PromptService(),
    )

    assert (
        bundle["longform_few_shot"]
        == _resolve_latest_curated_few_shot("霸道腹黑", "男")
    )
    assert bundle["voice_forbidden"] == DEFAULT_VOICE_FORBIDDEN


def test_longform_runtime_config_falls_back_to_v55_injection_depth():
    runtime_config_module = importlib.import_module("services.runtime_config")

    runtime_config = runtime_config_module.LongformRuntimeConfig.from_dict(
        {
            "prompt_file": "test.md",
            "character": {"Role_Nickname": "萧璟言", "personality": "霸道腹黑", "gender": "男"},
            "context": {"relationship": "暧昧"},
            "modules": {"longform_few_shot": _resolve_latest_curated_few_shot("霸道腹黑", "男")},
            "runtime": {},
        }
    )

    assert runtime_config.injection_depth == DEFAULT_INJECTION_DEPTH


def test_runtime_bundle_and_request_snapshot_preserve_custom_variables(tmp_path: Path):
    service = _build_service()
    config_data = _build_runtime_config(service, "xiaoJingYan")
    prompt_path = tmp_path / "v26_prompt.md"
    prompt_path.write_text(
        (
            "朋友圈：{{moments}}\n"
            "月程：{{monthly_schedule}}\n"
            "互动类型：{{last_cst_type}}\n"
            "时间：{{完整时间信息}}\n"
            "<!-- ======================== 以上为 messages[0] role=system 的内容 ======================== -->\n"
        ),
        encoding="utf-8",
    )
    config_data["prompt_file"] = str(prompt_path)
    config_data.setdefault("context", {}).update(
        {
            "currentTime": "2026-03-25 20:15",
            "weekDay": "星期三",
            "timeperiod": "傍晚",
            "season": "春季",
            "last_cst_type": "语音通话",
        }
    )
    config_data["custom_variables"] = {
        "moments": "她刚发了一条夜跑动态",
        "monthly_schedule": "本月最后一周要去深圳出差",
    }

    runtime_bundle = service._prepare_runtime_bundle(config_data)
    snapshot = service._build_request_payload_snapshot(
        config_data,
        runtime_bundle,
        messages=[{"role": "system", "content": runtime_bundle.rendered_system}],
        model_id="dry-run-pro",
    )

    assert "她刚发了一条夜跑动态" not in runtime_bundle.rendered_system
    assert runtime_bundle.memory_moments == "她刚发了一条夜跑动态"
    assert "本月最后一周要去深圳出差" in runtime_bundle.rendered_system
    assert "语音通话" in runtime_bundle.rendered_system
    assert "2026-03-25 20:15 / 星期三 / 傍晚 / 春季" in runtime_bundle.rendered_system
    assert snapshot["custom_variables"]["moments"] == "她刚发了一条夜跑动态"
    assert snapshot["custom_variables"]["monthly_schedule"] == "本月最后一周要去深圳出差"


def test_request_payload_snapshot_exposes_few_shot_debug_metadata():
    service = _build_service()
    config_data = _build_runtime_config(service, "xiaoJingYan")
    runtime_bundle = service._prepare_runtime_bundle(config_data)

    snapshot = service._build_request_payload_snapshot(
        config_data,
        runtime_bundle,
        messages=[{"role": "system", "content": "包含写作风格示例开始"}],
        model_id="dry-run-pro",
    )

    assert snapshot["few_shot_file"]
    assert snapshot["few_shot_message_count"] == len(runtime_bundle.few_shot_messages)
    assert snapshot["few_shot_messages"] == runtime_bundle.few_shot_messages


def test_turn1_runtime_contract_skips_few_shot_and_keeps_sentinel(isolated_db: Path):
    conversation_service_module, _ = _import_runtime_modules()
    service = _build_service()
    config_data = _build_runtime_config(service, "xiaoJingYan")
    conv_id = db.create_conversation(
        model_id="dry-run-pro",
        config=config_data,
        model_mini="dry-run-mini",
        prompt_version=config_data["prompt_file"],
    )

    results = asyncio.run(
        service.run_conversation(
            conv_id=conv_id,
            config=config_data,
            turns=["陪我聊聊今晚的安排"],
            model_id="dry-run-pro",
            model_mini="dry-run-mini",
            summary_interval=1,
            dry_run=True,
        )
    )

    messages = results[0]["messages_snapshot"]
    merged_text = "\n".join(str(msg.get("content", "")) for msg in messages)
    assert (
        "【写作风格示例开始】" in merged_text
        or "<writing_style_example>" in merged_text
    )
    from services.message_assembler import FIRST_TURN_SENTINEL

    sentinel_index = next(
        index for index, msg in enumerate(messages)
        if msg["role"] == "system"
        and FIRST_TURN_SENTINEL in msg["content"]
    )
    assert sentinel_index >= 1
    assert messages[-2]["role"] == "system"
    assert messages[-2]["content"].startswith("<Core_Constraints>")
    assert "300-500字完整叙事" in messages[-2]["content"]
    assert messages[-1] == {
        "role": "user",
        "content": "<user_input>陪我聊聊今晚的安排</user_input>",
    }


def test_turn2_runtime_contract_places_summary_and_history_correctly(isolated_db: Path):
    conversation_service_module, _ = _import_runtime_modules()
    service = _build_service()
    config_data = _build_runtime_config(service, "xiaoJingYan")
    conv_id = db.create_conversation(
        model_id="dry-run-pro",
        config=config_data,
        model_mini="dry-run-mini",
        prompt_version=config_data["prompt_file"],
    )
    user_inputs = ["先陪我打个招呼", "再继续聊两句"]

    results = asyncio.run(
        service.run_conversation(
            conv_id=conv_id,
            config=config_data,
            turns=user_inputs,
            model_id="dry-run-pro",
            model_mini="dry-run-mini",
            summary_interval=1,
            dry_run=True,
        )
    )

    messages = results[1]["messages_snapshot"]
    # dry-run-pro 不是 Gemma，STYLE_ISOLATION 和 memory_context 分离
    style_index = next(
        index for index, msg in enumerate(messages)
        if msg["role"] == "system"
        and conversation_service_module.STYLE_ISOLATION_MSG in msg["content"]
    )
    memory_index = next(
        index for index, msg in enumerate(messages)
        if msg["role"] == "system"
        and "【历史对话摘要】" in msg["content"]
    )
    assert style_index < memory_index  # 分离：先风格隔离，后 memory
    assert "【长期记忆用户画像】" in messages[memory_index]["content"]
    history_user_index = next(
        index for index, msg in enumerate(messages)
        if msg["role"] == "user" and msg["content"] == user_inputs[0]
    )
    history_assistant_index = next(
        index for index, msg in enumerate(messages)
        if msg["role"] == "assistant"
        and msg["content"] == "[dry-run] Turn 1 模拟回复"
    )

    assert memory_index < history_user_index < history_assistant_index
    assert "【用户画像信息】" not in messages[0]["content"]
    assert messages[-2]["role"] == "system"
    assert messages[-2]["content"].startswith("<Core_Constraints>")
    assert messages[-1] == {
        "role": "user",
        "content": f"<user_input>{user_inputs[1]}</user_input>",
    }


def test_target_presets_fill_module_defaults_with_safe_values():
    for preset_id in ("xiaoJingYan", "suTangTang", "xiaoZhan", "chiCheng"):
        modules = extract_preset_module_defaults(PRESET_CHARACTERS[preset_id])
        missing = [key for key in TARGET_PRESET_MODULE_KEYS if not modules.get(key, "").strip()]
        assert not missing, f"{preset_id} 缺少字段: {missing}"

    xiao_jing_yan_modules = extract_preset_module_defaults(PRESET_CHARACTERS["xiaoJingYan"])
    assert xiao_jing_yan_modules["user_Nickname"] == "小鹿"
    assert xiao_jing_yan_modules["system_module8"] == "古董鉴赏、红酒品鉴、高尔夫"

    su_tang_tang_modules = extract_preset_module_defaults(PRESET_CHARACTERS["suTangTang"])
    assert su_tang_tang_modules["user_Nickname"] == "你"
    assert "当前无额外长期记忆与朋友圈事实" in su_tang_tang_modules["dialogueStartPrompt"]

    xiao_zhan_modules = extract_preset_module_defaults(PRESET_CHARACTERS["xiaoZhan"])
    assert xiao_zhan_modules["system_Role_acting"] == CELEBRITY_ROLE_ACTING_BOUNDARY
    assert "音乐创作" in xiao_zhan_modules["system_module8"]

    for preset_id in ("xiaoJingYan", "suTangTang", "chiCheng"):
        modules = extract_preset_module_defaults(PRESET_CHARACTERS[preset_id])
        assert modules["system_Role_acting"] == NON_CELEBRITY_ROLE_ACTING_PLACEHOLDER
