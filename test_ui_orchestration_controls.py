import asyncio
import json
import os
import sys

from playwright.async_api import async_playwright


BASE_URL = os.environ.get("LONGFORM_UI_BASE_URL", "http://127.0.0.1:8000/")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def build_batch_run(status: str) -> dict:
    is_cancelling = status == "cancelling"
    item_status = "running" if is_cancelling else status
    terminal_items = 1 if status == "cancelled" else 0
    cancelled_items = 1 if status == "cancelled" else 0
    return {
        "id": "batch-run",
        "kind": "batch",
        "title": "批量恢复任务",
        "status": status,
        "created_at": "2026-04-21 10:00:00",
        "updated_at": "2026-04-21 10:00:00",
        "summary": {
            "total_items": 1,
            "terminal_items": terminal_items,
            "completed_items": 0,
            "failed_items": 0,
            "cancelled_items": cancelled_items,
        },
        "manifest": {
            "kind": "batch",
            "title": "批量恢复任务",
            "concurrency": 1,
            "groups": [
                {
                    "key": "group:1",
                    "label": "角色A",
                    "relationship": "暧昧",
                    "planned_turns": 2,
                    "items": [
                        {
                            "key": "group:1:item:1",
                            "label": "角色A",
                            "relationship": "暧昧",
                            "model_id": "doubao-pro",
                            "planned_turns": 2,
                            "payload": {
                                "nickname": "角色A",
                                "relationship": "暧昧",
                                "turns": ["第一轮", "第二轮"],
                                "model_id": "doubao-pro",
                                "dry_run": False,
                            },
                        }
                    ],
                }
            ],
        },
        "groups": [
            {
                "key": "group:1",
                "label": "角色A",
                "relationship": "暧昧",
                "planned_turns": 2,
                "status": item_status,
                "items": [
                    {
                        "key": "group:1:item:1",
                        "label": "角色A",
                        "relationship": "暧昧",
                        "model_id": "doubao-pro",
                        "planned_turns": 2,
                        "conversation_id": "batch-conv-1",
                        "status": item_status,
                        "turn_count": 1,
                        "avg_chars": 123,
                        "avg_score": None,
                        "resume_supported": False,
                        "error": "",
                    }
                ],
            }
        ],
    }


def build_compare_run(status: str) -> dict:
    is_retryable_terminal = status == "completed_retryable"
    is_cancelling = status == "cancelling"
    normalized_status = "completed" if is_retryable_terminal else status
    first_item_status = "running" if is_cancelling else ("completed" if is_retryable_terminal else normalized_status)
    second_item_status = "cancelled" if is_cancelling else ("failed" if is_retryable_terminal else normalized_status)
    return {
        "id": "compare-run",
        "kind": "compare",
        "title": "对比恢复任务",
        "status": normalized_status,
        "created_at": "2026-04-21 10:00:00",
        "updated_at": "2026-04-21 10:00:00",
        "summary": {
            "total_items": 2,
            "terminal_items": 1 if is_cancelling else (2 if is_retryable_terminal else 0),
            "completed_items": 1 if is_retryable_terminal else 0,
            "failed_items": 1 if is_retryable_terminal else 0,
            "cancelled_items": 1 if is_cancelling else 0,
        },
        "manifest": {
            "kind": "compare",
            "title": "对比恢复任务",
            "concurrency": 2,
            "groups": [
                {
                    "key": "compare:1",
                    "label": "角色B",
                    "relationship": "拉扯",
                    "planned_turns": 2,
                    "items": [
                        {
                            "key": "compare:1:item:1",
                            "label": "模型甲",
                            "relationship": "拉扯",
                            "model_id": "model-a",
                            "planned_turns": 2,
                            "payload": {
                                "nickname": "角色B",
                                "relationship": "拉扯",
                                "turns": ["第一轮", "第二轮"],
                                "model_id": "model-a",
                                "model_ids": ["model-a", "model-b"],
                            },
                        },
                        {
                            "key": "compare:1:item:2",
                            "label": "模型乙",
                            "relationship": "拉扯",
                            "model_id": "model-b",
                            "planned_turns": 2,
                            "payload": {
                                "nickname": "角色B",
                                "relationship": "拉扯",
                                "turns": ["第一轮", "第二轮"],
                                "model_id": "model-b",
                                "model_ids": ["model-a", "model-b"],
                            },
                        },
                    ],
                }
            ],
        },
        "groups": [
            {
                "key": "compare:1",
                "label": "角色B",
                "relationship": "拉扯",
                "planned_turns": 2,
                "status": normalized_status if not is_cancelling else "running",
                "items": [
                    {
                        "key": "compare:1:item:1",
                        "label": "模型甲",
                        "relationship": "拉扯",
                        "model_id": "model-a",
                        "planned_turns": 2,
                        "conversation_id": "compare-conv-a",
                        "status": first_item_status,
                        "turn_count": 2 if is_retryable_terminal else 1,
                        "avg_chars": 111,
                        "avg_score": None,
                        "resume_supported": False,
                        "error": "",
                    },
                    {
                        "key": "compare:1:item:2",
                        "label": "模型乙",
                        "relationship": "拉扯",
                        "model_id": "model-b",
                        "planned_turns": 2,
                        "conversation_id": "compare-conv-b",
                        "status": second_item_status,
                        "turn_count": 1,
                        "avg_chars": 118,
                        "avg_score": None,
                        "resume_supported": False,
                        "error": "第二个模型执行失败" if is_retryable_terminal else ("任务已取消" if is_cancelling else ""),
                    },
                ],
            }
        ],
    }


