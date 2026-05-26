import asyncio
import json
import os
import sys
from copy import deepcopy
from urllib.parse import urlparse

from playwright.async_api import async_playwright


BASE_URL = os.environ.get("LONGFORM_UI_BASE_URL", "http://127.0.0.1:8010/")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def make_turn(
    turn: int,
    user_input: str,
    ai_output: str,
    *,
    score_status: str,
    score_total: float = 0.0,
    reasoning: str = "",
    model_id: str = "doubao-pro",
) -> dict:
    base_score = 8 if score_status == "scored" else 0
    return {
        "turn": turn,
        "user_input": user_input,
        "ai_output": ai_output,
        "model_id": model_id,
        "score_status": score_status,
        "score_total": score_total,
        "score_reasoning": reasoning,
        "score_persona_fidelity": base_score,
        "score_narrative_immersion": base_score,
        "score_emotional_tension": base_score,
        "score_boundary_memory": base_score,
        "score_format_compliance": base_score,
        "score_context_coherence": base_score,
        "messages_snapshot": [],
        "request_payload_snapshot": {},
    }


def build_history_item(
    conv_id: str,
    role_name: str,
    *,
    status: str,
    total_turns: int,
    scored_turns: int,
    failed_turns: int,
    skipped_turns: int,
    score_avg: float | None,
    ai_report_status: str,
    ai_report_label: str,
) -> dict:
    return {
        "id": conv_id,
        "conversation_id": conv_id,
        "status": status,
        "created_at": "2026-04-22 12:00:00",
        "updated_at": "2026-04-22 12:05:00",
        "nickname": role_name,
        "character_name": role_name,
        "character_type": "测试角色",
        "model": "doubao-pro",
        "model_id": "doubao-pro",
        "prompt_version": "测试提示词_v1.md",
        "prompt_file": "测试提示词_v1.md",
        "total_turns": total_turns,
        "completed_turns": total_turns,
        "next_turn_index": total_turns,
        "scored_turns": scored_turns,
        "failed_turns": failed_turns,
        "skipped_turns": skipped_turns,
        "score_avg": score_avg,
        "last_message_preview": "最后一条消息预览",
        "ai_report_status": ai_report_status,
        "ai_report_label": ai_report_label,
        "ai_report_ready": ai_report_status == "ready",
        "ai_report_count": 1 if ai_report_status == "ready" else 0,
        "ai_report_updated_at": "2026-04-22 12:05:00" if ai_report_status == "ready" else "",
        "archived": False,
        "pinned": False,
    }


def build_conversation_detail(conv_id: str, role_name: str, results: list[dict]) -> dict:
    return {
        "id": conv_id,
        "status": "completed",
        "model_id": "doubao-pro",
        "prompt_version": "测试提示词_v1.md",
        "summary_prompt_version": "摘要提示词_v1.md",
        "scoring_prompt_version": "长文模式打分提示词_v4.1_20260422.md",
        "scoring_model_id": "qwen-plus",
        "total_turns": len(results),
        "results": deepcopy(results),
        "turns": deepcopy(results),
        "config": {
            "character": {
                "Role_Nickname": role_name,
                "personal_type": "测试角色",
                "gender": "女",
            },
            "context": {"relationship": "暧昧"},
            "runtime": {
                "total_turns": len(results),
                "next_turn_index": len(results),
                "resume_supported": False,
                "scoring_model_id": "qwen-plus",
                "scoring_prompt_version": "长文模式打分提示词_v4.1_20260422.md",
            },
        },
    }


def build_scoring_payload(
    conv_id: str,
    turns: list[dict],
    *,
    avg_total: float | None,
    scored_count: int,
    failed_count: int,
    skipped_count: int,
    report_status: str,
    report_label: str,
    recommended_action: str,
    recommended_action_label: str,
    scoring_active: bool = False,
) -> dict:
    summary = {
        "avg_total": avg_total,
        "scored_count": scored_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count,
        "total_count": len(turns),
        "report_status": report_status,
        "report_label": report_label,
        "report_ready": report_status == "ready",
        "report_updated_at": "2026-04-22 12:06:00" if report_status == "ready" else "",
        "scoring_active": scoring_active,
        "recommended_action": recommended_action,
        "recommended_action_label": recommended_action_label,
    }
    meta = {
        "model_id": "doubao-pro",
        "summary_prompt_version": "摘要提示词_v1.md",
        "scoring_prompt_version": "长文模式打分提示词_v4.1_20260422.md",
        "scoring_model_id": "qwen-plus",
        "prompt_version": "测试提示词_v1.md",
        "ai_report_status": report_status,
        "ai_report_label": report_label,
        "ai_report_ready": report_status == "ready",
        "ai_report_updated_at": summary["report_updated_at"],
        "dialogue_summary": "测试摘要",
        "scoring_active": scoring_active,
        "recommended_action": recommended_action,
        "recommended_action_label": recommended_action_label,
    }
    scoring_turns = []
    for item in turns:
        scoring_turns.append(
            {
                "turn": item["turn"],
                "scores": {
                    "persona_fidelity": item.get("score_persona_fidelity", 0),
                    "narrative_immersion": item.get("score_narrative_immersion", 0),
                    "emotional_tension": item.get("score_emotional_tension", 0),
                    "boundary_memory": item.get("score_boundary_memory", 0),
                    "format_compliance": item.get("score_format_compliance", 0),
                    "context_coherence": item.get("score_context_coherence", 0),
                },
                "total": item.get("score_total", 0),
                "reasoning": item.get("score_reasoning", ""),
                "status": item.get("score_status", "unscored"),
                "manual_star_score": None,
                "manual_comment": "",
            }
        )
    return {
        "conversation_id": conv_id,
        "meta": meta,
        "summary": summary,
        "action": {
            "scoring_active": scoring_active,
            "recommended_action": recommended_action,
            "recommended_action_label": recommended_action_label,
        },
        "turns": scoring_turns,
    }


