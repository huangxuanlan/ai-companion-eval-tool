#!/usr/bin/env python3
"""
Replay real production-like issue logs for long/short mode switching checks.

This script intentionally avoids synthetic character configs and synthetic user
turns. It reads payloads captured in the issue-log Markdown files, extracts the
real system prompt/history/current user input, then builds minimal A/B payloads:

- baseline: bridge last 20 turns
- optimized: bridge last 10 turns

Each scenario is one model call, saved immediately after completion so a timeout
does not lose prior results.
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
from json import JSONDecoder
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "server"))

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / "server" / ".env")
except ImportError:
    pass

if not os.environ.get("DOUBAO_API_KEY") and os.environ.get("VOLCENGINE_API_KEY"):
    os.environ["DOUBAO_API_KEY"] = os.environ["VOLCENGINE_API_KEY"]

from services.model_adapter import ModelAdapter


SHORT_LOG_DEFAULT = Path(
    r"E:\工作资料\产品资料\提示词资料\问题排查——短文\排查是否有问题.md"
)
LONG_LOG_DEFAULT = Path(
    r"E:\工作资料\产品资料\提示词资料\问题排查——长文\测试日志-截断问题0509 更新.md"
)

AB_CONFIGS = {
    "baseline": {"label": "baseline_20t", "bridge_turns": 20},
    "optimized": {"label": "optimized_10t", "bridge_turns": 10},
}

SHORT_START = "以下为短文模式回复记录，仅供剧情事实参考，不要模仿其字数、括号动作、语气格式"
SHORT_END = "短文模式记录结束，请继续以长文模式格式回复"
LONG_START = "以下为长文模式回复记录，仅供剧情事实参考，不要模仿其第三人称旁白、长段落、加粗对白格式"
LONG_END = "长文模式记录结束，请继续以短文对话格式回复"
TEMPLATE_LEAK_PATTERNS = (
    "以下为",
    "记录结束",
    "动态摘要",
    "摘要结束",
    "内部认知记录",
    "Core_Constraints",
    "System Prompt",
    "<user_input>",
)
EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U00002600-\U000026FF]"
)


@dataclass
class LogSample:
    path: Path
    raw: dict[str, Any]
    messages: list[dict[str, str]]
    mode: str
    model_hint: str
    prompt_kind: str


def read_json_payload(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            return JSONDecoder(strict=False).decode(text)
        except json.JSONDecodeError:
            pass
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            chunk = text[start : end + 1]
            try:
                return json.loads(chunk)
            except json.JSONDecodeError:
                return JSONDecoder(strict=False).decode(chunk)
        raise


def normalize_message(msg: dict[str, Any]) -> dict[str, str] | None:
    role = str(msg.get("role", "")).strip()
    content = msg.get("content", "")
    if role not in {"system", "user", "assistant"}:
        return None
    if content is None:
        content = ""
    return {"role": role, "content": str(content)}


def load_log_sample(path: Path, mode: str) -> LogSample:
    raw = read_json_payload(path)
    prompt_kind = "unknown"
    messages: list[dict[str, str]] = []

    if isinstance(raw.get("messages"), list):
        prompt_kind = "messages"
        messages = [m for item in raw["messages"] if (m := normalize_message(item))]
    elif isinstance(raw.get("prompt"), str):
        prompt_kind = "prompt"
        try:
            parsed = json.loads(raw["prompt"])
        except json.JSONDecodeError:
            parsed = JSONDecoder(strict=False).decode(raw["prompt"])
        messages = [m for item in parsed if (m := normalize_message(item))]
    else:
        dify_req = raw.get("difyChatRequest") or {}
        if isinstance(dify_req.get("additional_messages"), list):
            prompt_kind = "dify.additional_messages"
            messages = [
                m for item in dify_req["additional_messages"] if (m := normalize_message(item))
            ]

    if not messages:
        raise ValueError(f"未能从日志解析 messages: {path}")

    params = raw.get("parameters") or {}
    model_hint = (
        raw.get("model")
        or raw.get("model_id")
        or raw.get("modelId")
        or raw.get("lastModelId")
        or params.get("model")
        or ""
    )
    return LogSample(
        path=path,
        raw=raw,
        messages=messages,
        mode=mode,
        model_hint=str(model_hint),
        prompt_kind=prompt_kind,
    )


def first_system(messages: list[dict[str, str]]) -> dict[str, str]:
    for msg in messages:
        if msg["role"] == "system":
            return {"role": "system", "content": msg["content"]}
    return {"role": "system", "content": ""}


def last_user(messages: list[dict[str, str]]) -> dict[str, str]:
    for msg in reversed(messages):
        if msg["role"] == "user":
            return {"role": "user", "content": msg["content"]}
    raise ValueError("日志中没有 user 消息，无法构造当前输入")


def dialogue_history(sample: LogSample) -> list[dict[str, str]]:
    """Return user/assistant messages only, excluding initial system and trailing user."""
    history: list[dict[str, str]] = []
    for i, msg in enumerate(sample.messages):
        if i == 0 and msg["role"] == "system":
            continue
        if msg["role"] in {"user", "assistant"}:
            item = dict(msg)
            item["source_mode"] = sample.mode
            history.append(item)
    while history and history[-1]["role"] == "user":
        history.pop()
    return history


def cjk_len(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text or ""))


def paren_pairs(text: str) -> int:
    return min(text.count("（"), text.count("）"))


def ngram_overlap(a: str, b: str, n: int = 4) -> float:
    if not a or not b or len(b) < n:
        return 0.0
    a_grams = {a[i : i + n] for i in range(len(a) - n + 1)}
    b_grams = {b[i : i + n] for i in range(len(b) - n + 1)}
    if not b_grams:
        return 0.0
    return len(a_grams & b_grams) / len(b_grams)


def recent_assistant_texts(messages: list[dict[str, str]], limit: int = 5) -> list[str]:
    items = [m["content"] for m in messages if m.get("role") == "assistant"]
    return items[-limit:]


def detect_format_issues(text: str, target_mode: str) -> list[str]:
    issues: list[str] = []
    chars = cjk_len(text)
    if target_mode == "long":
        if chars < 300:
            issues.append(f"长文字数不足({chars})")
        if chars > 500:
            issues.append(f"长文字数超标({chars})")
        if paren_pairs(text) < 3:
            issues.append(f"圆括号不足({paren_pairs(text)}对)")
        if EMOJI_RE.search(text):
            issues.append("含Emoji")
        for pattern in TEMPLATE_LEAK_PATTERNS:
            if pattern in text:
                issues.append(f"模板泄漏({pattern})")
                break
    else:
        if chars < 20:
            issues.append(f"短文字数过少({chars})")
        if chars > 120:
            issues.append(f"短文字数过多({chars})")
        if "**" in text:
            issues.append("含加粗标记")
        if paren_pairs(text) >= 3 and chars > 80:
            issues.append("疑似长文旁白污染")
        if "第三人称" in text or LONG_START in text or LONG_END in text:
            issues.append("长文模板泄漏")
    return issues


def bridge_history(
    source_history: list[dict[str, str]],
    target_mode: str,
    bridge_turns: int,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    dialogue = [m for m in source_history if m["role"] in {"user", "assistant"}]
    recent = dialogue[-bridge_turns * 2 :]
    bridged: list[dict[str, str]] = []
    wrapped = 0
    source_counts: dict[str, int] = {}

    for msg in recent:
        source_mode = msg.get("source_mode", "")
        source_counts[source_mode or "unknown"] = source_counts.get(source_mode or "unknown", 0) + 1
        if msg["role"] == "assistant" and source_mode and source_mode != target_mode:
            if source_mode == "short":
                bridged.append({"role": "system", "content": SHORT_START})
                bridged.append({"role": "assistant", "content": msg["content"]})
                bridged.append({"role": "system", "content": SHORT_END})
                wrapped += 1
            elif source_mode == "long":
                bridged.append({"role": "system", "content": LONG_START})
                bridged.append({"role": "assistant", "content": msg["content"]})
                bridged.append({"role": "system", "content": LONG_END})
                wrapped += 1
            else:
                bridged.append({"role": msg["role"], "content": msg["content"]})
        else:
            bridged.append({"role": msg["role"], "content": msg["content"]})

    meta = {
        "bridge_turns_requested": bridge_turns,
        "bridge_dialogue_messages": len(recent),
        "bridge_effective_turns": len(recent) // 2,
        "bridge_payload_messages": len(bridged),
        "available_dialogue_messages": len(dialogue),
        "available_turns": len(dialogue) // 2,
        "hetero_assistant_wrapped": wrapped,
        "source_counts": source_counts,
    }
    return bridged, meta


def build_case_payload(
    scenario: str,
    short_sample: LogSample,
    long_sample: LogSample,
    bridge_turns: int,
) -> tuple[str, str, list[dict[str, str]], dict[str, Any]]:
    short_hist = dialogue_history(short_sample)
    long_hist = dialogue_history(long_sample)

    if scenario == "S5":
        target_mode = "long"
        current_user = last_user(long_sample.messages)
        history = short_hist
        system = first_system(long_sample.messages)
    elif scenario == "S6":
        target_mode = "short"
        current_user = last_user(short_sample.messages)
        history = long_hist
        system = first_system(short_sample.messages)
    elif scenario == "S8":
        target_mode = "short"
        current_user = last_user(short_sample.messages)
        # Short -> Long -> Short: preserve chronological mixed history from logs.
        history = short_hist + long_hist
        system = first_system(short_sample.messages)
    elif scenario == "S14":
        target_mode = "long"
        current_user = last_user(long_sample.messages)
        # Short -> Long, summary delayed: mixed recent window can cross into short history.
        history = short_hist + long_hist
        system = first_system(long_sample.messages)
    else:
        raise ValueError(f"未知场景: {scenario}")

    bridged, bridge_meta = bridge_history(history, target_mode, bridge_turns)
    messages = [system] + bridged + [current_user]
    target_model = "deepseek-v4-pro" if target_mode == "long" else "doubao-lite"
    meta = {
        "scenario": scenario,
        "target_mode": target_mode,
        "target_model": target_model,
        "short_log": str(short_sample.path),
        "long_log": str(long_sample.path),
        "short_model_hint": short_sample.model_hint,
        "long_model_hint": long_sample.model_hint,
        "current_user_preview": current_user["content"][:160],
        **bridge_meta,
    }
    return target_mode, target_model, messages, meta


def call_model(
    adapter: ModelAdapter,
    model_id: str,
    messages: list[dict[str, str]],
    target_mode: str,
    long_max_tokens: int,
    short_max_tokens: int,
) -> dict[str, Any]:
    max_tokens = long_max_tokens if target_mode == "long" else short_max_tokens
    thinking = "high" if target_mode == "long" else "disabled"
    started = time.perf_counter()
    result = adapter.chat(
        model_id=model_id,
        messages=messages,
        max_tokens=max_tokens,
        thinking_effort=thinking,
    )
    latency = round(time.perf_counter() - started, 3)
    return {
        "success": result.success,
        "error": result.error,
        "output": result.content or "",
        "latency": latency,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    }


def evaluate_output(output: str, messages: list[dict[str, str]], target_mode: str) -> dict[str, Any]:
    assistants = recent_assistant_texts(messages, limit=8)
    last_assistant = assistants[-1] if assistants else ""
    overlaps = [ngram_overlap(prev, output) for prev in assistants]
    return {
        "chars": len(output),
        "cjk_chars": cjk_len(output),
        "paren_pairs": paren_pairs(output),
        "format_issues": detect_format_issues(output, target_mode),
        "ngram_last_pct": round(ngram_overlap(last_assistant, output) * 100, 2),
        "ngram_max_recent_pct": round((max(overlaps) if overlaps else 0.0) * 100, 2),
        "output_preview": output[:500],
    }


def append_jsonl(path: Path, item: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def write_markdown_summary(results: list[dict[str, Any]], path: Path) -> None:
    lines = [
        "# 现网日志复放验证报告",
        "",
        f"- 生成时间: {datetime.now().isoformat()}",
        "- 输入来源: 问题排查目录中的真实 payload 日志",
        "- 对比变量: bridge 20 turns vs 10 turns",
        "",
        "| 场景 | 配置 | 目标 | 桥接轮数 | payload消息 | 包夹assistant | 成功 | 字数 | 格式问题 | last-ngram | recent-max-ngram |",
        "|:--|:--|:--|--:|--:|--:|:--:|--:|:--|--:|--:|",
    ]
    for r in results:
        issues = "；".join(r["metrics"].get("format_issues") or []) or "无"
        lines.append(
            "| {scenario} | {ab} | {target_mode}/{target_model} | {bridge_effective_turns} | "
            "{payload_messages} | {hetero_assistant_wrapped} | {success} | {cjk_chars} | "
            "{issues} | {ngram_last_pct} | {ngram_max_recent_pct} |".format(
                scenario=r["scenario"],
                ab=r["ab"],
                target_mode=r["target_mode"],
                target_model=r["target_model"],
                bridge_effective_turns=r["bridge_effective_turns"],
                payload_messages=r["payload_messages"],
                hetero_assistant_wrapped=r["hetero_assistant_wrapped"],
                success="Y" if r["success"] else "N",
                cjk_chars=r["metrics"].get("cjk_chars", 0),
                issues=issues,
                ngram_last_pct=r["metrics"].get("ngram_last_pct", 0),
                ngram_max_recent_pct=r["metrics"].get("ngram_max_recent_pct", 0),
            )
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay production issue logs for mode-switching validation")
    parser.add_argument("--short-log", default=str(SHORT_LOG_DEFAULT))
    parser.add_argument("--long-log", default=str(LONG_LOG_DEFAULT))
    parser.add_argument("--scenarios", nargs="*", default=["S5", "S6", "S8", "S14"])
    parser.add_argument("--ab", nargs="*", default=["baseline", "optimized"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--long-max-tokens", type=int, default=16384)
    parser.add_argument("--short-max-tokens", type=int, default=4096)
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args()

    short_sample = load_log_sample(Path(args.short_log), mode="short")
    long_sample = load_log_sample(Path(args.long_log), mode="long")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_dir) if args.output_dir else PROJECT_ROOT / "output" / "mode_switching_log_replay" / ts
    payload_dir = out_dir / "payloads"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload_dir.mkdir(parents=True, exist_ok=True)

    results_path = out_dir / "results.jsonl"
    summary_path = out_dir / "summary.md"
    adapter = ModelAdapter()
    results: list[dict[str, Any]] = []

    print(f"[INFO] short_log={short_sample.path} kind={short_sample.prompt_kind} messages={len(short_sample.messages)}")
    print(f"[INFO] long_log={long_sample.path} kind={long_sample.prompt_kind} messages={len(long_sample.messages)}")
    print(f"[INFO] output={out_dir}")

    for scenario in args.scenarios:
        for ab_name in args.ab:
            if ab_name not in AB_CONFIGS:
                raise ValueError(f"未知 AB 配置: {ab_name}")
            ab_cfg = AB_CONFIGS[ab_name]
            target_mode, target_model, messages, meta = build_case_payload(
                scenario=scenario,
                short_sample=short_sample,
                long_sample=long_sample,
                bridge_turns=ab_cfg["bridge_turns"],
            )
            case_id = f"{scenario}_{ab_cfg['label']}"
            payload_path = payload_dir / f"{case_id}.json"
            payload_path.write_text(
                json.dumps({"meta": meta, "messages": messages}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            print(
                f"[RUN] {case_id} target={target_mode}/{target_model} "
                f"bridge={meta['bridge_effective_turns']} payload_msgs={len(messages)}"
            )
            if args.dry_run:
                call = {
                    "success": True,
                    "error": "",
                    "output": "（dry-run 占位旁白。）（用于验证 payload 解析和桥接结构。）（不会调用模型。）先确认结构，再跑真实调用。",
                    "latency": 0.0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                }
            else:
                call = call_model(
                    adapter=adapter,
                    model_id=target_model,
                    messages=messages,
                    target_mode=target_mode,
                    long_max_tokens=args.long_max_tokens,
                    short_max_tokens=args.short_max_tokens,
                )
            metrics = evaluate_output(call["output"], messages, target_mode)
            record = {
                "case_id": case_id,
                "ab": ab_name,
                "ab_label": ab_cfg["label"],
                "payload_path": str(payload_path),
                "payload_messages": len(messages),
                **meta,
                **{k: v for k, v in call.items() if k != "output"},
                "metrics": metrics,
                "output": call["output"],
            }
            append_jsonl(results_path, record)
            results.append(record)
            write_markdown_summary(results, summary_path)
            print(
                f"[OK] {case_id} success={record['success']} chars={metrics['cjk_chars']} "
                f"issues={len(metrics['format_issues'])} max_ngram={metrics['ngram_max_recent_pct']}"
            )

    print(f"[DONE] results={results_path}")
    print(f"[DONE] summary={summary_path}")


if __name__ == "__main__":
    main()