def build_paused_conversation(status: str) -> dict:
    return {
        "id": "conv-paused",
        "status": status,
        "model_id": "doubao-pro",
        "prompt_version": "测试提示词.md",
        "summary_prompt_version": "摘要提示词.md",
        "scoring_prompt_version": "长文模式打分提示词_v4.0_20260421.md",
        "scoring_model_id": "qwen-plus",
        "total_turns": 3,
        "next_turn_index": 1,
        "resume_supported": True,
        "results": [
            {
                "turn": 1,
                "user_input": "第一轮",
                "ai_output": "先停在这里。",
                "model_id": "doubao-pro",
            }
        ],
        "config": {
            "character": {
                "Role_Nickname": "暂停会话",
                "gender": "男",
                "personality": "冷静克制",
            },
            "context": {"relationship": "暧昧"},
            "modules": {},
            "runtime": {
                "conversation_mode": "batch",
                "turns": ["第一轮", "第二轮", "第三轮"],
                "total_turns": 3,
                "next_turn_index": 1,
                "resume_supported": True,
                "active_model_id": "doubao-pro",
                "model_ids": ["doubao-pro"],
            },
        },
    }


async def wait_displayed(page, selector: str, message: str):
    try:
        await page.wait_for_function(
            """
            (targetSelector) => {
              const el = document.querySelector(targetSelector);
              return !!el && getComputedStyle(el).display !== 'none';
            }
            """,
            arg=selector,
            timeout=6000,
        )
    except Exception as exc:
        raise AssertionError(message) from exc


