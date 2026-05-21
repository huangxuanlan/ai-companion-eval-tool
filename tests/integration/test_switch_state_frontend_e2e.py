from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse

import pytest

try:
    from playwright.async_api import async_playwright
except ImportError:  # pragma: no cover - 本地开发依赖缺失时给出明确跳过原因
    async_playwright = None


PROJECT_DIR = Path(__file__).resolve().parents[2]
STATIC_DIR = PROJECT_DIR / "server" / "static"
INDEX_PATH = STATIC_DIR / "index.html"
JS_PATH = STATIC_DIR / "js" / "legacy_bundle.js"


MODELS = [
    {"id": "deepseek-v4-pro", "name": "deepseek-v4-pro", "tier": "pro", "capabilities": {}},
    {"id": "doubao-lite", "name": "doubao-lite", "tier": "mini", "capabilities": {}},
    {"id": "doubao-1.5-character", "name": "doubao-1.5-character", "tier": "pro", "capabilities": {}},
]


async def _fulfill_json(route, payload: dict | list, status: int = 200) -> None:
    await route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload, ensure_ascii=False),
    )


@pytest.mark.skipif(async_playwright is None, reason="playwright 未安装，无法执行浏览器级前端 E2E")
def test_frontend_mode_switch_posts_switch_state_in_interactive_payload() -> None:
    asyncio.run(_run_frontend_mode_switch_e2e())


