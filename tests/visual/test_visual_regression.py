# -*- coding: utf-8 -*-
"""第三层：视觉回归基线测试。

对三模式 6 个关键页面截图，与基线像素比对。沿用现有 E2E 的裸 sync_playwright
风格，不引入 pytest-playwright。

用法：
    py tests/visual/test_visual_regression.py --update   # 首次生成/刷新基线
    py tests/visual/test_visual_regression.py            # 比对验证

机制：
- 自行拉起隔离 server（端口 8001，临时 DB），跑完自动关闭，绝不碰生产库。
- 截图前注入稳定化 CSS：冻结动画/过渡、遮罩动态时间戳，降低无意义抖动。
- 基线存于 tests/visual/__screenshots__/，diff 图存于 __diff__/（已 gitignore）。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "visual"))

from diff_lib import compare  # noqa: E402

BASE = "http://127.0.0.1:8001"
BASELINE_DIR = Path(__file__).resolve().parent / "__screenshots__"
CURRENT_DIR = Path(__file__).resolve().parent / "__current__"
DIFF_DIR = Path(__file__).resolve().parent / "__diff__"

VIEWPORT = {"width": 1440, "height": 960}
RESPONSIVE_VIEWPORTS = [(768, 1024), (1920, 1080)]

# 稳定化 CSS：关闭一切动画/过渡/光标闪烁，保证截图可复现
STABILIZE_CSS = """
*, *::before, *::after {
  animation-duration: 0s !important;
  animation-delay: 0s !important;
  transition-duration: 0s !important;
  transition-delay: 0s !important;
  caret-color: transparent !important;
  scroll-behavior: auto !important;
}
"""

results = []


def record(case, name, ok, detail=""):
    results.append((case, name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {case} {name} :: {detail}", flush=True)


def wait_server(url: str, timeout_s: float = 25.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.4)
    return False


def start_isolated_server() -> subprocess.Popen:
    """拉起隔离 server（端口 8001 + 临时 DB），并 seed 桥接源会话。"""
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "_e2e_isolated_server.py")],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if not wait_server(BASE + "/", timeout_s=25.0):
        proc.terminate()
        raise RuntimeError("隔离 server 启动超时")
    subprocess.run(
        [sys.executable, str(ROOT / "_seed_bridge_source.py")],
        cwd=str(ROOT),
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc


def stabilize(page: Page) -> None:
    """注入稳定化 CSS + 遮罩动态时间戳，保证截图可复现。"""
    page.add_style_tag(content=STABILIZE_CSS)
    page.evaluate(
        """() => {
          const killDynamic = (sel) => {
            document.querySelectorAll(sel).forEach(el => {
              el.textContent = '——';
            });
          };
          // 时间戳/相对时间一类内容用占位符替换，避免无意义像素抖动
          killDynamic('[data-dynamic-time], .timestamp, .sf-time, .time-ago');
        }"""
    )
    page.wait_for_timeout(300)


def snap(page: Page, name: str, update: bool, clip=None) -> None:
    """截图并按模式（update/verify）落盘或比对。"""
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    CURRENT_DIR.mkdir(parents=True, exist_ok=True)
    page.wait_for_load_state("networkidle")
    stabilize(page)
    target_dir = BASELINE_DIR if update else CURRENT_DIR
    shot_path = target_dir / f"{name}.png"
    kwargs = {"path": str(shot_path), "animations": "disabled"}
    if clip:
        kwargs["clip"] = clip
    else:
        kwargs["full_page"] = True
    page.screenshot(**kwargs)
    if update:
        record("BASE", name, True, f"baseline saved: {shot_path.name}")
        return
    baseline = BASELINE_DIR / f"{name}.png"
    diff = compare(baseline, shot_path, DIFF_DIR / f"{name}.diff.png")
    record("VIS", name, diff.ok, diff.detail)


def capture_longform(page: Page, update: bool) -> None:
    """长文模式：默认页（聊天区 + 配置面板）。"""
    page.goto(BASE + "/", wait_until="networkidle")
    page.wait_for_timeout(800)
    snap(page, "01_longform_default", update)


def capture_shortform_cases(page: Page, update: bool) -> None:
    """短文模式 - 用例库 Tab。"""
    page.goto(BASE + "/#/shortform", wait_until="networkidle")
    page.wait_for_function(
        "() => typeof window.switchShortformTab === 'function'", timeout=8000)
    page.click('#page-shortform .sf-tab-btn[data-tab="case"]')
    page.wait_for_timeout(800)
    snap(page, "02_shortform_cases", update)


def capture_shortform_run(page: Page, update: bool) -> None:
    """短文模式 - 运行台（Prompt A/B + 模型选择）。"""
    page.goto(BASE + "/#/shortform", wait_until="networkidle")
    page.wait_for_function(
        "() => typeof window.switchShortformTab === 'function'", timeout=8000)
    page.click('#page-shortform .sf-tab-btn[data-tab="run"]')
    page.wait_for_timeout(800)
    snap(page, "03_shortform_run", update)


def capture_shortform_monitor(page: Page, update: bool) -> None:
    """短文模式 - 监控面板。"""
    page.goto(BASE + "/#/shortform", wait_until="networkidle")
    page.wait_for_function(
        "() => typeof window.switchShortformTab === 'function'", timeout=8000)
    page.click('#page-shortform .sf-tab-btn[data-tab="monitor"]')
    page.wait_for_timeout(1000)
    snap(page, "04_shortform_monitor", update)


def capture_bridge_list(page: Page, update: bool) -> None:
    """桥接模式 - 会话列表 + 源历史区。"""
    page.goto(BASE + "/#/bridge", wait_until="networkidle")
    page.wait_for_function(
        "() => typeof window.openNewBridgeSessionModal === 'function'",
        timeout=8000,
    )
    page.wait_for_timeout(1200)
    snap(page, "05_bridge_list", update)


def capture_bridge_modal(page: Page, update: bool) -> None:
    """桥接模式 - 新建会话模态框打开状态。"""
    page.goto(BASE + "/#/bridge", wait_until="networkidle")
    page.wait_for_function(
        "() => typeof window.openNewBridgeSessionModal === 'function'",
        timeout=8000,
    )
    page.wait_for_timeout(800)
    page.click('#page-bridge button[onclick="openNewBridgeSessionModal()"]')
    page.wait_for_function(
        "() => document.querySelector('#modal-new-bridge')?.style.display !== 'none'",
        timeout=5000,
    )
    page.wait_for_timeout(500)
    snap(page, "06_bridge_modal", update)


CAPTURES = [
    capture_longform,
    capture_shortform_cases,
    capture_shortform_run,
    capture_shortform_monitor,
    capture_bridge_list,
    capture_bridge_modal,
]


def _run_responsive(p, update: bool) -> None:
    """第四层：窄屏/宽屏布局检查。不参与基线比对，只验证无横向溢出 +
    存档参考截图（独立 resp_ 前缀，不污染 1440 基线）。"""
    routes = [
        ("longform", "/"),
        ("shortform", "/#/shortform"),
        ("bridge", "/#/bridge"),
    ]
    archive_dir = (BASELINE_DIR if update else CURRENT_DIR) / "responsive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    for w, h in RESPONSIVE_VIEWPORTS:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": w, "height": h})
        page = ctx.new_page()
        for label, route in routes:
            try:
                page.goto(BASE + route, wait_until="networkidle")
                page.wait_for_timeout(700)
                stabilize(page)
                page.screenshot(
                    path=str(archive_dir / f"resp_{label}_w{w}.png"),
                    full_page=True,
                )
                no_overflow = page.evaluate(
                    "document.documentElement.scrollWidth "
                    "<= window.innerWidth + 1"
                )
                record(
                    "RESP", f"{label}_w{w}", no_overflow,
                    "no horizontal overflow"
                    if no_overflow else "horizontal overflow detected",
                )
            except Exception as e:
                record("RESP", f"{label}_w{w}", False, f"exception: {e}")
        browser.close()


def run(update: bool, responsive: bool) -> int:
    proc = start_isolated_server()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport=VIEWPORT)
            page = ctx.new_page()
            for fn in CAPTURES:
                try:
                    fn(page, update)
                except Exception as e:
                    record("VIS", fn.__name__, False, f"exception: {e}")
            browser.close()

            if responsive:
                _run_responsive(p, update)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    print("\n===== SUMMARY =====", flush=True)
    passed = sum(1 for _, _, ok, _ in results if ok)
    total = len(results)
    for case, name, ok, detail in results:
        print(f"  {case} {'PASS' if ok else 'FAIL'} {name}", flush=True)
    print(f"\nRESULT: {passed}/{total} PASS", flush=True)
    return 0 if passed == total else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--update", action="store_true", help="生成/刷新基线截图（首次运行用）",
    )
    parser.add_argument(
        "--responsive", action="store_true",
        help="同时跑响应式 viewport（768/1920），仅做无横向溢出检查",
    )
    args = parser.parse_args()
    sys.exit(run(args.update, args.responsive))