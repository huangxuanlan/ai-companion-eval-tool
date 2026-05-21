#!/usr/bin/env python3
"""Evaluate long-form wake-up prompts with two backend payload shapes.

Shapes:
- user_only: backend replaces the next user message with the wake-up prompt.
- assistant_then_user: backend keeps the bad assistant output, then appends the wake-up prompt as user.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SERVER_DIR = PROJECT_ROOT / "server"
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SERVER_DIR))

try:
    from dotenv import load_dotenv

    load_dotenv(SERVER_DIR / ".env")
except ImportError:
    pass

from services.model_adapter import ModelAdapter

from compare_switching_strategies import DEFAULT_CASE_XLSX, load_excel_data

LONG_TARGET_MODEL = "deepseek-v4-pro"
DEFAULT_WAKE_PROMPT = Path(r"E:\工作资料\产品资料\提示词资料\醒一醒\D_字数不达标_长文版_v0.2.md")
DEFAULT_SOURCE_RESULTS = [
    PROJECT_ROOT / "output" / "mode_switching_switch_state" / "v56_supplement_t14_multimsg_20260514" / "results.jsonl",
    PROJECT_ROOT / "output" / "mode_switching_switch_state" / "v56_supplement_t15_n5_20260514" / "results.jsonl",
    PROJECT_ROOT / "output" / "mode_switching_switch_state" / "v56_supplement_t16_n5_20260514" / "results.jsonl",
]


def cjk_len(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text or ""))


def render_template(template: str, role: dict[str, Any], case: dict[str, Any]) -> str:
    values = {
        "Role_Nickname": role.get("role_name") or case.get("role_name") or "",
        "personal_type": role.get("personality") or "",
        "relationship": role.get("relationship") or "",
        "user_query": case.get("user_query") or "刚刚说到这里，你继续。",
    }
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered


def role_by_label(roles: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {r["label"]: r for r in roles}


def load_source_failures(paths: list[Path], *, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rows.append(json.loads(line))
    failures = [
        r
        for r in rows
        if r.get("target_mode") == "long"
        and not r.get("format_pass")
        and int(r.get("char_count") or 0) < 300
        and r.get("output")
    ]
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in failures:
        key = (row.get("test_id", ""), row.get("role_label", ""), str(row.get("char_count", "")))
        if key in seen:
            continue
        seen.add(key)
        selected.append(
            {
                "case_id": f"{row.get('test_id')}-{row.get('role_label')}-{row.get('run')}",
                "source_test_id": row.get("test_id", ""),
                "scenario": row.get("scenario", ""),
                "role_label": row.get("role_label", ""),
                "role_name": row.get("role_name", ""),
                "user_query": "刚刚说到这里，你继续。",
                "bad_output": row.get("output", ""),
                "bad_char_count": row.get("char_count", 0),
                "failure_reason": row.get("issues", []),
            }
        )
        if len(selected) >= limit:
            break
    return selected


def artificial_cases(roles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labels = [r["label"] for r in roles[:2]]
    samples = [
        ("short_one_line", "（他看着你。）别怕，我在。", ["字数过少", "疑似短文格式"]),
        ("no_parentheses", "他低声说别担心，我会一直陪着你，今晚哪里都不去。", ["字数过少", "丢失（）格式"]),
        ("bad_forbidden", "（他指尖轻轻敲着杯沿。）我知道你还在害怕。", ["禁词: 指尖", "字数过少"]),
        ("half_parentheses", "（他把灯调暗，声音压得很低。别怕，我就在这里。", ["（）不成对", "字数过少"]),
    ]
    cases: list[dict[str, Any]] = []
    for idx, (name, bad_output, reason) in enumerate(samples):
        label = labels[idx % len(labels)]
        cases.append(
            {
                "case_id": f"artificial-{name}",
                "source_test_id": "ART",
                "scenario": name,
                "role_label": label,
                "role_name": "",
                "user_query": "继续刚才的场景，不要停。",
                "bad_output": bad_output,
                "bad_char_count": cjk_len(bad_output),
                "failure_reason": reason,
            }
        )
    return cases


def evaluate_output(output: str) -> dict[str, Any]:
    issues: list[str] = []
    chars = cjk_len(output)
    if chars < 300:
        issues.append(f"字数过少({chars})")
    if chars > 500:
        issues.append(f"字数过多({chars})")
    if "（" not in output or "）" not in output:
        issues.append("丢失（）格式")
    if output.count("（") != output.count("）"):
        issues.append("（）不成对")
    if "指尖" in output:
        issues.append("禁词: 指尖")
    if any(marker in output for marker in ["以下是", "我来重写", "好的", "作为AI"]):
        issues.append("解释性话术泄漏")
    if any(marker in output for marker in ["❗ [以下为", "记录结束", "Core_Constraints", "<user_input>"]):
        issues.append("控制标签泄漏")
    return {
        "char_count": chars,
        "paren_left": output.count("（"),
        "paren_right": output.count("）"),
        "format_pass": not issues,
        "issues": issues,
    }


def build_messages(shape: str, prompt: str, bad_output: str) -> list[dict[str, str]]:
    system = {
        "role": "system",
        "content": "你是长文模式重写执行器。必须只输出重写后的角色回复，不解释。",
    }
    if shape == "user_only":
        return [system, {"role": "user", "content": prompt}]
    if shape == "assistant_then_user":
        return [
            system,
            {"role": "assistant", "content": bad_output},
            {"role": "user", "content": prompt},
        ]
    raise ValueError(f"unknown shape: {shape}")


def call_model(adapter: ModelAdapter | None, messages: list[dict[str, str]], *, dry_run: bool) -> dict[str, Any]:
    if dry_run:
        return {
            "api_success": True,
            "api_error": "",
            "latency": 0.0,
            "output": "（这是一段用于dryrun的长文重写占位内容。）" * 8,
        }
    start = time.time()
    result = adapter.chat(model_id=LONG_TARGET_MODEL, messages=messages, max_tokens=4096)
    return {
        "api_success": bool(result.success),
        "api_error": result.error or "",
        "latency": round(time.time() - start, 3),
        "output": result.content.strip() if result.success and result.content else "",
    }


def append_jsonl(path: Path, item: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def write_cases(path: Path, cases: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for case in cases:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")


def write_summary(path: Path, rows: list[dict[str, Any]], cases_path: Path) -> None:
    lines = [
        "# 长文醒一醒提示词评测报告",
        "",
        f"- 生成时间: {datetime.now().isoformat(timespec='seconds')}",
        f"- cases: {cases_path}",
        f"- 总调用: {len(rows)}",
        f"- API成功: {sum(1 for r in rows if r['api_success'])}/{len(rows)}",
        f"- 格式通过: {sum(1 for r in rows if r['format_pass'])}/{len(rows)}",
        "",
        "## Payload 形态对比",
        "| payload_shape | 总数 | 通过 | 通过率 | 平均字数 | p10字数 | 平均括号组数 |",
        "|:--|--:|--:|--:|--:|--:|--:|",
    ]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["payload_shape"]].append(row)
    for shape, subset in sorted(grouped.items()):
        passed = sum(1 for r in subset if r["format_pass"])
        chars = sorted(r["char_count"] for r in subset)
        p10 = chars[max(0, int(len(chars) * 0.1) - 1)] if chars else 0
        avg_chars = sum(chars) / len(chars)
        avg_paren = sum(min(r["paren_left"], r["paren_right"]) for r in subset) / len(subset)
        lines.append(
            f"| {shape} | {len(subset)} | {passed} | {passed / len(subset) * 100:.1f}% | "
            f"{avg_chars:.1f} | {p10} | {avg_paren:.1f} |"
        )

    lines += [
        "",
        "## 失败明细",
        "| shape | case | run | 原字数 | 新字数 | 问题 |",
        "|:--|:--|--:|--:|--:|:--|",
    ]
    for row in [r for r in rows if not r["format_pass"]][:80]:
        lines.append(
            f"| {row['payload_shape']} | {row['case_id']} | {row['run']} | "
            f"{row['bad_char_count']} | {row['char_count']} | {';'.join(row['issues'])} |"
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate long wake-up prompt payload shapes")
    parser.add_argument("--prompt", type=Path, default=DEFAULT_WAKE_PROMPT)
    parser.add_argument("--excel", type=Path, default=DEFAULT_CASE_XLSX)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--case-limit", type=int, default=12)
    parser.add_argument("--runs-per-case", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results_path = args.output_dir / "results.jsonl"
    cases_path = args.output_dir / "cases.jsonl"
    summary_path = args.output_dir / "summary.md"
    if results_path.exists():
        results_path.unlink()

    roles = load_excel_data(args.excel)
    roles_by_label = role_by_label(roles)
    cases = load_source_failures(DEFAULT_SOURCE_RESULTS, limit=args.case_limit)
    cases.extend(artificial_cases(roles))
    write_cases(cases_path, cases)

    template = args.prompt.read_text(encoding="utf-8")
    adapter = None if args.dry_run else ModelAdapter()
    rows: list[dict[str, Any]] = []
    shapes = ["user_only", "assistant_then_user"]

    print(f"[INFO] cases={len(cases)} shapes={shapes} runs={args.runs_per_case} dry_run={args.dry_run}")
    for case in cases:
        role = roles_by_label.get(case["role_label"]) or roles[0]
        rendered_prompt = render_template(template, role, case)
        for shape in shapes:
            messages = build_messages(shape, rendered_prompt, case["bad_output"])
            for run in range(1, args.runs_per_case + 1):
                print(f"[RUN] {shape} {case['case_id']} run={run}")
                call = call_model(adapter, messages, dry_run=args.dry_run)
                metrics = evaluate_output(call["output"])
                if not call["api_success"]:
                    metrics["format_pass"] = False
                    metrics["issues"] = [f"API失败: {call['api_error'][:120]}"] + metrics["issues"]
                row = {
                    "prompt_path": str(args.prompt),
                    "payload_shape": shape,
                    "case_id": case["case_id"],
                    "source_test_id": case["source_test_id"],
                    "scenario": case["scenario"],
                    "role_label": case["role_label"],
                    "role_name": role.get("role_name", ""),
                    "run": run,
                    "bad_output": case["bad_output"],
                    "bad_char_count": case["bad_char_count"],
                    "failure_reason": case["failure_reason"],
                    "message_count": len(messages),
                    "role_sequence": " > ".join(m["role"] for m in messages),
                    "dry_run": args.dry_run,
                    **call,
                    **metrics,
                }
                rows.append(row)
                append_jsonl(results_path, row)
                status = "PASS" if row["format_pass"] else "FAIL " + ";".join(row["issues"])
                print(f"  -> {row['char_count']}字 {status}")

    write_summary(summary_path, rows, cases_path)
    print(f"[DONE] cases={cases_path}")
    print(f"[DONE] results={results_path}")
    print(f"[DONE] summary={summary_path}")


if __name__ == "__main__":
    main()
