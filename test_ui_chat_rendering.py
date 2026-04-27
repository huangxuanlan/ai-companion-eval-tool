import asyncio
import json
import os
import sys

from playwright.async_api import async_playwright


BASE_URL = os.environ.get(
    "LONGFORM_UI_BASE_URL",
    "http://127.0.0.1:8000/static/index.html",
)
MOCK_REPLY = (
    "她故意把话说得很轻，像在试探你的底线。\n\n"
    '"dialogue">"今晚先陪我把情绪说完。"\n\n'
    "她没有继续逼近，只是把选择权留给你。"
)


async def main():
    print("开始执行聊天渲染流程冒烟...")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1440, "height": 960})

            async def fulfill_interactive(route):
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"id": "test-conv-render"}, ensure_ascii=False),
                )

            async def fulfill_generate(route):
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "success": True,
                            "turn": 1,
                            "model_id": "mock-chat-model",
                            "ai_output": MOCK_REPLY,
                            "input_tokens": 128,
                            "output_tokens": 256,
                            "latency_s": 1.2,
                            "messages_snapshot": [
                                {"role": "user", "content": "你今晚想我怎么陪你？"},
                                {"role": "assistant", "content": MOCK_REPLY},
                            ],
                            "request_payload_snapshot": {
                                "model_id": "mock-chat-model",
                                "messages": [
                                    {"role": "system", "content": "主 system"},
                                    {"role": "user", "content": "你今晚想我怎么陪你？"},
                                ],
                                "prompt_version": "星朋友长文模式_提示词_v2.6_20260325.md",
                                "summary_prompt_version": "长文模式摘要提示词_v1.0.md",
                                "scoring_prompt_version": "长文模式打分提示词_v2.0.md",
                                "scoring_model_id": "mock-chat-model",
                                "summary_interval": 10,
                                "injection_depth": 4,
                                "role_name": "萧璟言",
                                "relationship": "暧昧",
                                "personality": "霸道腹黑",
                                "system_prompt": "主 system",
                                "system_after": "后置规则",
                                "custom_variables": {
                                    "moments": "她刚发了一条夜景照",
                                    "完整时间信息": "2026-03-29 03:14 / 星期日 / 清晨 / 春季",
                                },
                                "character": {
                                    "Role_Nickname": "萧璟言",
                                    "personality": "霸道腹黑",
                                    "Role_info_works": "代表作A",
                                },
                                "modules": {
                                    "voice_forbidden": "当前为文字聊天场景，禁止输出任何语音条。",
                                },
                            },
                        },
                        ensure_ascii=False,
                    ),
                )

            await page.route("**/api/conversations/interactive", fulfill_interactive)
            await page.route("**/api/conversations/*/generate", fulfill_generate)

            await page.goto(BASE_URL, wait_until="networkidle")
            await page.wait_for_timeout(1200)

            await page.locator("#chat-input").fill("你今晚想我怎么陪你？")
            await page.locator("#btn-chat-send").click()

            ai_bubble = page.locator(".chat-bubble.ai").last
            await ai_bubble.wait_for(state="visible", timeout=5000)
            content = ai_bubble.locator(".chat-content")
            await content.wait_for(state="visible", timeout=5000)

            content_html = await content.inner_html()
            content_text = await content.inner_text()
            dialogue_count = await content.locator(".dialogue").count()

            if dialogue_count != 1:
                raise AssertionError(f"对白节点数量异常: {dialogue_count}")
            if "*" in content_html:
                raise AssertionError(f"渲染结果仍包含裸星号: {content_html}")
            if '<strong class="dialogue">"今晚先陪我把情绪说完。"</strong>' not in content_html:
                raise AssertionError(f"对白未按加粗对白格式渲染: {content_html}")
            if '&quot;dialogue&quot;&gt;' in content_html or '"dialogue">' in content_text:
                raise AssertionError(f"渲染结果仍残留伪标签前缀: {content_html} / {content_text}")
            if '**"' in content_text or '"**' in content_text:
                raise AssertionError(f"文本中仍残留错位粗体标记: {content_text}")
            if "她故意把话说得很轻" not in content_text or "今晚先陪我把情绪说完。" not in content_text:
                raise AssertionError(f"渲染文本缺失关键内容: {content_text}")

            await page.evaluate(
                """
                () => {
                  showModal('modal-debug');
                  renderDebugView(0);
                  switchDebugPanel('request');
                }
                """
            )
            await page.wait_for_timeout(300)
            debug_text = await page.locator("#debug-request-details").inner_text()
            debug_json = await page.locator("#debug-request-json").inner_text()
            if "主 System Prompt" not in debug_text or "Few-shot 之后的 System 片段" not in debug_text:
                raise AssertionError(f"调试请求视图未展示 system 分层: {debug_text}")
            if "变量覆盖" not in debug_text or "她刚发了一条夜景照" not in debug_text:
                raise AssertionError(f"调试请求视图未展示变量覆盖: {debug_text}")
            if '"system_after": "后置规则"' not in debug_json:
                raise AssertionError(f"调试请求 JSON 未保留 system_after: {debug_json}")

            await browser.close()
            print("UI_CHAT_RENDER 冒烟通过")
    except Exception as exc:
        print(f"UI_CHAT_RENDER 冒烟失败: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
