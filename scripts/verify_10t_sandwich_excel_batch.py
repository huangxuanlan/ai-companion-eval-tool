#!/usr/bin/env python3
"""Batch-validate 10-turn sandwich fallback with real shortform Excel cases.

This script keeps the switching path under the same fallback口径 as the v5.5
replay checks:

    old_summary + 10-turn sandwich-isolated hetero history + current user

Unlike the log-only replay scripts, the short target side is rendered from the
real shortform batch Excel matrix. The short->long direction first generates
real 10-turn short histories from that same Excel, then replays them into the
long target.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SERVER_DIR = PROJECT_ROOT / "server"
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SERVER_DIR))

import shortform_model_switch_batch_test as shortform
from services.model_adapter import ModelAdapter
from verify_interaction_points_sandwich_fallback_full_matrix import context_block
from verify_mode_switching_log_replay import (
    LONG_LOG_DEFAULT,
    SHORT_LOG_DEFAULT,
    bridge_history,
    detect_format_issues,
    dialogue_history,
    first_system,
    last_user,
    load_log_sample,
    ngram_overlap,
    recent_assistant_texts,
)

DEFAULT_CASE_XLSX = Path(
    r"E:\工作资料\产品资料\提示词资料\模型切换\短文模式聊天批量测试用例.xlsx"
)
SHORT_MODEL_IDS = ("doubao-lite", "doubao-1.5-character", "deepseek-v4-flash")
LONG_MODEL_ID = "deepseek-v4-pro"
CONTROL_TOKEN_RE = re.compile(r"\[(?:TRANSFER|ROUTE|SWITCH|STATE|MODE|SYSTEM)[^\]]*\]")


@dataclass(frozen=True)
class ShortSourceCase:
    source_model: str
    role_type: str
    role_name: str
    relationship: str
    turns: tuple[str, ...]


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def ensure_runtime_key_aliases() -> dict[str, bool]:
    load_env_file(SERVER_DIR / ".env")
    if not os.environ.get("ARK_API_KEY") and os.environ.get("VOLCENGINE_API_KEY"):
        os.environ["ARK_API_KEY"] = os.environ["VOLCENGINE_API_KEY"]
    if not os.environ.get("DOUBAO_API_KEY") and os.environ.get("VOLCENGINE_API_KEY"):
        os.environ["DOUBAO_API_KEY"] = os.environ["VOLCENGINE_API_KEY"]
    return {
        "VOLCENGINE_API_KEY": bool(os.environ.get("VOLCENGINE_API_KEY")),
        "ARK_API_KEY": bool(os.environ.get("ARK_API_KEY")),
        "DASHSCOPE_API_KEY": bool(os.environ.get("DASHSCOPE_API_KEY")),
    }


def dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def sample_user_inputs(turns: list[str], count: int) -> list[str]:
    values = dedupe_keep_order([str(item) for item in turns])
    if not values:
        return []
    if count <= 1 or len(values) == 1:
        return [values[0]]
    if len(values) <= count:
        return values

    positions = [
        round(index * (len(values) - 1) / (count - 1)) for index in range(count)
    ]
    sampled = [values[pos] for pos in positions]
    return dedupe_keep_order(sampled)


def call_model(
    adapter: ModelAdapter,
    model_id: str,
    messages: list[dict[str, str]],
    *,
    max_tokens: int,
    thinking: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    result = adapter.chat(
        model_id=model_id,
        messages=messages,
        max_tokens=max_tokens,
        thinking_effort=thinking,
    )
    return {
        "success": result.success,
        "error": result.error,
        "output": result.content or "",
        "latency": round(time.perf_counter() - started, 3),
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    }


def evaluate_short_output(text: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    checks = shortform.response_checks(text)
    issues = list(detect_format_issues(text, "short"))
    if checks["word_count_violation"] and not any(
        "短文字数" in item for item in issues
    ):
        issues.append(f"短文字数异常({checks['char_count']})")
    if checks["bracket_violation"]:
        issues.append("括号动作格式异常")
    if checks["banned_word_violation"]:
        issues.append("命中禁词指尖")
    if CONTROL_TOKEN_RE.search(text):
        issues.append("控制标记泄漏")
    assistants = recent_assistant_texts(messages, limit=8)
    overlaps = [ngram_overlap(prev, text) for prev in assistants]
    return {
        "char_count": checks["char_count"],
        "narrative_ratio": checks["narrative_ratio"],
        "ratio_warning": checks["ratio_warning"],
        "issues": dedupe_keep_order(issues),
        "format_pass": not issues,
        "ngram_max_recent_pct": round((max(overlaps) if overlaps else 0.0) * 100, 2),
    }


def evaluate_long_output(text: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    issues = list(detect_format_issues(text, "long"))
    if CONTROL_TOKEN_RE.search(text):
        issues.append("控制标记泄漏")
    assistants = recent_assistant_texts(messages, limit=8)
    overlaps = [ngram_overlap(prev, text) for prev in assistants]
    return {
        "char_count": len(re.findall(r"[\u4e00-\u9fff]", text)),
        "issues": dedupe_keep_order(issues),
        "format_pass": not issues,
        "ngram_max_recent_pct": round((max(overlaps) if overlaps else 0.0) * 100, 2),
    }


def append_jsonl(path: Path, item: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def write_payload(
    path: Path, meta: dict[str, Any], messages: list[dict[str, str]]
) -> None:
    path.write_text(
        json.dumps({"meta": meta, "messages": messages}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_short_source_cases(
    roles: list[shortform.RoleCase],
    messages_by_relationship: dict[str, list[str]],
    *,
    source_turns: int,
) -> list[ShortSourceCase]:
    cases: list[ShortSourceCase] = []
    for role in roles:
        relationship = str(role.variables.get("relationship") or "").strip()
        raw_turns = list(messages_by_relationship.get(relationship) or [])
        turns = tuple(shortform.normalize_turns(raw_turns, source_turns))
        role_name = str(role.variables.get("Role_Nickname") or "")
        for source_model in SHORT_MODEL_IDS:
            cases.append(
                ShortSourceCase(
                    source_model=source_model,
                    role_type=role.role_type,
                    role_name=role_name,
                    relationship=relationship,
                    turns=turns,
                )
            )
    return cases


def generate_short_history(
    *,
    adapter: ModelAdapter,
    role: shortform.RoleCase,
    source_model: str,
    turns: tuple[str, ...],
    short_max_tokens: int,
    output_dir: Path,
) -> dict[str, Any]:
    relationship = str(role.variables.get("relationship") or "").strip()
    variables = shortform.build_variables(role, relationship)
    validation_errors = shortform.validate_variables(variables, relationship)
    if validation_errors:
        raise ValueError(
            f"{role.role_type}/{source_model} 变量校验失败: {validation_errors}"
        )

    system_prompt = shortform.render_template(
        shortform.DEFAULT_SYSTEM_TEMPLATE, variables
    )
    assistant_seed = shortform.render_template(
        shortform.DEFAULT_ASSISTANT_SEED, variables
    )
    history: list[dict[str, str]] = []
    records: list[dict[str, Any]] = []

    for turn_index, user_message in enumerate(turns, start=1):
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "assistant", "content": assistant_seed},
            *history,
            {"role": "user", "content": user_message},
        ]
        call = call_model(
            adapter,
            source_model,
            messages,
            max_tokens=short_max_tokens,
            thinking="disabled",
        )
        metrics = evaluate_short_output(call["output"], messages)
        record = {
            "turn": turn_index,
            "user_input": user_message,
            "assistant_output": call["output"],
            "success": call["success"],
            "error": call["error"],
            "latency": call["latency"],
            "input_tokens": call["input_tokens"],
            "output_tokens": call["output_tokens"],
            **metrics,
        }
        records.append(record)
        if call["error"]:
            break
        history.append(
            {"role": "user", "content": user_message, "source_mode": "short"}
        )
        history.append(
            {"role": "assistant", "content": call["output"], "source_mode": "short"}
        )

    role_dir = output_dir / "source_histories"
    role_dir.mkdir(parents=True, exist_ok=True)
    role_slug = f"{role.role_type}_{source_model}".replace("/", "_")
    (role_dir / f"{role_slug}.json").write_text(
        json.dumps(
            {
                "source_model": source_model,
                "role_type": role.role_type,
                "role_name": variables.get("Role_Nickname", ""),
                "relationship": relationship,
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "source_model": source_model,
        "role_type": role.role_type,
        "role_name": variables.get("Role_Nickname", ""),
        "relationship": relationship,
        "records": records,
        "history": history,
    }


def summarize_source_histories(
    source_histories: list[dict[str, Any]],
    *,
    expected_source_turns: int,
) -> dict[str, Any]:
    total = len(source_histories)
    complete = 0
    format_pass_turns = 0
    total_turns = 0
    for item in source_histories:
        records = item.get("records") or []
        total_turns += len(records)
        format_pass_turns += sum(1 for row in records if row.get("format_pass"))
        if (
            records
            and all(not row.get("error") for row in records)
            and source_turns_from_records(records) == expected_source_turns
        ):
            complete += 1
    return {
        "total_histories": total,
        "complete_histories": complete,
        "source_turns": expected_source_turns,
        "format_pass_turns": format_pass_turns,
        "total_turns": total_turns,
    }


def source_turns_from_records(records: list[dict[str, Any]]) -> int:
    return max((int(row.get("turn") or 0) for row in records), default=0)


def run_long_to_short_batch(
    *,
    adapter: ModelAdapter,
    roles: list[shortform.RoleCase],
    messages_by_relationship: dict[str, list[str]],
    long_history: list[dict[str, str]],
    short_max_tokens: int,
    fallback_turns: int,
    samples_per_role: int,
    output_dir: Path,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    payload_dir = output_dir / "payloads" / "long_to_short"
    payload_dir.mkdir(parents=True, exist_ok=True)
    bridged, bridge_meta = bridge_history(long_history, "short", fallback_turns)
    for role in roles:
        relationship = str(role.variables.get("relationship") or "").strip()
        raw_turns = list(messages_by_relationship.get(relationship) or [])
        sampled_inputs = sample_user_inputs(raw_turns, samples_per_role)
        variables = shortform.build_variables(role, relationship)
        system_prompt = shortform.render_template(
            shortform.DEFAULT_SYSTEM_TEMPLATE, variables
        )
        role_name = str(variables.get("Role_Nickname") or "")
        for input_index, user_input in enumerate(sampled_inputs, start=1):
            for target_model in SHORT_MODEL_IDS:
                case_id = f"lts_{role.role_type}_{target_model}_{input_index}".replace(
                    "/", "_"
                )
                messages = [
                    {"role": "system", "content": system_prompt},
                    context_block(target_mode="short", label=f"{case_id}_old_summary"),
                    *bridged,
                    {"role": "user", "content": user_input},
                ]
                write_payload(
                    payload_dir / f"{case_id}.json",
                    {
                        "direction": "long_to_short",
                        "target_model": target_model,
                        "role_type": role.role_type,
                        "role_name": role_name,
                        "relationship": relationship,
                        "user_input": user_input,
                        **bridge_meta,
                    },
                    messages,
                )
                call = call_model(
                    adapter,
                    target_model,
                    messages,
                    max_tokens=short_max_tokens,
                    thinking="disabled",
                )
                metrics = evaluate_short_output(call["output"], messages)
                results.append(
                    {
                        "case_id": case_id,
                        "direction": "long_to_short",
                        "target_model": target_model,
                        "role_type": role.role_type,
                        "role_name": role_name,
                        "relationship": relationship,
                        "user_input": user_input,
                        "payload_messages": len(messages),
                        **bridge_meta,
                        **{k: v for k, v in call.items() if k != "output"},
                        "metrics": metrics,
                        "output": call["output"],
                    }
                )
    return results


def run_short_to_long_batch(
    *,
    adapter: ModelAdapter,
    source_histories: list[dict[str, Any]],
    long_system: dict[str, str],
    long_user: dict[str, str],
    long_max_tokens: int,
    fallback_turns: int,
    output_dir: Path,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    payload_dir = output_dir / "payloads" / "short_to_long"
    payload_dir.mkdir(parents=True, exist_ok=True)
    for item in source_histories:
        history = [dict(msg) for msg in (item.get("history") or [])]
        case_id = f"stl_{item['role_type']}_{item['source_model']}".replace("/", "_")
        bridged, bridge_meta = bridge_history(history, "long", fallback_turns)
        messages = [
            dict(long_system),
            context_block(target_mode="long", label=f"{case_id}_old_summary"),
            *bridged,
            dict(long_user),
        ]
        write_payload(
            payload_dir / f"{case_id}.json",
            {
                "direction": "short_to_long",
                "target_model": LONG_MODEL_ID,
                "source_model": item["source_model"],
                "role_type": item["role_type"],
                "role_name": item["role_name"],
                "relationship": item["relationship"],
                **bridge_meta,
            },
            messages,
        )
        call = call_model(
            adapter,
            LONG_MODEL_ID,
            messages,
            max_tokens=long_max_tokens,
            thinking="high",
        )
        metrics = evaluate_long_output(call["output"], messages)
        results.append(
            {
                "case_id": case_id,
                "direction": "short_to_long",
                "target_model": LONG_MODEL_ID,
                "source_model": item["source_model"],
                "role_type": item["role_type"],
                "role_name": item["role_name"],
                "relationship": item["relationship"],
                "payload_messages": len(messages),
                **bridge_meta,
                **{k: v for k, v in call.items() if k != "output"},
                "metrics": metrics,
                "output": call["output"],
            }
        )
    return results


def aggregate_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in results:
        key = (str(row.get("direction") or ""), str(row.get("target_model") or ""))
        buckets.setdefault(key, []).append(row)
    summary_rows: list[dict[str, Any]] = []
    for (direction, target_model), rows in sorted(buckets.items()):
        success_rows = [row for row in rows if row.get("success")]
        format_pass_rows = [
            row for row in rows if row.get("metrics", {}).get("format_pass")
        ]
        control_leaks = sum(
            1
            for row in rows
            if "控制标记泄漏" in (row.get("metrics", {}).get("issues") or [])
        )
        avg_chars = round(
            sum(float(row.get("metrics", {}).get("char_count") or 0) for row in rows)
            / len(rows),
            2,
        )
        summary_rows.append(
            {
                "direction": direction,
                "target_model": target_model,
                "total": len(rows),
                "api_success": len(success_rows),
                "format_pass": len(format_pass_rows),
                "control_leaks": control_leaks,
                "avg_chars": avg_chars,
            }
        )
    return summary_rows


def write_summary(
    *,
    path: Path,
    case_xlsx: Path,
    source_summary: dict[str, Any],
    results: list[dict[str, Any]],
    aggregate: list[dict[str, Any]],
    args: argparse.Namespace,
) -> None:
    lines = [
        "# 10轮三明治 Excel 批量验证报告",
        "",
        f"- 生成时间: {datetime.now().isoformat()}",
        f"- Excel输入: {case_xlsx}",
        f"- 短文目标模型: {', '.join(SHORT_MODEL_IDS)}",
        f"- 长文目标模型: {LONG_MODEL_ID}",
        f"- source_turns: {args.source_turns}",
        f"- fallback_turns: {args.fallback_turns}",
        f"- samples_per_role: {args.samples_per_role}",
        "",
        "## Source 短文历史生成",
        "",
        (
            "- 生成历史数: "
            f"{source_summary['complete_histories']}/"
            f"{source_summary['total_histories']}"
        ),
        (
            "- Source 总轮次格式通过: "
            f"{source_summary['format_pass_turns']}/"
            f"{source_summary['total_turns']}"
        ),
        "",
        "## 目标结果聚合",
        "",
        "| 方向 | 目标模型 | 总数 | API成功 | 格式通过 | 控制标记泄漏 | 平均字数 |",
        "|:--|:--|--:|--:|--:|--:|--:|",
    ]
    for row in aggregate:
        lines.append(
            (
                "| {direction} | {target_model} | {total} | {api_success} | "
                "{format_pass} | {control_leaks} | {avg_chars} |"
            ).format(
                **row
            )
        )

    failures = [row for row in results if not row.get("metrics", {}).get("format_pass")]
    lines.extend(
        [
            "",
            "## 失败样本",
            "",
            "| case_id | 方向 | 模型 | 角色 | 字数 | 问题 | 输出预览 |",
            "|:--|:--|:--|:--|--:|:--|:--|",
        ]
    )
    for row in failures[:20]:
        metrics = row.get("metrics", {})
        preview = str(row.get("output") or "").replace("\n", " ")[:90]
        issues = "；".join(metrics.get("issues") or []) or "无"
        lines.append(
            (
                "| {case_id} | {direction} | {target_model} | {role_name} | "
                "{chars} | {issues} | {preview} |"
            ).format(
                case_id=row.get("case_id", ""),
                direction=row.get("direction", ""),
                target_model=row.get("target_model", ""),
                role_name=row.get("role_name", ""),
                chars=metrics.get("char_count", 0),
                issues=issues,
                preview=preview,
            )
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate 10-turn sandwich fallback with Excel shortform cases"
    )
    parser.add_argument("--case-xlsx", default=str(DEFAULT_CASE_XLSX))
    parser.add_argument("--short-log", default=str(SHORT_LOG_DEFAULT))
    parser.add_argument("--long-log", default=str(LONG_LOG_DEFAULT))
    parser.add_argument("--source-turns", type=int, default=10)
    parser.add_argument("--fallback-turns", type=int, default=10)
    parser.add_argument("--samples-per-role", type=int, default=3)
    parser.add_argument("--short-max-tokens", type=int, default=2048)
    parser.add_argument("--long-max-tokens", type=int, default=8192)
    parser.add_argument("--output-dir", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.source_turns < 1:
        raise ValueError("--source-turns must be >= 1")
    if args.fallback_turns < 1:
        raise ValueError("--fallback-turns must be >= 1")
    if args.samples_per_role < 1:
        raise ValueError("--samples-per-role must be >= 1")

    env_status = ensure_runtime_key_aliases()
    case_xlsx = Path(args.case_xlsx)
    roles, messages_by_relationship = shortform.load_excel_cases(case_xlsx)
    short_sample = load_log_sample(Path(args.short_log), mode="short")
    long_sample = load_log_sample(Path(args.long_log), mode="long")
    long_history = dialogue_history(long_sample)
    long_system = first_system(long_sample.messages)
    long_user = last_user(long_sample.messages)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = (
        Path(args.output_dir)
        if args.output_dir
        else PROJECT_ROOT
        / "output"
        / "mode_switching_switch_state"
        / f"excel_sandwich_10t_batch_{ts}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.jsonl"
    source_path = out_dir / "source_histories.jsonl"
    summary_path = out_dir / "summary.md"
    for path in (results_path, source_path):
        if path.exists():
            path.unlink()

    adapter = ModelAdapter()
    print(f"[INFO] env_status={env_status}")
    print(f"[INFO] case_xlsx={case_xlsx}")
    print(f"[INFO] short_log={short_sample.path} messages={len(short_sample.messages)}")
    print(f"[INFO] long_log={long_sample.path} messages={len(long_sample.messages)}")
    print(f"[INFO] output={out_dir}")

    source_cases = build_short_source_cases(
        roles,
        messages_by_relationship,
        source_turns=args.source_turns,
    )
    source_histories: list[dict[str, Any]] = []
    for case in source_cases:
        role = next(item for item in roles if item.role_type == case.role_type)
        result = generate_short_history(
            adapter=adapter,
            role=role,
            source_model=case.source_model,
            turns=case.turns,
            short_max_tokens=args.short_max_tokens,
            output_dir=out_dir,
        )
        append_jsonl(
            source_path,
            {
                "source_model": result["source_model"],
                "role_type": result["role_type"],
                "role_name": result["role_name"],
                "relationship": result["relationship"],
                "records": result["records"],
            },
        )
        source_histories.append(result)

    source_summary = summarize_source_histories(
        source_histories,
        expected_source_turns=args.source_turns,
    )

    results: list[dict[str, Any]] = []
    for row in run_long_to_short_batch(
        adapter=adapter,
        roles=roles,
        messages_by_relationship=messages_by_relationship,
        long_history=long_history,
        short_max_tokens=args.short_max_tokens,
        fallback_turns=args.fallback_turns,
        samples_per_role=args.samples_per_role,
        output_dir=out_dir,
    ):
        append_jsonl(results_path, row)
        results.append(row)

    for row in run_short_to_long_batch(
        adapter=adapter,
        source_histories=source_histories,
        long_system=long_system,
        long_user=long_user,
        long_max_tokens=args.long_max_tokens,
        fallback_turns=args.fallback_turns,
        output_dir=out_dir,
    ):
        append_jsonl(results_path, row)
        results.append(row)

    aggregate = aggregate_results(results)
    write_summary(
        path=summary_path,
        case_xlsx=case_xlsx,
        source_summary=source_summary,
        results=results,
        aggregate=aggregate,
        args=args,
    )
    print(
        "[SUMMARY] "
        f"source_histories={source_summary['complete_histories']}/"
        f"{source_summary['total_histories']} "
        f"results={len(results)} "
        f"summary={summary_path}"
    )


if __name__ == "__main__":
    main()
