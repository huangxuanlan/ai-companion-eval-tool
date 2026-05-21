#!/usr/bin/env python3
"""Validate original-format interaction points plus sandwich fallback.

This script replays the S1-S14 MECE mode-switching matrix using production
issue-log payloads. The switching path under test is:

    old dialogue_summary (if any) + original-format interaction points + current user

When interaction points are unavailable, the fallback path is:

    old dialogue_summary + last N turns with v5.4 sandwich isolation + current user

The mini interaction-points input intentionally excludes old dialogue_summary.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
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

from services.model_adapter import ModelAdapter
from verify_mode_switching_log_replay import (
    LONG_LOG_DEFAULT,
    SHORT_LOG_DEFAULT,
    bridge_history,
    cjk_len,
    detect_format_issues,
    dialogue_history,
    first_system,
    last_user,
    load_log_sample,
    ngram_overlap,
    recent_assistant_texts,
)
from verify_mode_switching_short_model_matrix import (
    LONG_TARGET_MODEL,
    SHORT_TARGET_MODELS,
    safe_model_label,
)
from verify_v52_summary_points_replay import (
    POINTS_PROMPT_DEFAULT,
    extract_time_hint,
    transcript_from_messages,
)


EXTRACTOR_MODEL = "doubao-mini"
SCENARIO_ORDER = tuple(f"S{i}" for i in range(1, 15))
DEFAULT_S11_SEQUENCE = ("long", "short", "long", "short")
WHITESPACE_RE = re.compile(r"\s+")
POINT_LINE_RE = re.compile(r"^\s*\d+[.、]\s*\[(\d{2}-\d{2}\s+\d{2}:\d{2})\]")
TIME_RANGE_RE = re.compile(r"\[(\d{2}-\d{2})\s+\d{2}:\d{2}-(\d{2}:\d{2})\]")
RAW_BRIDGE_MARKERS = (
    "以下为长文模式回复记录",
    "长文模式记录结束",
    "以下为短文模式回复记录",
    "短文模式记录结束",
)


@dataclass(frozen=True)
class ScenarioSpec:
    id: str
    label: str
    target_modes: tuple[str, ...]
    is_switch: bool
    notes: str


SCENARIOS: dict[str, ScenarioSpec] = {
    "S1": ScenarioSpec("S1", "纯短文连续聊<20轮", ("short",), False, "无切换；无互动要点"),
    "S2": ScenarioSpec("S2", "纯短文连续聊>=20轮", ("short",), False, "旧摘要+短文最近10轮"),
    "S3": ScenarioSpec("S3", "纯长文连续聊<10轮", ("long",), False, "无切换；无互动要点"),
    "S4": ScenarioSpec("S4", "纯长文连续聊>=10轮", ("long",), False, "旧摘要+长文最近10轮"),
    "S5": ScenarioSpec("S5", "短->长切换", ("long",), True, "旧摘要+短文互动要点"),
    "S6": ScenarioSpec("S6", "长->短切换", ("short",), True, "旧摘要+长文互动要点"),
    "S7": ScenarioSpec("S7", "短->长后<10轮关闭再接续", ("long",), True, "互动要点存活+长文STM"),
    "S8": ScenarioSpec("S8", "短->长->短快速往返", ("short",), True, "旧摘要+混合历史互动要点"),
    "S9": ScenarioSpec("S9", "长->短后<20轮关闭再接续", ("short",), True, "互动要点/兜底+短文STM"),
    "S10": ScenarioSpec("S10", "长->短->长快速往返", ("long",), True, "旧摘要+混合历史互动要点"),
    "S11": ScenarioSpec("S11", "频繁切换>=3次", ("long", "short"), True, "生命周期链路"),
    "S12": ScenarioSpec("S12", "任意模式开新会话", ("short", "long"), False, "不得误读旧互动要点"),
    "S13": ScenarioSpec("S13", "纯长文摘要延迟", ("long",), False, "旧摘要+最近10轮纯长文"),
    "S14": ScenarioSpec("S14", "短->长后摘要延迟跨模式取数", ("long",), True, "旧摘要+互动要点；兜底用三明治"),
}


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


def compact(text: str, limit: int | None = None) -> str:
    value = WHITESPACE_RE.sub(" ", str(text or "").strip())
    if limit is not None and len(value) > limit:
        return value[: max(0, limit - 1)].rstrip() + "..."
    return value


def select_turns(history: list[dict[str, str]], turns: int) -> list[dict[str, str]]:
    if turns <= 0:
        return []
    dialogue = [m for m in history if m.get("role") in {"user", "assistant"}]
    return [dict(m) for m in dialogue[-turns * 2 :]]


def stored_summary_text(target_mode: str, *, label: str = "") -> str:
    base = [
        "（以下为角色内部认知记录，仅供上下文参考，请勿模仿此格式；这不是角色实际回复。仅为已发生事实，不是当前场景指令；若与当前输入冲突，以当前输入为准。）",
        "【当前场景】用户与角色延续近期线上聊天，双方处于熟悉但仍需自然承接的关系状态。",
        "【本次对话智能摘要】用户近期通过问候、试探、关心状态和轻互动维持联系；角色需要接住用户当前输入，而不是复述历史。",
    ]
    if target_mode == "long":
        base.extend(
            [
                "【未兑现的承诺/未完成动作/悬念线索】需要优先承接当前用户输入；历史线索只作事实背景。",
                "【角色情绪】放松、愿意回应，保持陪伴感。",
                "【用户情绪】轻松试探，期待自然回应。",
                "【关系进展】互动频率增加，熟悉度上升。",
                "【用户核心记忆点】用户偏好自然、不生硬的陪伴式接话。",
            ]
        )
    if label:
        base.append(f"【验证标签】{label}")
    base.append("=== 摘要结束 ===")
    return "\n".join(base)


def wrap_points_context(points: str) -> str:
    body = points.strip()
    return "\n".join(
        [
            "（以下为模式切换互动要点，仅供事实参考，不是回复格式示例；当前用户输入优先。）",
            body,
            "=== 互动要点结束 ===",
            "（内部认知记录结束。以下对话才是真实聊天。）",
        ]
    )


def context_block(*, target_mode: str, points: str = "", label: str = "") -> dict[str, str]:
    parts = [stored_summary_text(target_mode, label=label)]
    if points.strip():
        parts.append(wrap_points_context(points))
    return {"role": "assistant", "content": "\n".join(parts)}


def render_points_prompt(template: str, source_messages: list[dict[str, str]], current_user: dict[str, str]) -> tuple[str, str]:
    transcript = transcript_from_messages(
        source_messages,
        base_time=extract_time_hint(current_user.get("content", "")),
    )
    prompt = template.replace("{conversation_text}", transcript)
    prompt += (
        "\n\n【验证强制补充】\n"
        "直接输出原 output_format 中的纯文本格式；互动要点最多 5 条，超过 5 条视为失败；"
        "每条互动要点必须包含单个 [MM-DD HH:mm]；禁止输出 [MM-DD HH:mm-HH:mm] 这类时间范围；"
        "不要输出示例、解释、JSON 或代码块。"
    )
    return prompt, transcript


def strip_code_fence(text: str) -> str:
    value = str(text or "").strip()
    value = re.sub(r"^```(?:text|markdown)?\s*", "", value, flags=re.I)
    value = re.sub(r"\s*```$", "", value)
    return value.strip()


def normalize_points_text(text: str) -> tuple[str, list[str]]:
    changes: list[str] = []

    def replace_time_range(match: re.Match[str]) -> str:
        changes.append("time_range_to_end_time")
        return f"[{match.group(1)} {match.group(2)}]"

    return TIME_RANGE_RE.sub(replace_time_range, text), changes


def validate_original_points(points: str, source_messages: list[dict[str, str]]) -> dict[str, Any]:
    clean = strip_code_fence(points)
    issues: list[str] = []
    if not clean:
        issues.append("empty_points")
    if "【最近互动要点（桥接迁移）】" not in clean:
        issues.append("missing_original_points_header")
    if "【待接续线索】" not in clean:
        issues.append("missing_pending_hook")
    if "【最后场景】" not in clean:
        issues.append("missing_last_scene")
    if "{" in clean and "}" in clean:
        issues.append("looks_like_json")
    if "```" in str(points or ""):
        issues.append("code_fence")
    point_lines = [line for line in clean.splitlines() if re.match(r"^\s*\d+[.、]", line)]
    if len(point_lines) > 5:
        issues.append(f"too_many_points={len(point_lines)}")
    for line in point_lines:
        if not POINT_LINE_RE.search(line):
            issues.append("point_missing_absolute_time")
            break
    cjk_chars = cjk_len(clean)
    if cjk_chars > 520:
        issues.append(f"points_too_long={cjk_chars}")
    overlaps = [
        ngram_overlap(msg.get("content", ""), clean)
        for msg in source_messages
        if msg.get("role") == "assistant"
    ]
    raw_overlap = round((max(overlaps) if overlaps else 0.0) * 100, 2)
    if raw_overlap >= 65:
        issues.append(f"raw_assistant_overlap={raw_overlap}%")
    return {
        "pass": not issues,
        "issues": issues,
        "points_count": len(point_lines),
        "points_cjk_chars": cjk_chars,
        "raw_assistant_overlap_pct": raw_overlap,
    }


def call_model(
    adapter: ModelAdapter,
    model_id: str,
    messages: list[dict[str, str]],
    *,
    target_mode: str,
    long_max_tokens: int,
    short_max_tokens: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    result = adapter.chat(
        model_id=model_id,
        messages=messages,
        max_tokens=long_max_tokens if target_mode == "long" else short_max_tokens,
        thinking_effort="high" if target_mode == "long" else "disabled",
    )
    return {
        "success": result.success,
        "error": result.error,
        "output": result.content or "",
        "latency": round(time.perf_counter() - started, 3),
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    }


def call_interaction_points(
    *,
    adapter: ModelAdapter,
    template: str,
    source_messages: list[dict[str, str]],
    current_user: dict[str, str],
    aux_dir: Path,
    case_id: str,
    dry_run: bool,
    force_fallback: bool,
    latency_threshold: float,
) -> tuple[str, dict[str, Any]]:
    prompt, transcript = render_points_prompt(template, source_messages, current_user)
    aux_dir.mkdir(parents=True, exist_ok=True)
    (aux_dir / f"{case_id}_points_prompt.txt").write_text(prompt, encoding="utf-8")
    (aux_dir / f"{case_id}_points_transcript.txt").write_text(transcript, encoding="utf-8")
    if force_fallback:
        return "", {
            "points_attempted": False,
            "points_success": False,
            "points_error": "force_fallback",
            "points_latency": 0.0,
            "points_input_tokens": 0,
            "points_output_tokens": 0,
            "points_quality": {"pass": False, "issues": ["force_fallback"]},
            "points_postprocesses": [],
            "points_latency_exceeded": False,
            "points_source_messages": len(source_messages),
            "points_source_turns": len(source_messages) // 2,
            "points_input_excludes_old_summary": True,
        }
    if dry_run:
        output = (
            "【最近互动要点（桥接迁移）】\n"
            "1. [05-09 16:00] 用户延续轻互动，角色以自然陪伴回应\n"
            "2. [05-09 16:02] 双方围绕当前状态继续试探式聊天\n"
            "【待接续线索】用户仍在等待角色接住当前输入\n"
            "【最后场景】线上聊天界面，气氛轻松"
        )
        call = {
            "success": True,
            "error": "",
            "output": output,
            "latency": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
        }
    else:
        started = time.perf_counter()
        result = adapter.chat(
            model_id=EXTRACTOR_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=900,
            thinking_effort="disabled",
            temperature=0.0,
            top_p=0.1,
            provider_retry_delays=[],
        )
        call = {
            "success": result.success,
            "error": result.error,
            "output": result.content or "",
            "latency": round(time.perf_counter() - started, 3),
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
        }
    raw_output = strip_code_fence(call["output"])
    output, postprocesses = normalize_points_text(raw_output)
    (aux_dir / f"{case_id}_points_output_raw.txt").write_text(raw_output, encoding="utf-8")
    (aux_dir / f"{case_id}_points_output.txt").write_text(output, encoding="utf-8")
    quality = validate_original_points(output, source_messages)
    latency_exceeded = call["latency"] > latency_threshold
    return output, {
        "points_attempted": True,
        "points_success": call["success"],
        "points_error": call["error"],
        "points_latency": call["latency"],
        "points_input_tokens": call["input_tokens"],
        "points_output_tokens": call["output_tokens"],
        "points_quality": quality,
        "points_postprocesses": postprocesses,
        "points_latency_exceeded": latency_exceeded,
        "points_source_messages": len(source_messages),
        "points_source_turns": len(source_messages) // 2,
        "points_input_excludes_old_summary": True,
    }


def payload_has_raw_bridge_markers(messages: list[dict[str, str]]) -> bool:
    return any(any(marker in m.get("content", "") for marker in RAW_BRIDGE_MARKERS) for m in messages)


def evaluate_output(output: str, messages: list[dict[str, str]], target_mode: str) -> dict[str, Any]:
    assistants = recent_assistant_texts(messages, limit=8)
    overlaps = [ngram_overlap(prev, output) for prev in assistants]
    return {
        "chars": len(output),
        "cjk_chars": cjk_len(output),
        "format_issues": detect_format_issues(output, target_mode),
        "ngram_max_recent_pct": round((max(overlaps) if overlaps else 0.0) * 100, 2),
        "output_preview": output[:500],
    }


def target_models_for_mode(target_mode: str, short_models: list[str]) -> list[str]:
    return [LONG_TARGET_MODEL] if target_mode == "long" else short_models


def scenario_source(
    scenario: str,
    target_mode: str,
    short_hist: list[dict[str, str]],
    long_hist: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Return (points_source, same_mode_recent_history)."""
    if scenario in {"S5", "S7"}:
        return select_turns(short_hist, 20), select_turns(long_hist, 5 if scenario == "S7" else 0)
    if scenario in {"S6", "S9"}:
        return select_turns(long_hist, 10), select_turns(short_hist, 5 if scenario == "S9" else 0)
    if scenario in {"S8", "S14"}:
        return select_turns(short_hist + long_hist, 10), []
    if scenario == "S10":
        return select_turns(long_hist + short_hist, 10), []
    if scenario == "S11":
        return select_turns(short_hist, 10), []
    return [], []


