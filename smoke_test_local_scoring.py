"""
真实冒烟测试: gemma4-31b-local 打分链路端到端验证。
会发一次真实请求到本地 vLLM，消耗一次模型推理。
"""
import asyncio
import os
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
SERVER_DIR = PROJECT_DIR / "server"

if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

# 加载 .env
from dotenv import load_dotenv
load_dotenv(SERVER_DIR / ".env")

from services.scoring_service import ScoringService


async def smoke_test():
    service = ScoringService()

    # Step 1: 可用性检查
    print("=" * 60)
    print("[Step 1] is_available(gemma4-31b-local)")
    available = service.is_available("gemma4-31b-local")
    print(f"  结果: {available}")
    if not available:
        print(f"  错误: {service.get_last_error()}")
        return False

    # Step 2: get_dimensions
    print("[Step 2] get_dimensions(gemma4-31b-local)")
    dims = service.get_dimensions(model_id="gemma4-31b-local")
    print(f"  维度: {dims.get('dimensions', [])}")

    # Step 3: score_turn — 真实调用
    print("[Step 3] score_turn (real API call to local Gemma4)")
    turn_data = {
        "user_input": "今天天气真好，想出去走走",
        "ai_output": (
            "*午后的阳光从窗帘缝隙里溜进来，在地板上画出一道暖黄色的光带。"
            "他放下手里的书，指尖还停在刚翻过的那一页，抬头看你的表情比平时多了点认真。*\n\n"
            "「那就走吧。」\n\n"
            "*他把外套从椅背上拎起来，动作不急不缓，像是早就在等这句话。"
            "门把手被他握住的瞬间，回头瞥了你一眼——"
            "没催，只是把门开得刚好够你先出去的宽度，然后自己侧身跟上，"
            "鞋跟在门槛上磕了一声，混在风里，轻得像故意的。*"
        ),
        "turn": 1,
        "role_name": "肖景言",
        "personality": "理性沉稳",
        "relationship": "暧昧",
        "prompt_name": "冒烟测试",
    }

    start = time.time()
    result = await service.score_turn(
        turn_data,
        model_id="gemma4-31b-local",
    )
    elapsed = round(time.time() - start, 2)

    print(f"  耗时: {elapsed}s")
    print(f"  成功: {result.get('success')}")
    print(f"  模型: {result.get('model_id')}")
    print(f"  总分: {result.get('mapped_total')}")
    print(f"  各维度: {result.get('scores')}")
    print(f"  推理: {str(result.get('reasoning', ''))[:200]}")
    if not result.get("success"):
        print(f"  错误: {result.get('error')}")

    print("=" * 60)
    if result.get("success") and result.get("mapped_total", 0) > 0:
        print("[PASS] smoke test OK: gemma4-31b-local scoring pipeline works end-to-end")
        return True
    else:
        print("[FAIL] smoke test failed")
        return False


if __name__ == "__main__":
    success = asyncio.run(smoke_test())
    sys.exit(0 if success else 1)
