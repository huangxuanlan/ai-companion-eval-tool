from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "verify_10t_sandwich_excel_batch.py"

spec = importlib.util.spec_from_file_location(
    "verify_10t_sandwich_excel_batch",
    SCRIPT_PATH,
)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_sample_user_inputs_picks_first_middle_last_without_duplicates():
    turns = ["第一句", "第二句", "第三句", "第四句", "第五句"]

    sampled = module.sample_user_inputs(turns, 3)

    assert sampled == ["第一句", "第三句", "第五句"]


def test_evaluate_short_output_flags_control_tokens_and_bad_brackets():
    messages = [{"role": "assistant", "content": "之前的回复"}]

    metrics = module.evaluate_short_output(
        "[TRANSFER:520:short](摸摸你)我在。",
        messages,
    )

    assert metrics["format_pass"] is False
    assert "控制标记泄漏" in metrics["issues"]
    assert "括号动作格式异常" in metrics["issues"]