def same_mode_payload(
    scenario: str,
    target_mode: str,
    short_sample: Any,
    long_sample: Any,
    short_hist: list[dict[str, str]],
    long_hist: list[dict[str, str]],
) -> list[dict[str, str]]:
    sample = short_sample if target_mode == "short" else long_sample
    history = short_hist if target_mode == "short" else long_hist
    if scenario in {"S1", "S3"}:
        recent = select_turns(history, 4)
        return [first_system(sample.messages)] + recent + [last_user(sample.messages)]
    if scenario == "S2":
        recent = select_turns(short_hist, 10)
        return [
            first_system(short_sample.messages),
            context_block(target_mode="short", label="S2_old_summary"),
            *recent,
            last_user(short_sample.messages),
        ]
    if scenario in {"S4", "S13"}:
        recent = select_turns(long_hist, 10)
        return [
            first_system(long_sample.messages),
            context_block(target_mode="long", label=f"{scenario}_old_summary"),
            *recent,
            last_user(long_sample.messages),
        ]
    if scenario == "S12":
        stm_turns = 20 if target_mode == "short" else 10
        recent = select_turns(short_hist if target_mode == "short" else long_hist, stm_turns)
        return [
            first_system(sample.messages),
            context_block(target_mode=target_mode, label=f"S12_new_session_{target_mode}"),
            *recent,
            last_user(sample.messages),
        ]
    raise ValueError(f"same-mode payload not defined: {scenario}/{target_mode}")


