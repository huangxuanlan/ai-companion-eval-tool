#!/usr/bin/env python3
"""Benchmark DeepSeek V4 Pro thinking speed in the longform generation path.

This script is intentionally self-contained and keeps credentials in process
environment variables only. It does not edit model YAML files or .env files.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import sys
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MethodType
from typing import Any

from openai import OpenAI

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SERVER_DIR = PROJECT_ROOT / "server"
DEFAULT_TEST_DB = PROJECT_ROOT / "output" / "test_runtime" / "deepseek_speed_probe.db"

# This must happen before importing server/config.py or database.py.
if not os.environ.get("LONGFORM_DB_PATH"):
    os.environ["LONGFORM_DB_PATH"] = str(DEFAULT_TEST_DB)

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SERVER_DIR))

import database  # noqa: E402
from services.conversation_service import ConversationService  # noqa: E402
from services.model_adapter import ModelAdapter  # noqa: E402


REQUESTED_MODEL = "deepseek-v4-pro"
DEFAULT_EFFORTS = ("disabled", "high", "max")
DEFAULT_TURNS = 20
DEFAULT_SUMMARY_INTERVAL = 10_000
EXTRA_TURNS = [
    "你刚才说晚安的时候，好像并不是真的想走",
    "如果我现在留下来，你会高兴吗",
    "你总是这样，把话说一半就停住",
    "我今天其实有点不安",
    "你能不能不要用这种命令的语气",
    "那你希望我怎么回应你",
    "我好像越来越看不懂你了",
    "如果我说我有点心动，你会怎么办",
    "别靠这么近，我会乱想",
    "这次真的晚安了",
]


@dataclass(frozen=True)
class Candidate:
    provider: str
    model_name: str
    thinking_control: str
    supports_reasoning_effort: bool


@dataclass(frozen=True)
class Channel:
    channel_id: str
    label: str
    base_url: str
    api_key_env: str
    candidates_by_effort: dict[str, tuple[Candidate, ...]]


@dataclass
class BenchProviderResult:
    content: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency: float = 0.0
    success: bool = True
    error: str = ""


class DeepSeekOfficialProvider:
    """Script-local provider for DeepSeek official OpenAI-compatible API."""

    def __init__(self, model_config: dict[str, Any]):
        self.config = model_config
        self.display_name = model_config.get("display_name", "DeepSeek official")
        self.api_config = dict(model_config.get("api", {}) or {})
        self.parameters = dict(model_config.get("parameters", {}) or {})
        self.rate_limit = dict(model_config.get("rate_limit", {}) or {})
        self.retry_delays = self.rate_limit.get("retry_delays", [])
        api_key = str(self.api_config.get("api_key", "") or "")
        if api_key.startswith("${") and api_key.endswith("}"):
            api_key = os.environ.get(api_key[2:-1], "")
        self.client = OpenAI(
            base_url=str(self.api_config.get("base_url", "https://api.deepseek.com")).rstrip("/"),
            api_key=api_key,
        )
        self.model_name = str(self.api_config.get("model_name", REQUESTED_MODEL) or REQUESTED_MODEL)
        self.max_tokens = int(self.parameters.get("max_tokens", 4096) or 4096)
        self.temperature = float(self.parameters.get("temperature", 1.0))
        self.top_p = float(self.parameters.get("top_p", 1.0))

    def call_with_retry(
        self,
        messages: list[dict],
        *,
        retry_delays: list[float] | tuple[float, ...] | None = None,
        **kwargs,
    ) -> BenchProviderResult:
        delays = list(self.retry_delays if retry_delays is None else retry_delays)
        for attempt, delay in enumerate(delays + [0]):
            try:
                start = time.perf_counter()
                result = self.call(messages, **kwargs)
                result.latency = round(time.perf_counter() - start, 2)
                return result
            except Exception as exc:
                if attempt < len(delays):
                    time.sleep(delay)
                else:
                    return BenchProviderResult(success=False, error=str(exc), latency=0.0)
        return BenchProviderResult(success=False, error="Unknown error")

    def call(self, messages: list[dict], **kwargs) -> BenchProviderResult:
        effort = str(kwargs.get("thinking_effort", "disabled") or "disabled").strip().lower()
        thinking_enabled = effort != "disabled"
        api_kwargs: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "extra_body": {
                "thinking": {
                    "type": "enabled" if thinking_enabled else "disabled",
                }
            },
        }
        if thinking_enabled:
            api_kwargs["reasoning_effort"] = "max" if effort in {"max", "xhigh"} else "high"

        # Non-streaming call: latency is measured after the full response returns.
        response = self.client.chat.completions.create(**api_kwargs)
        return self._parse_response(response)

    def _parse_response(self, response: Any) -> BenchProviderResult:
        content = ""
        if response.choices:
            message = response.choices[0].message
            content = str(getattr(message, "content", "") or "")
        usage = getattr(response, "usage", None)
        return BenchProviderResult(
            content=content,
            input_tokens=int(getattr(usage, "prompt_tokens", 0) if usage else 0),
            output_tokens=int(getattr(usage, "completion_tokens", 0) if usage else 0),
            success=True,
        )


CHANNELS = (
    Channel(
        channel_id="deepseek_official",
        label="DeepSeek official",
        base_url="https://api.deepseek.com",
        api_key_env="DEEPSEEK_OFFICIAL_API_KEY",
        candidates_by_effort={
            "disabled": (Candidate("deepseek_official", REQUESTED_MODEL, "official_thinking", True),),
            "high": (Candidate("deepseek_official", REQUESTED_MODEL, "official_thinking", True),),
            "max": (Candidate("deepseek_official", REQUESTED_MODEL, "official_thinking", True),),
        },
    ),
    Channel(
        channel_id="dashscope",
        label="Aliyun DashScope",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key_env="DASHSCOPE_API_KEY",
        candidates_by_effort={
            "disabled": (Candidate("aliyun", REQUESTED_MODEL, "reasoning_effort", True),),
            "high": (Candidate("aliyun", REQUESTED_MODEL, "reasoning_effort", True),),
            "max": (Candidate("aliyun", REQUESTED_MODEL, "reasoning_effort", True),),
        },
    ),
    Channel(
        channel_id="bitleap",
        label="Bitleap third-party",
        base_url="https://llm.bitleapai.cn/v1",
        api_key_env="BITLEAP_API_KEY",
        candidates_by_effort={
            "disabled": (
                Candidate("aliyun", REQUESTED_MODEL, "reasoning_effort", True),
                Candidate("openrouter", REQUESTED_MODEL, "none", False),
            ),
            "high": (
                Candidate("aliyun", REQUESTED_MODEL, "reasoning_effort", True),
                Candidate("openrouter", "deepseek-reasoner", "model-mapped", False),
            ),
            "max": (
                Candidate("aliyun", REQUESTED_MODEL, "reasoning_effort", True),
                Candidate("openrouter", "deepseek-reasoner", "model-mapped", False),
            ),
        },
    ),
)


SECRET_RE = re.compile(r"sk-[A-Za-z0-9_\-]{8,}")


def sanitize_text(value: Any) -> str:
    text = str(value or "")
    text = SECRET_RE.sub("sk-***", text)
    for env_name in ("DEEPSEEK_OFFICIAL_API_KEY", "DASHSCOPE_API_KEY", "BITLEAP_API_KEY"):
        secret = os.environ.get(env_name, "")
        if secret:
            text = text.replace(secret, "<redacted>")
    return text


def parse_csv(value: str, allowed: set[str] | None = None) -> list[str]:
    items = [item.strip() for item in str(value or "").split(",") if item.strip()]
    if allowed is not None:
        invalid = [item for item in items if item not in allowed]
        if invalid:
            raise SystemExit(f"invalid value(s): {', '.join(invalid)}")
    return items


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    fraction = rank - low
    return ordered[low] + (ordered[high] - ordered[low]) * fraction


def cjk_len(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text or ""))


def load_config(turns: int, include_summaries: bool) -> dict[str, Any]:
    config_path = PROJECT_ROOT / "test_conversation_萧璟言.json"
    with config_path.open("r", encoding="utf-8") as f:
        config = json.load(f)

    original_turns = [str(item) for item in config.get("turns", [])]
    expanded = (original_turns + EXTRA_TURNS)[:turns]
    if len(expanded) < turns:
        raise SystemExit(f"not enough turns: required={turns}, available={len(expanded)}")

    config["turns"] = expanded
    config["prompt_file"] = str(PROJECT_ROOT / "prompt" / "星朋友长文模式_提示词_v2.0.md")
    config["few_shot_file"] = str(PROJECT_ROOT / "few_shot" / "长文模式_Few-shot示例库.md")
    runtime = config.setdefault("runtime", {})
    runtime["summary_interval"] = 5 if include_summaries else DEFAULT_SUMMARY_INTERVAL
    runtime["temperature"] = 1.0
    runtime["top_p"] = 1.0
    return config


def model_config(channel: Channel, candidate: Candidate) -> dict[str, Any]:
    thinking_enabled = candidate.thinking_control in {"reasoning_effort", "official_thinking"}
    return {
        "name": candidate.model_name,
        "display_name": f"{channel.label} {candidate.model_name}",
        "provider": candidate.provider,
        "api": {
            "base_url": channel.base_url,
            "api_key": f"${{{channel.api_key_env}}}",
            "model_name": candidate.model_name,
        },
        "parameters": {"temperature": 1.0, "max_tokens": 4096, "top_p": 1.0},
        "thinking": {
            "enabled": thinking_enabled,
            "supports_reasoning_effort": candidate.supports_reasoning_effort,
            "allowed_efforts": ["disabled", "high", "max"],
            "default_effort": "high",
        },
        "capabilities": {
            "web_search": False,
            "thinking": thinking_enabled,
            "thinking_efforts": ["disabled", "high", "max"] if thinking_enabled else ["disabled"],
            "default_thinking_effort": "high" if thinking_enabled else "disabled",
        },
        "rate_limit": {"retry_delays": []},
    }


def register_model(adapter: ModelAdapter, model_id: str, channel: Channel, candidate: Candidate) -> None:
    adapter._models[model_id] = model_config(channel, candidate)
    adapter._providers.pop(model_id, None)
    if candidate.thinking_control == "official_thinking":
        if not getattr(adapter, "_bench_deepseek_official_patch", False):
            original_instantiate = adapter._instantiate_provider

            def instantiate_provider(self: ModelAdapter, patched_model_id: str):
                normalized = self.normalize_model_id(patched_model_id)
                config = self._models.get(normalized, {})
                if config.get("provider") == "deepseek_official":
                    return DeepSeekOfficialProvider(deepcopy(config))
                return original_instantiate(patched_model_id)

            adapter._instantiate_provider = MethodType(instantiate_provider, adapter)
            adapter._bench_deepseek_official_patch = True
        adapter._providers[model_id] = DeepSeekOfficialProvider(adapter._models[model_id])


def candidate_model_id(channel: Channel, effort: str, candidate: Candidate, index: int | None = None) -> str:
    if candidate.model_name == REQUESTED_MODEL:
        return REQUESTED_MODEL
    suffix = f"_candidate_{index}" if index is not None else ""
    return f"bench_{channel.channel_id}_{effort}{suffix}"


def preflight(
    adapter: ModelAdapter,
    channel: Channel,
    effort: str,
    dry_run: bool,
) -> dict[str, Any]:
    candidates = channel.candidates_by_effort.get(effort) or channel.candidates_by_effort["disabled"]
    if dry_run:
        candidate = candidates[0]
        model_id = candidate_model_id(channel, effort, candidate)
        register_model(adapter, model_id, channel, candidate)
        return {
            "status": "dry-run",
            "model_id": model_id,
            "effective_model": candidate.model_name,
            "provider": candidate.provider,
            "thinking_control": candidate.thinking_control,
            "error": "",
        }

    if not os.environ.get(channel.api_key_env):
        return {
            "status": "missing-key",
            "model_id": "",
            "effective_model": "",
            "provider": "",
            "thinking_control": "",
            "error": f"missing env {channel.api_key_env}",
        }

    messages = [{"role": "user", "content": "你好，请用一句话回复。"}]
    errors: list[str] = []
    for index, candidate in enumerate(candidates, start=1):
        model_id = candidate_model_id(channel, effort, candidate, index)
        register_model(adapter, model_id, channel, candidate)
        call_effort = effort if candidate.supports_reasoning_effort else "disabled"
        preflight_max_tokens = 1024 if call_effort != "disabled" else 64
        result = adapter.chat(
            model_id,
            messages,
            max_tokens=preflight_max_tokens,
            thinking_effort=call_effort,
            provider_retry_delays=[],
        )
        if result.success and str(result.content or "").strip():
            return {
                "status": "ok",
                "model_id": model_id,
                "effective_model": candidate.model_name,
                "provider": candidate.provider,
                "thinking_control": candidate.thinking_control,
                "error": "",
            }
        error = sanitize_text(result.error)
        if result.success and not str(result.content or "").strip():
            error = "empty content"
        errors.append(f"{candidate.model_name}: {error}")

    return {
        "status": "unsupported",
        "model_id": "",
        "effective_model": "",
        "provider": "",
        "thinking_control": "",
        "error": " | ".join(errors),
    }


def flatten_turn(
    *,
    run_id: str,
    channel: Channel,
    effort: str,
    preflight_result: dict[str, Any],
    turn: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    output = str(turn.get("ai_output", "") or "")
    latency = float(turn.get("latency_s", 0) or 0)
    output_tokens = int(turn.get("output_tokens", 0) or 0)
    return {
        "run_id": run_id,
        "channel_id": channel.channel_id,
        "channel_label": channel.label,
        "base_url": channel.base_url,
        "requested_model": REQUESTED_MODEL,
        "effective_model": preflight_result.get("effective_model", ""),
        "provider": preflight_result.get("provider", ""),
        "thinking_effort": effort,
        "thinking_control": preflight_result.get("thinking_control", ""),
        "turn": int(turn.get("turn", 0) or 0),
        "success": bool(dry_run or output),
        "error_type": "",
        "latency_s": latency,
        "input_tokens": int(turn.get("input_tokens", 0) or 0),
        "output_tokens": output_tokens,
        "word_count": int(turn.get("word_count", 0) or cjk_len(output)),
        "tokens_per_s": round(output_tokens / latency, 4) if latency > 0 else 0,
        "chars_per_s": round(cjk_len(output) / latency, 4) if latency > 0 else 0,
        "msg_count": int(turn.get("msg_count", 0) or 0),
        "quality_retries": int(turn.get("quality_retries", 0) or 0),
    }


def make_failed_turn_rows(
    *,
    channel: Channel,
    effort: str,
    preflight_result: dict[str, Any],
    turns: int,
) -> list[dict[str, Any]]:
    run_id = f"bench-{channel.channel_id}-{effort}-{int(time.time())}"
    error = sanitize_text(preflight_result.get("error", ""))
    return [
        {
            "run_id": run_id,
            "channel_id": channel.channel_id,
            "channel_label": channel.label,
            "base_url": channel.base_url,
            "requested_model": REQUESTED_MODEL,
            "effective_model": preflight_result.get("effective_model", ""),
            "provider": preflight_result.get("provider", ""),
            "thinking_effort": effort,
            "thinking_control": preflight_result.get("thinking_control", ""),
            "turn": turn,
            "success": False,
            "error_type": preflight_result.get("status", "preflight_failed"),
            "error": error,
            "latency_s": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "word_count": 0,
            "tokens_per_s": 0,
            "chars_per_s": 0,
            "msg_count": 0,
            "quality_retries": 0,
        }
        for turn in range(1, turns + 1)
    ]


def summarize_group(rows: list[dict[str, Any]], preflight_result: dict[str, Any]) -> dict[str, Any]:
    success_rows = [row for row in rows if row.get("success")]
    latencies = [float(row.get("latency_s", 0) or 0) for row in success_rows]
    total_latency = sum(latencies)
    total_out = sum(int(row.get("output_tokens", 0) or 0) for row in success_rows)
    total_chars = sum(int(row.get("word_count", 0) or 0) for row in success_rows)
    return {
        "channel_id": rows[0]["channel_id"] if rows else "",
        "channel_label": rows[0]["channel_label"] if rows else "",
        "base_url": rows[0]["base_url"] if rows else "",
        "requested_model": REQUESTED_MODEL,
        "effective_model": preflight_result.get("effective_model", ""),
        "provider": preflight_result.get("provider", ""),
        "thinking_effort": rows[0]["thinking_effort"] if rows else "",
        "thinking_control": preflight_result.get("thinking_control", ""),
        "preflight_status": preflight_result.get("status", ""),
        "preflight_error": sanitize_text(preflight_result.get("error", "")),
        "turns_requested": len(rows),
        "turns_success": len(success_rows),
        "total_latency_s": round(total_latency, 2),
        "avg_latency_s": round(total_latency / len(latencies), 4) if latencies else 0,
        "p50_latency_s": round(percentile(latencies, 0.50), 4) if latencies else 0,
        "p95_latency_s": round(percentile(latencies, 0.95), 4) if latencies else 0,
        "total_input_tokens": sum(int(row.get("input_tokens", 0) or 0) for row in success_rows),
        "total_output_tokens": total_out,
        "total_word_count": total_chars,
        "tokens_per_s": round(total_out / total_latency, 4) if total_latency > 0 else 0,
        "chars_per_s": round(total_chars / total_latency, 4) if total_latency > 0 else 0,
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(
    path: Path,
    *,
    started_at: str,
    db_path: str,
    dry_run: bool,
    include_summaries: bool,
    summaries: list[dict[str, Any]],
) -> None:
    ok = [row for row in summaries if row.get("turns_success")]
    ranked = sorted(ok, key=lambda row: float(row.get("avg_latency_s", 0) or 0))
    lines = [
        "# DeepSeek V4 Pro 长文模式生成速度测试报告",
        "",
        f"- 生成时间: {started_at}",
        f"- Dry-run: {dry_run}",
        f"- 隔离数据库: `{db_path}`",
        f"- 主指标: 20 轮主生成完整响应返回 `latency_s`，不含摘要/画像/导出耗时",
        f"- 摘要调用: {'开启' if include_summaries else '关闭'}",
        f"- API Key: 仅来自进程环境变量，未写入报告",
        "",
        "## 总览",
        "",
        "| 排名 | 渠道 | 思考档位 | effective_model | 成功轮数 | 平均延迟(s) | P95(s) | 输出tok/s | 字符/s |",
        "|---:|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for index, row in enumerate(ranked, start=1):
        lines.append(
            "| {rank} | {channel} | {effort} | `{model}` | {turns} | {avg} | {p95} | {tps} | {cps} |".format(
                rank=index,
                channel=row["channel_label"],
                effort=row["thinking_effort"],
                model=row["effective_model"],
                turns=row["turns_success"],
                avg=row["avg_latency_s"],
                p95=row["p95_latency_s"],
                tps=row["tokens_per_s"],
                cps=row["chars_per_s"],
            )
        )
    if not ranked:
        lines.append("| - | - | - | - | 0 | 0 | 0 | 0 | 0 |")

    lines.extend(["", "## 渠道与模型映射", ""])
    for row in summaries:
        mapped = (
            ""
            if row.get("effective_model") == row.get("requested_model")
            else f"；映射为 `{row.get('effective_model')}`"
        )
        status = row.get("preflight_status", "")
        err = row.get("preflight_error", "")
        lines.append(
            f"- {row.get('channel_label')} / {row.get('thinking_effort')}: "
            f"preflight={status}，请求 `{row.get('requested_model')}`{mapped}，"
            f"thinking_control={row.get('thinking_control') or 'n/a'}"
            + (f"，错误: `{err}`" if err and status not in {"ok", "dry-run"} else "")
        )

    lines.extend(["", "## 明细文件", ""])
    lines.append("- `results.jsonl`: 每轮 latency/tokens/字数/消息数")
    lines.append("- `summary.csv`: 每组聚合指标")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def initialize_database() -> None:
    database.init_db()
    database.migrate_add_score_columns()
    database.migrate_add_v51_columns()
    database.migrate_add_compare_reports_table()
    database.migrate_add_ai_report_summaries_table()
    database.migrate_add_conversation_events_table()
    database.migrate_add_orchestration_runs_table()
    database.migrate_add_ab_sessions_table()


async def run_group(
    *,
    service: ConversationService,
    channel: Channel,
    effort: str,
    preflight_result: dict[str, Any],
    turns: int,
    dry_run: bool,
    include_summaries: bool,
) -> list[dict[str, Any]]:
    config = load_config(turns, include_summaries)
    runtime = config.setdefault("runtime", {})
    runtime["thinking_enabled"] = effort != "disabled"
    runtime["thinking_effort"] = effort
    run_id = f"bench-{channel.channel_id}-{effort}-{int(time.time())}"
    conv_id = service.create_conversation(
        model_id=preflight_result["model_id"],
        model_mini=preflight_result["model_id"],
        config=config,
        prompt_version=str(config.get("prompt_file", "")),
    )

    # Keep run_conversation_chain on the main path while preventing background
    # summary/profile calls from adding unreported model cost.
    if not include_summaries:
        service._schedule_summary_job_if_needed = lambda **_: None
    service._schedule_profile_job_if_needed = lambda **_: None

    started = time.perf_counter()
    try:
        results = await service.run_conversation(
            conv_id=conv_id,
            config=config,
            turns=config["turns"][:turns],
            model_id=preflight_result["model_id"],
            model_mini=preflight_result["model_id"],
            summary_interval=5 if include_summaries else DEFAULT_SUMMARY_INTERVAL,
            dry_run=dry_run,
        )
    except Exception as exc:
        return [
            {
                "run_id": run_id,
                "channel_id": channel.channel_id,
                "channel_label": channel.label,
                "base_url": channel.base_url,
                "requested_model": REQUESTED_MODEL,
                "effective_model": preflight_result.get("effective_model", ""),
                "provider": preflight_result.get("provider", ""),
                "thinking_effort": effort,
                "thinking_control": preflight_result.get("thinking_control", ""),
                "turn": 0,
                "success": False,
                "error_type": "run_failed",
                "error": sanitize_text(exc),
                "latency_s": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "word_count": 0,
                "tokens_per_s": 0,
                "chars_per_s": 0,
                "msg_count": 0,
                "quality_retries": 0,
            }
        ]
    wall_time = round(time.perf_counter() - started, 2)
    rows = [
        flatten_turn(
            run_id=run_id,
            channel=channel,
            effort=effort,
            preflight_result=preflight_result,
            turn=turn,
            dry_run=dry_run,
        )
        for turn in results
    ]
    for row in rows:
        row["group_wall_time_s"] = wall_time
    return rows


async def async_main(args: argparse.Namespace) -> int:
    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir or PROJECT_ROOT / "output" / "deepseek_v4pro_speed" / timestamp)
    output_dir.mkdir(parents=True, exist_ok=True)

    efforts = parse_csv(args.efforts, set(DEFAULT_EFFORTS))
    channel_ids = set(parse_csv(args.channels))
    channels = [channel for channel in CHANNELS if channel.channel_id in channel_ids]
    if not channels:
        raise SystemExit("no channels selected")

    initialize_database()
    service = ConversationService()
    adapter = service.model
    all_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []

    print(f"[bench] output_dir={output_dir}")
    print(f"[bench] db={os.environ.get('LONGFORM_DB_PATH')}")
    print(f"[bench] dry_run={args.dry_run} turns={args.turns} efforts={','.join(efforts)}")

    for channel in channels:
        for effort in efforts:
            print(f"[bench] preflight channel={channel.channel_id} effort={effort}")
            preflight_result = preflight(adapter, channel, effort, args.dry_run)
            if preflight_result["status"] not in {"ok", "dry-run"}:
                rows = make_failed_turn_rows(
                    channel=channel,
                    effort=effort,
                    preflight_result=preflight_result,
                    turns=args.turns,
                )
                all_rows.extend(rows)
                summaries.append(summarize_group(rows, preflight_result))
                print(f"[bench] skip channel={channel.channel_id} effort={effort} status={preflight_result['status']}")
                continue

            print(
                "[bench] run channel={channel} effort={effort} model={model}".format(
                    channel=channel.channel_id,
                    effort=effort,
                    model=preflight_result["effective_model"],
                )
            )
            rows = await run_group(
                service=service,
                channel=channel,
                effort=effort,
                preflight_result=preflight_result,
                turns=args.turns,
                dry_run=args.dry_run,
                include_summaries=args.include_summaries,
            )
            all_rows.extend(rows)
            summaries.append(summarize_group(rows, preflight_result))
            time.sleep(max(0.0, float(args.pause_s)))

    write_jsonl(output_dir / "results.jsonl", all_rows)
    write_csv(output_dir / "summary.csv", summaries)
    write_markdown(
        output_dir / "summary.md",
        started_at=started_at,
        db_path=str(os.environ.get("LONGFORM_DB_PATH", "")),
        dry_run=args.dry_run,
        include_summaries=args.include_summaries,
        summaries=summaries,
    )
    print(f"[bench] wrote {output_dir / 'results.jsonl'}")
    print(f"[bench] wrote {output_dir / 'summary.csv'}")
    print(f"[bench] wrote {output_dir / 'summary.md'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark DeepSeek V4 Pro thinking speed with longform prompts.",
    )
    parser.add_argument("--turns", type=int, default=DEFAULT_TURNS)
    parser.add_argument("--efforts", default="disabled,high,max")
    parser.add_argument(
        "--channels",
        default="deepseek_official,dashscope,bitleap",
        help="Comma-separated channel ids.",
    )
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--pause-s", type=float, default=1.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--serial", action="store_true", help="Accepted for explicitness; execution is always serial.")
    parser.add_argument(
        "--include-summaries",
        action="store_true",
        help="Allow longform summary calls every 5 turns. Disabled by default to keep main-call cost bounded.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.turns < 1:
        raise SystemExit("--turns must be >= 1")
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
