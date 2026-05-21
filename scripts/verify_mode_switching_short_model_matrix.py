#!/usr/bin/env python3
"""
Replay all mode-switching validation strategies across short target models.

Inputs are real issue-log payloads. This script covers:

1. v5.4 sandwich bridge: 20 turns and 10 turns
2. v5.2 summary/interaction-points only: no raw bridged history
3. 10-turn sandwich bridge plus generated summary/interaction points

Short targets are tested with:
- doubao-lite
- doubao-1.5-character
- deepseek-v4-flash

Long targets keep deepseek-v4-pro.
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


SHORT_TARGET_MODELS = ("doubao-lite", "doubao-1.5-character", "deepseek-v4-flash")
LONG_TARGET_MODEL = "deepseek-v4-pro"


@dataclass(frozen=True)
class Strategy:
    id: str
    label: str
    bridge_turns: int | None
    summary_mode: str
    wrap_bridge: bool = True


STRATEGIES = (
    Strategy("raw_bridge_20", "原样长文历史20轮", 20, "none", False),
    Strategy("v54_bridge_20", "v5.4强三明治20轮", 20, "none"),
    Strategy("v54_bridge_10", "v5.4强三明治10轮", 10, "none"),
    Strategy("v52_summary_points", "v5.2纯摘要互动要点", None, "v52"),
    Strategy("10t_summary_points_bridge", "10轮桥接+摘要互动要点", 10, "combo"),
    Strategy("switch_state", "确定性切换接话状态", None, "state"),
    Strategy("summary_switch_state", "预置摘要+确定性接话状态", None, "state_summary"),
)


def ensure_runtime_key_aliases() -> dict[str, bool]:
    """Map compatible key env names without printing secrets."""
    if not os.environ.get("ARK_API_KEY") and os.environ.get("VOLCENGINE_API_KEY"):
        os.environ["ARK_API_KEY"] = os.environ["VOLCENGINE_API_KEY"]
    if not os.environ.get("DOUBAO_API_KEY") and os.environ.get("VOLCENGINE_API_KEY"):
        os.environ["DOUBAO_API_KEY"] = os.environ["VOLCENGINE_API_KEY"]
    return {
        "VOLCENGINE_API_KEY": bool(os.environ.get("VOLCENGINE_API_KEY")),
        "ARK_API_KEY": bool(os.environ.get("ARK_API_KEY")),
        "DASHSCOPE_API_KEY": bool(os.environ.get("DASHSCOPE_API_KEY")),
    }


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


def append_jsonl(path: Path, item: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def raw_bridge_history(
    source_history: list[dict[str, str]],
    bridge_turns: int,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    dialogue = [m for m in source_history if m["role"] in {"user", "assistant"}]
    recent = dialogue[-bridge_turns * 2 :]
    source_counts: dict[str, int] = {}
    raw_messages: list[dict[str, str]] = []
    for msg in recent:
        source_mode = str(msg.get("source_mode", "") or "unknown")
        source_counts[source_mode] = source_counts.get(source_mode, 0) + 1
        raw_messages.append({"role": msg["role"], "content": msg["content"]})
    meta = {
        "bridge_turns_requested": bridge_turns,
        "bridge_dialogue_messages": len(recent),
        "bridge_effective_turns": len(recent) // 2,
        "bridge_payload_messages": len(raw_messages),
        "available_dialogue_messages": len(dialogue),
        "available_turns": len(dialogue) // 2,
        "hetero_assistant_wrapped": 0,
        "source_counts": source_counts,
    }
    return raw_messages, meta


TIME_PREFIX_RE = re.compile(r"^\s*\[[^\]]*?\]\s*")
PAREN_RE = re.compile(r"（[^）]*）|\([^)]*\)")
WHITESPACE_RE = re.compile(r"\s+")


def compact_text(text: str, *, limit: int) -> str:
    cleaned = WHITESPACE_RE.sub(" ", str(text or "").strip())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 1)].rstrip() + "…"


def clean_user_text(text: str, *, limit: int) -> str:
    cleaned = TIME_PREFIX_RE.sub("", str(text or "").strip())
    return compact_text(cleaned, limit=limit)


def clean_assistant_intent(text: str, *, limit: int) -> str:
    without_parentheses = PAREN_RE.sub("", str(text or ""))
    without_markup = without_parentheses.replace("**", "")
    cleaned = compact_text(without_markup, limit=limit)
    if cleaned:
        return cleaned
    return "上一轮角色在回应用户并维持陪伴感。"


def extract_scene_hint(text: str, *, limit: int) -> str:
    fragments = [
        compact_text(match.group(0).strip("（）()"), limit=limit)
        for match in PAREN_RE.finditer(str(text or ""))
    ]
    fragments = [item for item in fragments if item]
    if not fragments:
        return ""
    return compact_text("；".join(fragments[-2:]), limit=limit)


def extract_open_question(text: str, *, limit: int) -> str:
    cleaned = clean_assistant_intent(text, limit=400)
    parts = re.split(r"(?<=[。！？!?])", cleaned)
    question = ""
    for part in parts:
        if any(mark in part for mark in ("？", "?", "吗", "呢", "要不要", "是不是")):
            question = part.strip()
    return compact_text(question, limit=limit) if question else ""


def build_switch_state(
    source_history: list[dict[str, str]],
    target_mode: str,
) -> tuple[dict[str, str], dict[str, Any]]:
    dialogue = [m for m in source_history if m["role"] in {"user", "assistant"}]
    if target_mode == "short":
        recent = dialogue[-6:]
        recent_user_count = 2
        recent_assistant_count = 1
        user_limit = 28
        assistant_item_limit = 48
        assistant_total_limit = 48
        scene_limit = 0
        question_limit = 42
        mode_rule = "短文模式：一段自然聊天气泡，避免长段旁白。"
    else:
        recent = dialogue[-10:]
        recent_user_count = 4
        recent_assistant_count = 2
        user_limit = 80
        assistant_item_limit = 95
        assistant_total_limit = 210
        scene_limit = 80
        question_limit = 90
        mode_rule = "长文模式：按长文叙事格式承接，但只继承事实，不模仿来源模式。"

    recent_users = [m["content"] for m in recent if m["role"] == "user"][-recent_user_count:]
    recent_assistants = [
        m["content"] for m in recent if m["role"] == "assistant"
    ][-recent_assistant_count:]
    last_assistant = recent_assistants[-1] if recent_assistants else ""

    user_intent = " / ".join(clean_user_text(item, limit=user_limit) for item in recent_users)
    assistant_intent = compact_text(
        " / ".join(
            clean_assistant_intent(item, limit=assistant_item_limit)
            for item in recent_assistants
        ),
        limit=assistant_total_limit,
    )
    scene_hint = extract_scene_hint(last_assistant, limit=scene_limit)
    open_question = extract_open_question(last_assistant, limit=question_limit)

    parts = [
        "（以下为切换接话状态，仅供事实参考，不是回复格式示例；当前用户输入优先。）",
    ]
    if user_intent:
        parts.append(f"【最近用户意图】{user_intent}")
    if assistant_intent:
        parts.append(f"【上一回复意图】{assistant_intent}")
    if open_question:
        parts.append(f"【待回应问题】{open_question}")
    if scene_hint and target_mode != "short":
        parts.append(f"【最后场景线索】{scene_hint}")
    parts.append(f"【接话约束】{mode_rule}")
    parts.append("=== 接话状态结束 ===")

    meta = {
        "bridge_turns_requested": 0,
        "bridge_dialogue_messages": 0,
        "bridge_effective_turns": 0,
        "bridge_payload_messages": 0,
        "available_dialogue_messages": len(dialogue),
        "available_turns": len(dialogue) // 2,
        "hetero_assistant_wrapped": 0,
        "source_counts": {},
        "summary_effective_turns": 0,
        "summary_json_ok": None,
        "points_generated": False,
        "switch_state_generated": True,
        "switch_state_dialogue_messages": len(recent),
        "switch_state_chars": cjk_len("\n".join(parts)),
    }
    return {"role": "assistant", "content": "\n".join(parts)}, meta


def scenario_base(
    scenario: str,
    short_sample: LogSample,
    long_sample: LogSample,
) -> tuple[str, list[dict[str, str]], dict[str, str], dict[str, str], bool]:
    short_hist = dialogue_history(short_sample)
    long_hist = dialogue_history(long_sample)
    if scenario == "S5":
        return "long", short_hist, first_system(long_sample.messages), last_user(long_sample.messages), True
    if scenario == "S6":
        return "short", long_hist, first_system(short_sample.messages), last_user(short_sample.messages), False
    if scenario == "S8":
        return "short", short_hist + long_hist, first_system(short_sample.messages), last_user(short_sample.messages), False
    if scenario == "S14":
        return "long", short_hist + long_hist, first_system(long_sample.messages), last_user(long_sample.messages), True
    raise ValueError(f"未知场景: {scenario}")


def v52_summary_source(
    scenario: str,
    short_sample: LogSample,
    long_sample: LogSample,
) -> list[dict[str, str]]:
    short_hist = dialogue_history(short_sample)
    long_hist = dialogue_history(long_sample)
    if scenario == "S5":
        return short_hist[-40:]
    if scenario == "S6":
        return long_hist[-20:]
    if scenario == "S8":
        return (short_hist + long_hist)[-20:]
    if scenario == "S14":
        return (short_hist + long_hist)[-40:]
    raise ValueError(f"未知场景: {scenario}")


def generate_context_block(
    *,
    adapter: ModelAdapter,
    strategy: Strategy,
    scenario: str,
    target_mode: str,
    current_user: dict[str, str],
    source_messages: list[dict[str, str]],
    needs_points: bool,
    summary_template: str,
    points_template: str,
    aux_dir: Path,
    dry_run: bool,
) -> tuple[dict[str, str], dict[str, Any]]:
    transcript = transcript_from_messages(
        source_messages,
        base_time=extract_time_hint(current_user["content"]),
    )
    current_mode = "longform" if target_mode == "long" else "shortform"
    summary_prompt = render_summary_prompt(
        summary_template,
        current_mode=current_mode,
        transcript=transcript,
    )
    points_prompt = render_points_prompt(points_template, transcript=transcript)
    aux_id = f"{scenario}_{strategy.id}"

    if dry_run:
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
        } if needs_points else {
            "success": True,
            "error": "",
            "output": "",
            "latency": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
        }
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
            else {
                "success": True,
                "error": "",
                "output": "",
                "latency": 0.0,
                "input_tokens": 0,
                "output_tokens": 0,
            }
        )

    summary_json, summary_json_error = extract_json_object(summary_call["output"])
    context_block = build_context_block(
        summary=summary_json,
        points=points_call["output"],
        target_mode=target_mode,
    )
    aux_dir.mkdir(parents=True, exist_ok=True)
    (aux_dir / f"{aux_id}_transcript.txt").write_text(transcript, encoding="utf-8")
    (aux_dir / f"{aux_id}_summary_prompt.txt").write_text(summary_prompt, encoding="utf-8")
    (aux_dir / f"{aux_id}_summary_output.txt").write_text(summary_call["output"], encoding="utf-8")
    (aux_dir / f"{aux_id}_points_prompt.txt").write_text(points_prompt if needs_points else "", encoding="utf-8")
    (aux_dir / f"{aux_id}_points_output.txt").write_text(points_call["output"], encoding="utf-8")

    meta = {
        "summary_effective_turns": len([m for m in source_messages if m["role"] in {"user", "assistant"}]) // 2,
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
    }
    return {"role": "assistant", "content": context_block}, meta


def build_payload(
    *,
    strategy: Strategy,
    scenario: str,
    short_sample: LogSample,
    long_sample: LogSample,
    adapter: ModelAdapter,
    summary_template: str,
    points_template: str,
    aux_dir: Path,
    dry_run: bool,
    force_points: bool,
) -> tuple[str, list[dict[str, str]], dict[str, Any]]:
    target_mode, source_history, system_msg, current_user, needs_points = scenario_base(
        scenario,
        short_sample,
        long_sample,
    )
    needs_points = needs_points or force_points
    target_models = [LONG_TARGET_MODEL] if target_mode == "long" else list(SHORT_TARGET_MODELS)

    if strategy.summary_mode == "state":
        context_msg, state_meta = build_switch_state(source_history, target_mode)
        messages = [system_msg, context_msg, current_user]
        return target_mode, messages, {"target_models": target_models, **state_meta}

    if strategy.summary_mode == "state_summary":
        summary_source = v52_summary_source(scenario, short_sample, long_sample)
        summary_msg, summary_meta = generate_context_block(
            adapter=adapter,
            strategy=strategy,
            scenario=scenario,
            target_mode=target_mode,
            current_user=current_user,
            source_messages=summary_source,
            needs_points=False,
            summary_template=summary_template,
            points_template=points_template,
            aux_dir=aux_dir,
            dry_run=dry_run,
        )
        state_msg, state_meta = build_switch_state(source_history, target_mode)
        messages = [system_msg, summary_msg, state_msg, current_user]
        meta = {**state_meta, **summary_meta}
        return target_mode, messages, {"target_models": target_models, **meta}

    if strategy.summary_mode == "none":
        assert strategy.bridge_turns is not None
        if strategy.wrap_bridge:
            bridged, bridge_meta = bridge_history(source_history, target_mode, strategy.bridge_turns)
        else:
            bridged, bridge_meta = raw_bridge_history(source_history, strategy.bridge_turns)
        messages = [system_msg] + bridged + [current_user]
        meta = {
            "summary_effective_turns": 0,
            "summary_json_ok": None,
            "points_generated": False,
            **bridge_meta,
        }
        return target_mode, messages, {"target_models": target_models, **meta}

    if strategy.summary_mode == "v52":
        summary_source = v52_summary_source(scenario, short_sample, long_sample)
        context_msg, summary_meta = generate_context_block(
            adapter=adapter,
            strategy=strategy,
            scenario=scenario,
            target_mode=target_mode,
            current_user=current_user,
            source_messages=summary_source,
            needs_points=needs_points,
            summary_template=summary_template,
            points_template=points_template,
            aux_dir=aux_dir,
            dry_run=dry_run,
        )
        messages = [system_msg, context_msg, current_user]
        meta = {
            "bridge_turns_requested": 0,
            "bridge_dialogue_messages": 0,
            "bridge_effective_turns": 0,
            "bridge_payload_messages": 0,
            "available_dialogue_messages": len(source_history),
            "available_turns": len(source_history) // 2,
            "hetero_assistant_wrapped": 0,
            "source_counts": {},
            **summary_meta,
        }
        return target_mode, messages, {"target_models": target_models, **meta}

    if strategy.summary_mode == "combo":
        assert strategy.bridge_turns is not None
        bridged, bridge_meta = bridge_history(source_history, target_mode, strategy.bridge_turns)
        recent_source = [m for m in source_history if m["role"] in {"user", "assistant"}][
            -strategy.bridge_turns * 2 :
        ]
        context_msg, summary_meta = generate_context_block(
            adapter=adapter,
            strategy=strategy,
            scenario=scenario,
            target_mode=target_mode,
            current_user=current_user,
            source_messages=recent_source,
            needs_points=needs_points,
            summary_template=summary_template,
            points_template=points_template,
            aux_dir=aux_dir,
            dry_run=dry_run,
        )
        messages = [system_msg, context_msg] + bridged + [current_user]
        meta = {**bridge_meta, **summary_meta}
        return target_mode, messages, {"target_models": target_models, **meta}

    raise ValueError(f"未知 summary_mode: {strategy.summary_mode}")


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


def safe_model_label(model_id: str) -> str:
    return model_id.replace(".", "").replace("-", "_")


def summarize_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in results:
        groups.setdefault((item["strategy"], item["target_model"]), []).append(item)

    rows: list[dict[str, Any]] = []
    for (strategy, model), items in sorted(groups.items()):
        total = len(items)
        ok = sum(1 for r in items if r["success"] and not r["metrics"].get("format_issues"))
        success = sum(1 for r in items if r["success"])
        avg_chars = round(sum(r["metrics"].get("cjk_chars", 0) for r in items) / total, 1) if total else 0
        max_ngram = max((r["metrics"].get("ngram_max_recent_pct", 0) for r in items), default=0)
        rows.append(
            {
                "strategy": strategy,
                "target_model": model,
                "cases": total,
                "api_success": success,
                "format_pass": ok,
                "format_pass_rate": round(ok / total * 100, 1) if total else 0,
                "avg_cjk_chars": avg_chars,
                "max_recent_ngram": max_ngram,
            }
        )
    return rows


def write_markdown(results: list[dict[str, Any]], path: Path) -> None:
    aggregate = summarize_results(results)
    lines = [
        "# 长短文切换全策略短文模型矩阵验证报告",
        "",
        f"- 生成时间: {datetime.now().isoformat()}",
        "- 输入来源: 问题排查目录中的真实 payload 日志",
        "- 长文目标模型: deepseek-v4-pro",
        "- 短文目标模型: doubao-lite / doubao-1.5-character / deepseek-v4-flash",
        "- 辅助摘要/互动要点模型: doubao-lite",
        "",
        "## 逐条结果",
        "",
        "| 策略 | 场景 | 目标模型 | 目标 | 桥接轮数 | 摘要轮数 | 互动要点 | payload消息 | 包夹assistant | 摘要JSON | 成功 | 字数 | 格式问题 | recent-max-ngram |",
        "|:--|:--|:--|:--|--:|--:|:--:|--:|--:|:--:|:--:|--:|:--|--:|",
    ]
    for r in results:
        issues = "；".join(r["metrics"].get("format_issues") or []) or "无"
        summary_json = r.get("summary_json_ok")
        if summary_json is None:
            summary_json_text = "-"
        else:
            summary_json_text = "Y" if summary_json else "N"
        lines.append(
            "| {strategy} | {scenario} | {target_model} | {target_mode} | {bridge_turns} | {summary_turns} | {points} | "
            "{payload_messages} | {wrapped} | {summary_json} | {success} | {chars} | {issues} | {ngram} |".format(
                strategy=r["strategy"],
                scenario=r["scenario"],
                target_model=r["target_model"],
                target_mode=r["target_mode"],
                bridge_turns=r.get("bridge_effective_turns", 0),
                summary_turns=r.get("summary_effective_turns", 0),
                points="Y" if r.get("points_generated") else "N",
                payload_messages=r["payload_messages"],
                wrapped=r.get("hetero_assistant_wrapped", 0),
                summary_json=summary_json_text,
                success="Y" if r["success"] else "N",
                chars=r["metrics"].get("cjk_chars", 0),
                issues=issues,
                ngram=r["metrics"].get("ngram_max_recent_pct", 0),
            )
        )

    lines.extend(
        [
            "",
            "## 聚合结果",
            "",
            "| 策略 | 目标模型 | case数 | API成功 | 格式通过 | 格式通过率 | 平均字数 | 最大recent-ngram |",
            "|:--|:--|--:|--:|--:|--:|--:|--:|",
        ]
    )
    for row in aggregate:
        lines.append(
            "| {strategy} | {target_model} | {cases} | {api_success} | {format_pass} | {format_pass_rate}% | {avg_cjk_chars} | {max_recent_ngram} |".format(
                **row
            )
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay mode-switching strategies across short target models")
    parser.add_argument("--short-log", default=str(SHORT_LOG_DEFAULT))
    parser.add_argument("--long-log", default=str(LONG_LOG_DEFAULT))
    parser.add_argument("--summary-prompt", default=str(SUMMARY_PROMPT_DEFAULT))
    parser.add_argument("--points-prompt", default=str(POINTS_PROMPT_DEFAULT))
    parser.add_argument("--scenarios", nargs="*", default=["S5", "S6", "S8", "S14"])
    parser.add_argument("--strategies", nargs="*", default=[s.id for s in STRATEGIES])
    parser.add_argument("--short-models", nargs="*", default=list(SHORT_TARGET_MODELS))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force-points", action="store_true", help="Generate interaction points for summary strategies even when target mode is short")
    parser.add_argument("--long-max-tokens", type=int, default=16384)
    parser.add_argument("--short-max-tokens", type=int, default=4096)
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args()

    env_status = ensure_runtime_key_aliases()
    unknown_short_models = [m for m in args.short_models if m not in SHORT_TARGET_MODELS]
    if unknown_short_models:
        raise ValueError(f"未知短文模型: {unknown_short_models}")

    selected_strategies = [s for s in STRATEGIES if s.id in set(args.strategies)]
    if len(selected_strategies) != len(set(args.strategies)):
        known = {s.id for s in STRATEGIES}
        raise ValueError(f"未知策略: {sorted(set(args.strategies) - known)}")

    short_sample = load_log_sample(Path(args.short_log), mode="short")
    long_sample = load_log_sample(Path(args.long_log), mode="long")
    summary_template = Path(args.summary_prompt).read_text(encoding="utf-8", errors="ignore")
    points_template = Path(args.points_prompt).read_text(encoding="utf-8", errors="ignore")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_dir) if args.output_dir else PROJECT_ROOT / "output" / "mode_switching_short_model_matrix" / ts
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
    print(f"[INFO] env_status={env_status}")
    print(f"[INFO] output={out_dir}")

    for strategy in selected_strategies:
        for scenario in args.scenarios:
            target_mode, base_messages, meta = build_payload(
                strategy=strategy,
                scenario=scenario,
                short_sample=short_sample,
                long_sample=long_sample,
                adapter=adapter,
                summary_template=summary_template,
                points_template=points_template,
                aux_dir=aux_dir,
                dry_run=args.dry_run,
                force_points=args.force_points,
            )
            target_models = [LONG_TARGET_MODEL] if target_mode == "long" else list(args.short_models)
            for target_model in target_models:
                case_id = f"{strategy.id}_{scenario}_{safe_model_label(target_model)}"
                payload_path = payload_dir / f"{case_id}.json"
                payload_path.write_text(
                    json.dumps(
                        {
                            "meta": {
                                "case_id": case_id,
                                "strategy": strategy.id,
                                "strategy_label": strategy.label,
                                "scenario": scenario,
                                "target_mode": target_mode,
                                "target_model": target_model,
                                **{k: v for k, v in meta.items() if k != "target_models"},
                            },
                            "messages": base_messages,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                print(
                    f"[RUN] {case_id} target={target_mode}/{target_model} "
                    f"payload_msgs={len(base_messages)}"
                )
                if args.dry_run:
                    call = {
                        "success": True,
                        "error": "",
                        "output": "（dry-run 占位旁白。）（用于验证全策略短文模型矩阵 payload。）（不会调用目标模型。）",
                        "latency": 0.0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                    }
                else:
                    call = call_model(
                        adapter,
                        target_model,
                        base_messages,
                        max_tokens=args.long_max_tokens if target_mode == "long" else args.short_max_tokens,
                        thinking="high" if target_mode == "long" else "disabled",
                    )
                metrics = evaluate_output(call["output"], base_messages, target_mode)
                record = {
                    "case_id": case_id,
                    "strategy": strategy.id,
                    "strategy_label": strategy.label,
                    "scenario": scenario,
                    "target_mode": target_mode,
                    "target_model": target_model,
                    "payload_path": str(payload_path),
                    "payload_messages": len(base_messages),
                    **{k: v for k, v in meta.items() if k != "target_models"},
                    **{k: v for k, v in call.items() if k != "output"},
                    "metrics": metrics,
                    "output": call["output"],
                }
                append_jsonl(results_path, record)
                results.append(record)
                write_markdown(results, summary_path)
                issues = metrics.get("format_issues") or []
                print(
                    f"[OK] {case_id} success={record['success']} chars={metrics['cjk_chars']} "
                    f"issues={len(issues)} max_ngram={metrics['ngram_max_recent_pct']}"
                )

    print(f"[DONE] results={results_path}")
    print(f"[DONE] summary={summary_path}")


if __name__ == "__main__":
    main()