async def _run_frontend_mode_switch_e2e() -> None:
    html = INDEX_PATH.read_text(encoding="utf-8")
    js = JS_PATH.read_text(encoding="utf-8")
    captured_interactive_payloads: list[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 960})

        async def route_handler(route):
            request = route.request
            parsed = urlparse(request.url)
            path = parsed.path

            if path.endswith("/static/index.html") or path == "/":
                await route.fulfill(status=200, content_type="text/html", body=html)
                return
            if path.endswith("/static/js/legacy_bundle.js"):
                await route.fulfill(status=200, content_type="application/javascript", body=js)
                return
            if path.endswith("/static/css/main.css"):
                await route.fulfill(status=200, content_type="text/css", body="")
                return
            if path.endswith("/static/vendor/xlsx.full.min.js"):
                await route.fulfill(status=200, content_type="application/javascript", body="window.XLSX={};")
                return
            if "/api/conversations/interactive" in path and request.method == "POST":
                post_data_json = request.post_data_json
                captured_interactive_payloads.append(post_data_json() if callable(post_data_json) else post_data_json)
                await _fulfill_json(route, {"id": f"switch-target-{len(captured_interactive_payloads)}", "status": "running"})
                return
            if path.endswith("/generate") and request.method == "POST":
                await _fulfill_json(
                    route,
                    {
                        "success": True,
                        "turn": 1,
                        "model_id": "doubao-lite",
                        "ai_output": "我记得，你刚才是在问周末安排。我们接着说。",
                        "messages_snapshot": [],
                        "request_payload_snapshot": {},
                    },
                )
                return
            if path == "/api/models":
                tier = dict(item.split("=", 1) for item in parsed.query.split("&") if "=" in item).get("tier", "")
                models = [m for m in MODELS if not tier or m["tier"] == tier]
                await _fulfill_json(route, {"models": models or MODELS})
                return
            if path == "/api/presets":
                await _fulfill_json(
                    route,
                    {
                        "presets": [
                            {
                                "id": "preset-linye",
                                "nickname": "林野",
                                "personality_type": "温柔可靠",
                                "is_builtin": True,
                                "config": {
                                    "character": {"Role_Nickname": "林野", "gender": "男", "personality": "温柔可靠"},
                                    "context": {"relationship": "暧昧", "scene": "客厅"},
                                    "modules": {},
                                },
                            }
                        ]
                    },
                )
                return
            if path.startswith("/api/presets/"):
                await _fulfill_json(route, {"config": {}})
                return
            if path == "/api/conversations" and request.method == "GET":
                await _fulfill_json(route, {"conversations": []})
                return
            if path == "/api/prompts":
                await _fulfill_json(route, {"prompts": [], "active_filename": ""})
                return
            if path == "/api/scoring-prompts":
                await _fulfill_json(route, {"prompts": []})
                return
            await _fulfill_json(route, {})

        await page.route("**/*", route_handler)
        await page.goto("http://switch-state-e2e.local/static/index.html", wait_until="domcontentloaded")
        await page.wait_for_function("() => typeof toggleCompareMode === 'function' && !!document.getElementById('btn-toggle-compare')")
        await page.evaluate(
            """
            () => {
              document.getElementById('f-nickname').value = '林野';
              document.getElementById('header-global-model').innerHTML = '<option value="deepseek-v4-pro">deepseek-v4-pro</option>';
              document.getElementById('header-global-model').value = 'deepseek-v4-pro';
              state.chatSessionMode = 'interactive';
              state.convId = 'long-source-conv';
              state.turns = [
                {
                  turn: 1,
                  user_input: '你刚才说周末安排还没讲完，要不要继续？',
                  ai_output: '他把茶杯放回桌面。**"当然继续，我先说周六上午的安排。"**',
                },
                {
                  turn: 2,
                  user_input: '那周六上午到底怎么安排？',
                  ai_output: '他看向你，语气放轻。**"先一起吃早饭，再去书店。"**',
                },
              ];
              syncChatHistoryFromTurns();
            }
            """
        )

        await page.locator("#btn-toggle-compare").click()
        await page.wait_for_function("() => document.querySelectorAll('#freechat-model-slots .fc-model-slot').length > 0")
        await page.locator("#freechat-input").fill("接着说。")
        await page.locator("#btn-freechat-send").click()
        await page.wait_for_function(
            "() => window.__switchStateE2EReady || document.querySelectorAll('.chat-bubble.ai:not(.chat-bubble-loading)').length > 0",
            timeout=8000,
        )

        await page.locator("#btn-toggle-compare").click()
        await page.locator("#chat-input").fill("那我们换成长文继续。")
        await page.locator("#btn-chat-send").click()
        await page.wait_for_function(
            "() => document.querySelectorAll('#chat-area .chat-bubble.ai:not(.chat-bubble-loading)').length > 0",
            timeout=8000,
        )

        await browser.close()

    assert len(captured_interactive_payloads) >= 2, "前端没有创建双向切换目标会话"
    short_payload = captured_interactive_payloads[0]
    short_custom_variables = short_payload.get("custom_variables") or {}
    short_switch_state = short_custom_variables.get("switch_state", "")

    assert "switch_state" not in short_payload, "switch_state 不应作为顶层字段发送"
    assert short_switch_state, "长切短创建会话时未写入 custom_variables.switch_state"
    assert "切换接话状态" in short_switch_state
    assert "【最近用户意图】" in short_switch_state
    assert "【上一回复意图】" in short_switch_state
    assert "【接话约束】短文模式" in short_switch_state
    assert "不是回复格式示例" in short_switch_state
    assert "旧摘要" not in short_switch_state
    assert len(short_switch_state) < 360

    long_payload = captured_interactive_payloads[1]
    long_custom_variables = long_payload.get("custom_variables") or {}
    long_switch_state = long_custom_variables.get("switch_state", "")

    assert "switch_state" not in long_payload, "switch_state 不应作为顶层字段发送"
    assert long_switch_state, "短切长创建会话时未写入 custom_variables.switch_state"
    assert "切换接话状态" in long_switch_state
    assert "【最近用户意图】" in long_switch_state
    assert "【上一回复意图】" in long_switch_state
    assert "【接话约束】长文模式" in long_switch_state
    assert "不是回复格式示例" in long_switch_state
    assert "旧摘要" not in long_switch_state
    assert len(long_switch_state) < 520