async def main():
    print("开始执行 scoring action 浏览器回归...")
    summary_turns = [
        make_turn(1, "第一轮输入", "第一轮输出", score_status="scored", score_total=8.1, reasoning="稳定"),
        make_turn(2, "第二轮输入", "第二轮输出", score_status="scored", score_total=8.3, reasoning="稳定"),
    ]
    retry_turns = [
        make_turn(1, "第一轮输入", "第一轮输出", score_status="scored", score_total=7.1, reasoning="可用"),
        make_turn(2, "第二轮输入", "第二轮输出", score_status="failed", score_total=0.0, reasoning="超时"),
        make_turn(3, "第三轮输入", "第三轮输出", score_status="unscored", score_total=0.0, reasoning=""),
    ]
    batch_failed_turns = [
        make_turn(1, "第一轮输入", "第一轮输出", score_status="failed", score_total=0.0, reasoning="超时"),
        make_turn(2, "第二轮输入", "第二轮输出", score_status="unscored", score_total=0.0, reasoning=""),
        make_turn(3, "第三轮输入", "第三轮输出", score_status="unscored", score_total=0.0, reasoning=""),
    ]

    history_items = {
        "conv-summary": build_history_item(
            "conv-summary",
            "待汇总会话",
            status="completed",
            total_turns=2,
            scored_turns=2,
            failed_turns=0,
            skipped_turns=0,
            score_avg=8.2,
            ai_report_status="pending",
            ai_report_label="等待生成报告",
        ),
        "conv-retry": build_history_item(
            "conv-retry",
            "待重试会话",
            status="completed",
            total_turns=3,
            scored_turns=1,
            failed_turns=1,
            skipped_turns=0,
            score_avg=7.1,
            ai_report_status="waiting_scoring",
            ai_report_label="待评分完成",
        ),
    }
    detail_items = {
        "conv-summary": build_conversation_detail("conv-summary", "待汇总会话", summary_turns),
        "conv-retry": build_conversation_detail("conv-retry", "待重试会话", retry_turns),
        "conv-batch-failed": build_conversation_detail("conv-batch-failed", "批量失败会话", batch_failed_turns),
    }
    scoring_items = {
        "conv-summary": build_scoring_payload(
            "conv-summary",
            summary_turns,
            avg_total=8.2,
            scored_count=2,
            failed_count=0,
            skipped_count=0,
            report_status="pending",
            report_label="等待生成报告",
            recommended_action="repair_summary",
            recommended_action_label="汇总评分",
        ),
        "conv-retry": build_scoring_payload(
            "conv-retry",
            retry_turns,
            avg_total=7.1,
            scored_count=1,
            failed_count=1,
            skipped_count=0,
            report_status="waiting_scoring",
            report_label="待评分完成",
            recommended_action="retry_failed_turns",
            recommended_action_label="重试失败项",
        ),
        "conv-batch-failed": build_scoring_payload(
            "conv-batch-failed",
            batch_failed_turns,
            avg_total=None,
            scored_count=0,
            failed_count=1,
            skipped_count=0,
            report_status="waiting_scoring",
            report_label="待评分完成",
            recommended_action="",
            recommended_action_label="",
        ),
    }
    for container_key in ("summary", "meta", "action"):
        scoring_items["conv-batch-failed"][container_key].pop("recommended_action", None)
        scoring_items["conv-batch-failed"][container_key].pop("recommended_action_label", None)
    results_call_count = {"conv-summary": 0, "conv-retry": 0}
    request_log: list[str] = []

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1680, "height": 1080})

            async def fulfill_history(route):
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"conversations": list(history_items.values())}, ensure_ascii=False),
                )

            async def fulfill_conversation_detail(route):
                conv_id = urlparse(route.request.url).path.rsplit("/", 1)[-1]
                payload = detail_items.get(conv_id)
                if payload is None:
                    await route.fulfill(status=404, content_type="application/json", body=json.dumps({"detail": "not found"}))
                    return
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(payload, ensure_ascii=False),
                )

            async def fulfill_scoring(route):
                path = urlparse(route.request.url).path
                request_log.append(f"{route.request.method} {path}")
                if path.endswith("/conv-summary/results"):
                    if results_call_count["conv-summary"] == 0:
                        await asyncio.sleep(0.35)
                    results_call_count["conv-summary"] += 1
                    await route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps(scoring_items["conv-summary"], ensure_ascii=False),
                    )
                    return
                if path.endswith("/conv-retry/results"):
                    results_call_count["conv-retry"] += 1
                    await route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps(scoring_items["conv-retry"], ensure_ascii=False),
                    )
                    return
                if path.endswith("/conv-batch-failed/results"):
                    await route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps(scoring_items["conv-batch-failed"], ensure_ascii=False),
                    )
                    return
                if path.endswith("/conv-summary/repair-summary"):
                    scoring_items["conv-summary"] = build_scoring_payload(
                        "conv-summary",
                        summary_turns,
                        avg_total=8.2,
                        scored_count=2,
                        failed_count=0,
                        skipped_count=0,
                        report_status="ready",
                        report_label="报告就绪",
                        recommended_action="view_results",
                        recommended_action_label="查看结果",
                    )
                    history_items["conv-summary"].update(
                        {
                            "ai_report_status": "ready",
                            "ai_report_label": "报告就绪",
                            "ai_report_ready": True,
                            "ai_report_count": 1,
                            "ai_report_updated_at": "2026-04-22 12:06:00",
                        }
                    )
                    response_payload = deepcopy(scoring_items["conv-summary"])
                    response_payload["status"] = "summary_repaired"
                    response_payload["report"] = {"markdown": "# 测试报告"}
                    await route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps(response_payload, ensure_ascii=False),
                    )
                    return
                if path.endswith("/conv-retry/retry-failed-turns"):
                    retry_completed_turns = [
                        make_turn(1, "第一轮输入", "第一轮输出", score_status="scored", score_total=7.1, reasoning="可用"),
                        make_turn(2, "第二轮输入", "第二轮输出", score_status="scored", score_total=7.8, reasoning="重试成功"),
                        make_turn(3, "第三轮输入", "第三轮输出", score_status="scored", score_total=8.0, reasoning="补打完成"),
                    ]
                    detail_items["conv-retry"] = build_conversation_detail("conv-retry", "待重试会话", retry_completed_turns)
                    scoring_items["conv-retry"] = build_scoring_payload(
                        "conv-retry",
                        retry_completed_turns,
                        avg_total=7.63,
                        scored_count=3,
                        failed_count=0,
                        skipped_count=0,
                        report_status="pending",
                        report_label="等待生成报告",
                        recommended_action="repair_summary",
                        recommended_action_label="汇总评分",
                    )
                    history_items["conv-retry"].update(
                        {
                            "scored_turns": 3,
                            "failed_turns": 0,
                            "score_avg": 7.63,
                            "ai_report_status": "pending",
                            "ai_report_label": "等待生成报告",
                        }
                    )
                    await route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps(
                            {
                                "status": "scoring_started",
                                "conversation_id": "conv-retry",
                                "turns_to_score": 2,
                                "action": {
                                    "recommended_action": "retry_failed_turns",
                                    "recommended_action_label": "重试失败项",
                                },
                            },
                            ensure_ascii=False,
                        ),
                    )
                    return
                if path.endswith("/conv-batch-failed/retry-failed-turns"):
                    batch_completed_turns = [
                        make_turn(1, "第一轮输入", "第一轮输出", score_status="scored", score_total=7.2, reasoning="重试成功"),
                        make_turn(2, "第二轮输入", "第二轮输出", score_status="scored", score_total=7.6, reasoning="补打完成"),
                        make_turn(3, "第三轮输入", "第三轮输出", score_status="scored", score_total=7.8, reasoning="补打完成"),
                    ]
                    detail_items["conv-batch-failed"] = build_conversation_detail("conv-batch-failed", "批量失败会话", batch_completed_turns)
                    scoring_items["conv-batch-failed"] = build_scoring_payload(
                        "conv-batch-failed",
                        batch_completed_turns,
                        avg_total=7.53,
                        scored_count=3,
                        failed_count=0,
                        skipped_count=0,
                        report_status="pending",
                        report_label="等待生成报告",
                        recommended_action="repair_summary",
                        recommended_action_label="汇总评分",
                    )
                    await route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps(
                            {
                                "status": "scoring_started",
                                "conversation_id": "conv-batch-failed",
                                "turns_to_score": 3,
                                "action": {
                                    "recommended_action": "retry_failed_turns",
                                    "recommended_action_label": "重试失败项",
                                },
                            },
                            ensure_ascii=False,
                        ),
                    )
                    return
                if path.endswith("/rescore-all"):
                    await route.fulfill(
                        status=500,
                        content_type="application/json",
                        body=json.dumps({"detail": "不应走到 rescore-all"}, ensure_ascii=False),
                    )
                    return
                if path.endswith("/resume-sync"):
                    await route.fulfill(
                        status=500,
                        content_type="application/json",
                        body=json.dumps({"detail": "本用例不应走到 resume-sync"}, ensure_ascii=False),
                    )
                    return
                await route.continue_()

            async def fulfill_empty_active_run(route):
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"run": None}, ensure_ascii=False),
                )

            async def fulfill_empty_ab_session(route):
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body="null",
                )

            await page.route("**/api/conversations?*", fulfill_history)
            await page.route("**/api/conversations/conv-*", fulfill_conversation_detail)
            await page.route("**/api/scoring/**", fulfill_scoring)
            await page.route("**/api/orchestrations/active?kind=batch*", fulfill_empty_active_run)
            await page.route("**/api/orchestrations/active?kind=compare*", fulfill_empty_active_run)
            await page.route("**/api/orchestrations/active?kind=ab*", fulfill_empty_active_run)
            await page.route("**/api/orchestrations/latest?kind=batch*", fulfill_empty_active_run)
            await page.route("**/api/orchestrations/latest?kind=compare*", fulfill_empty_active_run)
            await page.route("**/api/orchestrations/latest?kind=ab*", fulfill_empty_active_run)
            await page.route("**/api/ab-sessions/active", fulfill_empty_ab_session)

            await page.goto(BASE_URL, wait_until="domcontentloaded")
            await page.wait_for_timeout(1200)

            await page.wait_for_function(
                "() => (document.getElementById('history-tbody')?.innerText || '').includes('汇总评分')",
                timeout=8000,
            )
            history_text = await page.locator("#history-tbody").text_content()
            if "汇总评分" not in (history_text or ""):
                raise AssertionError("历史列表未显示“汇总评分”动作")
            if "重试失败项" not in (history_text or ""):
                raise AssertionError("历史列表未显示“重试失败项”动作")

            await page.evaluate("() => viewConversation('conv-summary')")
            await page.wait_for_timeout(600)
            await page.evaluate("() => { void triggerScoring(); }")
            await page.wait_for_timeout(80)
            avg_during_sync = (await page.locator("#score-avg").text_content() or "").strip()
            if avg_during_sync != "--":
                raise AssertionError(f"一键打分开始后均分应先显示 --，实际为: {avg_during_sync}")

            await page.wait_for_function(
                "() => (document.getElementById('score-avg')?.textContent || '').trim() === '8.2'",
                timeout=8000,
            )
            avg_after_repair = (await page.locator("#score-avg").text_content() or "").strip()
            if avg_after_repair != "8.2":
                raise AssertionError(f"汇总评分完成后均分未更新为 8.2，实际为: {avg_after_repair}")

            await page.evaluate("() => retryFailedScoringForConv('conv-retry', null)")
            await page.wait_for_timeout(1500)

            await page.evaluate("() => triggerConversationScoringFromBatch('conv-batch-failed', null)")
            await page.wait_for_timeout(1500)

            history_text_after_retry = await page.locator("#history-tbody").text_content()
            if "7.6" not in (history_text_after_retry or ""):
                raise AssertionError(f"重试失败项后历史列表未更新综合评分: {history_text_after_retry}")

            if "POST /api/scoring/conv-summary/repair-summary" not in request_log:
                raise AssertionError(f"一键打分未命中 repair-summary: {request_log}")
            if "POST /api/scoring/conv-retry/retry-failed-turns" not in request_log:
                raise AssertionError(f"历史重试未命中 retry-failed-turns: {request_log}")
            if "POST /api/scoring/conv-batch-failed/retry-failed-turns" not in request_log:
                raise AssertionError(f"批量行重试未命中 retry-failed-turns: {request_log}")
            if any(path.endswith("/rescore-all") for path in request_log):
                raise AssertionError(f"本次回归不应触发 rescore-all: {request_log}")

            await browser.close()
            print("scoring action 浏览器回归通过")
    except Exception as exc:
        print(f"scoring action 浏览器回归失败: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
