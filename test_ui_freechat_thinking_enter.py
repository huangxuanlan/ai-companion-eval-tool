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
            "capabilities": {"thinking": True, "web_search": True, "thinking_efforts": ["disabled", "high", "max"], "default_thinking_effort": "high"},
        },
        {
            "id": "deepseek-v4-pro",
            "name": "deepseek-v4-pro",
            "provider": "dashscope",
            "capabilities": {"thinking": True, "web_search": True, "thinking_efforts": ["disabled", "high", "max"], "default_thinking_effort": "high"},
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
    print("开始执行 freechat per-model thinking + Enter 发送 E2E...")
    interactive_count = 0
    captured_generate_payloads = []

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
            captured_generate_payloads.append(payload)
            await route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "success": True,
                        "turn": 1,
                        "model_id": payload.get("model_id"),
                        "ai_output": f"{payload.get('model_id')} ok",
                        "input_tokens": 10,
                        "output_tokens": 12,
                        "latency_s": 0.1,
                    },
                    ensure_ascii=False,
                ),
            )

        await page.route("**/api/models**", fulfill_models)
        await page.route("**/api/conversations/interactive", fulfill_interactive)
        await page.route("**/api/conversations/*/generate", fulfill_generate)

        await page.goto(BASE_URL, wait_until="domcontentloaded")
        await page.evaluate("() => toggleCompareMode()")
        await page.wait_for_selector(".fc-thinking-select", state="visible", timeout=5000)
        await page.click("#btn-add-model-slot")
        await page.click("#btn-add-model-slot")
        await page.wait_for_selector(".fc-model-slot:nth-child(3) .fc-thinking-select", timeout=5000)

        thinking_selects = page.locator(".fc-thinking-select")
        if await thinking_selects.count() != 3:
            raise AssertionError("自由聊天模型槽未渲染 3 个思考下拉")

        await thinking_selects.nth(0).select_option("max")
        await thinking_selects.nth(1).select_option("disabled")
        disabled_third = await thinking_selects.nth(2).is_disabled()
        if not disabled_third:
            raise AssertionError("不支持思考的模型没有禁用 per-slot 思考下拉")

        await page.locator("#freechat-input").fill("按 Enter 发送这一轮")
        await page.locator("#freechat-input").press("Enter")
        await page.wait_for_function("() => document.querySelector('#freechat-input').value === ''", timeout=5000)
        await page.wait_for_function(
            "() => document.querySelectorAll('.chat-bubble.ai:not(.chat-bubble-loading)').length >= 3",
            timeout=5000,
        )
        await page.route(
            "**/api/conversations/freechat-conv-1",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "id": "freechat-conv-1",
                        "model_id": "qwen3.6-plus",
                        "status": "completed",
                        "turns": [
                            {
                                "turn": 1,
                                "user_input": "按 Enter 发送这一轮",
                                "ai_output": "qwen3.6-plus ok",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        await page.locator("button", has_text="预览详情").first.click()
        await page.wait_for_selector("#modal-freechat-conversation", state="visible", timeout=5000)
        active_page = await page.evaluate("() => document.querySelector('.page.active')?.id")
        if active_page != "page-freechat":
            raise AssertionError(f"点击预览详情不应跳出模型对比页，当前页面: {active_page}")

        await browser.close()

    if len(captured_generate_payloads) != 3:
        raise AssertionError(f"Enter 发送后生成请求数量异常: {len(captured_generate_payloads)}")

    by_model = {payload["model_id"]: payload for payload in captured_generate_payloads}
    qwen_payload = by_model["qwen3.6-plus"]
    deepseek_payload = by_model["deepseek-v4-pro"]
    doubao_payload = by_model["doubao-character"]

    if qwen_payload.get("thinking_enabled") is not True or qwen_payload.get("thinking_effort") != "max":
        raise AssertionError(f"qwen per-slot thinking 未生效: {qwen_payload}")
    if deepseek_payload.get("thinking_enabled") is not False or deepseek_payload.get("thinking_effort") != "disabled":
        raise AssertionError(f"deepseek per-slot thinking 未关闭: {deepseek_payload}")
    if doubao_payload.get("thinking_enabled") is not False or doubao_payload.get("thinking_effort") != "disabled":
        raise AssertionError(f"doubao unsupported thinking 未禁用: {doubao_payload}")

    print("PASS: freechat Enter 发送与 per-model thinking 请求体均正确")


def test_freechat_enter_and_per_model_thinking_e2e():
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
