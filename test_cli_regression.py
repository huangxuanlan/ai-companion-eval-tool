#!/usr/bin/env python3
"""统一版 CLI 回归测试。"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = BASE_DIR / "longform_multi_turn.py"
CONFIG_PATH = BASE_DIR / "test_conversation_萧璟言.json"
OUTPUT_ROOT = BASE_DIR / "output" / "test_runtime" / "cli_regression"


def assert_true(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)


def run_cli(args: list[str], env: dict[str, str] | None = None):
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=BASE_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    return proc


def message_counts(stdout: str) -> list[int]:
    return [int(num) for num in re.findall(r"消息数量:\s*(\d+)", stdout)]


def make_explicit_fewshot_config(target: Path) -> Path:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    payload["few_shot_file"] = str(BASE_DIR / "few_shot" / "长文模式_Few-shot示例库.md")
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def reset_dir(path: Path):
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def test_default_encoding_and_no_exports():
    out_dir = OUTPUT_ROOT / "dryrun_default"
    reset_dir(out_dir)
    env = os.environ.copy()
    env.pop("PYTHONIOENCODING", None)
    proc = run_cli(
        [str(CONFIG_PATH), "--dry-run", "--turns", "2", "--output-dir", str(out_dir)],
        env=env,
    )
    assert_true(proc.returncode == 0, f"默认编码 dry-run 失败: {proc.stderr}")
    exported = list(out_dir.glob("*.json")) + list(out_dir.glob("*.xlsx"))
    assert_true(not exported, f"dry-run 产生了导出文件: {[p.name for p in exported]}")


def test_default_json_fewshot_and_summary():
    out_dir = OUTPUT_ROOT / "dryrun_default_6turns"
    reset_dir(out_dir)
    env = os.environ.copy()
    env.pop("PYTHONIOENCODING", None)
    proc = run_cli(
        [str(CONFIG_PATH), "--dry-run", "--turns", "6", "--output-dir", str(out_dir)],
        env=env,
    )
    assert_true(proc.returncode == 0, f"默认 JSON dry-run 失败: {proc.stderr}")
    counts = message_counts(proc.stdout)
    assert_true(len(counts) >= 6, f"未解析到 6 轮消息数: {counts}")
    # legacy CLI 首轮跳过 few-shot，仅保留 system + 首轮提示 + Core_Constraints + 当前输入
    assert_true(counts[0] == 4, f"Turn1 消息数错误: {counts}")
    # legacy CLI 仍沿用旧 dry-run 拼接：2 组 few-shot + 5 轮历史 + Core_Constraints + 当前输入
    assert_true(counts[5] == 20, f"Turn6 消息数错误: {counts}")


def test_explicit_fewshot_path():
    with tempfile.TemporaryDirectory(prefix="longform_cli_", dir=str(OUTPUT_ROOT)) as tmpdir:
        tmpdir_path = Path(tmpdir)
        config_path = make_explicit_fewshot_config(tmpdir_path / "explicit_fewshot.json")
        out_dir = tmpdir_path / "out"
        out_dir.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env.pop("PYTHONIOENCODING", None)
        proc = run_cli(
            [str(config_path), "--dry-run", "--turns", "2", "--output-dir", str(out_dir)],
            env=env,
        )
        assert_true(proc.returncode == 0, f"显式 Few-shot dry-run 失败: {proc.stderr}")
        counts = message_counts(proc.stdout)
        assert_true(counts[:2] == [4, 12], f"显式 Few-shot 消息数错误: {counts}")
        exported = list(out_dir.glob("*.json")) + list(out_dir.glob("*.xlsx"))
        assert_true(not exported, f"显式 Few-shot dry-run 产生导出文件: {[p.name for p in exported]}")


def test_cli_constraints_aligned_to_v26():
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert_true("300-500字完整叙事" in source, "CLI Core_Constraints 未对齐 300-500 字")
    assert_true('对白用 **""** 包裹' in source, "CLI Core_Constraints 未对齐 v2.6 对白格式")
    assert_true("600-800字完整叙事" not in source, "CLI 仍残留 600-800 字旧约束")
    assert_true("旁白用*包裹" not in source, "CLI 仍残留旧旁白格式约束")
    assert_true("对白用「」包裹" not in source, "CLI 仍残留旧对白格式约束")


def main():
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    tests = [
        ("默认编码与 dry-run 零导出", test_default_encoding_and_no_exports),
        ("默认 JSON Few-shot 与摘要注入", test_default_json_fewshot_and_summary),
        ("显式 Few-shot 路径", test_explicit_fewshot_path),
        ("CLI 约束已对齐 v2.6", test_cli_constraints_aligned_to_v26),
    ]
    passed = 0
    for name, test in tests:
        test()
        passed += 1
        print(f"[PASS] {name}")
    print(f"\nCLI 回归通过: {passed}/{len(tests)}")


if __name__ == "__main__":
    main()
