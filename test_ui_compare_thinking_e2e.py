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
            "name": "doubao-seed-character-251128",
            "provider": "volcengine",
            "capabilities": {"thinking": False, "web_search": False},
        },
    ]
}


async def main():
    print("开始执行 compare per-model thinking 浏览器 E2E...")
    captured_payloads = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1600, "height": 1000})

        async def fulfill_models(route):
            await route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(MODELS_PAYLOAD, ensure_ascii=False),
            )

        async def fulfill_empty_run(route):
            await route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"run": None}, ensure_ascii=False),
            )

        async def fulfill_orchestration_create(route):
            payload = json.loads(route.request.post_data or "{}")
            captured_payloads.append(payload)
            await route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "id": "compare-thinking-run",
                        "kind": "compare",
                        "status": "completed",
                        "title": payload.get("title") or "模型对比",
                        "summary": {"total_items": 2, "terminal_items": 2},
                        "manifest": payload,
                        "groups": [],
                    },
                    ensure_ascii=False,
                ),
            )

        await page.route("**/api/models**", fulfill_models)
        await page.route("**/api/orchestrations/active?kind=*", fulfill_empty_run)
        await page.route("**/api/orchestrations/latest?kind=*", fulfill_empty_run)
        await page.route("**/api/orchestrations", fulfill_orchestration_create)

        await page.goto(BASE_URL, wait_until="domcontentloaded")
        await page.wait_for_selector("#compare-model-checkboxes input[value='qwen3.6-plus']", state="attached", timeout=8000)
        await page.evaluate("() => switchPage('test-center', { persist: false })")
        await page.evaluate("() => switchTestCenterMode('compare')")
        await page.wait_for_selector("#compare-model-checkboxes input[value='qwen3.6-plus']", state="visible", timeout=3000)
        await page.evaluate(
            """
            () => {
              for (const id of ['qwen3.6-plus', 'deepseek-v4-pro']) {
                const input = document.querySelector(`#compare-model-checkboxes input[value="${id}"]`);
                input.checked = true;
                input.dispatchEvent(new Event('change', { bubbles: true }));
              }
            }
            """
        )
        await page.select_option("select.compare-thinking-select[data-model-id='qwen3.6-plus']", "max")
        await page.select_option("select.compare-thinking-select[data-model-id='deepseek-v4-pro']", "disabled")
        await page.evaluate(
            """
            () => {
              document.querySelector('#f-nickname').value = 'E2E角色';
              loadConfigToCompare();
              document.querySelector('#compare-turns').value = '第一轮';
              document.querySelector('#compare-dryrun').checked = true;
              state.notificationPermissionRequested = true;
              refreshTestCenterShell();
            }
            """
        )
        await page.evaluate("async () => { await startModelCompare(); }")
        await page.wait_for_timeout(500)

        await browser.close()

    if not captured_payloads:
        raise AssertionError("未捕获 /api/orchestrations 创建请求")

    payload = captured_payloads[-1]
    if payload.get("kind") != "compare":
        raise AssertionError(f"创建任务 kind 不正确: {payload.get('kind')}")
    items = payload["groups"][0]["items"]
    by_model = {item["model_id"]: item["payload"] for item in items}

    qwen_payload = by_model["qwen3.6-plus"]
    deepseek_payload = by_model["deepseek-v4-pro"]
    if qwen_payload.get("thinking_enabled") is not True or qwen_payload.get("thinking_effort") != "max":
        raise AssertionError(f"qwen thinking 参数未按模型生效: {qwen_payload}")
    if deepseek_payload.get("thinking_enabled") is not False or deepseek_payload.get("thinking_effort") != "disabled":
        raise AssertionError(f"deepseek thinking 参数未按模型关闭: {deepseek_payload}")

    print("PASS: compare per-model thinking 请求体已按模型分别注入 max/disabled")


def test_compare_per_model_thinking_e2e():
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