async def main():
    print("开始执行 orchestration/control 浏览器冒烟...")
    batch_status = {"value": "paused"}
    compare_status = {"value": "paused"}
    conversation_status = {"value": "paused"}
    batch_cancel_poll_count = {"value": 0}
    compare_cancel_poll_count = {"value": 0}

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1600, "height": 1000})

            async def fulfill_active_batch(route):
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"run": build_batch_run(batch_status["value"])}, ensure_ascii=False),
                )

            async def fulfill_active_compare(route):
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"run": build_compare_run(compare_status["value"])}, ensure_ascii=False),
                )

            async def fulfill_active_ab(route):
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"run": None}, ensure_ascii=False),
                )

            async def fulfill_run_detail(route):
                url = route.request.url
                if url.endswith("/batch-run"):
                    if batch_status["value"] == "cancelling":
                        batch_cancel_poll_count["value"] += 1
                        if batch_cancel_poll_count["value"] >= 2:
                            batch_status["value"] = "cancelled"
                    payload = build_batch_run(batch_status["value"])
                else:
                    if compare_status["value"] == "cancelling":
                        compare_cancel_poll_count["value"] += 1
                        if compare_cancel_poll_count["value"] >= 2:
                            compare_status["value"] = "cancelled"
                    payload = build_compare_run(compare_status["value"])
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(payload, ensure_ascii=False),
                )

            async def fulfill_run_control(route):
                body = json.loads(route.request.post_data or "{}")
                action = body.get("action")
                if "/batch-run/control" in route.request.url:
                    if action == "cancel":
                        batch_cancel_poll_count["value"] = 0
                    batch_status["value"] = (
                        "running" if action == "resume" else "paused" if action == "pause" else "cancelling"
                    )
                    payload = build_batch_run(batch_status["value"])
                else:
                    if action == "cancel":
                        compare_cancel_poll_count["value"] = 0
                    compare_status["value"] = (
                        "running" if action == "resume" else "paused" if action == "pause" else "cancelling"
                    )
                    payload = build_compare_run(compare_status["value"])
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(payload, ensure_ascii=False),
                )

            async def fulfill_conversation_detail(route):
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(build_paused_conversation(conversation_status["value"]), ensure_ascii=False),
                )

            async def fulfill_conversation_control(route):
                body = json.loads(route.request.post_data or "{}")
                action = body.get("action")
                if action == "resume":
                    conversation_status["value"] = "queued"
                    payload = {"id": "conv-paused", "status": "queued"}
                elif action == "pause":
                    conversation_status["value"] = "paused"
                    payload = {"id": "conv-paused", "status": "paused"}
                else:
                    conversation_status["value"] = "cancelled"
                    payload = {"id": "conv-paused", "status": "cancelling"}
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(payload, ensure_ascii=False),
                )

            await page.route("**/api/orchestrations/active?kind=batch*", fulfill_active_batch)
            await page.route("**/api/orchestrations/active?kind=compare*", fulfill_active_compare)
            await page.route("**/api/orchestrations/active?kind=ab*", fulfill_active_ab)
            await page.route("**/api/orchestrations/batch-run", fulfill_run_detail)
            await page.route("**/api/orchestrations/compare-run", fulfill_run_detail)
            await page.route("**/api/orchestrations/*/control", fulfill_run_control)
            await page.route("**/api/conversations/conv-paused/control", fulfill_conversation_control)
            await page.route("**/api/conversations/conv-paused", fulfill_conversation_detail)

            await page.goto(BASE_URL, wait_until="networkidle")
            await page.wait_for_timeout(1500)

            current_page = await page.evaluate("() => getCurrentPageName()")
            if current_page != "test-center":
                raise AssertionError(f"恢复任务后未自动回到测试中心: {current_page}")
            batch_mode_active = await page.locator("#tc-mode-batch").evaluate("el => el.classList.contains('active')")
            if not batch_mode_active:
                raise AssertionError("恢复任务后未自动聚焦到上次/默认测试中心子 tab")
            await page.evaluate("() => switchTestCenterMode('batch')")
            await page.wait_for_timeout(300)
            await wait_displayed(page, "#batch-control-row", "批量恢复后未显示控制区")
            if await page.locator("#btn-batch-resume").evaluate("el => getComputedStyle(el).display") == "none":
                raise AssertionError("批量恢复任务未显示继续按钮")
            await page.evaluate("() => resumeBatchTest()")
            await page.wait_for_timeout(400)
            if await page.locator("#btn-batch-pause").evaluate("el => getComputedStyle(el).display") == "none":
                raise AssertionError("批量任务恢复后未切换到暂停按钮")
            if await page.locator("#btn-batch-stop").evaluate("el => getComputedStyle(el).display") == "none":
                raise AssertionError("批量任务恢复后未显示停止按钮")
            await page.evaluate("() => document.getElementById('btn-batch-stop')?.click()")
            await page.wait_for_timeout(400)
            batch_progress_text = await page.locator("#batch-progress-text").text_content()
            if "停止中" not in (batch_progress_text or ""):
                raise AssertionError(f"批量任务停止中状态未展示: {batch_progress_text}")
            if not await page.locator("#btn-batch-stop").evaluate("el => el.disabled"):
                raise AssertionError("批量任务停止中按钮未禁用")
            batch_row_display = await page.locator("#batch-control-row").evaluate("el => getComputedStyle(el).display")
            if batch_row_display == "none":
                raise AssertionError("批量任务停止中控制区不应提前隐藏")
            await page.wait_for_timeout(2800)
            batch_row_display = await page.locator("#batch-control-row").evaluate("el => getComputedStyle(el).display")
            if batch_row_display != "none":
                raise AssertionError("批量任务最终取消后控制区未隐藏")

            await page.evaluate("() => switchTestCenterMode('compare')")
            await page.wait_for_timeout(400)
            await wait_displayed(page, "#compare-control-row", "对比恢复后未显示控制区")
            if await page.locator("#btn-compare-resume").evaluate("el => getComputedStyle(el).display") == "none":
                raise AssertionError("对比恢复任务未显示继续按钮")
            await page.evaluate("() => resumeCompareTest()")
            await page.wait_for_timeout(400)
            if await page.locator("#btn-compare-pause").evaluate("el => getComputedStyle(el).display") == "none":
                raise AssertionError("对比任务恢复后未切换到暂停按钮")
            if await page.locator("#btn-compare-stop").evaluate("el => getComputedStyle(el).display") == "none":
                raise AssertionError("对比任务恢复后未显示停止按钮")
            await page.evaluate("() => document.getElementById('btn-compare-stop')?.click()")
            await page.wait_for_timeout(400)
            compare_progress_text = await page.locator("#compare-progress-text").text_content()
            if "停止中" not in (compare_progress_text or ""):
                raise AssertionError(f"模型对比停止中状态未展示: {compare_progress_text}")
            if not await page.locator("#btn-compare-stop").evaluate("el => el.disabled"):
                raise AssertionError("模型对比停止中按钮未禁用")
            compare_row_display = await page.locator("#compare-control-row").evaluate("el => getComputedStyle(el).display")
            if compare_row_display == "none":
                raise AssertionError("模型对比停止中控制区不应提前隐藏")
            await page.wait_for_timeout(2800)
            compare_row_display = await page.locator("#compare-control-row").evaluate("el => getComputedStyle(el).display")
            if compare_row_display == "none":
                raise AssertionError("模型对比最终取消后应保留重试控制区")
            if await page.locator("#btn-compare-stop").evaluate("el => getComputedStyle(el).display") != "none":
                raise AssertionError("模型对比最终取消后停止按钮未隐藏")
            if await page.locator("#btn-compare-retry").evaluate("el => getComputedStyle(el).display") == "none":
                raise AssertionError("模型对比最终取消后未显示重试按钮")
            await page.evaluate(
                "(payload) => { applyCompareOrchestrationRun(payload); }",
                build_compare_run("completed_retryable"),
            )
            await page.wait_for_timeout(300)
            await wait_displayed(page, "#compare-control-row", "对比失败后未显示重试控制区")
            if await page.locator("#btn-compare-retry").evaluate("el => getComputedStyle(el).display") == "none":
                raise AssertionError("对比失败后未显示重试未完成项按钮")
            failed_text = await page.locator("#compare-progress-failed").text_content()
            if "未完成" not in (failed_text or ""):
                raise AssertionError(f"对比失败计数未显示: {failed_text}")

            await page.evaluate("() => viewConversation('conv-paused')")
            await page.wait_for_timeout(700)
            await wait_displayed(page, "#chat-control-row", "暂停会话未显示控制区")
            if await page.locator("#btn-chat-resume").evaluate("el => getComputedStyle(el).display") == "none":
                raise AssertionError("暂停会话未显示继续按钮")
            await page.evaluate("() => resumeActiveConversation()")
            await page.wait_for_timeout(400)
            if await page.locator("#btn-chat-pause").evaluate("el => getComputedStyle(el).display") == "none":
                raise AssertionError("会话恢复后未切换到暂停按钮")
            await page.evaluate("() => cancelActiveConversation()")
            await page.wait_for_timeout(400)
            row_display = await page.locator("#chat-control-row").evaluate("el => getComputedStyle(el).display")
            if row_display != "none":
                raise AssertionError("取消会话后控制区未隐藏")

            await browser.close()
            print("orchestration/control 浏览器冒烟通过")
    except Exception as exc:
        print(f"orchestration/control 浏览器冒烟失败: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
