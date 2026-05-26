import asyncio
import json
import os
import sys

from playwright.async_api import async_playwright


BASE_URL = os.environ.get("LONGFORM_UI_BASE_URL", "http://127.0.0.1:8000/static/index.html")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


MODELS_PAYLOAD = {
    "models": [
        {
            "id": "qwen3.6-plus",
            "name": "qwen3.6-plus",
            "provider": "dashscope",
            "capabilities": {"thinking": True, "web_search": True},
        },
        {
            "id": "deepseek-v4-pro",
            "name": "deepseek-v4-pro",
            "provider": "dashscope",
            "capabilities": {"thinking": True, "web_search": True},
        },
        {
            "id": "doubao-character",
            "name": "doubao-character",
            "provider": "volcengine",
            "capabilities": {"thinking": False, "web_search": False},
        },
    ]
}


async def main():
    print("开始执行 freechat 详情预览不跳转 E2E...")
    interactive_count = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 920})
        await page.add_init_script("() => localStorage.clear()")

        async def fulfill_models(route):
            await route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(MODELS_PAYLOAD, ensure_ascii=False),
            )

        async def fulfill_interactive(route):
            nonlocal interactive_count
            interactive_count += 1
            await route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"id": f"freechat-conv-{interactive_count}"}, ensure_ascii=False),
            )

        async def fulfill_generate(route):
            payload = json.loads(route.request.post_data or "{}")
            conv_id = route.request.url.split("/api/conversations/")[1].split("/generate")[0]
            await route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "success": True,
                        "turn": 1,
                        "model_id": payload.get("model_id"),
                        "ai_output": f"{payload.get('model_id')} preview ok",
                        "input_tokens": 10,
                        "output_tokens": 12,
                        "latency_s": 0.1,
                        "conversation_id": conv_id,
                    },
                    ensure_ascii=False,
                ),
            )

        async def fulfill_conversation_detail(route):
            conv_id = route.request.url.rsplit("/", 1)[-1]
            await route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "id": conv_id,
                        "model_id": "qwen3.6-plus",
                        "status": "completed",
                        "turns": [
                            {
                                "turn": 1,
                                "user_input": "预览这一轮",
                                "ai_output": "这是详情弹窗里的模型输出",
                                "model_id": "qwen3.6-plus",
                                "input_tokens": 10,
                                "output_tokens": 12,
                                "latency_s": 0.1,
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
            )

        await page.route("**/api/models**", fulfill_models)
        await page.route("**/api/conversations/interactive", fulfill_interactive)
        await page.route("**/api/conversations/*/generate", fulfill_generate)
        await page.route("**/api/conversations/freechat-conv-*", fulfill_conversation_detail)

        await page.goto(BASE_URL, wait_until="domcontentloaded")
        await page.evaluate("() => toggleCompareMode()")
        await page.wait_for_selector(".fc-thinking-select", state="visible", timeout=5000)
        await page.click("#btn-add-model-slot")
        await page.click("#btn-add-model-slot")

        await page.locator("#freechat-input").fill("预览这一轮")
        await page.locator("#freechat-input").press("Enter")
        await page.wait_for_selector("button:has-text('预览详情')", timeout=5000)

        before_state = await page.evaluate(
            """
            () => ({
              freechatActive: document.querySelector('#page-freechat')?.classList.contains('active'),
              compareActive: window._compareModeActive,
              slotCount: document.querySelectorAll('.fc-model-slot').length,
              replyCount: document.querySelectorAll('#freechat-area .chat-bubble.ai:not(.chat-bubble-loading)').length,
            })
            """
        )
        if not before_state["freechatActive"] or before_state["slotCount"] != 3 or before_state["replyCount"] < 3:
            raise AssertionError(f"自由聊天发送后的初始状态异常: {before_state}")

        await page.locator("button", has_text="预览详情").first.click()
        await page.wait_for_selector("#modal-freechat-conversation[aria-hidden='false']", timeout=5000)
        await page.wait_for_selector("#freechat-conversation-body >> text=这是详情弹窗里的模型输出", timeout=5000)

        after_state = await page.evaluate(
            """
            () => ({
              freechatActive: document.querySelector('#page-freechat')?.classList.contains('active'),
              chatActive: document.querySelector('#page-chat')?.classList.contains('active'),
              compareActive: window._compareModeActive,
              slotCount: document.querySelectorAll('.fc-model-slot').length,
              replyCount: document.querySelectorAll('#freechat-area .chat-bubble.ai:not(.chat-bubble-loading)').length,
            })
            """
        )
        await page.locator("#btn-freechat-open-full-conversation").click()
        await page.wait_for_selector("#page-chat.active", timeout=5000)
        full_detail_state = await page.evaluate(
            """
            () => ({
              chatActive: document.querySelector('#page-chat')?.classList.contains('active'),
              compareActive: window._compareModeActive,
              returnVisible: getComputedStyle(document.querySelector('#btn-return-freechat')).display !== 'none',
              slotCount: document.querySelectorAll('.fc-model-slot').length,
              replyCount: document.querySelectorAll('#freechat-area .chat-bubble.ai:not(.chat-bubble-loading)').length,
            })
            """
        )
        await page.locator("#btn-return-freechat").click()
        await page.wait_for_selector("#page-freechat.active", timeout=5000)
        returned_state = await page.evaluate(
            """
            () => ({
              freechatActive: document.querySelector('#page-freechat')?.classList.contains('active'),
              compareButtonActive: getComputedStyle(document.querySelector('#btn-toggle-compare')).backgroundColor !== 'rgba(0, 0, 0, 0)',
              slotCount: document.querySelectorAll('.fc-model-slot').length,
              replyCount: document.querySelectorAll('#freechat-area .chat-bubble.ai:not(.chat-bubble-loading)').length,
            })
            """
        )
        await browser.close()

    if not after_state["freechatActive"] or after_state["chatActive"]:
        raise AssertionError(f"预览详情不应跳转到单聊页: {after_state}")
    if after_state["slotCount"] != 3 or after_state["replyCount"] < 3:
        raise AssertionError(f"预览详情不应重置自由聊天工作台: {after_state}")
    if not full_detail_state["chatActive"] or full_detail_state["compareActive"] or not full_detail_state["returnVisible"]:
        raise AssertionError(f"进入完整会话后应显示返回模型对比入口: {full_detail_state}")
    if returned_state["slotCount"] != 3 or returned_state["replyCount"] < 3:
        raise AssertionError(f"返回模型对比不应重置自由聊天工作台: {returned_state}")
    if not returned_state["freechatActive"] or not returned_state["compareButtonActive"]:
        raise AssertionError(f"返回模型对比后页面状态异常: {returned_state}")

    print("PASS: freechat 详情预览和完整会话返回均保留 3 模型对比现场")


def test_freechat_detail_preview_keeps_compare_workspace():
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
