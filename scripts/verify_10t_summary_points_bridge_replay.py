#!/usr/bin/env python3
"""
Replay real issue logs with combined switching context:

- 10-turn raw history bridge with v5.4 sandwich isolation
- generated summary from the same 10-turn transcript
- generated interaction points for short -> long targets

This is the third validation口径: not pure 10-turn bridge, and not pure
summary/points replacement. Inputs are production issue-log payloads.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "server"))

from services.model_adapter import ModelAdapter
from verify_mode_switching_log_replay import (
    LONG_LOG_DEFAULT,
    SHORT_LOG_DEFAULT,
    LogSample,
    bridge_history,
    cjk_len,
    detect_format_issues,
    dialogue_history,
    first_system,
    last_user,
    load_log_sample,
    ngram_overlap,
)
from verify_v52_summary_points_replay import (
    AUX_MODEL,
    POINTS_PROMPT_DEFAULT,
    SUMMARY_PROMPT_DEFAULT,
    build_context_block,
    extract_json_object,
    extract_time_hint,
    render_points_prompt,
    render_summary_prompt,
    transcript_from_messages,
)


BRIDGE_TURNS = 10


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


def scenario_parts(
    scenario: str,
    short_sample: LogSample,
    long_sample: LogSample,
) -> tuple[str, str, list[dict[str, str]], dict[str, str], dict[str, str], bool]:
    short_hist = dialogue_history(short_sample)
    long_hist = dialogue_history(long_sample)
    if scenario == "S5":
        return "long", "deepseek-v4-pro", short_hist, first_system(long_sample.messages), last_user(long_sample.messages), True
    if scenario == "S6":
        return "short", "doubao-lite", long_hist, first_system(short_sample.messages), last_user(short_sample.messages), False
    if scenario == "S8":
        return "short", "doubao-lite", short_hist + long_hist, first_system(short_sample.messages), last_user(short_sample.messages), False
    if scenario == "S14":
        return "long", "deepseek-v4-pro", short_hist + long_hist, first_system(long_sample.messages), last_user(long_sample.messages), True
    raise ValueError(f"未知场景: {scenario}")


def recent_assistants(messages: list[dict[str, str]]) -> list[str]:
    return [m["content"] for m in messages if m.get("role") == "assistant"]


def evaluate_output(
    output: str,
    *,
    target_mode: str,
    full_messages: list[dict[str, str]],
    bridged_messages: list[dict[str, str]],
) -> dict[str, Any]:
    full_assistants = recent_assistants(full_messages)[-8:]
    bridge_assistants = recent_assistants(bridged_messages)[-8:]
    full_overlaps = [ngram_overlap(prev, output) for prev in full_assistants]
    bridge_overlaps = [ngram_overlap(prev, output) for prev in bridge_assistants]
    return {
        "chars": len(output),
        "cjk_chars": cjk_len(output),
        "format_issues": detect_format_issues(output, target_mode),
        "ngram_max_recent_pct": round((max(full_overlaps) if full_overlaps else 0.0) * 100, 2),
        "ngram_max_bridge_pct": round((max(bridge_overlaps) if bridge_overlaps else 0.0) * 100, 2),
        "output_preview": output[:500],
    }


def append_jsonl(path: Path, item: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def write_summary(results: list[dict[str, Any]], path: Path) -> None:
    lines = [
        "# 10轮桥接 + 摘要/互动要点组合复放验证报告",
        "",
        f"- 生成时间: {datetime.now().isoformat()}",
        "- 输入来源: 问题排查目录中的真实 payload 日志",
        "- 切换方式: 10轮强三明治桥接 + 同10轮生成摘要/互动要点",
        f"- 辅助模型: {AUX_MODEL}",
        "",
        "| 场景 | 目标 | 桥接轮数 | 摘要输入轮数 | 互动要点 | payload消息 | 包夹assistant | 摘要JSON | 成功 | 字数 | 格式问题 | recent-max-ngram | bridge-max-ngram |",
        "|:--|:--|--:|--:|:--:|--:|--:|:--:|:--:|--:|:--|--:|--:|",
    ]
    for r in results:
        issues = "；".join(r["metrics"].get("format_issues") or []) or "无"
        lines.append(
            "| {scenario} | {target_mode}/{target_model} | {bridge_turns} | {summary_turns} | {points} | "
            "{payload_messages} | {wrapped} | {summary_json} | {success} | {chars} | {issues} | "
            "{recent_ngram} | {bridge_ngram} |".format(
                scenario=r["scenario"],
                target_mode=r["target_mode"],
                target_model=r["target_model"],
                bridge_turns=r["bridge_effective_turns"],
                summary_turns=r["summary_effective_turns"],
                points="Y" if r["points_generated"] else "N",
                payload_messages=r["payload_messages"],
                wrapped=r["hetero_assistant_wrapped"],
                summary_json="Y" if r["summary_json_ok"] else "N",
                success="Y" if r["success"] else "N",
                chars=r["metrics"].get("cjk_chars", 0),
                issues=issues,
                recent_ngram=r["metrics"].get("ngram_max_recent_pct", 0),
                bridge_ngram=r["metrics"].get("ngram_max_bridge_pct", 0),
            )
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate 10-turn bridge plus generated summary/points")
    parser.add_argument("--short-log", default=str(SHORT_LOG_DEFAULT))
    parser.add_argument("--long-log", default=str(LONG_LOG_DEFAULT))
    parser.add_argument("--summary-prompt", default=str(SUMMARY_PROMPT_DEFAULT))
    parser.add_argument("--points-prompt", default=str(POINTS_PROMPT_DEFAULT))
    parser.add_argument("--scenarios", nargs="*", default=["S5", "S6", "S8", "S14"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--long-max-tokens", type=int, default=16384)
    parser.add_argument("--short-max-tokens", type=int, default=4096)
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args()

    short_sample = load_log_sample(Path(args.short_log), mode="short")
    long_sample = load_log_sample(Path(args.long_log), mode="long")
    summary_template = Path(args.summary_prompt).read_text(encoding="utf-8", errors="ignore")
    points_template = Path(args.points_prompt).read_text(encoding="utf-8", errors="ignore")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_dir) if args.output_dir else PROJECT_ROOT / "output" / "10t_summary_points_bridge_replay" / ts
    payload_dir = out_dir / "payloads"
    aux_dir = out_dir / "auxiliary"
    payload_dir.mkdir(parents=True, exist_ok=True)
    aux_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.jsonl"
    summary_path = out_dir / "summary.md"

    adapter = ModelAdapter()
    results: list[dict[str, Any]] = []
    print(f"[INFO] short_log={short_sample.path} messages={len(short_sample.messages)}")
    print(f"[INFO] long_log={long_sample.path} messages={len(long_sample.messages)}")
    print(f"[INFO] output={out_dir}")

    for scenario in args.scenarios:
        target_mode, target_model, source_history, system_msg, current_user, needs_points = scenario_parts(
            scenario,
            short_sample,
            long_sample,
        )
        bridged, bridge_meta = bridge_history(source_history, target_mode, BRIDGE_TURNS)
        recent_source = [m for m in source_history if m["role"] in {"user", "assistant"}][-BRIDGE_TURNS * 2 :]
        transcript = transcript_from_messages(recent_source, base_time=extract_time_hint(current_user["content"]))
        current_mode = "longform" if target_mode == "long" else "shortform"
        summary_prompt = render_summary_prompt(summary_template, current_mode=current_mode, transcript=transcript)
        points_prompt = render_points_prompt(points_template, transcript=transcript)

        case_id = f"{scenario}_10t_summary_points_bridge"
        if args.dry_run:
            summary_call = {
                "success": True,
                "error": "",
                "output": '{"scene_description":"dry-run场景","plot_summary":"[05-09 16:00]dry-run摘要","pending_hooks":"","character_emotion":"","user_emotion":"","relationship_shift":"","user_profile_signals":""}',
                "latency": 0.0,
                "input_tokens": 0,
                "output_tokens": 0,
            }
            points_call = {
                "success": True,
                "error": "",
                "output": "【最近互动要点（桥接迁移）】\n1. [05-09 16:00] dry-run互动要点\n【待接续线索】\n【最后场景】",
                "latency": 0.0,
                "input_tokens": 0,
                "output_tokens": 0,
            } if needs_points else {"success": True, "error": "", "output": "", "latency": 0.0, "input_tokens": 0, "output_tokens": 0}
        else:
            summary_call = call_model(
                adapter,
                AUX_MODEL,
                [{"role": "user", "content": summary_prompt}],
                max_tokens=1200,
                thinking="disabled",
            )
            points_call = (
                call_model(
                    adapter,
                    AUX_MODEL,
                    [{"role": "user", "content": points_prompt}],
                    max_tokens=900,
                    thinking="disabled",
                )
                if needs_points
                else {"success": True, "error": "", "output": "", "latency": 0.0, "input_tokens": 0, "output_tokens": 0}
            )

        summary_json, summary_json_error = extract_json_object(summary_call["output"])
        context_block = build_context_block(
            summary=summary_json,
            points=points_call["output"],
            target_mode=target_mode,
        )
        messages = [system_msg, {"role": "assistant", "content": context_block}] + bridged + [current_user]

        (aux_dir / f"{case_id}_transcript.txt").write_text(transcript, encoding="utf-8")
        (aux_dir / f"{case_id}_summary_prompt.txt").write_text(summary_prompt, encoding="utf-8")
        (aux_dir / f"{case_id}_summary_output.txt").write_text(summary_call["output"], encoding="utf-8")
        (aux_dir / f"{case_id}_points_prompt.txt").write_text(points_prompt if needs_points else "", encoding="utf-8")
        (aux_dir / f"{case_id}_points_output.txt").write_text(points_call["output"], encoding="utf-8")
        payload_path = payload_dir / f"{case_id}.json"
        payload_path.write_text(
            json.dumps(
                {
                    "meta": {
                        "scenario": scenario,
                        "target_mode": target_mode,
                        "target_model": target_model,
                        "bridge_turns": BRIDGE_TURNS,
                        "summary_prompt": str(args.summary_prompt),
                        "points_prompt": str(args.points_prompt),
                        **bridge_meta,
                    },
                    "messages": messages,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        print(
            f"[RUN] {case_id} target={target_mode}/{target_model} "
            f"bridge={bridge_meta['bridge_effective_turns']} payload_msgs={len(messages)}"
        )
        if args.dry_run:
            target_call = {
                "success": True,
                "error": "",
                "output": "（dry-run 占位旁白。）（用于验证10轮桥接加摘要互动要点 payload。）（不会调用目标模型。）",
                "latency": 0.0,
                "input_tokens": 0,
                "output_tokens": 0,
            }
        else:
            target_call = call_model(
                adapter,
                target_model,
                messages,
                max_tokens=args.long_max_tokens if target_mode == "long" else args.short_max_tokens,
                thinking="high" if target_mode == "long" else "disabled",
            )

        metrics = evaluate_output(
            target_call["output"],
            target_mode=target_mode,
            full_messages=messages,
            bridged_messages=bridged,
        )
        record = {
            "case_id": case_id,
            "scenario": scenario,
            "target_mode": target_mode,
            "target_model": target_model,
            "summary_effective_turns": len(recent_source) // 2,
            "summary_model": AUX_MODEL,
            "summary_success": summary_call["success"],
            "summary_error": summary_call["error"],
            "summary_latency": summary_call["latency"],
            "summary_input_tokens": summary_call["input_tokens"],
            "summary_output_tokens": summary_call["output_tokens"],
            "summary_json_ok": summary_json is not None,
            "summary_json_error": summary_json_error,
            "summary_output": summary_call["output"],
            "points_generated": needs_points,
            "points_model": AUX_MODEL if needs_points else "",
            "points_success": points_call["success"],
            "points_error": points_call["error"],
            "points_latency": points_call["latency"],
            "points_input_tokens": points_call["input_tokens"],
            "points_output_tokens": points_call["output_tokens"],
            "points_output": points_call["output"],
            "payload_path": str(payload_path),
            "payload_messages": len(messages),
            **bridge_meta,
            **{k: v for k, v in target_call.items() if k != "output"},
            "metrics": metrics,
            "output": target_call["output"],
        }
        append_jsonl(results_path, record)
        results.append(record)
        write_summary(results, summary_path)
        print(
            f"[OK] {case_id} success={record['success']} summary_json={record['summary_json_ok']} "
            f"chars={metrics['cjk_chars']} issues={len(metrics['format_issues'])} "
            f"bridge_ngram={metrics['ngram_max_bridge_pct']}"
        )

    print(f"[DONE] results={results_path}")
    print(f"[DONE] summary={summary_path}")


if __name__ == "__main__":
    main()
