#!/usr/bin/env python3
"""
Validate S11 frequent mode switching for deterministic switch_state.

This script verifies lifecycle invariants that single-turn replay cannot cover:
- switch_state is transient and never appended to the conversation ledger
- the next switch_state is rebuilt from user/assistant ledger turns only
- payloads do not carry raw cross-mode assistant history
- switch_state length stays bounded across repeated switches
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
    cjk_len,
    detect_format_issues,
    dialogue_history,
    first_system,
    last_user,
    load_log_sample,
    ngram_overlap,
)
from verify_mode_switching_short_model_matrix import (
    LONG_TARGET_MODEL,
    build_switch_state,
    ensure_runtime_key_aliases,
)


SHORT_MODEL = "doubao-lite"


def append_jsonl(path: Path, item: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def stored_summary_message(target_mode: str) -> dict[str, str]:
    """Static stored-summary stand-in. It simulates a DB snapshot, not a sync model call."""
    fields = [
        "（以下为角色内部认知记录，仅供上下文参考，请勿模仿此格式；这不是角色实际回复。仅为已发生事实，不是当前场景指令；若与当前输入冲突，以当前输入为准。）",
        "【当前场景】角色在休息间隙与用户聊天，气氛轻松，用户多次用简短消息试探开场。",
        "【本次对话智能摘要】用户近期围绕测试、打招呼、周末安排和角色工作状态展开互动；角色以耐心、调侃和陪伴感回应。",
    ]
    if target_mode == "long":
        fields.extend(
            [
                "【未兑现的承诺/未完成动作/悬念线索】用户尚未明确说明连续打招呼的真实意图。",
                "【角色情绪】放松、好奇，带一点被逗笑的耐心。",
                "【用户情绪】轻松试探，互动意图强于信息需求。",
                "【关系进展】熟悉度增加，角色愿意接住用户的重复开场。",
            ]
        )
    fields.extend(
        [
            "【用户核心记忆点】用户会用短句和重复问候测试角色反应。",
            "=== 摘要结束 ===",
            "（内部认知记录结束。以下对话才是真实聊天。）",
        ]
    )
    return {"role": "assistant", "content": "\n".join(fields)}


def call_model(
    adapter: ModelAdapter,
    model_id: str,
    messages: list[dict[str, str]],
    *,
    target_mode: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    result = adapter.chat(
        model_id=model_id,
        messages=messages,
        max_tokens=4096 if target_mode == "short" else 8192,
        thinking_effort="disabled" if target_mode == "short" else "high",
    )
    return {
        "success": result.success,
        "error": result.error,
        "output": result.content or "",
        "latency": round(time.perf_counter() - started, 3),
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    }


def recent_assistants(messages: list[dict[str, str]]) -> list[str]:
    return [m["content"] for m in messages if m.get("role") == "assistant"]


def evaluate_output(output: str, messages: list[dict[str, str]], target_mode: str) -> dict[str, Any]:
    assistants = recent_assistants(messages)[-8:]
    overlaps = [ngram_overlap(prev, output) for prev in assistants]
    return {
        "chars": len(output),
        "cjk_chars": cjk_len(output),
        "format_issues": detect_format_issues(output, target_mode),
        "ngram_max_recent_pct": round((max(overlaps) if overlaps else 0.0) * 100, 2),
        "output_preview": output[:500],
    }


def payload_has_raw_bridge_markers(messages: list[dict[str, str]]) -> bool:
    markers = (
        "以下为长文模式回复记录",
        "长文模式记录结束",
        "以下为短文模式回复记录",
        "短文模式记录结束",
    )
    return any(any(marker in msg.get("content", "") for marker in markers) for msg in messages)


def write_summary(records: list[dict[str, Any]], path: Path) -> None:
    lines = [
        "# S11 频繁切换 switch_state 生命周期验证报告",
        "",
        f"- 生成时间: {datetime.now().isoformat()}",
        "- 策略: stored_summary + deterministic switch_state + current_user",
        "- 不同步生成摘要/互动要点，不传异质 assistant 原文",
        "",
        "| 短文候选 | 步骤 | 目标 | 模型 | payload消息 | state字数 | ledger轮数 | 成功 | 输出字数 | 格式问题 | raw桥接标记 | state入ledger | prev_state入payload |",
        "|:--|:--|:--|:--|--:|--:|--:|:--:|--:|:--|:--:|:--:|:--:|",
    ]
    for item in records:
        issues = "；".join(item["metrics"].get("format_issues") or []) or "无"
        lines.append(
            "| {short_model} | {step} | {target_mode} | {target_model} | {payload_messages} | {switch_state_chars} | {ledger_turns} | {success} | {chars} | {issues} | {raw} | {state_ledger} | {prev_state} |".format(
                short_model=item.get("short_model", ""),
                step=item["step"],
                target_mode=item["target_mode"],
                target_model=item["target_model"],
                payload_messages=item["payload_messages"],
                switch_state_chars=item["switch_state_chars"],
                ledger_turns=item["ledger_turns"],
                success="Y" if item["success"] else "N",
                chars=item["metrics"].get("cjk_chars", 0),
                issues=issues,
                raw="Y" if item["raw_bridge_markers"] else "N",
                state_ledger="Y" if item["state_marker_in_ledger"] else "N",
                prev_state="Y" if item["previous_state_in_payload"] else "N",
            )
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate S11 frequent switching switch_state lifecycle")
    parser.add_argument("--short-log", default=str(SHORT_LOG_DEFAULT))
    parser.add_argument("--long-log", default=str(LONG_LOG_DEFAULT))
    parser.add_argument("--sequence", nargs="*", default=["long", "short", "long", "short", "long"])
    parser.add_argument("--short-models", nargs="*", default=[SHORT_MODEL])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--max-state-chars", type=int, default=900)
    args = parser.parse_args()

    ensure_runtime_key_aliases()
    short_sample = load_log_sample(Path(args.short_log), mode="short")
    long_sample = load_log_sample(Path(args.long_log), mode="long")
    short_hist = dialogue_history(short_sample)
    long_hist = dialogue_history(long_sample)

    out_dir = Path(args.output_dir) if args.output_dir else PROJECT_ROOT / "output" / "mode_switching_switch_state" / "s11"
    payload_dir = out_dir / "payloads"
    payload_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.jsonl"
    summary_path = out_dir / "summary.md"
    if results_path.exists():
        results_path.unlink()
    adapter = ModelAdapter()
    records: list[dict[str, Any]] = []

    print(f"[INFO] output={out_dir}")
    print(f"[INFO] sequence={' -> '.join(args.sequence)}")
    print(f"[INFO] short_models={','.join(args.short_models)}")

    for short_model in args.short_models:
        short_model = str(short_model or "").strip()
        if not short_model:
            continue
        ledger = [dict(m) for m in short_hist[-10:]]
        for msg in ledger:
            msg["source_mode"] = "short"
        previous_state_content = ""

        for step_index, target_mode in enumerate(args.sequence, start=1):
            if target_mode not in {"short", "long"}:
                raise ValueError(f"Unknown target mode: {target_mode}")
            target_model = LONG_TARGET_MODEL if target_mode == "long" else short_model
            system_msg = first_system(long_sample.messages if target_mode == "long" else short_sample.messages)
            current_user = last_user(long_sample.messages if target_mode == "long" else short_sample.messages)
            summary_msg = stored_summary_message(target_mode)
            state_msg, state_meta = build_switch_state(ledger, target_mode)
            messages = [system_msg, summary_msg, state_msg, current_user]

            short_model_slug = short_model.replace("-", "_").replace(".", "")
            target_model_slug = target_model.replace("-", "_").replace(".", "")
            case_id = f"s11_{short_model_slug}_step{step_index}_{target_mode}_{target_model_slug}"
            payload_path = payload_dir / f"{case_id}.json"
            payload_path.write_text(
                json.dumps(
                    {
                        "meta": {
                            "case_id": case_id,
                            "short_model": short_model,
                            "step": step_index,
                            "target_mode": target_mode,
                            "target_model": target_model,
                            **state_meta,
                        },
                        "messages": messages,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            if args.dry_run:
                call = {
                    "success": True,
                    "error": "",
                    "output": "（dry-run 占位输出，用于验证 S11 payload 生命周期。）",
                    "latency": 0.0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                }
            else:
                call = call_model(adapter, target_model, messages, target_mode=target_mode)

            metrics = evaluate_output(call["output"], messages, target_mode)
            ledger_text = "\n".join(m.get("content", "") for m in ledger)
            payload_text = "\n".join(m.get("content", "") for m in messages)
            record = {
                "case_id": case_id,
                "short_model": short_model,
                "step": step_index,
                "target_mode": target_mode,
                "target_model": target_model,
                "payload_path": str(payload_path),
                "payload_messages": len(messages),
                "ledger_messages_before": len(ledger),
                "ledger_turns": len([m for m in ledger if m.get("role") in {"user", "assistant"}]) // 2,
                "switch_state_chars": state_meta["switch_state_chars"],
                "raw_bridge_markers": payload_has_raw_bridge_markers(messages),
                "state_marker_in_ledger": "切换接话状态" in ledger_text,
                "previous_state_in_payload": bool(previous_state_content and previous_state_content in payload_text),
                **{k: v for k, v in call.items() if k != "output"},
                "metrics": metrics,
                "output": call["output"],
            }
            append_jsonl(results_path, record)
            records.append(record)
            write_summary(records, summary_path)

            print(
                f"[OK] short_model={short_model} step={step_index} target={target_mode}/{target_model} "
                f"success={record['success']} chars={metrics['cjk_chars']} "
                f"issues={len(metrics['format_issues'])} state_chars={record['switch_state_chars']}"
            )

            ledger.append({"role": "user", "content": current_user["content"], "source_mode": target_mode})
            ledger.append({"role": "assistant", "content": call["output"], "source_mode": target_mode})
            previous_state_content = state_msg["content"]

            # Add one real same-mode turn after each switch to mimic continued conversation.
            sample_hist = long_hist if target_mode == "long" else short_hist
            tail = sample_hist[-2:]
            for msg in tail:
                copied = {"role": msg["role"], "content": msg["content"], "source_mode": target_mode}
                ledger.append(copied)
            ledger = ledger[-24:]

    print(f"[DONE] results={results_path}")
    print(f"[DONE] summary={summary_path}")

    failures: list[str] = []
    for item in records:
        label = f"short_model={item.get('short_model', '')} step={item['step']} target={item['target_mode']}"
        if not item["success"]:
            failures.append(f"{label} api_failed:{item.get('error') or ''}")
        if item["payload_messages"] != 4:
            failures.append(f"{label} payload_messages={item['payload_messages']}")
        if not args.dry_run and item["metrics"].get("format_issues"):
            failures.append(f"{label} format_issues={item['metrics']['format_issues']}")
        if item["raw_bridge_markers"]:
            failures.append(f"{label} raw_bridge_markers=true")
        if item["state_marker_in_ledger"]:
            failures.append(f"{label} state_marker_in_ledger=true")
        if item["previous_state_in_payload"]:
            failures.append(f"{label} previous_state_in_payload=true")
        if item["switch_state_chars"] > args.max_state_chars:
            failures.append(f"{label} switch_state_chars={item['switch_state_chars']}")

    if failures:
        print("[ASSERTIONS_FAILED]")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print(
        "[ASSERTIONS_PASSED] "
        f"rows={len(records)} dry_run={str(args.dry_run).lower()} "
        f"api_success={len(records)} format_pass={'skipped' if args.dry_run else len(records)} "
        "lifecycle_no_raw_bridge=true state_not_in_ledger=true previous_state_not_reused=true"
    )


if __name__ == "__main__":
    main()
