#!/usr/bin/env python3
"""Run v5.6 supplemental mode-switch tests T14/T15/T16.

This script is intentionally separate from compare_switching_strategies.py:
the v5.6补测 uses a direction-specific contract and long-form validation
requires full-width Chinese parentheses.
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

from compare_switching_strategies import (
    DEFAULT_CASE_XLSX,
    EXTRACTOR_MODEL,
    LONG_SANDWICH_END,
    LONG_SANDWICH_START,
    LONG_TARGET_MODEL,
    SHORT_SANDWICH_END,
    SHORT_SANDWICH_START,
    build_short_system,
    build_transcript_with_timestamp,
    generate_interaction_points,
    generate_long_summary,
    generate_short_summary,
    load_excel_data,
    render_summary_json_to_labels,
    sandwich_history,
    split_switch_context,
)

SHORT_TARGET_MODEL = "doubao-lite"
RESULT_SCHEMA_VERSION = "v56-supplement-20260514"
DEFAULT_LONG_WAKE_PROMPT_PATH = Path(r"E:\工作资料\产品资料\提示词资料\醒一醒\D_字数不达标_长文版_v0.3_20260514.md")


def cjk_len(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text or ""))


def message_pairs(history: list[dict[str, str]], turns: int, *, start_pair: int = 0) -> list[dict[str, str]]:
    """Return complete user/assistant pairs from a history."""
    pairs: list[list[dict[str, str]]] = []
    current: list[dict[str, str]] = []
    for msg in history:
        role = msg.get("role")
        if role == "user":
            if current:
                current = []
            current = [msg]
        elif role == "assistant" and current and current[0].get("role") == "user":
            current.append(msg)
            pairs.append(current)
            current = []
    selected = pairs[start_pair : start_pair + turns]
    flattened: list[dict[str, str]] = []
    for pair in selected:
        flattened.extend(pair)
    return flattened


def take_recent_pairs(history: list[dict[str, str]], turns: int) -> list[dict[str, str]]:
    pairs = message_pairs(history, 10_000)
    pair_count = len(pairs) // 2
    return pairs[-turns * 2 :] if pair_count >= turns else pairs


def v56_long_system(role: dict[str, Any]) -> str:
    return f"""# 星朋友·长文沉浸式叙事模式

你通过第三人称沉浸式叙事，完全化身为用户创建的虚拟恋人角色。

# v5.6 硬性输出格式
- 输出长度必须为 300-500 个中文字符。
- 必须使用中文全角括号（）包裹动作、神态、心理或环境描写，括号必须成对闭合。
- 对白自然嵌入在叙事中；不得退化为短文聊天格式。
- 不得出现"指尖"。
- 必须衔接历史事实，不可凭空重启场景。

# 当前时间
- 现在时间是2026-05-14  晚上 星期四 春季

# 你们的关系
- {role['relationship']}

# 身份设定
- 角色为{role['role_name']}，性格{role['personality']}

# 语言风格
{role['speaking_style']}

# 长期记忆用户画像
{role['dialogue_start_prompt']}
"""


def render_sandwich_block(history: list[dict[str, str]], target_mode: str) -> str:
    lines: list[str] = []
    for msg in history:
        role = msg.get("role")
        content = msg.get("content", "")
        source = msg.get("source_mode", "")
        if role == "assistant" and source and source != target_mode:
            if source == "short":
                content = f"{SHORT_SANDWICH_START}\n{content}\n{SHORT_SANDWICH_END}"
            else:
                content = f"{LONG_SANDWICH_START}\n{content}\n{LONG_SANDWICH_END}"
        label = "用户" if role == "user" else "角色"
        lines.append(f"{label}：{content}")
    return "\n\n".join(lines)


def build_v56_short_to_long_messages(
    role: dict[str, Any],
    summary: str,
    bridge_history: list[dict[str, str]],
    current_user: str,
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": v56_long_system(role)},
        {
            "role": "assistant",
            "content": (
                "（以下为角色内部认知记录，仅供事实衔接，请勿模仿此格式。）\n"
                f"=== 切换摘要开始 ===\n{summary}\n=== 切换摘要结束 ==="
            ),
        },
        *bridge_history,
        {
            "role": "user",
            "content": (
                "<Core_Constraints>"
                "你现在必须切换为长文模式输出；输出300-500个中文字符；"
                "必须使用中文全角括号（）包裹动作、神态、心理或环境描写；"
                "不得按短文模式只回一句话；不得出现指尖；只输出角色回复。"
                "</Core_Constraints>\n\n"
                f"<user_input>{current_user}</user_input>"
            ),
        },
    ]


def build_v56_long_to_short_messages(
    role: dict[str, Any],
    summary: str,
    points_or_fallback: str,
    current_user: str,
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": build_short_system(role)},
        {
            "role": "assistant",
            "content": (
                "（以下为角色内部认知记录，仅供上下文参考，请勿模仿此格式。）\n"
                f"=== 动态摘要开始 ===\n{summary}\n\n{points_or_fallback}\n=== 摘要结束 ==="
            ),
        },
        {"role": "user", "content": current_user},
    ]


def build_raw_history_fallback(history: list[dict[str, str]], target_mode: str, turns: int = 5) -> str:
    recent = take_recent_pairs(history, turns)
    return "【L1原始对话历史兜底】\n" + render_sandwich_block(recent, target_mode)


def short_wake_messages(bad_output: str, current_user: str) -> list[dict[str, str]]:
    prompt = f"""你是短文模式格式守门员。请把下面不合规回复重写为合规短文回复。

