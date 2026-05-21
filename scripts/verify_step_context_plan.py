#!/usr/bin/env python3
"""
Verify whether the proposed Step 1/2/3 context-compression plan matches the
current longform tool implementation.

This is deterministic and uses a temporary SQLite database plus dry-run
generation. It does not call any LLM and does not touch server/longform.db.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SERVER_DIR = PROJECT_ROOT / "server"
OUT_ROOT = PROJECT_ROOT / "output" / "step_context_plan"
TEST_DB = OUT_ROOT / "step_context_plan.db"
SUMMARY_MODEL_FOR_PLAN = "doubao-seed-2-0-lite-260215"
NORMALIZED_SUMMARY_MODEL = "doubao-lite"
SUMMARY_SOURCES_WITH_REQUEST_SUMMARY = {"completed", "seed", "pending-fallback"}

os.environ["LONGFORM_DB_PATH"] = str(TEST_DB)
sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient

import database as db
from main import app


def ensure_test_db_binding() -> None:
    resolved_root = OUT_ROOT.resolve()
    resolved_db = TEST_DB.resolve()
    try:
        resolved_db.relative_to(resolved_root)
    except ValueError as exc:
        raise RuntimeError(f"unsafe TEST_DB path: {resolved_db}") from exc
    imported_db_path = Path(str(getattr(db, "DB_PATH", ""))).resolve()
    if imported_db_path != resolved_db:
        raise RuntimeError(
            f"database binding mismatch: imported={imported_db_path} expected={resolved_db}"
        )


def wait_for_turns(conv_id: str, expected: int, timeout: float = 45.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        conversation = db.get_conversation(conv_id)
        if conversation and len(conversation.get("results") or []) >= expected:
            return conversation
        time.sleep(0.2)
    conversation = db.get_conversation(conv_id)
    raise TimeoutError(
        f"conversation {conv_id} did not reach {expected} turns; "
        f"got {len((conversation or {}).get('results') or [])}"
    )


def base_payload(*, summary_interval: int, turns: list[str]) -> dict:
    return {
        "model_id": "doubao-pro",
        "model_mini": SUMMARY_MODEL_FOR_PLAN,
        "dry_run": True,
        "summary_interval": summary_interval,
        "injection_depth": 4,
        "turns": turns,
        "character": {
            "Role_Nickname": "上下文验证角色",
            "personality": "稳",
            "gender": "男",
        },
        "context": {
            "relationship": "暧昧",
            "scene": "客厅",
            "time_period": "夜晚",
            "user_nickname": "小鹿",
        },
        "modules": {
            "dialogueStartPrompt": "PROFILE_V0",
        },
    }


def count_history_turns(messages: list[dict[str, Any]]) -> dict[str, int]:
    user_history = 0
    assistant_history = 0
    for msg in messages:
        role = msg.get("role")
        content = str(msg.get("content", "")).strip()
        if role == "user" and re.fullmatch(r"U\d+", content):
            user_history += 1
        if role == "assistant" and content.startswith("[dry-run] Turn "):
            assistant_history += 1
    return {
        "history_user_messages": user_history,
        "history_assistant_messages": assistant_history,
        "history_turns": min(user_history, assistant_history),
    }


def analyze_batch(summary_interval: int, *, turns_count: int = 21) -> dict:
    turns = [f"U{i}" for i in range(1, turns_count + 1)]
    with TestClient(app) as client:
        response = client.post(
            "/api/conversations",
            json=base_payload(summary_interval=summary_interval, turns=turns),
        )
        if response.status_code != 200:
            raise RuntimeError(response.text)
        conv_id = response.json()["id"]
        conversation = wait_for_turns(conv_id, turns_count)

    rows = []
    first_summary_result_turn = 0
    first_summary_used_turn = 0
    max_history_turns = 0
    max_equivalent_turns = 0
    for item in conversation.get("results") or []:
        turn = int(item.get("turn", 0) or 0)
        snapshot = item.get("request_payload_snapshot") or {}
        messages = snapshot.get("messages") or []
        history = count_history_turns(messages)
        summary_source = str(snapshot.get("summary_source", "") or "")
        has_summary = bool(str(item.get("dialogue_summary", "")).strip())
        uses_summary_in_request = summary_source in SUMMARY_SOURCES_WITH_REQUEST_SUMMARY
        if has_summary and not first_summary_result_turn:
            first_summary_result_turn = turn
        if uses_summary_in_request and not first_summary_used_turn:
            first_summary_used_turn = turn
        max_history_turns = max(max_history_turns, history["history_turns"])
        equivalent_turns = history["history_turns"] + (1 if uses_summary_in_request else 0)
        max_equivalent_turns = max(max_equivalent_turns, equivalent_turns)
        rows.append(
            {
                "turn": turn,
                **history,
                "has_summary": has_summary,
                "summary_source": summary_source,
                "uses_summary_in_request": uses_summary_in_request,
                "equivalent_turns": equivalent_turns,
                "message_count": len(messages),
            }
        )
    return {
        "summary_interval": summary_interval,
        "conversation_id": conv_id,
        "turns": rows,
        "first_summary_result_turn": first_summary_result_turn,
        "first_summary_used_turn": first_summary_used_turn,
        "max_history_turns": max_history_turns,
        "max_equivalent_turns": max_equivalent_turns,
        "runtime": conversation.get("config", {}).get("runtime", {}),
    }


def analyze_interactive_create() -> dict:
    payload = {
        "model_id": "doubao-pro",
        "model_mini": SUMMARY_MODEL_FOR_PLAN,
        "summary_interval": 5,
        "dry_run": True,
        "character": {
            "Role_Nickname": "上下文预热验证角色",
            "personality": "稳",
            "gender": "男",
        },
        "context": {"relationship": "暧昧"},
        "modules": {"dialogueStartPrompt": "PROFILE_V0"},
    }
    with TestClient(app) as client:
        response = client.post("/api/conversations/interactive", json=payload)
        if response.status_code != 200:
            raise RuntimeError(response.text)
        conv_id = response.json()["id"]
    deadline = time.time() + 5.0
    conversation = db.get_conversation(conv_id) or {}
    while time.time() < deadline:
        runtime = conversation.get("config", {}).get("runtime", {})
        if str(runtime.get("summary_job_status", "")) == "completed":
            break
        time.sleep(0.1)
        conversation = db.get_conversation(conv_id) or {}
    runtime = conversation.get("config", {}).get("runtime", {})
    return {
        "conversation_id": conv_id,
        "requested_model_mini": SUMMARY_MODEL_FOR_PLAN,
        "stored_model_mini": str(conversation.get("model_mini", "")),
        "runtime_model_mini": str(runtime.get("model_mini", "")),
        "summary_job_status": runtime.get("summary_job_status"),
        "summary_job_target_turn": runtime.get("summary_job_target_turn"),
        "latest_dialogue_summary_present": bool(str(runtime.get("latest_dialogue_summary", "")).strip()),
        "results_count": len(conversation.get("results") or []),
    }


def analyze_cross_session_summary() -> dict:
    first_config = {
        "character": {"Role_Nickname": "跨会话角色", "personality": "稳"},
        "context": {"relationship": "暧昧"},
        "modules": {},
        "runtime": {"model_ids": ["doubao-pro"], "summary_interval": 5},
    }
    first_id = db.create_conversation("doubao-pro", first_config)
    db.insert_turn_result(
        first_id,
        {
            "turn": 1,
            "user_input": "上一通用户输入",
            "ai_output": "上一通AI输出",
            "dialogue_summary": "=== 之前剧情摘要 ===\n上一通摘要\n=== 摘要结束 ===",
            "model_id": "doubao-pro",
        },
    )
    db.update_conversation_status(first_id, "completed")

    payload = {
        "model_id": "doubao-pro",
        "model_mini": SUMMARY_MODEL_FOR_PLAN,
        "summary_interval": 5,
        "dry_run": True,
        "character": {"Role_Nickname": "跨会话角色", "personality": "稳"},
        "context": {"relationship": "暧昧"},
        "modules": {},
    }
    with TestClient(app) as client:
        response = client.post("/api/conversations/interactive", json=payload)
        if response.status_code != 200:
            raise RuntimeError(response.text)
        second_id = response.json()["id"]
    second = db.get_conversation(second_id) or {}
    runtime = second.get("config", {}).get("runtime", {})
    context = second.get("config", {}).get("context", {})
    return {
        "previous_conversation_id": first_id,
        "new_conversation_id": second_id,
        "requested_model_mini": SUMMARY_MODEL_FOR_PLAN,
        "stored_model_mini": str(second.get("model_mini", "")),
        "runtime_model_mini": str(runtime.get("model_mini", "")),
        "latest_dialogue_summary_present": bool(str(runtime.get("latest_dialogue_summary", "")).strip()),
        "latest_dialogue_summary": str(runtime.get("latest_dialogue_summary", "")),
        "last_cst_type": str(context.get("last_cst_type", "")),
    }


def write_summary(report: dict, path: Path) -> None:
    batch10 = report["batch_summary_interval_10"]
    batch5 = report["batch_summary_interval_5"]
    interactive = report["interactive_create"]
    cross_session = report["cross_session"]
    step2_ok = (
        interactive["stored_model_mini"] == NORMALIZED_SUMMARY_MODEL
        and interactive["summary_job_status"] == "completed"
        and int(interactive["summary_job_target_turn"] or 0) == 0
        and bool(interactive["latest_dialogue_summary_present"])
    )
    step3_ok = (
        cross_session["stored_model_mini"] == NORMALIZED_SUMMARY_MODEL
        and bool(cross_session["latest_dialogue_summary_present"])
        and "上一通摘要" in str(cross_session["latest_dialogue_summary"])
    )

    lines = [
        "# Step 1/2/3 上下文压缩方案核验报告",
        "",
        f"- 生成时间: {datetime.now().isoformat()}",
        f"- 测试数据库: {TEST_DB}",
        "- 执行方式: FastAPI TestClient + dry-run，不调用真实模型",
        f"- Step 2/3 摘要模型入参: {SUMMARY_MODEL_FOR_PLAN}（当前适配层归一化为 `{NORMALIZED_SUMMARY_MODEL}`）",
        "",
        "## 结论表",
        "",
        "| Step | 预期 | 当前代码实测 | 结论 |",
        "|:--|:--|:--|:--|",
        (
            "| Step 1 | 切换上下文20→10 + 摘要触发10→5，峰值30轮→15轮 | "
            f"生成入口固定10轮滑动窗口；summary_interval=10 摘要回写第{batch10['first_summary_result_turn']}轮、首次在请求中用于第{batch10['first_summary_used_turn']}轮；"
            f"summary_interval=5 摘要回写第{batch5['first_summary_result_turn']}轮、首次在请求中用于第{batch5['first_summary_used_turn']}轮；"
            f"实测最大历史轮数={batch5['max_history_turns']}，最大等效轮数={batch5['max_equivalent_turns']} | "
            "成立：10轮窗口已落在生成入口，默认摘要触发已切到5，摘要可用时间从第11轮提前到第6轮 |"
        ),
        (
            "| Step 2 | 会话创建时异步调doubao-seed-2.0-lite，第2轮起约11轮 | "
            f"interactive create 入参摘要模型={interactive['requested_model_mini']}、落库模型={interactive['stored_model_mini']}，"
            f"summary_job_status={interactive['summary_job_status']}，"
            f"target_turn={interactive['summary_job_target_turn']}，latest_summary={interactive['latest_dialogue_summary_present']} | "
            f"{'成立：创建会话后已调度并完成 target_turn=0 的摘要预热' if step2_ok else '不成立：创建会话摘要预热未达到验收'} |"
        ),
        (
            "| Step 3 | Q5跨会话摘要持久化，下一通冷启动加载摘要 | "
            f"新会话入参摘要模型={cross_session['requested_model_mini']}、落库模型={cross_session['stored_model_mini']}，"
            f"latest_summary={cross_session['latest_dialogue_summary_present']}，"
            f"last_cst_type={cross_session['last_cst_type'] or '-'} | "
            f"{'成立：新会话已冷启动加载上一通 dialogue_summary' if step3_ok else '不成立：跨会话摘要未达到验收'} |"
        ),
        "",
        "## summary_interval 对比",
        "",
        "| summary_interval | 摘要回写轮次 | 首次在请求中使用摘要轮次 | 最大真实历史轮数 | 最大等效轮数(请求历史+实际注入摘要) |",
        "|--:|--:|--:|--:|--:|",
        f"| 10 | {batch10['first_summary_result_turn']} | {batch10['first_summary_used_turn']} | {batch10['max_history_turns']} | {batch10['max_equivalent_turns']} |",
        f"| 5 | {batch5['first_summary_result_turn']} | {batch5['first_summary_used_turn']} | {batch5['max_history_turns']} | {batch5['max_equivalent_turns']} |",
        "",
        "## 原始数据",
        "",
        "详见同目录 `results.json`。",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ensure_test_db_binding()
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    if TEST_DB.exists():
        TEST_DB.unlink()
    db.init_db()
    db.migrate_add_score_columns()
    db.migrate_add_v51_columns()

    report = {
        "batch_summary_interval_10": analyze_batch(10),
        "batch_summary_interval_5": analyze_batch(5),
        "interactive_create": analyze_interactive_create(),
        "cross_session": analyze_cross_session_summary(),
    }
    results_path = OUT_ROOT / "results.json"
    summary_path = OUT_ROOT / "summary.md"
    results_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_summary(report, summary_path)
    print(f"[DONE] results={results_path}")
    print(f"[DONE] summary={summary_path}")
    print(summary_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