def switch_payload(
    *,
    strategy: str,
    scenario: str,
    target_mode: str,
    short_sample: Any,
    long_sample: Any,
    short_hist: list[dict[str, str]],
    long_hist: list[dict[str, str]],
    points: str,
    fallback_turns: int,
    extra_same_mode_history: list[dict[str, str]],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    sample = short_sample if target_mode == "short" else long_sample
    current_user = last_user(sample.messages)
    source, _ = scenario_source(scenario, target_mode, short_hist, long_hist)
    if strategy == "points_ready":
        messages = [
            first_system(sample.messages),
            context_block(target_mode=target_mode, points=points, label=f"{scenario}_old_summary"),
            *extra_same_mode_history,
            current_user,
        ]
        return messages, {
            "strategy": strategy,
            "fallback_turns": 0,
            "fallback_bridge_messages": 0,
            "raw_bridge_markers_expected": False,
        }
    bridged, bridge_meta = bridge_history(source, target_mode, fallback_turns)
    messages = [
        first_system(sample.messages),
        context_block(target_mode=target_mode, label=f"{scenario}_fallback_old_summary"),
        *bridged,
        *extra_same_mode_history,
        current_user,
    ]
    return messages, {
        "strategy": strategy,
        "fallback_turns": fallback_turns,
        "fallback_bridge_messages": len(bridged),
        **bridge_meta,
        "raw_bridge_markers_expected": True,
    }


def append_jsonl(path: Path, item: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def write_payload(path: Path, meta: dict[str, Any], messages: list[dict[str, str]]) -> None:
    path.write_text(
        json.dumps({"meta": meta, "messages": messages}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def sanitize_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    clean: list[dict[str, str]] = []
    for msg in messages:
        role = str(msg.get("role", "")).strip()
        content = str(msg.get("content", ""))
        clean.append({"role": role, "content": content})
    return clean


def run_single_case(
    *,
    adapter: ModelAdapter,
    case_id: str,
    scenario: str,
    scenario_label: str,
    strategy: str,
    target_mode: str,
    target_model: str,
    messages: list[dict[str, str]],
    meta: dict[str, Any],
    output_dir: Path,
    dry_run: bool,
    long_max_tokens: int,
    short_max_tokens: int,
) -> dict[str, Any]:
    api_messages = sanitize_messages(messages)
    payload_dir = output_dir / "payloads"
    payload_dir.mkdir(parents=True, exist_ok=True)
    payload_path = payload_dir / f"{case_id}.json"
    write_payload(
        payload_path,
        {
            "case_id": case_id,
            "scenario": scenario,
            "scenario_label": scenario_label,
            "strategy": strategy,
            "target_mode": target_mode,
            "target_model": target_model,
            **meta,
        },
        api_messages,
    )
    if dry_run:
        output = (
            "（dry-run 占位旁白。）（用于验证互动要点与三明治兜底全量矩阵 payload。）（不会调用目标模型。）"
            if target_mode == "long"
            else "（dry-run）我在，继续说。"
        )
        call = {
            "success": True,
            "error": "",
            "output": output,
            "latency": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
        }
    else:
        call = call_model(
            adapter,
            target_model,
            api_messages,
            target_mode=target_mode,
            long_max_tokens=long_max_tokens,
            short_max_tokens=short_max_tokens,
        )
    metrics = evaluate_output(call["output"], api_messages, target_mode)
    return {
        "case_id": case_id,
        "scenario": scenario,
        "scenario_label": scenario_label,
        "strategy": strategy,
        "target_mode": target_mode,
        "target_model": target_model,
        "payload_path": str(payload_path),
        "payload_messages": len(api_messages),
        "raw_bridge_markers": payload_has_raw_bridge_markers(api_messages),
        **meta,
        **{k: v for k, v in call.items() if k != "output"},
        "metrics": metrics,
        "output": call["output"],
    }


def scenario_current_user(scenario: str, target_mode: str, short_sample: Any, long_sample: Any) -> dict[str, str]:
    sample = short_sample if target_mode == "short" else long_sample
    return last_user(sample.messages)


def run_standard_scenarios(
    *,
    adapter: ModelAdapter,
    args: argparse.Namespace,
    short_sample: Any,
    long_sample: Any,
    points_template: str,
    output_dir: Path,
) -> list[dict[str, Any]]:
    short_hist = dialogue_history(short_sample)
    long_hist = dialogue_history(long_sample)
    aux_dir = output_dir / "auxiliary"
    results: list[dict[str, Any]] = []

    for scenario in args.scenarios:
        if scenario == "S11":
            continue
        spec = SCENARIOS[scenario]
        for target_mode in spec.target_modes:
            for strategy in args.strategies:
                if not spec.is_switch and strategy != "points_ready":
                    continue
                source, extra_same_mode_history = scenario_source(
                    scenario,
                    target_mode,
                    short_hist,
                    long_hist,
                )
                points = ""
                points_meta: dict[str, Any] = {
                    "points_attempted": False,
                    "points_success": False,
                    "points_error": "",
                    "points_latency": 0.0,
                    "points_quality": {"pass": True, "issues": []},
                    "points_postprocesses": [],
                    "points_latency_exceeded": False,
                    "points_source_messages": 0,
                    "points_source_turns": 0,
                    "points_input_excludes_old_summary": True,
                }
                if spec.is_switch and strategy == "points_ready":
                    current_user = scenario_current_user(scenario, target_mode, short_sample, long_sample)
                    points_case_id = f"{scenario}_{target_mode}_{strategy}"
                    points, points_meta = call_interaction_points(
                        adapter=adapter,
                        template=points_template,
                        source_messages=source,
                        current_user=current_user,
                        aux_dir=aux_dir,
                        case_id=points_case_id,
                        dry_run=args.dry_run,
                        force_fallback=args.force_fallback,
                        latency_threshold=args.latency_threshold,
                    )
                    if args.force_fallback:
                        strategy = "fallback_sandwich"
                if spec.is_switch:
                    messages, payload_meta = switch_payload(
                        strategy=strategy,
                        scenario=scenario,
                        target_mode=target_mode,
                        short_sample=short_sample,
                        long_sample=long_sample,
                        short_hist=short_hist,
                        long_hist=long_hist,
                        points=points,
                        fallback_turns=args.fallback_turns,
                        extra_same_mode_history=extra_same_mode_history,
                    )
                    base_meta = {**points_meta, **payload_meta}
                else:
                    messages = same_mode_payload(
                        scenario,
                        target_mode,
                        short_sample,
                        long_sample,
                        short_hist,
                        long_hist,
                    )
                    base_meta = {
                        **points_meta,
                        "strategy": "same_mode_baseline",
                        "fallback_turns": 0,
                        "fallback_bridge_messages": 0,
                    }
                for target_model in target_models_for_mode(target_mode, list(args.short_models)):
                    case_id = f"{scenario}_{strategy}_{safe_model_label(target_model)}"
                    print(f"[RUN] {case_id} target={target_mode}/{target_model} payload={len(messages)}")
                    record = run_single_case(
                        adapter=adapter,
                        case_id=case_id,
                        scenario=scenario,
                        scenario_label=spec.label,
                        strategy=strategy if spec.is_switch else "same_mode_baseline",
                        target_mode=target_mode,
                        target_model=target_model,
                        messages=messages,
                        meta=base_meta,
                        output_dir=output_dir,
                        dry_run=args.dry_run,
                        long_max_tokens=args.long_max_tokens,
                        short_max_tokens=args.short_max_tokens,
                    )
                    results.append(record)
                    issues = record["metrics"].get("format_issues") or []
                    print(
                        f"[OK] {case_id} success={record['success']} "
                        f"chars={record['metrics']['cjk_chars']} issues={len(issues)} "
                        f"points={record.get('points_quality', {}).get('pass')}"
                    )
    return results


def run_s11(
    *,
    adapter: ModelAdapter,
    args: argparse.Namespace,
    short_sample: Any,
    long_sample: Any,
    points_template: str,
    output_dir: Path,
) -> list[dict[str, Any]]:
    if "S11" not in args.scenarios:
        return []
    short_hist = dialogue_history(short_sample)
    long_hist = dialogue_history(long_sample)
    aux_dir = output_dir / "auxiliary"
    results: list[dict[str, Any]] = []
    spec = SCENARIOS["S11"]

    for short_model in args.short_models:
        ledger = [dict(m) for m in select_turns(short_hist, 5)]
        for msg in ledger:
            msg["source_mode"] = "short"
        previous_context = ""
        for step, target_mode in enumerate(args.s11_sequence, start=1):
            target_model = LONG_TARGET_MODEL if target_mode == "long" else short_model
            sample = long_sample if target_mode == "long" else short_sample
            current_user = last_user(sample.messages)
            source = select_turns(ledger, 10)
            points = ""
            strategy = "points_ready"
            points_meta: dict[str, Any]
            if "points_ready" in args.strategies and not args.force_fallback:
                points, points_meta = call_interaction_points(
                    adapter=adapter,
                    template=points_template,
                    source_messages=source,
                    current_user=current_user,
                    aux_dir=aux_dir,
                    case_id=f"S11_step{step}_{safe_model_label(short_model)}_{target_mode}",
                    dry_run=args.dry_run,
                    force_fallback=False,
                    latency_threshold=args.latency_threshold,
                )
            else:
                strategy = "fallback_sandwich"
                points, points_meta = call_interaction_points(
                    adapter=adapter,
                    template=points_template,
                    source_messages=source,
                    current_user=current_user,
                    aux_dir=aux_dir,
                    case_id=f"S11_step{step}_{safe_model_label(short_model)}_{target_mode}",
                    dry_run=args.dry_run,
                    force_fallback=True,
                    latency_threshold=args.latency_threshold,
                )
            if args.force_fallback:
                strategy = "fallback_sandwich"
            messages, payload_meta = switch_payload(
                strategy=strategy,
                scenario="S11",
                target_mode=target_mode,
                short_sample=short_sample,
                long_sample=long_sample,
                short_hist=short_hist,
                long_hist=long_hist,
                points=points,
                fallback_turns=args.fallback_turns,
                extra_same_mode_history=[],
            )
            # S11 uses the live ledger as source; replace the generic source-derived bridge.
            if strategy == "fallback_sandwich":
                bridged, bridge_meta = bridge_history(source, target_mode, args.fallback_turns)
                messages = [
                    first_system(sample.messages),
                    context_block(target_mode=target_mode, label=f"S11_step{step}_fallback"),
                    *bridged,
                    current_user,
                ]
                payload_meta = {**payload_meta, **bridge_meta, "fallback_bridge_messages": len(bridged)}
            else:
                messages = [
                    first_system(sample.messages),
                    context_block(target_mode=target_mode, points=points, label=f"S11_step{step}"),
                    current_user,
                ]

            context_text = "\n".join(m.get("content", "") for m in messages)
            ledger_text = "\n".join(m.get("content", "") for m in ledger)
            lifecycle_meta = {
                **points_meta,
                **payload_meta,
                "short_model_under_test": short_model,
                "s11_step": step,
                "ledger_messages_before": len(ledger),
                "ledger_turns_before": len(ledger) // 2,
                "context_marker_in_ledger": "最近互动要点（桥接迁移）" in ledger_text
                or "模式切换互动要点" in ledger_text
                or any(marker in ledger_text for marker in RAW_BRIDGE_MARKERS),
                "previous_context_reused": bool(previous_context and previous_context in context_text),
            }
            case_id = f"S11_{safe_model_label(short_model)}_step{step}_{strategy}_{safe_model_label(target_model)}"
            print(f"[RUN] {case_id} target={target_mode}/{target_model} payload={len(messages)}")
            record = run_single_case(
                adapter=adapter,
                case_id=case_id,
                scenario="S11",
                scenario_label=spec.label,
                strategy=strategy,
                target_mode=target_mode,
                target_model=target_model,
                messages=messages,
                meta=lifecycle_meta,
                output_dir=output_dir,
                dry_run=args.dry_run,
                long_max_tokens=args.long_max_tokens,
                short_max_tokens=args.short_max_tokens,
            )
            results.append(record)
            issues = record["metrics"].get("format_issues") or []
            print(
                f"[OK] {case_id} success={record['success']} chars={record['metrics']['cjk_chars']} "
                f"issues={len(issues)} context_in_ledger={record['context_marker_in_ledger']}"
            )
            previous_context = messages[1].get("content", "") if len(messages) > 1 else ""
            ledger.append({"role": "user", "content": current_user["content"], "source_mode": target_mode})
            ledger.append({"role": "assistant", "content": record["output"], "source_mode": target_mode})
            sample_hist = long_hist if target_mode == "long" else short_hist
            for msg in select_turns(sample_hist, 1):
                copied = dict(msg)
                copied["source_mode"] = target_mode
                ledger.append(copied)
            ledger = ledger[-24:]
    return results


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    api_success = sum(1 for r in results if r.get("success"))
    target_pass = sum(
        1
        for r in results
        if r.get("success") and not r.get("metrics", {}).get("format_issues")
    )
    points_rows = [r for r in results if r.get("points_attempted")]
    points_success = sum(1 for r in points_rows if r.get("points_success"))
    points_quality = sum(1 for r in points_rows if r.get("points_quality", {}).get("pass"))
    points_latency_exceeded = sum(1 for r in points_rows if r.get("points_latency_exceeded"))
    latencies = [r.get("points_latency", 0.0) for r in points_rows if r.get("points_success")]
    return {
        "total": total,
        "api_success": api_success,
        "target_pass": target_pass,
        "points_cases": len(points_rows),
        "points_success": points_success,
        "points_quality": points_quality,
        "points_latency_exceeded": points_latency_exceeded,
        "avg_points_latency": round(statistics.mean(latencies), 3) if latencies else 0.0,
        "p95_points_latency": round(
            statistics.quantiles(latencies, n=100, method="inclusive")[94], 3
        )
        if len(latencies) > 1
        else (latencies[0] if latencies else 0.0),
    }


def write_summary(results: list[dict[str, Any]], path: Path, args: argparse.Namespace) -> None:
    agg = summarize(results)
    lines = [
        "# 原格式互动要点 + 三明治兜底 S1-S14 全量验证报告",
        "",
        f"- 生成时间: {datetime.now().isoformat(timespec='seconds')}",
        "- 输入来源: 问题排查目录中的真实 payload 日志",
        f"- 互动要点模型: {EXTRACTOR_MODEL}",
        f"- 短文目标模型: {', '.join(args.short_models)}",
        f"- 长文目标模型: {LONG_TARGET_MODEL}",
        f"- 策略: {', '.join(args.strategies)}",
        f"- fallback_turns: {args.fallback_turns}",
        f"- dry_run: {args.dry_run}",
        "",
        "## 聚合结果",
        "",
        f"- 目标模型调用成功: {agg['api_success']}/{agg['total']}",
        f"- 目标格式通过: {agg['target_pass']}/{agg['total']}",
        f"- 互动要点 API 成功: {agg['points_success']}/{agg['points_cases']}",
        f"- 互动要点质量通过: {agg['points_quality']}/{agg['points_cases']}",
        f"- 互动要点延迟超过阈值: {agg['points_latency_exceeded']}/{agg['points_cases']} (阈值 {args.latency_threshold}s)",
        f"- 互动要点平均延迟: {agg['avg_points_latency']}s",
        f"- 互动要点 p95 延迟: {agg['p95_points_latency']}s",
        "",
        "## 逐场景结果",
        "",
        "| 场景 | 策略 | 目标模型 | payload | 互动要点 | 点数/字数 | 点延迟 | 兜底轮数 | 成功 | 输出字数 | 格式问题 | recent-ngram | 生命周期问题 |",
        "|:--|:--|:--|--:|:--:|:--|--:|--:|:--:|--:|:--|--:|:--|",
    ]
    for r in results:
        issues = "；".join(r.get("metrics", {}).get("format_issues") or []) or "无"
        q = r.get("points_quality", {}) or {}
        point_cell = "-"
        if r.get("points_attempted"):
            point_cell = "Y" if r.get("points_success") else "N"
        lifecycle: list[str] = []
        if r.get("context_marker_in_ledger"):
            lifecycle.append("context入ledger")
        if r.get("previous_context_reused"):
            lifecycle.append("复用旧context")
        if r.get("points_input_excludes_old_summary") is False:
            lifecycle.append("points输入含旧摘要")
        lines.append(
            "| {scenario} {label} | {strategy} | {target_mode}/{target_model} | {payload} | {point_cell} | {points} | {latency} | {fallback} | {success} | {chars} | {issues} | {ngram} | {life} |".format(
                scenario=r["scenario"],
                label=r.get("scenario_label", ""),
                strategy=r["strategy"],
                target_mode=r["target_mode"],
                target_model=r["target_model"],
                payload=r["payload_messages"],
                point_cell=point_cell,
                points=f"{q.get('points_count', '-')}/{q.get('points_cjk_chars', '-')}",
                latency=r.get("points_latency", 0.0),
                fallback=r.get("fallback_turns", 0),
                success="Y" if r.get("success") else "N",
                chars=r.get("metrics", {}).get("cjk_chars", 0),
                issues=issues,
                ngram=r.get("metrics", {}).get("ngram_max_recent_pct", 0),
                life="；".join(lifecycle) or "无",
            )
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate original interaction points + sandwich fallback S1-S14")
    parser.add_argument("--short-log", default=str(SHORT_LOG_DEFAULT))
    parser.add_argument("--long-log", default=str(LONG_LOG_DEFAULT))
    parser.add_argument("--points-prompt", default=str(POINTS_PROMPT_DEFAULT))
    parser.add_argument("--scenarios", nargs="*", default=list(SCENARIO_ORDER))
    parser.add_argument("--strategies", nargs="*", default=["points_ready"], choices=["points_ready", "fallback_sandwich"])
    parser.add_argument("--short-models", nargs="*", default=list(SHORT_TARGET_MODELS))
    parser.add_argument("--s11-sequence", nargs="*", default=list(DEFAULT_S11_SEQUENCE))
    parser.add_argument("--fallback-turns", type=int, default=1)
    parser.add_argument("--force-fallback", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--latency-threshold", type=float, default=5.0)
    parser.add_argument("--long-max-tokens", type=int, default=8192)
    parser.add_argument("--short-max-tokens", type=int, default=2048)
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args()
    unknown = sorted(set(args.scenarios) - set(SCENARIO_ORDER))
    if unknown:
        raise ValueError(f"unknown scenarios: {unknown}")
    unknown_short = sorted(set(args.short_models) - set(SHORT_TARGET_MODELS))
    if unknown_short:
        raise ValueError(f"unknown short models: {unknown_short}")
    unknown_modes = sorted(set(args.s11_sequence) - {"short", "long"})
    if unknown_modes:
        raise ValueError(f"unknown s11 target modes: {unknown_modes}")
    if args.fallback_turns < 1:
        raise ValueError("--fallback-turns must be >= 1")
    if args.force_fallback and "fallback_sandwich" not in args.strategies:
        args.strategies = ["fallback_sandwich"]
    return args


def main() -> None:
    args = parse_args()
    env_status = ensure_runtime_key_aliases()
    short_sample = load_log_sample(Path(args.short_log), mode="short")
    long_sample = load_log_sample(Path(args.long_log), mode="long")
    points_template = Path(args.points_prompt).read_text(encoding="utf-8", errors="ignore")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_dir) if args.output_dir else PROJECT_ROOT / "output" / "mode_switching_switch_state" / f"points_sandwich_full_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.jsonl"
    summary_path = out_dir / "summary.md"
    if results_path.exists():
        results_path.unlink()

    adapter = ModelAdapter()
    print(f"[INFO] env_status={env_status}")
    print(f"[INFO] short_log={short_sample.path} messages={len(short_sample.messages)}")
    print(f"[INFO] long_log={long_sample.path} messages={len(long_sample.messages)}")
    print(f"[INFO] points_prompt={args.points_prompt}")
    print(f"[INFO] output={out_dir}")
    print(f"[INFO] scenarios={','.join(args.scenarios)} strategies={','.join(args.strategies)}")

    results: list[dict[str, Any]] = []
    standard = run_standard_scenarios(
        adapter=adapter,
        args=args,
        short_sample=short_sample,
        long_sample=long_sample,
        points_template=points_template,
        output_dir=out_dir,
    )
    for record in standard:
        append_jsonl(results_path, record)
        results.append(record)
        write_summary(results, summary_path, args)

    s11 = run_s11(
        adapter=adapter,
        args=args,
        short_sample=short_sample,
        long_sample=long_sample,
        points_template=points_template,
        output_dir=out_dir,
    )
    for record in s11:
        append_jsonl(results_path, record)
        results.append(record)
        write_summary(results, summary_path, args)

    write_summary(results, summary_path, args)
    agg = summarize(results)
    print(
        "[SUMMARY] "
        f"target_success={agg['api_success']}/{agg['total']} "
        f"target_format_pass={agg['target_pass']}/{agg['total']} "
        f"points_success={agg['points_success']}/{agg['points_cases']} "
        f"points_quality={agg['points_quality']}/{agg['points_cases']} "
        f"avg_points_latency={agg['avg_points_latency']}s "
        f"summary={summary_path}"
    )


if __name__ == "__main__":
    main()
