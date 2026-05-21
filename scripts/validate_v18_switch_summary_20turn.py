#!/usr/bin/env python3
"""Validate v1.8 switch-summary mode switching with 20-turn mixed context.

The tested contract is:
- Build a v1.8 switch summary from 20 mixed turns.
- Main path: old dialogue summary + switch summary + current user.
- Fallback path: old dialogue summary + 20-turn sandwich context + current user.
- Auto wake-up is part of the evaluated final result.

The pass/fail gate intentionally focuses on deterministic output shape:
length, control-label leakage, and whether parenthesized narration is balanced.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
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

if not os.environ.get("DOUBAO_API_KEY") and os.environ.get("VOLCENGINE_API_KEY"):
    os.environ["DOUBAO_API_KEY"] = os.environ["VOLCENGINE_API_KEY"]
if not os.environ.get("ARK_API_KEY") and os.environ.get("VOLCENGINE_API_KEY"):
    os.environ["ARK_API_KEY"] = os.environ["VOLCENGINE_API_KEY"]

from services.model_adapter import ModelAdapter

from compare_switching_strategies import (
    DEFAULT_CASE_XLSX,
    EXTRACTOR_MODEL,
    LONG_TARGET_MODEL,
    SHORT_TARGET_MODELS,
    build_short_system,
    build_transcript_with_timestamp,
    generate_long_summary,
    generate_short_summary,
    load_excel_data,
)
from run_v56_supplement_tests import v56_long_system


DEFAULT_SWITCH_PROMPT = Path(
    r"E:\工作资料\产品资料\提示词资料\长文模式\摘要提示词\互动要点提示词_v1.8_20260515.md"
)
DEFAULT_LONG_WAKE_PROMPT = Path(
    r"E:\工作资料\产品资料\提示词资料\醒一醒\D_字数不达标_长文版_v0.4_20260515.md"
)
DEFAULT_SHORT_WAKE_PROMPT = Path(
    r"E:\工作资料\产品资料\提示词资料\醒一醒\手动醒一醒提示词——短文.md"
)
RESULT_SCHEMA = "v18-switch-summary-20turn-20260515"

LONG_SANDWICH_START = "以下为长文模式回复记录，仅供剧情事实参考，不要模仿其第三人称旁白、长段落格式"
LONG_SANDWICH_END = "长文模式记录结束，请继续以短文对话格式回复"
SHORT_SANDWICH_START = "以下为短文模式回复记录，仅供剧情事实参考，不要模仿其短句格式"
SHORT_SANDWICH_END = "短文模式记录结束，请继续以长文叙事格式回复"
CONTROL_MARKERS = (
    "Core_Constraints",
    "<user_input>",
    "以下为",
    "记录结束",
    "切换摘要",
    "旧摘要",
    "醒一醒",
    "作为AI",
    "我来重写",
)
LONG_NARRATION_LEAK_RE = re.compile(
    r"(?:^|[。！？\n])\s*(他|她|角色|男人|女人)[^。！？\n]{0,18}"
    r"(看|望|走|坐|站|靠|伸|抬|低|垂|握|拿|放|转|笑|皱|沉默|停|呼吸)"
)


def cjk_len(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text or ""))


def append_jsonl(path: Path, item: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def message_pairs(history: list[dict[str, str]], limit: int = 10_000) -> list[list[dict[str, str]]]:
    pairs: list[list[dict[str, str]]] = []
    current: list[dict[str, str]] = []
    for msg in history:
        role = msg.get("role")
        if role == "user":
            current = [dict(msg)]
        elif role == "assistant" and current:
            current.append(dict(msg))
            pairs.append(current)
            current = []
        if len(pairs) >= limit:
            break
    return pairs


def flatten_pairs(pairs: list[list[dict[str, str]]]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for pair in pairs:
        items.extend(dict(m) for m in pair)
    return items


def recent_pairs(history: list[dict[str, str]], turns: int) -> list[list[dict[str, str]]]:
    return message_pairs(history)[-turns:]


def mixed_history(role: dict[str, Any], direction: str, turns: int) -> list[dict[str, str]]:
    """Build the required extreme 1+19 mixed history."""
    if direction == "long_to_short":
        long_part = recent_pairs(role["longform_history"], 1)
        short_part = recent_pairs(role["shortform_history"], max(0, turns - 1))
        return flatten_pairs(long_part + short_part)
    if direction == "short_to_long":
        short_part = recent_pairs(role["shortform_history"], 1)
        long_part = recent_pairs(role["longform_history"], max(0, turns - 1))
        return flatten_pairs(short_part + long_part)
    raise ValueError(f"unknown direction: {direction}")


def current_user_for(direction: str) -> str:
    if direction == "long_to_short":
        return "那你现在想怎么回我？"
    if direction == "short_to_long":
        return "刚刚说到这里，你继续。"
    raise ValueError(f"unknown direction: {direction}")


def render_switch_prompt(template: str, history: list[dict[str, str]]) -> tuple[str, str]:
    transcript = build_transcript_with_timestamp(history, "english")
    return template.replace("{conversation_text}", transcript), transcript


def validate_switch_summary(summary: str) -> dict[str, Any]:
    issues: list[str] = []
    text = (summary or "").strip()
    if not text:
        issues.append("empty_summary")
    if "【以下为近期对话内容】" not in text:
        issues.append("missing_header")
    if "=== 以上为摘要内容，请勿模仿上述格式，对话风格===" not in text:
        issues.append("missing_tail")
    point_lines = [line for line in text.splitlines() if re.match(r"^\s*\d+[.、]\s*\[", line)]
    if len(point_lines) > 5:
        issues.append(f"too_many_points({len(point_lines)})")
    for line in point_lines:
        if not re.search(r"\[\d{2}-\d{2}\s+\d{2}:\d{2}\]", line):
            issues.append("bad_timestamp")
            break
    return {
        "summary_pass": not issues,
        "summary_issues": issues,
        "summary_points": len(point_lines),
        "summary_chars": cjk_len(text),
    }


def assistant_context(title: str, body: str) -> dict[str, str]:
    return {
        "role": "assistant",
        "content": (
            "（以下为角色内部认知记录，仅供事实衔接，请勿模仿此格式。）\n"
            f"=== {title}开始 ===\n{body}\n=== {title}结束 ==="
        ),
    }


def render_sandwich(history: list[dict[str, str]], target_mode: str) -> str:
    lines: list[str] = []
    for msg in history:
        role = msg.get("role", "")
        content = msg.get("content", "")
        source = msg.get("source_mode", "")
        if role == "assistant" and source and source != target_mode:
            if source == "short":
                content = f"{SHORT_SANDWICH_START}\n{content}\n{SHORT_SANDWICH_END}"
            elif source == "long":
                content = f"{LONG_SANDWICH_START}\n{content}\n{LONG_SANDWICH_END}"
        label = "用户" if role == "user" else "角色"
        lines.append(f"{label}: {content}")
    return "\n\n".join(lines)


def old_summary(adapter: ModelAdapter | None, role: dict[str, Any], direction: str, history: list[dict[str, str]], dry_run: bool) -> str:
    if dry_run:
        return "dry-run old dialogue summary"
    if direction == "long_to_short":
        return generate_long_summary(adapter, history)
    return generate_short_summary(adapter, history)


def build_primary_messages(
    *,
    role: dict[str, Any],
    direction: str,
    old_summary_text: str,
    switch_summary: str,
    current_user: str,
    include_old_summary: bool = True,
) -> list[dict[str, str]]:
    if direction == "long_to_short":
        messages = [
            {"role": "system", "content": build_short_system(role)},
        ]
        if include_old_summary:
            messages.append(assistant_context("旧摘要", old_summary_text or "（旧摘要为空）"))
        messages.extend(
            [
                assistant_context("切换摘要", switch_summary or "（切换摘要为空）"),
                {"role": "user", "content": current_user},
            ]
        )
        return messages
    messages = [
        {"role": "system", "content": v56_long_system(role)},
    ]
    if include_old_summary:
        messages.append(assistant_context("旧摘要", old_summary_text or "（旧摘要为空）"))
    messages.extend(
        [
            assistant_context("切换摘要", switch_summary or "（切换摘要为空）"),
        {
            "role": "user",
            "content": (
                "<Core_Constraints>长度300-500字；旁白用（）包裹；对白纯文本；"
                "只继承旧摘要和切换摘要中的真实事实；不要输出解释。</Core_Constraints>\n\n"
                f"<user_input>{current_user}</user_input>"
            ),
        },
        ]
    )
    return messages


def build_fallback_messages(
    *,
    role: dict[str, Any],
    direction: str,
    old_summary_text: str,
    history: list[dict[str, str]],
    current_user: str,
    include_old_summary: bool = True,
) -> list[dict[str, str]]:
    target_mode = "short" if direction == "long_to_short" else "long"
    if direction == "long_to_short":
        messages = [
            {"role": "system", "content": build_short_system(role)},
        ]
        if include_old_summary:
            messages.append(assistant_context("旧摘要", old_summary_text or "（旧摘要为空）"))
        messages.extend(
            [
                assistant_context("20轮三明治兜底", render_sandwich(history, target_mode)),
                {"role": "user", "content": current_user},
            ]
        )
        return messages
    messages = [
        {"role": "system", "content": v56_long_system(role)},
    ]
    if include_old_summary:
        messages.append(assistant_context("旧摘要", old_summary_text or "（旧摘要为空）"))
    messages.extend(
        [
            assistant_context("20轮三明治兜底", render_sandwich(history, target_mode)),
        {
            "role": "user",
            "content": (
                "<Core_Constraints>长度300-500字；旁白用（）包裹；对白纯文本；"
                "三明治历史只取事实，不模仿短文格式；不要输出解释。</Core_Constraints>\n\n"
                f"<user_input>{current_user}</user_input>"
            ),
        },
        ]
    )
    return messages


def render_template(template: str, role: dict[str, Any], current_user: str, bad_output: str) -> str:
    values = {
        "Role_Nickname": role.get("role_name", ""),
        "role_Nickname": role.get("role_name", ""),
        "personal_type": role.get("personality", ""),
        "relationship": role.get("relationship", ""),
        "retry_count": "第1次自动醒一醒",
        "history_wakeup_content": bad_output,
        "user_query": current_user,
    }
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered


def wake_messages(
    *,
    direction: str,
    role: dict[str, Any],
    current_user: str,
    bad_output: str,
    long_template: str,
    short_template: str,
) -> list[dict[str, str]]:
    template = short_template if direction == "long_to_short" else long_template
    return [{"role": "user", "content": render_template(template, role, current_user, bad_output)}]


def strip_parenthetical(text: str) -> str:
    return re.sub(r"（[^（）]*）", "", text or "")


def evaluate_output(text: str, direction: str) -> dict[str, Any]:
    issues: list[str] = []
    chars = cjk_len(text)
    left = text.count("（")
    right = text.count("）")
    outside = strip_parenthetical(text)
    if direction == "long_to_short":
        if chars < 30:
            issues.append(f"short_chars_under_30({chars})")
        if chars > 90:
            issues.append(f"short_chars_over_90({chars})")
        if left != right:
            issues.append("paren_unbalanced")
        if LONG_NARRATION_LEAK_RE.search(outside):
            issues.append("narration_outside_parentheses")
        if left >= 3 and chars > 80:
            issues.append("short_suspected_longform")
    else:
        if chars < 300:
            issues.append(f"long_chars_under_300({chars})")
        if chars > 500:
            issues.append(f"long_chars_over_500({chars})")
        if left == 0 or right == 0:
            issues.append("paren_missing")
        if left != right:
            issues.append("paren_unbalanced")
        if LONG_NARRATION_LEAK_RE.search(outside):
            issues.append("narration_outside_parentheses")
    if any(marker in text for marker in CONTROL_MARKERS):
        issues.append("control_marker_leak")
    return {
        "char_count": chars,
        "paren_left": left,
        "paren_right": right,
        "shape_pass": not issues,
        "shape_issues": issues,
    }


def call_model(
    adapter: ModelAdapter | None,
    *,
    model_id: str,
    messages: list[dict[str, str]],
    direction: str,
    dry_run: bool,
) -> dict[str, Any]:
    if dry_run:
        if direction == "long_to_short":
            output = "我记得你刚才说的那件事。（低头看你，声音放轻。）先别急，慢慢说，我一直在听。"
        else:
            output = "（他垂下眼，像是把刚才的话又在心里过了一遍。）我知道。（声音放得很轻。）" * 12
        return {"api_success": True, "api_error": "", "latency": 0.0, "output": output}
    start = time.time()
    result = adapter.chat(model_id=model_id, messages=messages, max_tokens=4096 if direction == "short_to_long" else 800)
    return {
        "api_success": bool(result.success),
        "api_error": result.error or "",
        "latency": round(time.time() - start, 3),
        "output": result.content.strip() if result.success and result.content else "",
    }


def target_model(direction: str, short_model: str) -> str:
    return short_model if direction == "long_to_short" else LONG_TARGET_MODEL


def direction_label(direction: str) -> str:
    return "long->short" if direction == "long_to_short" else "short->long"


def run_generation(
    *,
    adapter: ModelAdapter | None,
    args: argparse.Namespace,
    direction: str,
    role: dict[str, Any],
    run: int,
    case_type: str,
    messages: list[dict[str, str]],
    current_user: str,
    long_wake_template: str,
    short_wake_template: str,
) -> dict[str, Any]:
    model_id = target_model(direction, args.short_target_model)
    primary = call_model(adapter, model_id=model_id, messages=messages, direction=direction, dry_run=args.dry_run)
    primary_metrics = evaluate_output(primary["output"], direction)
    final = primary
    final_metrics = dict(primary_metrics)
    wake_used = False
    if not primary["api_success"] or not primary_metrics["shape_pass"]:
        wake_used = True
        wake = wake_messages(
            direction=direction,
            role=role,
            current_user=current_user,
            bad_output=primary["output"],
            long_template=long_wake_template,
            short_template=short_wake_template,
        )
        final = call_model(adapter, model_id=model_id, messages=wake, direction=direction, dry_run=args.dry_run)
        final_metrics = evaluate_output(final["output"], direction)
    return {
        "case_type": case_type,
        "direction": direction,
        "direction_label": direction_label(direction),
        "role_label": role["label"],
        "role_name": role["role_name"],
        "run": run,
        "target_model": model_id,
        "message_count": len(messages),
        "role_sequence": " > ".join(m["role"] for m in messages),
        "wake_used": wake_used,
        "primary_api_success": primary["api_success"],
        "primary_api_error": primary["api_error"],
        "primary_latency": primary["latency"],
        "primary_output": primary["output"],
        "final_api_success": final["api_success"],
        "final_api_error": final["api_error"],
        "final_latency": final["latency"],
        "final_output": final["output"],
        **{f"primary_{k}": v for k, v in primary_metrics.items()},
        **{f"final_{k}": v for k, v in final_metrics.items()},
    }


def write_summary(rows: list[dict[str, Any]], path: Path, cases_path: Path, results_path: Path) -> None:
    lines = [
        "# v1.8 20-turn switch summary validation",
        "",
        f"- generated_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- cases: {cases_path}",
        f"- results: {results_path}",
        f"- total_rows: {len(rows)}",
        "",
        "## Overall",
        "| direction | case_type | total | summary_pass | primary_pass | final_pass | wake_used | avg_primary_chars | avg_final_chars |",
        "|:--|:--|--:|--:|--:|--:|--:|--:|--:|",
    ]
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["direction_label"], row["case_type"])].append(row)
    for (direction, case_type), subset in sorted(grouped.items()):
        total = len(subset)
        summary_pass = sum(1 for r in subset if r.get("summary_pass"))
        primary_pass = sum(1 for r in subset if r.get("primary_shape_pass") and r.get("primary_api_success"))
        final_pass = sum(1 for r in subset if r.get("final_shape_pass") and r.get("final_api_success"))
        wake_used = sum(1 for r in subset if r.get("wake_used"))
        avg_primary = sum(r.get("primary_char_count", 0) for r in subset) / total
        avg_final = sum(r.get("final_char_count", 0) for r in subset) / total
        lines.append(
            f"| {direction} | {case_type} | {total} | {summary_pass}/{total} | "
            f"{primary_pass}/{total} | {final_pass}/{total} | {wake_used}/{total} | "
            f"{avg_primary:.1f} | {avg_final:.1f} |"
        )
    lines += [
        "",
        "## Failure Reasons",
        "| stage | issue | count |",
        "|:--|:--|--:|",
    ]
    counts: Counter[tuple[str, str]] = Counter()
    for row in rows:
        if not row.get("primary_shape_pass"):
            for issue in row.get("primary_shape_issues", []):
                counts[("primary", issue)] += 1
        if not row.get("final_shape_pass"):
            for issue in row.get("final_shape_issues", []):
                counts[("final", issue)] += 1
    for (stage, issue), count in counts.most_common():
        lines.append(f"| {stage} | {issue} | {count} |")
    lines += [
        "",
        "## Details",
        "| direction | case | role | run | wake | primary_chars | primary_pass | final_chars | final_pass | final_issues |",
        "|:--|:--|:--|--:|:--|--:|:--|--:|:--|:--|",
    ]
    for row in rows:
        lines.append(
            f"| {row['direction_label']} | {row['case_type']} | {row['role_label']} {row['role_name']} | "
            f"{row['run']} | {row['wake_used']} | {row['primary_char_count']} | {row['primary_shape_pass']} | "
            f"{row['final_char_count']} | {row['final_shape_pass']} | {';'.join(row['final_shape_issues'])} |"
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate v1.8 switch summary with 20-turn mixed context")
    parser.add_argument("--excel", type=Path, default=DEFAULT_CASE_XLSX)
    parser.add_argument("--switch-prompt", type=Path, default=DEFAULT_SWITCH_PROMPT)
    parser.add_argument("--long-wake-prompt", type=Path, default=DEFAULT_LONG_WAKE_PROMPT)
    parser.add_argument("--short-wake-prompt", type=Path, default=DEFAULT_SHORT_WAKE_PROMPT)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--roles-limit", type=int, default=4)
    parser.add_argument("--runs-per-case", type=int, default=3)
    parser.add_argument("--turns", type=int, default=20)
    parser.add_argument("--short-target-model", choices=SHORT_TARGET_MODELS, default="doubao-lite")
    parser.add_argument("--case-types", choices=["primary", "fallback", "both"], default="both")
    parser.add_argument(
        "--omit-old-summary",
        action="store_true",
        help="Evaluate the launch candidate without old dialogue_summary in the switching payload.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results_path = args.output_dir / "results.jsonl"
    cases_path = args.output_dir / "cases.jsonl"
    summary_path = args.output_dir / "summary.md"
    for path in (results_path, cases_path, summary_path):
        if path.exists():
            path.unlink()

    roles = load_excel_data(args.excel)[: args.roles_limit]
    switch_template = args.switch_prompt.read_text(encoding="utf-8")
    long_wake_template = args.long_wake_prompt.read_text(encoding="utf-8")
    short_wake_template = args.short_wake_prompt.read_text(encoding="utf-8")
    adapter = None if args.dry_run else ModelAdapter()
    rows: list[dict[str, Any]] = []

    print(f"[INFO] roles={len(roles)} dry_run={args.dry_run} output={args.output_dir}")
    for role in roles:
        for direction in ("long_to_short", "short_to_long"):
            history = mixed_history(role, direction, args.turns)
            current_user = current_user_for(direction)
            old = "" if args.omit_old_summary else old_summary(adapter, role, direction, history, args.dry_run)
            switch_prompt, transcript = render_switch_prompt(switch_template, history)
            if args.dry_run:
                switch_summary = (
                    "【以下为近期对话内容】\n"
                    "1. [04-20 14:00] 用户和角色延续上一段互动，准备继续当前话题\n"
                    "=== 以上为摘要内容，请勿模仿上述格式，对话风格==="
                )
            else:
                call = adapter.chat(model_id=EXTRACTOR_MODEL, messages=[{"role": "user", "content": switch_prompt}], max_tokens=900)
                switch_summary = call.content.strip() if call.success and call.content else ""
            summary_metrics = validate_switch_summary(switch_summary)
            case_meta = {
                "schema": RESULT_SCHEMA,
                "role_label": role["label"],
                "role_name": role["role_name"],
                "direction": direction,
                "direction_label": direction_label(direction),
                "turn_messages": len(history),
                "turn_pairs": len(message_pairs(history)),
                "current_user": current_user,
                "old_summary_ok": bool(old.strip()),
                "old_summary_included": not args.omit_old_summary,
                "switch_summary": switch_summary,
                "transcript": transcript,
                **summary_metrics,
            }
            append_jsonl(cases_path, case_meta)
            print(
                f"[CASE] {role['label']} {role['role_name']} {direction_label(direction)} "
                f"summary_pass={summary_metrics['summary_pass']} points={summary_metrics['summary_points']}"
            )
            if args.case_types in {"primary", "both"}:
                messages = build_primary_messages(
                    role=role,
                    direction=direction,
                    old_summary_text=old,
                    switch_summary=switch_summary,
                    current_user=current_user,
                    include_old_summary=not args.omit_old_summary,
                )
                for run in range(1, args.runs_per_case + 1):
                    row = run_generation(
                        adapter=adapter,
                        args=args,
                        direction=direction,
                        role=role,
                        run=run,
                        case_type="primary_summary",
                        messages=messages,
                        current_user=current_user,
                        long_wake_template=long_wake_template,
                        short_wake_template=short_wake_template,
                    )
                    row.update(case_meta)
                    append_jsonl(results_path, row)
                    rows.append(row)
                    print(
                        f"  [primary] run={run} primary={row['primary_char_count']} "
                        f"pass={row['primary_shape_pass']} final={row['final_char_count']} "
                        f"pass={row['final_shape_pass']} wake={row['wake_used']}"
                    )
            if args.case_types in {"fallback", "both"}:
                messages = build_fallback_messages(
                    role=role,
                    direction=direction,
                    old_summary_text=old,
                    history=history,
                    current_user=current_user,
                    include_old_summary=not args.omit_old_summary,
                )
                for run in range(1, args.runs_per_case + 1):
                    row = run_generation(
                        adapter=adapter,
                        args=args,
                        direction=direction,
                        role=role,
                        run=run,
                        case_type="fallback_20turn_sandwich",
                        messages=messages,
                        current_user=current_user,
                        long_wake_template=long_wake_template,
                        short_wake_template=short_wake_template,
                    )
                    row.update(case_meta)
                    append_jsonl(results_path, row)
                    rows.append(row)
                    print(
                        f"  [fallback] run={run} primary={row['primary_char_count']} "
                        f"pass={row['primary_shape_pass']} final={row['final_char_count']} "
                        f"pass={row['final_shape_pass']} wake={row['wake_used']}"
                    )
    write_summary(rows, summary_path, cases_path, results_path)
    print(f"[DONE] cases={cases_path}")
    print(f"[DONE] results={results_path}")
    print(f"[DONE] summary={summary_path}")


if __name__ == "__main__":
    main()
