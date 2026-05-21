#!/usr/bin/env python3
"""Validate interaction-points bridge extraction for long->short switching.

Scope:
- Build a 19-turn longform transcript from the production issue log.
- Call doubao2.0-mini several times to generate a compact interaction points.
- Measure latency, original-format stability, points quality heuristics, and optional
  shortform first-turn format after injecting the points.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
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
    cjk_len,
    detect_format_issues,
    dialogue_history,
    first_system,
    last_user,
    load_log_sample,
    ngram_overlap,
)
from verify_mode_switching_short_model_matrix import SHORT_TARGET_MODELS, call_model, safe_model_label
from verify_v52_summary_points_replay import POINTS_PROMPT_DEFAULT, transcript_from_messages
from verify_interaction_points_sandwich_fallback_full_matrix import (
    normalize_points_text,
    strip_code_fence,
    validate_original_points,
    wrap_points_context,
)


DEFAULT_EXTRACTOR_MODEL = "doubao-mini"
WHITESPACE_RE = re.compile(r"\s+")


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
        return value[: max(0, limit - 1)].rstrip() + "…"
    return value


def select_19_turns(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    dialogue = [m for m in messages if m.get("role") in {"user", "assistant"}]
    return dialogue[-38:] if len(dialogue) >= 38 else dialogue


def transcript(messages: list[dict[str, str]]) -> str:
    lines: list[str] = []
    turn = 0
    for msg in messages:
        if msg.get("role") == "user":
            turn += 1
        role = "用户" if msg.get("role") == "user" else "角色"
        content = compact(msg.get("content", ""), 1400)
        lines.append(f"[第{turn}轮][{role}]\n{content}")
    return "\n\n".join(lines)


def build_prompt(long_turns: list[dict[str, str]]) -> list[dict[str, str]]:
    template = POINTS_PROMPT_DEFAULT.read_text(encoding="utf-8", errors="ignore")
    conversation_text = transcript_from_messages(long_turns)
    prompt = template.replace("{conversation_text}", conversation_text)
    prompt += (
        "\n\n【验证强制补充】\n"
        "直接输出原 output_format 中的纯文本格式；互动要点最多 5 条，超过 5 条视为失败；"
        "每条互动要点必须包含单个 [MM-DD HH:mm]；禁止输出 [MM-DD HH:mm-HH:mm] 这类时间范围；"
        "不要输出示例、解释、JSON 或代码块。"
    )
    return [{"role": "user", "content": prompt}]


def fallback_bridge(long_turns: list[dict[str, str]]) -> str:
    last_user = ""
    for msg in reversed(long_turns):
        if msg.get("role") == "user" and compact(msg.get("content", "")):
            last_user = compact(msg.get("content", ""), 120)
            break
    lines = [
        "（以下为长切短兜底上下文，仅供事实参考，不是回复格式示例；当前用户输入优先。）",
    ]
    if last_user:
        lines.append(f"【最近用户意图】用户最后说：{last_user}")
    lines.append("【短文接话提示】短文模式：用自然短句回复，可有少量短动作括号；不要输出长段旁白、第三人称叙事或分段长文。")
    lines.append("=== 兜底上下文结束 ===")
    lines.append("（内部认知记录结束。以下对话才是真实聊天。）")
    return "\n".join(lines)


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[int(pct) - 1]


def append_jsonl(path: Path, item: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def write_points_report(
    rows: list[dict[str, Any]],
    path: Path,
    threshold_s: float,
    extractor_model: str,
) -> None:
    extraction = [r for r in rows if r["type"] == "mini_interaction_points"]
    target = [r for r in rows if r["type"] == "short_target_generation"]
    latencies = [r["latency_s"] for r in extraction if r.get("api_success")]
    lines = [
        "# 19轮长文互动要点抽取验证报告",
        "",
        f"- 生成时间: {datetime.now().isoformat(timespec='seconds')}",
        f"- 抽取模型: {extractor_model}",
        f"- 输入: 真实长文日志尾部 19 轮",
        f"- 延迟阈值: {threshold_s}s",
        "",
        "## 聚合结果",
        "",
        f"- API 成功: {sum(1 for r in extraction if r.get('api_success'))}/{len(extraction)}",
        f"- 原格式成功: {sum(1 for r in extraction if r.get('format_ok'))}/{len(extraction)}",
        f"- 质量通过: {sum(1 for r in extraction if r.get('quality', {}).get('pass'))}/{len(extraction)}",
        f"- 平均延迟: {round(statistics.mean(latencies), 3) if latencies else 0}s",
        f"- p50 延迟: {round(statistics.median(latencies), 3) if latencies else 0}s",
        f"- p95 延迟: {round(percentile(latencies, 95), 3) if latencies else 0}s",
        f"- 短文首轮格式通过: {sum(1 for r in target if r.get('api_success') and not r.get('format_issues'))}/{len(target)}",
        "",
        "## 互动要点明细",
        "",
        "| run | API | 原格式 | 延迟(s) | 字数 | raw重叠 | 质量问题 |",
        "|--:|:--:|:--:|--:|--:|--:|:--|",
    ]
    for row in extraction:
        quality = row.get("quality", {})
        lines.append(
            "| {run} | {api} | {format_ok} | {latency} | {chars} | {overlap} | {issues} |".format(
                run=row["run"],
                api="Y" if row.get("api_success") else "N",
                format_ok="Y" if row.get("format_ok") else "N",
                latency=row.get("latency_s", 0),
                chars=quality.get("points_cjk_chars", 0),
                overlap=quality.get("raw_assistant_overlap_pct", 0),
                issues="; ".join(quality.get("issues", [])) or "-",
            )
        )
    lines.extend(
        [
            "",
            "## 短文首轮明细",
            "",
            "| run | 目标模型 | API | 字数 | 格式问题 | recent-ngram |",
            "|--:|:--|:--:|--:|:--|--:|",
        ]
    )
    for row in target:
        lines.append(
            "| {run} | {model} | {api} | {chars} | {issues} | {ngram} |".format(
                run=row["run"],
                model=row["target_model"],
                api="Y" if row.get("api_success") else "N",
                chars=row.get("cjk_chars", 0),
                issues="; ".join(row.get("format_issues", [])) or "-",
                ngram=row.get("ngram_max_recent_pct", 0),
            )
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate interaction points bridge extraction")
    parser.add_argument("--long-log", default=str(LONG_LOG_DEFAULT))
    parser.add_argument("--short-log", default=str(SHORT_LOG_DEFAULT))
    parser.add_argument("--extractor-model", default=DEFAULT_EXTRACTOR_MODEL)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--latency-threshold", type=float, default=2.0)
    parser.add_argument("--short-models", nargs="*", default=["doubao-lite"])
    parser.add_argument("--skip-target-generation", action="store_true")
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args()

    env_status = ensure_runtime_key_aliases()
    unknown = [m for m in args.short_models if m not in SHORT_TARGET_MODELS]
    if unknown:
        raise ValueError(f"unknown short models: {unknown}")

    long_sample = load_log_sample(Path(args.long_log), mode="long")
    short_sample = load_log_sample(Path(args.short_log), mode="short")
    long_turns = select_19_turns(dialogue_history(long_sample))
    if not long_turns:
        raise RuntimeError("no longform dialogue messages loaded")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_dir) if args.output_dir else PROJECT_ROOT / "output" / "mode_switching_switch_state" / f"mini_interaction_points_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    aux_dir = out_dir / "auxiliary"
    payload_dir = out_dir / "payloads"
    aux_dir.mkdir(exist_ok=True)
    payload_dir.mkdir(exist_ok=True)
    results_path = out_dir / "results.jsonl"
    summary_path = out_dir / "summary.md"

    adapter = ModelAdapter()
    prompt_messages = build_prompt(long_turns)
    (aux_dir / "mini_prompt.json").write_text(
        json.dumps({"messages": prompt_messages}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (aux_dir / "long_19_turn_transcript.txt").write_text(transcript(long_turns), encoding="utf-8")

    print(f"[INFO] env_status={env_status}")
    print(f"[INFO] long_log={long_sample.path} dialogue_messages={len(dialogue_history(long_sample))} selected_messages={len(long_turns)}")
    print(f"[INFO] output={out_dir}")

    rows: list[dict[str, Any]] = []
    for run_idx in range(1, args.runs + 1):
        started = time.perf_counter()
        result = adapter.chat(
            model_id=args.extractor_model,
            messages=prompt_messages,
            max_tokens=700,
            thinking_effort="disabled",
            temperature=0.0,
            top_p=0.1,
            provider_retry_delays=[],
        )
        latency_s = round(time.perf_counter() - started, 3)
        raw_output = result.content or ""
        raw_points_text = strip_code_fence(raw_output)
        points_text, postprocesses = normalize_points_text(raw_points_text)
        quality = validate_original_points(points_text, long_turns)
        latency_exceeded = latency_s > args.latency_threshold
        if result.success and quality.get("pass"):
            bridge = wrap_points_context(points_text)
            used_fallback = False
        else:
            bridge = fallback_bridge(long_turns)
            used_fallback = True
        extraction_row = {
            "type": "mini_interaction_points",
            "run": run_idx,
            "model": args.extractor_model,
            "api_success": result.success,
            "error": result.error,
            "latency_s": latency_s,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "format_ok": bool(quality.get("pass")),
            "latency_exceeded": latency_exceeded,
            "points_postprocesses": postprocesses,
            "parse_error": "",
            "used_fallback": used_fallback,
            "bridge": bridge,
            "raw_output_preview": raw_output[:1000],
            "quality": quality,
        }
        rows.append(extraction_row)
        append_jsonl(results_path, extraction_row)
        (aux_dir / f"run_{run_idx:02d}_raw_output.txt").write_text(raw_output, encoding="utf-8")
        (aux_dir / f"run_{run_idx:02d}_bridge.txt").write_text(bridge, encoding="utf-8")

        if args.skip_target_generation:
            continue

        base_messages = [
            first_system(short_sample.messages),
            {"role": "assistant", "content": bridge},
            last_user(short_sample.messages),
        ]
        for short_model in args.short_models:
            target = call_model(
                adapter,
                short_model,
                base_messages,
                max_tokens=4096,
                thinking="disabled",
            )
            overlaps = [
                ngram_overlap(m["content"], target["output"])
                for m in base_messages
                if m.get("role") == "assistant"
            ]
            target_row = {
                "type": "short_target_generation",
                "run": run_idx,
                "target_model": short_model,
                "api_success": target["success"],
                "error": target["error"],
                "latency_s": target["latency"],
                "cjk_chars": cjk_len(target["output"]),
                "format_issues": detect_format_issues(target["output"], "short"),
                "ngram_max_recent_pct": round((max(overlaps) if overlaps else 0.0) * 100, 2),
                "output_preview": target["output"][:500],
            }
            rows.append(target_row)
            append_jsonl(results_path, target_row)
            (payload_dir / f"run_{run_idx:02d}_{safe_model_label(short_model)}.json").write_text(
                json.dumps(
                    {
                        "messages": base_messages,
                        "target_model": short_model,
                        "target_output_preview": target["output"][:500],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

    write_points_report(rows, summary_path, args.latency_threshold, args.extractor_model)
    extraction = [r for r in rows if r["type"] == "mini_interaction_points"]
    target = [r for r in rows if r["type"] == "short_target_generation"]
    latencies = [r["latency_s"] for r in extraction if r.get("api_success")]
    print(
        "[SUMMARY] "
        f"api={sum(1 for r in extraction if r.get('api_success'))}/{len(extraction)} "
        f"format={sum(1 for r in extraction if r.get('format_ok'))}/{len(extraction)} "
        f"quality={sum(1 for r in extraction if r.get('quality', {}).get('pass'))}/{len(extraction)} "
        f"avg_latency={round(statistics.mean(latencies), 3) if latencies else 0}s "
        f"p95={round(percentile(latencies, 95), 3) if latencies else 0}s "
        f"short_format={sum(1 for r in target if r.get('api_success') and not r.get('format_issues'))}/{len(target)} "
        f"summary={summary_path}"
    )


if __name__ == "__main__":
    main()

