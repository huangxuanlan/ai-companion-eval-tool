# -*- coding: utf-8 -*-
"""D11/F4 双模式前端融合 E2E 真验证（连接 localhost:8000 真实 server）。"""
from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000"
results = []


def record(case, name, ok, detail=""):
    results.append((case, name, ok, detail))
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {case} {name} :: {detail}", flush=True)


def visible(page, sel):
    el = page.query_selector(sel)
    if not el:
        return False
    return page.eval_on_selector(sel, "el => getComputedStyle(el).display !== 'none'")


def run():
    captured = []
    console_errors = []
    page_errors = []
    critical_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 960})
        page = ctx.new_page()
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.on("request", lambda r: captured.append((r.method, r.url)) if "/api/" in r.url else None)

        # ===== A 组：模式切换 =====
        page.goto(BASE + "/", wait_until="networkidle")
        page.wait_for_timeout(700)
        hash_ = page.evaluate("location.hash")
        mode = page.evaluate("window.currentMode")
        chat_vis = visible(page, "#page-chat")
        record("A1", "默认长文模式", hash_ in ("", "#/longform") and mode == "longform" and chat_vis,
               f"hash={hash_!r} currentMode={mode} chatVisible={chat_vis}")

        # A2: 切换到短文
        page.click('button.mode-tab-btn[data-mode="shortform"]')
        page.wait_for_function("() => typeof window.switchShortformTab === 'function'", timeout=8000)
        page.wait_for_timeout(400)
        hash_ = page.evaluate("location.hash")
        mode = page.evaluate("window.currentMode")
        sf_vis = visible(page, "#page-shortform")
        record("A2", "切换到短文", hash_ == "#/shortform" and mode == "shortform" and sf_vis,
               f"hash={hash_!r} currentMode={mode} shortformVisible={sf_vis}")

        # A3: 切换到桥接
        page.click('button.mode-tab-btn[data-mode="bridge"]')
        page.wait_for_function("() => typeof window.openNewBridgeSessionModal === 'function'", timeout=8000)
        page.wait_for_timeout(400)
        hash_ = page.evaluate("location.hash")
        mode = page.evaluate("window.currentMode")
        br_vis = visible(page, "#page-bridge")
        record("A3", "切换到桥接", hash_ == "#/bridge" and mode == "bridge" and br_vis,
               f"hash={hash_!r} currentMode={mode} bridgeVisible={br_vis}")

        # A4: 刷新保持状态（停在 shortform）
        page.goto(BASE + "/#/shortform", wait_until="networkidle")
        page.wait_for_function("() => typeof window.switchShortformTab === 'function'", timeout=8000)
        page.wait_for_timeout(400)
        mode = page.evaluate("window.currentMode")
        sf_vis = visible(page, "#page-shortform")
        record("A4", "刷新保持短文状态", mode == "shortform" and sf_vis,
               f"currentMode={mode} shortformVisible={sf_vis}")

        # ===== B 组：短文子功能（当前已在 shortform 模式）=====
        # B1: 5 个子 Tab 可见 + 默认用例库 active
        sf_tab_count = page.eval_on_selector_all("#page-shortform .sf-tab-btn", "els => els.length")
        case_active = page.eval_on_selector(
            '#page-shortform .sf-tab-btn[data-tab="case"]',
            "el => el.classList.contains('active')")
        case_sub_active = page.eval_on_selector(
            "#sf-subpage-case", "el => el.classList.contains('active')")
        record("B1", "短文 5 子Tab + 默认用例库",
               sf_tab_count == 5 and case_active and case_sub_active,
               f"tabCount={sf_tab_count} caseTabActive={case_active} caseSubActive={case_sub_active}")

        # B2: 用例库表格渲染（真实调 /api/configs?mode=short 已在 init 内）
        page.wait_for_timeout(800)
        table_present = page.query_selector("#sf-cases-table") is not None
        has_rows = page.eval_on_selector_all("#sf-cases-table tr", "els => els.length")
        has_empty = page.eval_on_selector_all("#page-shortform .empty-state", "els => els.length")
        record("B2", "用例库表格渲染", table_present and (has_rows > 0 or has_empty > 0),
               f"tablePresent={table_present} rows={has_rows} emptyStates={has_empty}")

        # B3: 运行台 Tab — Prompt A/B 下拉 + 模型选择可见
        page.click('#page-shortform .sf-tab-btn[data-tab="run"]')
        page.wait_for_timeout(500)
        run_sub_active = page.eval_on_selector("#sf-subpage-run", "el => el.classList.contains('active')")
        pa = visible(page, "#sf-run-prompt-a")
        pb = visible(page, "#sf-run-prompt-b")
        model_sel = visible(page, "#sf-run-model")
        record("B3", "运行台 PromptA/B + 模型",
               run_sub_active and pa and pb and model_sel,
               f"runActive={run_sub_active} promptA={pa} promptB={pb} model={model_sel}")

        # ===== C 组：桥接面板 =====
        page.goto(BASE + "/#/bridge", wait_until="networkidle")
        page.wait_for_function("() => typeof window.openNewBridgeSessionModal === 'function'", timeout=8000)
        page.wait_for_timeout(900)

        # C1: 会话选择器（真实调 /api/bridge/sessions）
        selector_present = page.query_selector("#bridge-session-selector") is not None
        opt_count = page.eval_on_selector_all("#bridge-session-selector option", "els => els.length")
        record("C1", "会话选择器有选项", selector_present and opt_count >= 1,
               f"selectorPresent={selector_present} optionCount={opt_count}")

        # C2: 新建会话按钮 -> 模态框弹出
        page.click('#page-bridge button[onclick="openNewBridgeSessionModal()"]')
        page.wait_for_timeout(400)
        modal_vis = visible(page, "#modal-new-bridge")
        record("C2", "新建会话模态框弹出", modal_vis, f"modalVisible={modal_vis}")
        # 关闭模态框
        if page.query_selector('#modal-new-bridge button[onclick="closeNewBridgeSessionModal()"]'):
            page.click('#modal-new-bridge button[onclick="closeNewBridgeSessionModal()"]')
            page.wait_for_timeout(300)

        # C3: 源历史区存在（空状态或气泡）
        history_present = page.query_selector("#bridge-source-history") is not None
        history_content = page.eval_on_selector(
            "#bridge-source-history", "el => el.children.length")
        record("C3", "源历史区渲染", history_present and history_content >= 1,
               f"present={history_present} childCount={history_content}")

        # ===== D 组：Fetch 拦截（mode 参数注入）=====
        captured.clear()
        page.goto(BASE + "/#/shortform", wait_until="networkidle")
        page.wait_for_function("() => typeof window.switchShortformTab === 'function'", timeout=8000)
        page.wait_for_timeout(800)
        # 主动触发一个 /api/prompts GET，验证 mode=short 注入
        page.evaluate("fetch('/api/prompts').catch(()=>{})")
        page.wait_for_timeout(700)
        prompts_calls = [u for m, u in captured if "/api/prompts" in u]
        injected = any("mode=short" in u for u in prompts_calls)
        record("D1", "GET /api/prompts 注入 mode=short", injected,
               f"prompts_calls={prompts_calls[-3:]}")

        # 收集 console/page 错误（排除已知噪音）
        for e in page_errors:
            critical_errors.append("PAGEERR: " + e)
        for e in console_errors:
            if "favicon" in e.lower():
                continue
            critical_errors.append("CONSOLE: " + e)

        browser.close()

    print("\n===== SUMMARY =====", flush=True)
    passed = sum(1 for _, _, ok, _ in results if ok)
    total = len(results)
    for case, name, ok, detail in results:
        print(f"  {case} {'PASS' if ok else 'FAIL'} {name}", flush=True)
    print(f"\nRESULT: {passed}/{total} PASS", flush=True)
    if critical_errors:
        print(f"\nCONSOLE/PAGE ERRORS ({len(critical_errors)}):", flush=True)
        for e in critical_errors[:20]:
            print(f"  - {e}", flush=True)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(run())