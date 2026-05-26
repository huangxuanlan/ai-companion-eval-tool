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
        await page.add_init_script("() => localStorage.clear()")

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

        async def fulfill_app_config(route):
            await route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"public_demo_mode": False}, ensure_ascii=False),
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
        await page.route("**/api/app-config", fulfill_app_config)
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
        compare_turns = page.locator("#compare-turns")
        await compare_turns.focus()
        await compare_turns.press("Enter")
        await page.wait_for_timeout(300)
        if captured_payloads:
            raise AssertionError("compare-turns 普通 Enter 不应启动模型对比")
        await page.keyboard.down("Control")
        await page.keyboard.press("Enter")
        await page.keyboard.up("Control")
        for _ in range(20):
            if captured_payloads:
                break
            await page.wait_for_timeout(250)

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


async def run_same_model_thinking_variant_case():
    print("开始执行 compare 同模型 thinking 变体 E2E...")
    captured_payloads = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1600, "height": 1000})
        await page.add_init_script("() => localStorage.clear()")

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

        async def fulfill_app_config(route):
            await route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"public_demo_mode": False}, ensure_ascii=False),
            )

        async def fulfill_orchestration_create(route):
            payload = json.loads(route.request.post_data or "{}")
            captured_payloads.append(payload)
            await route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "id": "compare-thinking-variant-run",
                        "kind": "compare",
                        "status": "completed",
                        "title": payload.get("title") or "模型对比",
                        "summary": {"total_items": 3, "terminal_items": 3},
                        "manifest": payload,
                        "groups": [],
                    },
                    ensure_ascii=False,
                ),
            )

        await page.route("**/api/models**", fulfill_models)
        await page.route("**/api/app-config", fulfill_app_config)
        await page.route("**/api/orchestrations/active?kind=*", fulfill_empty_run)
        await page.route("**/api/orchestrations/latest?kind=*", fulfill_empty_run)
        await page.route("**/api/orchestrations", fulfill_orchestration_create)

        await page.goto(BASE_URL, wait_until="domcontentloaded")
        await page.wait_for_selector("#compare-model-checkboxes input[value='deepseek-v4-pro']", state="attached", timeout=8000)
        await page.evaluate("() => switchPage('test-center', { persist: false })")
        await page.evaluate("() => switchTestCenterMode('compare')")
        await page.select_option("#compare-variant-mode", "thinking")
        await page.locator("#compare-model-checkboxes input[value='deepseek-v4-pro']").check()
        await page.evaluate(
            """
            () => {
              document.querySelector('#f-nickname').value = 'E2E思考角色';
              loadConfigToCompare();
              document.querySelector('#compare-turns').value = '第一轮';
              document.querySelector('#compare-dryrun').checked = true;
              state.notificationPermissionRequested = true;
              refreshTestCenterShell();
            }
            """
        )
        await page.evaluate("() => startModelCompare()")
        for _ in range(20):
            if captured_payloads:
                break
            await page.wait_for_timeout(250)

        await browser.close()

    if not captured_payloads:
        raise AssertionError("未捕获同模型 thinking 变体 /api/orchestrations 创建请求")

    payload = captured_payloads[-1]
    items = payload["groups"][0]["items"]
    if len(items) != 3:
        raise AssertionError(f"同模型思考对比应生成 3 个变体，实际 {len(items)} 个: {items}")
    if {item["model_id"] for item in items} != {"deepseek-v4-pro"}:
        raise AssertionError(f"同模型思考对比不应混入其他 model_id: {items}")
    efforts = [item["payload"].get("thinking_effort") for item in items]
    if efforts != ["disabled", "high", "max"]:
        raise AssertionError(f"同模型思考变体档位错误: {efforts}")
    keys = [item["key"] for item in items]
    if len(set(keys)) != len(keys):
        raise AssertionError(f"同模型思考变体 key 不唯一: {keys}")
    labels = [item["label"] for item in items]
    if not all("DeepSeek" in label or "deepseek-v4-pro" in label for label in labels):
        raise AssertionError(f"同模型思考变体 label 缺失模型名: {labels}")
    if payload.get("config_snapshot", {}).get("compare_variant_mode") != "thinking":
        raise AssertionError(f"config_snapshot 未记录 thinking 模式: {payload.get('config_snapshot')}")

    print("PASS: compare 同模型 thinking 变体已生成 disabled/high/max 三列")


def test_compare_per_model_thinking_e2e():
    asyncio.run(main())
    asyncio.run(run_same_model_thinking_variant_case())


if __name__ == "__main__":
    asyncio.run(main())
    asyncio.run(run_same_model_thinking_variant_case())
