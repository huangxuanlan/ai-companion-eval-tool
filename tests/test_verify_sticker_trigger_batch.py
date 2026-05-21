from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "verify_sticker_trigger_batch.py"

spec = importlib.util.spec_from_file_location(
    "verify_sticker_trigger_batch",
    SCRIPT_PATH,
)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_scene_matrix_has_10_cases_with_7_trigger_and_3_suppress():
    scenes = module.build_sticker_scenes()

    assert len(scenes) == 10
    assert sum(1 for scene in scenes if scene.expect_sticker) == 7
    assert sum(1 for scene in scenes if not scene.expect_sticker) == 3
    assert {scene.scene_id for scene in scenes} == {
        "user_sent_sticker",
        "user_misses_role",
        "user_good_news",
        "user_low_mood",
        "user_praises_role",
        "flirty_tease",
        "summon_companion",
        "previous_sticker_suppress",
        "plain_info_suppress",
        "serious_boundary_suppress",
    }


def test_rendered_prompt_has_no_unresolved_placeholders():
    role = module.build_male_role_fixtures()[0]
    scene = module.build_sticker_scenes()[0]

    rendered = module.render_prompt(module.DEFAULT_PROMPT_TEMPLATE, role, scene)

    assert "{{" not in rendered
    assert "}}" not in rendered
    assert role.variables["Role_Nickname"] in rendered
    assert scene.relationship in rendered


def test_validate_sticker_output_flags_hard_format_errors():
    trigger_scene = next(
        scene
        for scene in module.build_sticker_scenes()
        if scene.scene_id == "user_sent_sticker"
    )
    suppress_scene = next(
        scene
        for scene in module.build_sticker_scenes()
        if scene.scene_id == "plain_info_suppress"
    )

    clean = module.validate_sticker_output(
        "（他低头笑了一下）这下被你拿捏到了。[STICKER:搓手手]",
        trigger_scene,
    )
    assert clean["pass"]
    assert clean["warnings"] == []

    trailing_text = module.validate_sticker_output(
        "（他低头笑了一下）这下被你拿捏到了。[STICKER:搓手手]嘿嘿",
        trigger_scene,
    )
    assert trailing_text["pass"]
    assert "表情包信号后存在文字" in trailing_text["warnings"]

    assert "表情包信号数量超过1" in module.validate_sticker_output(
        "（他眨了眨眼）来啦。[STICKER:来啦][STICKER:比心]",
        trigger_scene,
    )["issues"]
    assert "表情包信号格式错乱" in module.validate_sticker_output(
        "（他眨了眨眼）来啦。[STICKER 比心]",
        trigger_scene,
    )["issues"]
    assert "表情包信号未用[]包裹" in module.validate_sticker_output(
        "（他眨了眨眼）来啦。STICKER:比心",
        trigger_scene,
    )["issues"]

    invalid_name = module.validate_sticker_output(
        "（他眨了眨眼）来啦。[STICKER:不存在]",
        trigger_scene,
    )
    assert not invalid_name["pass"]
    assert "表情包名称不在可用集合" in invalid_name["issues"]

    scene_mismatch = module.validate_sticker_output(
        "（他眨了眨眼）来啦。[STICKER:小狗的肯定]",
        trigger_scene,
    )
    assert scene_mismatch["pass"]
    assert scene_mismatch["issues"] == []
    assert "表情包名称不在推荐集合" in scene_mismatch["warnings"]

    suppress_misfire = module.validate_sticker_output(
        "（他点点头）这条信息我看到了。[STICKER:比心]",
        suppress_scene,
    )
    assert suppress_misfire["pass"]
    assert suppress_misfire["issues"] == []
    assert "抑制场景误发表情包" in suppress_misfire["warnings"]

    trigger_missing = module.validate_sticker_output(
        "（他点点头）这条信息我看到了，先把你这句接住。",
        trigger_scene,
    )
    assert trigger_missing["pass"]
    assert trigger_missing["issues"] == []
    assert "应触发表情包但未输出" in trigger_missing["warnings"]

    red_packet_leak = module.validate_sticker_output(
        "（他点点头）这条信息我看到了。[TRANSFER:520:想你了]",
        suppress_scene,
    )
    assert red_packet_leak["pass"]
    assert red_packet_leak["issues"] == []


def test_previous_sticker_context_uses_additional_messages():
    scene = next(
        scene
        for scene in module.build_sticker_scenes()
        if scene.scene_id == "previous_sticker_suppress"
    )
    case = module.StickerCase(
        case_id="sample_previous_sticker",
        role=module.build_male_role_fixtures()[0],
        scene=scene,
    )

    assert scene.additional_messages
    assert not hasattr(scene, "history")
    messages = module.build_messages(
        prompt_template=module.DEFAULT_PROMPT_TEMPLATE,
        case=case,
    )

    assert messages[-1] == {"role": "user", "content": scene.user_input}
    assert any("[STICKER:比心]" in item["content"] for item in messages[2:-1])


def test_dry_run_writes_expected_artifacts(tmp_path):
    out_dir = tmp_path / "sticker_trigger"

    result = module.run_batch(
        output_dir=out_dir,
        run_level="dry-run",
        prompt_template=module.DEFAULT_PROMPT_TEMPLATE,
    )

    assert result["output_dir"] == out_dir
    assert result["total"] == 20
    assert result["passed"] == 20
    assert (out_dir / "prompt_snapshot.md").exists()
    assert (out_dir / "cases.jsonl").exists()
    assert (out_dir / "results.jsonl").exists()
    assert (out_dir / "summary.md").exists()


def test_load_prompt_template_does_not_silently_fallback(monkeypatch, tmp_path):
    missing = tmp_path / "missing_prompt.md"
    monkeypatch.setattr(module, "REFERENCE_PROMPT_PATH", missing)

    try:
        module.load_prompt_template(None)
    except FileNotFoundError as exc:
        assert "--prompt-file" in str(exc)
    else:
        raise AssertionError("expected missing default prompt to fail")