硬性要求：
- 30-90个中文字符。
- 不出现"指尖"。
- 不输出长文隔离标签、加粗对白或第三人称长段叙事。
- 只输出重写后的角色回复，不解释。

当前用户输入：{current_user}

不合规回复：
{bad_output}
"""
    return [{"role": "user", "content": prompt}]


def long_wake_messages(bad_output: str, current_user: str) -> list[dict[str, str]]:
    prompt = f"""你是长文模式格式守门员。请把下面不合规回复重写为合规长文回复。

硬性要求：
- 300-500个中文字符。
- 必须使用中文全角括号（）包裹动作、神态、心理或环境描写，括号必须成对闭合。
- 衔接当前用户输入，不要重启场景。
- 不出现"指尖"。
- 只输出重写后的角色回复，不解释。

当前用户输入：{current_user}

不合规回复：
{bad_output}
"""
    return [{"role": "user", "content": prompt}]


def render_long_wake_prompt(template: str, role: dict[str, Any], current_user: str) -> str:
    values = {
        "Role_Nickname": role.get("role_name", ""),
        "personal_type": role.get("personality", ""),
        "relationship": role.get("relationship", ""),
        "user_query": current_user,
    }
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered


def long_wake_user_only_messages(role: dict[str, Any], current_user: str, prompt_path: Path) -> list[dict[str, str]]:
    template = prompt_path.read_text(encoding="utf-8")
    return [{"role": "user", "content": render_long_wake_prompt(template, role, current_user)}]


def fact_overlap_score(output: str, context: str) -> float:
    """A small deterministic continuity proxy based on CJK 2-gram overlap."""
    out_chars = re.findall(r"[\u4e00-\u9fff]", output or "")
    ctx_chars = re.findall(r"[\u4e00-\u9fff]", context or "")
    out_grams = {"".join(out_chars[i : i + 2]) for i in range(max(0, len(out_chars) - 1))}
    ctx_grams = {"".join(ctx_chars[i : i + 2]) for i in range(max(0, len(ctx_chars) - 1))}
    stop = {"我们", "你们", "这个", "那个", "什么", "一下", "没有", "不是", "就是", "可以"}
    out_grams -= stop
    ctx_grams -= stop
    if not out_grams or not ctx_grams:
        return 0.0
    return len(out_grams & ctx_grams) / max(1, len(out_grams))


def evaluate_v56(output: str, target_mode: str, context_text: str = "") -> dict[str, Any]:
    issues: list[str] = []
    chars = cjk_len(output)
    if "指尖" in output:
        issues.append("禁词: 指尖")

    if target_mode == "short":
        if chars < 30:
            issues.append(f"字数过少({chars})")
        if chars > 90:
            issues.append(f"字数超标({chars}>90)")
        if "❗ [以下为" in output or "记录结束" in output:
            issues.append("隔离标签泄漏")
        if "**" in output:
            issues.append("加粗对白泄漏")
        if output.count("\n") > 3:
            issues.append("换行过多")
    else:
        if chars < 300:
            issues.append(f"字数过少({chars})")
        if chars > 500:
            issues.append(f"字数过多({chars})")
        if "（" not in output or "）" not in output:
            issues.append("丢失（）格式")
        if output.count("（") != output.count("）"):
            issues.append("（）不成对")
        if output.startswith("（") and chars < 150:
            issues.append("疑似短文格式")

    overlap = fact_overlap_score(output, context_text) if context_text else 0.0
    if context_text and overlap < 0.015:
        issues.append(f"事实衔接弱(overlap={overlap:.3f})")

    return {
        "char_count": chars,
        "fact_overlap": round(overlap, 4),
        "format_pass": not issues,
        "issues": issues,
    }


def call_model(
    adapter: ModelAdapter | None,
    *,
    model_id: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    dry_run: bool,
    target_mode: str,
) -> dict[str, Any]:
    start = time.time()
    if dry_run:
        output = (
            "这是一条用于结构验证的短文占位回复内容已经超过三十个中文字符"
            if target_mode == "short"
            else "（dryrun动作描写）" * 90
        )
        return {"api_success": True, "api_error": "", "output": output, "latency": 0.0}
    result = adapter.chat(model_id=model_id, messages=messages, max_tokens=max_tokens)
    return {
        "api_success": bool(result.success),
        "api_error": result.error or "",
        "output": result.content.strip() if result.success and result.content else "",
        "latency": round(time.time() - start, 3),
    }


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_case(
    *,
    adapter: ModelAdapter | None,
    results_path: Path,
    test_id: str,
    scenario: str,
    role: dict[str, Any],
    run: int,
    target_mode: str,
    target_model: str,
    messages: list[dict[str, str]],
    context_text: str,
    dry_run: bool,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    print(f"[{test_id}] {scenario} | {role['label']} {role['role_name']} | run {run} | {target_model}")
    call = call_model(
        adapter,
        model_id=target_model,
        messages=messages,
        max_tokens=4096 if target_mode == "long" else 600,
        dry_run=dry_run,
        target_mode=target_mode,
    )
    metrics = evaluate_v56(call["output"], target_mode, "" if dry_run else context_text)
    if not call["api_success"]:
        metrics["format_pass"] = False
        metrics["issues"] = [f"API失败: {call['api_error'][:120]}"] + metrics["issues"]
    row = {
        "schema": RESULT_SCHEMA_VERSION,
        "test_id": test_id,
        "scenario": scenario,
        "role_label": role["label"],
        "role_name": role["role_name"],
        "run": run,
        "target_mode": target_mode,
        "target_model": target_model,
        "message_count": len(messages),
        "role_sequence": " > ".join(m["role"] for m in messages),
        "dry_run": dry_run,
        **call,
        **metrics,
        **(extra or {}),
    }
    append_jsonl(results_path, row)
    status = "PASS" if row["format_pass"] else "FAIL " + ";".join(row["issues"])
    print(f"  -> {row['char_count']}字 overlap={row['fact_overlap']} {status}")
    return row


def make_multisegment_history(role: dict[str, Any], pattern: list[tuple[str, int]]) -> list[dict[str, str]]:
    offsets = {"short": 0, "long": 0}
    history: list[dict[str, str]] = []
    for mode, turns in pattern:
        source = role["shortform_history"] if mode == "short" else role["longform_history"]
        segment = message_pairs(source, turns, start_pair=offsets[mode])
        if len(segment) < turns * 2:
            segment = take_recent_pairs(source, turns)
        history.extend(segment)
        offsets[mode] += turns
    return history


def current_user_for(target_mode: str) -> str:
    if target_mode == "long":
        return "刚刚说到这里，你继续。"
    return "那你现在想怎么回我？"


def run_t14(adapter: ModelAdapter | None, roles: list[dict[str, Any]], args: argparse.Namespace, results_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for turns in [1, 3, 5]:
        for role in roles[:4]:
            source_context = split_switch_context(role["shortform_history"])
            context_hist = source_context.context_history
            current_user = source_context.current_user
            summary = "dry-run短文切换摘要" if args.dry_run else generate_short_summary(adapter, context_hist)
            bridge = sandwich_history(context_hist, "long", turns)
            messages = build_v56_short_to_long_messages(role, summary, bridge, current_user)
            context_text = render_sandwich_block(bridge, "long") + "\n" + summary
            for run in range(1, args.runs_per_case + 1):
                rows.append(
                    run_case(
                        adapter=adapter,
                        results_path=results_path,
                        test_id=f"T14-{turns}",
                        scenario=f"{turns}轮三明治",
                        role=role,
                        run=run,
                        target_mode="long",
                        target_model=LONG_TARGET_MODEL,
                        messages=messages,
                        context_text=context_text,
                        dry_run=args.dry_run,
                        extra={"sandwich_turns": turns},
                    )
                )
    return rows


T15_SCENARIOS = [
    ("T15-1", "短起步三段切长", [("short", 3), ("long", 4), ("short", 3)], "long"),
    ("T15-2", "长起步三段切短", [("long", 3), ("short", 4), ("long", 3)], "short"),
    ("T15-3", "快速往返切长", [("short", 1), ("long", 1), ("short", 1)], "long"),
    ("T15-4", "快速往返切短", [("long", 1), ("short", 1), ("long", 1)], "short"),
    ("T15-5", "10轮短文后切长", [("short", 10)], "long"),
    ("T15-6", "8轮长文后切短", [("long", 8)], "short"),
]


def run_t15(adapter: ModelAdapter | None, roles: list[dict[str, Any]], args: argparse.Namespace, results_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for test_id, scenario, pattern, target_mode in T15_SCENARIOS:
        for role in roles[:2]:
            mixed = make_multisegment_history(role, pattern)
            current_user = current_user_for(target_mode)
            if target_mode == "long":
                summary = "dry-run多段切换摘要" if args.dry_run else generate_short_summary(adapter, mixed)
                bridge = sandwich_history(mixed, "long", args.sandwich_turns)
                messages = build_v56_short_to_long_messages(role, summary, bridge, current_user)
                target_model = LONG_TARGET_MODEL
                context_text = build_transcript_with_timestamp(mixed, "chinese")
            else:
                summary = "【剧情】dry-run多段长文摘要" if args.dry_run else generate_long_summary(adapter, mixed)
                points = "dry-run互动要点" if args.dry_run else generate_interaction_points(adapter, mixed)
                messages = build_v56_long_to_short_messages(role, summary, points, current_user)
                target_model = args.short_target_model
                context_text = build_transcript_with_timestamp(mixed, "chinese")
            for run in range(1, 3):
                rows.append(
                    run_case(
                        adapter=adapter,
                        results_path=results_path,
                        test_id=test_id,
                        scenario=scenario,
                        role=role,
                        run=run,
                        target_mode=target_mode,
                        target_model=target_model,
                        messages=messages,
                        context_text=context_text,
                        dry_run=args.dry_run,
                        extra={"sandwich_turns": args.sandwich_turns, "pattern": pattern},
                    )
                )
    return rows


def run_t16(adapter: ModelAdapter | None, roles: list[dict[str, Any]], args: argparse.Namespace, results_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    bad_short = "我会把这些长文记录全部照搬出来，" * 8
    bad_long = "好，我知道了。"
    for role in roles[:2]:
        long_context = split_switch_context(role["longform_history"])
        short_context = split_switch_context(role["shortform_history"])

        t16_specs = [
            ("T16-1", "长→短互动要点为空，走L1原始历史", "short", args.short_target_model, None),
            ("T16-2", "长→短L1超长，走L1.5短文醒一醒", "short", args.short_target_model, "short_wake"),
            ("T16-3", "短→长切换摘要为空，走L1原始历史", "long", LONG_TARGET_MODEL, None),
            ("T16-4", "短→长L1过短，走L1.5长文醒一醒", "long", LONG_TARGET_MODEL, "long_wake"),
        ]
        for test_id, scenario, target_mode, target_model, wake_kind in t16_specs:
            for run in range(1, 3):
                if target_mode == "short":
                    current_user = long_context.current_user
                    context_hist = long_context.context_history
                    if wake_kind == "short_wake":
                        messages = short_wake_messages(bad_short, current_user)
                        context_text = ""
                    else:
                        summary = "【剧情】dry-run长文摘要" if args.dry_run else generate_long_summary(adapter, context_hist)
                        fallback = build_raw_history_fallback(context_hist, "short", 5)
                        messages = build_v56_long_to_short_messages(role, summary, fallback, current_user)
                        context_text = fallback
                else:
                    current_user = short_context.current_user
                    context_hist = short_context.context_history
                    if wake_kind == "long_wake":
                        messages = long_wake_user_only_messages(role, current_user, args.long_wake_prompt)
                        context_text = ""
                    else:
                        fallback = build_raw_history_fallback(context_hist, "long", 5)
                        messages = build_v56_short_to_long_messages(
                            role, "", sandwich_history(context_hist, "long", 5), current_user
                        )
                        context_text = fallback
                rows.append(
                    run_case(
                        adapter=adapter,
                        results_path=results_path,
                        test_id=test_id,
                        scenario=scenario,
                        role=role,
                        run=run,
                        target_mode=target_mode,
                        target_model=target_model,
                        messages=messages,
                        context_text=context_text,
                        dry_run=args.dry_run,
                        extra={"wake_kind": wake_kind or "", "sandwich_turns": args.sandwich_turns},
                    )
                )
    return rows


def choose_t14_turns(rows: list[dict[str, Any]]) -> int | None:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("test_id", "").startswith("T14"):
            grouped[int(row["sandwich_turns"])].append(row)
    if not grouped:
        return None
    ranked = []
    for turns, subset in grouped.items():
        passed = sum(1 for r in subset if r["format_pass"])
        pass_rate = passed / len(subset)
        chars = [r["char_count"] for r in subset]
        avg_abs_dev = sum(abs(c - 400) for c in chars) / len(chars)
        ranked.append((pass_rate, -avg_abs_dev, -turns, turns))
    ranked.sort(reverse=True)
    return ranked[0][3]


def write_summary(rows: list[dict[str, Any]], path: Path, selected_turns: int | None) -> None:
    lines = [
        "# v5.6 补测 T14/T15/T16 结果摘要",
        "",
        f"- 生成时间: {datetime.now().isoformat(timespec='seconds')}",
        f"- 总调用数: {len(rows)}",
        f"- API成功: {sum(1 for r in rows if r['api_success'])}/{len(rows)}",
        f"- 格式通过: {sum(1 for r in rows if r['format_pass'])}/{len(rows)}",
        f"- T14建议三明治轮数N: {selected_turns if selected_turns is not None else '未运行'}",
        "",
        "## 分组汇总",
        "| 测试 | 场景 | 总数 | 通过 | 通过率 | 平均字数 | 平均事实重叠 |",
        "|:--|:--|--:|--:|--:|--:|--:|",
    ]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["test_id"], row["scenario"])].append(row)
    for (test_id, scenario), subset in sorted(groups.items()):
        passed = sum(1 for r in subset if r["format_pass"])
        avg_chars = sum(r["char_count"] for r in subset) / len(subset)
        avg_overlap = sum(r["fact_overlap"] for r in subset) / len(subset)
        lines.append(
            f"| {test_id} | {scenario} | {len(subset)} | {passed} | "
            f"{passed / len(subset) * 100:.1f}% | {avg_chars:.1f} | {avg_overlap:.3f} |"
        )
    failures = [r for r in rows if not r["format_pass"]]
    if failures:
        lines += [
            "",
            "## 失败明细",
            "| 测试 | 角色 | run | 字数 | 事实重叠 | 问题 |",
            "|:--|:--|--:|--:|--:|:--|",
        ]
        for row in failures[:80]:
            lines.append(
                f"| {row['test_id']} {row['scenario']} | {row['role_label']} {row['role_name']} | "
                f"{row['run']} | {row['char_count']} | {row['fact_overlap']:.3f} | "
                f"{';'.join(row['issues'])} |"
            )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run v5.6 T14/T15/T16 supplemental tests")
    parser.add_argument("--excel", type=Path, default=DEFAULT_CASE_XLSX)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--phase", choices=["t14", "t15", "t16", "all"], default="all")
    parser.add_argument("--sandwich-turns", type=int, default=5, help="T15/T16使用的三明治轮数；T14会自动测试1/3/5")
    parser.add_argument("--runs-per-case", type=int, default=3, help="T14重复次数")
    parser.add_argument("--short-target-model", default=SHORT_TARGET_MODEL)
    parser.add_argument("--long-wake-prompt", type=Path, default=DEFAULT_LONG_WAKE_PROMPT_PATH)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results_path = args.output_dir / "results.jsonl"
    if results_path.exists():
        results_path.unlink()

    roles = load_excel_data(args.excel)
    print(f"[INFO] roles={len(roles)} output={args.output_dir} dry_run={args.dry_run}")
    adapter = None if args.dry_run else ModelAdapter()
    rows: list[dict[str, Any]] = []

    if args.phase in {"t14", "all"}:
        rows.extend(run_t14(adapter, roles, args, results_path))
        selected = choose_t14_turns(rows)
        if selected is not None:
            print(f"[T14] selected sandwich turns: {selected}")
            args.sandwich_turns = selected
    else:
        selected = args.sandwich_turns

    if args.phase in {"t15", "all"}:
        rows.extend(run_t15(adapter, roles, args, results_path))
    if args.phase in {"t16", "all"}:
        rows.extend(run_t16(adapter, roles, args, results_path))

    summary_path = args.output_dir / "summary.md"
    write_summary(rows, summary_path, choose_t14_turns(rows) or selected)
    print(f"[DONE] results={results_path}")
    print(f"[DONE] summary={summary_path}")


if __name__ == "__main__":
    main()
