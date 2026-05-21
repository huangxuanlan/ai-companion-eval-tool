import asyncio
import json
import os
import sys
import time

from playwright.async_api import async_playwright


BASE_URL = os.environ.get("LONGFORM_UI_BASE_URL", "http://127.0.0.1:8000/")


async def ensure_visible(page, selector: str, message: str):
    locator = page.locator(selector)
    if await locator.count() == 0 or not await locator.first.is_visible():
        raise AssertionError(message)


async def wait_for_preset_card(page, preset_name: str):
    locator = page.locator("#preset-grid .preset-card", has_text=preset_name).first
    await locator.wait_for(state="visible", timeout=10000)
    return locator


async def main():
    print("开始执行 UI_FIX 新规格冒烟...")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1500, "height": 980})

            await page.goto(BASE_URL, wait_until="networkidle")
            await page.wait_for_timeout(1600)
            if "/static/index.html?v=" not in page.url:
                raise AssertionError(f"根路径未跳转到带版本号入口页: {page.url}")

            await page.locator("#rightPanel .panel-tab").filter(has_text="🎭 角色").click()
            await page.wait_for_timeout(300)
            await ensure_visible(page, "#preset-grid", "角色预设区未显示")
            await ensure_visible(page, "#role-variable-editor", "右侧主变量编辑面板未渲染")
            await ensure_visible(page, ".role-variable-editor-legend", "右侧变量工作台缺少状态 legend")
            await ensure_visible(page, "#role-variable-editor [data-editor-key='Role_info_works']", "右侧主面板缺少 Role_info_works 输入框")
            await ensure_visible(page, "#role-variable-editor .role-variable-editor-row:has([data-editor-key='voice_forbidden']) .role-variable-editor-summary-card", "右侧主面板缺少 voice_forbidden 摘要卡")
            editor_metrics = await page.evaluate(
                """
                () => {
                  const nicknameInput = document.querySelector("#role-variable-editor [data-editor-key='Role_Nickname']");
                  const voiceSummary = document.querySelector("#role-variable-editor .role-variable-editor-row:has([data-editor-key='voice_forbidden']) .role-variable-editor-summary-card");
                  const voiceTextarea = document.querySelector("#role-variable-editor [data-editor-key='voice_forbidden']");
                  const voiceExpand = [...document.querySelectorAll("#role-variable-editor .role-variable-editor-row:has([data-editor-key='voice_forbidden']) .role-variable-editor-inline-btn")].find(el => (el.textContent || '').includes('展开编辑') || (el.textContent || '').includes('收起编辑'));
                  const nicknameRow = nicknameInput?.closest('.role-variable-editor-row');
                  const voiceRow = voiceSummary?.closest('.role-variable-editor-row');
                  const nicknameStatus = nicknameRow?.querySelector('.role-variable-editor-status')?.innerText || '';
                  const voiceStatus = voiceRow?.querySelector('.role-variable-editor-status')?.innerText || '';
                  return {
                    nicknameWidth: Math.round(nicknameInput?.getBoundingClientRect().width || 0),
                    voiceWidth: Math.round(voiceSummary?.getBoundingClientRect().width || 0),
                    nicknameValue: nicknameInput?.value || '',
                    voiceValue: voiceTextarea?.value || '',
                    nicknameStatus,
                    voiceStatus,
                    voiceHasExpand: !!voiceExpand,
                    legendCount: document.querySelectorAll('.role-variable-editor-legend-pill').length,
                  };
                }
                """
            )
            if editor_metrics["nicknameWidth"] < 180 or editor_metrics["voiceWidth"] < 180:
                raise AssertionError(f"右侧变量输入框仍被压扁: {editor_metrics}")
            if not editor_metrics["nicknameValue"].strip():
                raise AssertionError(f"角色昵称默认值未显示在右侧输入框: {editor_metrics}")
            if "预设" not in editor_metrics["nicknameStatus"]:
                raise AssertionError(f"右侧变量编辑状态文案不明确: {editor_metrics}")
            if "系统" not in editor_metrics["voiceStatus"]:
                raise AssertionError(f"系统自动填充变量未标明来源: {editor_metrics}")
            if not editor_metrics["voiceValue"].strip() or not editor_metrics["voiceHasExpand"]:
                raise AssertionError(f"长文本变量未按摘要卡 + 展开编辑呈现: {editor_metrics}")
            if editor_metrics["legendCount"] < 4:
                raise AssertionError(f"右侧变量工作台 legend 不完整: {editor_metrics}")
            legacy_form_visible = await page.evaluate(
                """
                () => {
                  const storage = document.getElementById('role-form-legacy-storage');
                  if (!storage) return false;
                  const style = getComputedStyle(storage);
                  return style.display !== 'none' && style.visibility !== 'hidden';
                }
                """
            )
            if legacy_form_visible:
                raise AssertionError("旧的右侧角色表单仍然可见")

            voice_forbidden = await page.locator("#f-voice-forbidden").input_value()
            summary_interval = await page.locator("#f-summary-interval").input_value()
            injection_depth = await page.locator("#f-injection-depth").input_value()
            if not voice_forbidden.strip():
                raise AssertionError("voice_forbidden 未默认填充")
            if summary_interval != "5":
                raise AssertionError(f"默认摘要间隔未对齐 v5.5: {summary_interval}")
            if injection_depth != "4":
                raise AssertionError(f"默认注入深度未对齐 v5.5: {injection_depth}")
            if await page.locator("#right-panel-runtime-vars").count() != 0:
                raise AssertionError("旧的顶部变量区仍然存在")

            await page.locator("#rightPanel .panel-tab").filter(has_text="⚙️ 参数").click()
            await page.wait_for_timeout(300)
            params_generation_visible = await page.evaluate(
                """
                () => {
                  const host = document.getElementById('tab-params');
                  if (!host) return false;
                  return [...host.querySelectorAll('*')].some(el => {
                    const text = (el.textContent || '').trim();
                    const style = getComputedStyle(el);
                    return text === '生成多样性'
                      && style.display !== 'none'
                      && style.visibility !== 'hidden'
                      && el.offsetParent !== null;
                  });
                }
                """
            )
            if params_generation_visible:
                raise AssertionError("参数页仍然展示生成多样性卡片")

            await ensure_visible(page, "#btn-header-model-settings", "单模型顶部缺少设置入口")
            await page.locator("#btn-header-model-settings").click()
            await page.locator("#modal-sp-edit").wait_for(state="visible", timeout=5000)
            await page.wait_for_timeout(400)
            await page.locator("#sp-btn-generation-preset-creative").click()
            await page.wait_for_timeout(250)
            modal_metrics = await page.evaluate(
                """
                () => {
                  const chips = [...document.querySelectorAll('#runtime-prompt-editor-vars-body .variable-preview-chip')];
                  const names = [...document.querySelectorAll('#runtime-prompt-editor-vars-body .variable-preview-chip-name')];
                  const firstName = names[0];
                  const firstChip = chips[0];
                  const activeToggle = document.querySelector('#runtime-prompt-editor-vars-body .variable-preview-segmented-btn.active');
                  const generationVisible = (() => {
                    const el = document.getElementById('runtime-prompt-editor-generation');
                    return !!el && getComputedStyle(el).display !== 'none';
                  })();
                  const varsVisible = (() => {
                    const el = document.getElementById('runtime-prompt-editor-vars');
                    return !!el && getComputedStyle(el).display !== 'none';
                  })();
                  const creative = document.getElementById('sp-btn-generation-preset-creative');
                  const rect = creative?.getBoundingClientRect();
                  const pointEl = rect ? document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2) : null;
                  return {
                    generationVisible,
                    varsVisible,
                    chipCount: chips.length,
                    inputCount: document.querySelectorAll('#runtime-prompt-editor-vars-body input[data-var]').length,
                    textAlign: firstName ? getComputedStyle(firstName).textAlign : '',
                    hasColorChip: firstChip ? getComputedStyle(firstChip).backgroundColor !== 'rgba(0, 0, 0, 0)' : false,
                    activeToggleText: activeToggle ? (activeToggle.textContent || '').trim() : '',
                    hasRelatedToggle: !!activeToggle,
                    hasAllToggle: [...document.querySelectorAll('#runtime-prompt-editor-vars-body .variable-preview-segmented-btn')].some(el => (el.textContent || '').includes('全部变量')),
                    creativeActive: !!creative && creative.classList.contains('active'),
                    creativeReceivesPointer: pointEl === creative || creative?.contains(pointEl),
                    topElementTag: pointEl?.tagName || '',
                    topElementId: pointEl?.id || '',
                    temperature: document.getElementById('sp-temperature')?.value || '',
                    topP: document.getElementById('sp-top-p')?.value || '',
                  };
                }
                """
            )
            if not modal_metrics["generationVisible"] or not modal_metrics["varsVisible"]:
                raise AssertionError(f"主提示词编辑器右栏未正常显示: {modal_metrics}")
            if modal_metrics["chipCount"] <= 0:
                raise AssertionError("主提示词编辑器彩色变量预览未渲染")
            if modal_metrics["inputCount"] <= 0:
                raise AssertionError(f"主提示词编辑器右栏缺少可编辑输入框: {modal_metrics}")
            if modal_metrics["textAlign"] not in {"left", "start"}:
                raise AssertionError(f"变量标签未左对齐: {modal_metrics}")
            if not modal_metrics["hasColorChip"]:
                raise AssertionError(f"主提示词编辑器右栏未显示彩色变量 chip: {modal_metrics}")
            if not modal_metrics["creativeReceivesPointer"] or not modal_metrics["creativeActive"]:
                raise AssertionError(f"主提示词编辑器生成多样性按钮仍被遮挡或点击未生效: {modal_metrics}")
            if modal_metrics["temperature"] != "0.8" or modal_metrics["topP"] != "1":
                raise AssertionError(f"主提示词编辑器创意模式未同步到采样参数: {modal_metrics}")
            if "相关变量" not in modal_metrics["activeToggleText"]:
                raise AssertionError(f"主提示词编辑器默认未落在相关变量视图: {modal_metrics}")
            if not modal_metrics["hasRelatedToggle"] or not modal_metrics["hasAllToggle"]:
                raise AssertionError(f"主提示词编辑器右栏缺少相关/全部变量切换: {modal_metrics}")
            await page.locator("#runtime-prompt-editor-vars-body .variable-preview-segmented-btn", has_text="全部变量").click()
            await page.wait_for_timeout(250)
            modal_label_metrics = await page.evaluate(
                """
                () => {
                  const primaryTexts = [...document.querySelectorAll('#runtime-prompt-editor-vars-body .variable-preview-chip-name')]
                    .map(el => (el.textContent || '').trim());
                  return {
                    hasRoleWorksZh: primaryTexts.some(text => text.includes('代表作品')),
                    hasVoiceForbiddenZh: primaryTexts.some(text => text.includes('语音条禁用规则')),
                  };
                }
                """
            )
            if not modal_label_metrics["hasRoleWorksZh"] or not modal_label_metrics["hasVoiceForbiddenZh"]:
                raise AssertionError(f"变量中文名未正确显示: {modal_label_metrics}")
            await page.locator("#modal-sp-edit .runtime-prompt-editor-actions .btn-secondary").click()

            await page.locator("#rightPanel .panel-tab").filter(has_text="🎭 角色").click()
            await page.wait_for_timeout(300)
            preset_name = f"UI删除测试_{int(time.time())}"
            await page.locator("#role-variable-editor [data-editor-key='Role_Nickname']").fill(preset_name)
            await page.wait_for_timeout(250)
            await page.locator("#btn-save-preset").click()
            await page.wait_for_timeout(600)
            card = await wait_for_preset_card(page, preset_name)
            delete_button = card.locator(".preset-card-delete")
            if not await delete_button.is_visible():
                raise AssertionError("自定义模板卡片缺少删除按钮")
            await delete_button.click()
            await page.locator("#modal-preset-delete").wait_for(state="visible", timeout=5000)
            delete_message = await page.locator("#preset-delete-message").inner_text()
            if preset_name not in delete_message:
                raise AssertionError(f"删除确认弹窗文案错误: {delete_message}")
            await page.locator("#btn-confirm-delete-preset").click()
            await page.wait_for_function(
                "(name) => ![...document.querySelectorAll('#preset-grid .preset-card')].some(el => el.innerText.includes(name))",
                arg=preset_name,
                timeout=10000,
            )

            async def fulfill_generate(route):
                await asyncio.sleep(1.2)
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "success": True,
                            "turn": 1,
                            "model_id": "mock-chat-model",
                            "ai_output": "窗边暖光落下来。**\"我在，继续说。\"**",
                            "input_tokens": 32,
                            "output_tokens": 64,
                            "latency_s": 1.2,
                            "messages_snapshot": [
                                {"role": "system", "content": "主 system"},
                                {"role": "user", "content": "你在吗？"},
                                {"role": "assistant", "content": "窗边暖光落下来。**\"我在，继续说。\"**"},
                            ],
                            "request_payload_snapshot": {
                                "model_id": "mock-chat-model",
                                "summary_interval": 10,
                                "injection_depth": 4,
                                "messages": [
                                    {"role": "system", "content": "主 system"},
                                    {"role": "user", "content": "你在吗？"},
                                ],
                                "character": {"Role_Nickname": preset_name},
                            },
                        },
                        ensure_ascii=False,
                    ),
                )

            async def fulfill_interactive(route):
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"id": "interactive-e2e-conv"}, ensure_ascii=False),
                )

            await page.route("**/api/conversations/interactive", fulfill_interactive)
            await page.route("**/api/conversations/*/generate", fulfill_generate)
            await page.evaluate(
                """
                () => {
                  state.chatSessionMode = 'history';
                  state.convId = 'history-stale-conv';
                  state.turns = [{ turn: 1, user_input: '旧消息', ai_output: '旧回复：不该继续留在画布上' }];
                  window._chatHistory = [
                    { role: 'user', content: '旧消息' },
                    { role: 'assistant', content: '旧回复：不该继续留在画布上' },
                  ];
                  const empty = document.getElementById('chat-empty');
                  if (empty) empty.style.display = 'none';
                  const area = document.getElementById('chat-area');
                  if (area) {
                    area.innerHTML = `
                      <div class="chat-bubble user"><div class="chat-content">旧消息</div></div>
                      <div class="chat-bubble ai"><div class="chat-content">旧回复：不该继续留在画布上</div></div>
                    `;
                  }
                }
                """
            )
            await page.locator("#chat-input").fill("你在吗？")
            await page.locator("#btn-chat-send").click()
            await page.wait_for_timeout(350)
            waiting_metrics = await page.evaluate(
                """
                () => {
                  const typing = document.getElementById('chat-typing');
                  return {
                    inlineCount: document.querySelectorAll('.chat-bubble-loading').length,
                    typingDisplay: typing ? getComputedStyle(typing).display : '',
                  };
                }
                """
            )
            if waiting_metrics["inlineCount"] != 1:
                raise AssertionError(f"interactive 等待态数量异常: {waiting_metrics}")
            if waiting_metrics["typingDisplay"] != "none":
                raise AssertionError(f"interactive 仍出现底部重复气泡: {waiting_metrics}")
            await page.wait_for_function(
                """
                () => {
                  const loadingCount = document.querySelectorAll('.chat-bubble-loading').length;
                  const aiBubbles = [...document.querySelectorAll('.chat-bubble.ai:not(.chat-bubble-loading) .chat-content')];
                  return loadingCount === 0 && aiBubbles.some(el => (el.textContent || '').includes('我在，继续说'));
                }
                """,
                timeout=8000,
            )
            remaining_loading = await page.locator(".chat-bubble-loading").count()
            if remaining_loading != 0:
                raise AssertionError("生成完成后等待态未清理")
            post_history_reset = await page.evaluate(
                """
                () => ({
                  convId: state.convId,
                  mode: state.chatSessionMode,
                  chatText: (document.getElementById('chat-area')?.innerText || ''),
                  staleCount: [...document.querySelectorAll('#chat-area .chat-bubble')]
                    .filter(el => (el.innerText || '').includes('旧回复：不该继续留在画布上')).length,
                  aiCount: document.querySelectorAll('#chat-area .chat-bubble.ai:not(.chat-bubble-loading)').length,
                  userCount: document.querySelectorAll('#chat-area .chat-bubble.user').length,
                })
                """
            )
            if post_history_reset["mode"] != "interactive" or post_history_reset["convId"] != "interactive-e2e-conv":
                raise AssertionError(f"历史态发送后未切入新交互会话: {post_history_reset}")
            if post_history_reset["staleCount"] != 0 or "旧回复：不该继续留在画布上" in post_history_reset["chatText"]:
                raise AssertionError(f"历史态残留气泡未清理: {post_history_reset}")
            if post_history_reset["aiCount"] != 1 or post_history_reset["userCount"] != 1:
                raise AssertionError(f"历史态发消息后气泡数量异常: {post_history_reset}")

            await browser.close()
            print("UI_FIX 冒烟通过")
    except Exception as exc:
        print(f"UI_FIX 冒烟失败: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
