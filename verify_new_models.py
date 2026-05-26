"""
新模型配置验证脚本
=====================
一次性测试 5 个新增/变更的模型能否调通 API。

用法：
    cd e:\\提效工具\\长文模式生成
    python verify_new_models.py

预计耗时：30 秒以内（每模型一条 "你好" 短调用）。
预计 token 消耗：每模型 < 100 token，总计 < 500 token。
"""
from __future__ import annotations
import os
import sys
import time
from pathlib import Path

# ── 加载 server/.env ──────────────────────────────────────────
_SERVER_DIR = Path(__file__).resolve().parent / "server"
sys.path.insert(0, str(_SERVER_DIR))

try:
    from dotenv import load_dotenv
    load_dotenv(_SERVER_DIR / ".env")
except ImportError:
    print("[警告] 未安装 python-dotenv，请确保已手动设置环境变量")

# ── 待验证模型清单 ────────────────────────────────────────────
# 2026-05-26 变更：mimo-v2.5-pro 与 kimi-k2.6 因 API Key 未开通对应产品，暂不接入。
MODELS_TO_VERIFY = [
    ("minimax-m27",        "MiniMax M2.7（model_name 已改 MiniMax/MiniMax-M2.7）"),
    ("qwen3.7-max",        "千问 3.7 Max（已通过）"),
    ("glm-5.1",            "GLM-5.1（已通过）"),
    ("gemma4-31b-shortform", "Gemma4 31B 短文微调版（115.190.27.75:19010）"),
]


def check_one_model(model_id: str, label: str) -> tuple[str, str]:
    """对单个模型发一条最简调用，返回 (状态, 详情)。"""
    try:
        from services.model_adapter import ModelAdapter
    except ImportError as exc:
        return ("ERROR", f"导入 ModelAdapter 失败: {exc}")

    try:
        adapter = ModelAdapter()
        if model_id not in adapter._models:
            return ("MISS", f"模型 {model_id} 未注册到 ModelAdapter")

        messages = [
            {"role": "system", "content": "你是测试助手，请极简回复。"},
            {"role": "user", "content": "你好"},
        ]
        t0 = time.time()
        result = adapter.chat(
            model_id=model_id,
            messages=messages,
            max_tokens=64,
        )
        latency = time.time() - t0

        if not getattr(result, "success", False):
            err = str(getattr(result, "error", "") or "未知错误")
            lower = err.lower()
            if "model_not_found" in lower or "model not exist" in lower or "model not found" in lower:
                return ("404", f"模型名错误: {err[:120]}")
            if "401" in err or "unauthorized" in lower or "invalid api key" in lower:
                return ("401", f"API Key 无效或权限不足: {err[:120]}")
            if "403" in err or "region" in lower or "permission" in lower:
                return ("403", f"地域/权限不匹配（MiMo 北京限制？）: {err[:120]}")
            if "429" in err:
                return ("429", "限流，稍后重试")
            return ("FAIL", f"{err[:120]}")

        text = str(getattr(result, "content", "") or "")
        if text.strip():
            preview = text.strip().replace("\n", " ")[:30]
            return ("OK", f"{latency:.2f}s | {preview}...")
        return ("EMPTY", f"{latency:.2f}s | 返回空文本")
    except Exception as exc:
        return ("ERROR", f"{type(exc).__name__}: {str(exc)[:120]}")


def main() -> int:
    # Windows GBK 终端兼容：强制 stdout 走 UTF-8
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print("=" * 70)
    print(f"新模型配置验证（{len(MODELS_TO_VERIFY)} 个）")
    print("=" * 70)
    print(f"{'状态':6} | {'模型':22} | 详情")
    print("-" * 70)

    results = []
    for model_id, label in MODELS_TO_VERIFY:
        status, detail = check_one_model(model_id, label)
        symbol = {
            "OK": "[OK]",
            "EMPTY": "[??]",
            "MISS": "[XX]",
            "404": "[XX]",
            "401": "[XX]",
            "403": "[XX]",
            "429": "[!!]",
            "FAIL": "[XX]",
            "ERROR": "[XX]",
        }.get(status, "[??]")
        line = f"{symbol} {status:4} | {model_id:22} | {detail}"
        print(line)
        results.append((model_id, status, detail))

    print("=" * 70)
    ok_count = sum(1 for _, s, _ in results if s == "OK")
    print(f"通过: {ok_count}/{len(results)}")

    failed = [(m, s, d) for m, s, d in results if s != "OK"]
    if failed:
        print("\n失败模型需要处理：")
        for m, s, d in failed:
            print(f"  - {m} ({s}): {d}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
