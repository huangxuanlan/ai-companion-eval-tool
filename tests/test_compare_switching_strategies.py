from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

from openpyxl import Workbook

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "compare_switching_strategies.py"

spec = importlib.util.spec_from_file_location(
    "compare_switching_strategies",
    SCRIPT_PATH,
)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def _history() -> list[dict[str, str]]:
    return [
        {"role": "user", "content": "第一句", "source_mode": "long"},
        {"role": "assistant", "content": "第一段长文回复", "source_mode": "long"},
        {"role": "user", "content": "第二句", "source_mode": "long"},
        {"role": "assistant", "content": "第二段长文回复", "source_mode": "long"},
        {"role": "user", "content": "切换后当前输入", "source_mode": "long"},
        {"role": "assistant", "content": "旧模式已经回答过当前输入", "source_mode": "long"},
    ]


def _case_xlsx(path: Path) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    rows = [
        ["变量代码", "角色1"],
        ["@全局用户参数_relationship&", "暧昧"],
        ["@全局用户参数_Role_Nickname&", "肖战"],
        ["@全局用户参数_personality&", "温暖"],
        ["@全局用户参数_speaking_style&", "自然口语"],
        ["@全局用户参数_user_Nickname&", "小满"],
        ["@全局用户参数_dialogueStartPrompt&", "<dialogue_history>无</dialogue_history>"],
        [
            "短文对话示例",
            "用户\n早安\n\nAI\n（看向你）早安。\n\n用户\n想你\n\nAI\n（弯眼）我也想你。\n\n用户\n晚上见",
        ],
        [
            "长文对话示例",
            "[05-13 18:00][user]\n今天累吗？\n[05-13 18:03][assistant]\n他抬眼看向你，声音放轻。\n[05-13 18:06][user]\n那你早点休息。\n[05-13 18:09][assistant]\n他点点头，把疲惫藏进笑意里。\n[05-13 18:12][user]\n明天还拍戏吗？",
        ],
    ]
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    return path


def test_split_switch_context_excludes_current_user_and_answered_tail():
    context = module.split_switch_context(_history())

    assert context.current_user == "切换后当前输入"
    assert [m["content"] for m in context.context_history] == [
        "第一句",
        "第一段长文回复",
        "第二句",
        "第二段长文回复",
    ]


def test_strategy_b_messages_do_not_repeat_current_user():
    context = module.split_switch_context(_history())
    bridged = module.sandwich_history(context.context_history, "short", 5)
    messages = module.build_strategy_b_messages("system", "summary", bridged, context.current_user)

    structure = module.evaluate_message_structure(messages, context.current_user)

    assert structure["structure_pass"] is True
    assert structure["duplicate_current_user_in_history"] == 0
    assert messages[-1] == {"role": "user", "content": "切换后当前输入"}
    assert "长文模式回复记录" in messages[3]["content"]


def test_sandwich_history_normalizes_boundaries_and_same_role_runs():
    raw = [
        {"role": "assistant", "content": "孤立assistant", "source_mode": "short"},
        {"role": "assistant", "content": "连续assistant", "source_mode": "short"},
        {"role": "user", "content": "用户1", "source_mode": "short"},
        {"role": "assistant", "content": "短文回复1", "source_mode": "short"},
        {"role": "assistant", "content": "短文回复2", "source_mode": "short"},
        {"role": "user", "content": "未回答用户", "source_mode": "short"},
    ]

    bridged = module.sandwich_history(raw, "long", 5)
    roles = [msg["role"] for msg in bridged]
    merged_text = "\n".join(msg["content"] for msg in bridged)

    # F5 修复后开头孤立 assistant 不再被丢弃，而是补占位 user 保留历史；
    # 同 role 连跑仍会合并，末尾的孤立 user 被剔除。
    assert roles[0] == "user"
    assert roles[-1] == "assistant"
    assert all(
        roles[i] != roles[i + 1] for i in range(len(roles) - 1)
    ), f"sandwich 后不应有连续相同 role: {roles}"
    assert "孤立assistant" in merged_text and "连续assistant" in merged_text
    assert "短文回复1" in merged_text and "短文回复2" in merged_text
    last_assistant_content = next(
        msg["content"] for msg in reversed(bridged) if msg["role"] == "assistant"
    )
    assert "短文回复1" in last_assistant_content
    assert "短文回复2" in last_assistant_content
    assert "未回答用户" not in merged_text


def test_evaluate_output_uses_declared_word_ranges():
    short_metrics = module.evaluate_output("太短了", "short")
    long_metrics = module.evaluate_output("短句。" * 80, "long")

    assert short_metrics["format_pass"] is False
    assert "字数过少" in short_metrics["issues"][0]
    assert long_metrics["format_pass"] is False
    assert "字数过少" in long_metrics["issues"][0]


def test_cli_dry_run_smoke_writes_structure_results(tmp_path):
    excel = _case_xlsx(tmp_path / "cases.xlsx")
    output_dir = tmp_path / "out"

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--excel",
            str(excel),
            "--output-dir",
            str(output_dir),
            "--dry-run",
        ],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    results = (output_dir / "results.jsonl").read_text(encoding="utf-8")
    assert '"dry_run": true' in results
    assert '"structure_pass": true' in results
    assert "当前user在历史中重复" not in results
    assert (output_dir / "summary.md").exists()
