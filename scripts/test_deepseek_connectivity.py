#!/usr/bin/env python3
"""测试deepseek模型连通性"""
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SERVER_DIR = PROJECT_ROOT / "server"
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SERVER_DIR))

from services.model_adapter import ModelAdapter

def test_model(model_id: str, with_thinking: bool = False):
    """测试单个模型"""
    print(f"\n测试 {model_id} (thinking={with_thinking})...")
    
    adapter = ModelAdapter()
    messages = [{"role": "user", "content": "你好，请用一句话回复"}]
    
    start_time = time.time()
    try:
        if with_thinking:
            result = adapter.chat(
                model_id=model_id,
                messages=messages,
                max_tokens=100,
                thinking_effort="low"
            )
        else:
            result = adapter.chat(
                model_id=model_id,
                messages=messages,
                max_tokens=100
            )
        
        latency = time.time() - start_time
        
        if result.success:
            print(f"✅ 成功: {latency:.3f}s")
            print(f"   输出: {result.content[:50]}...")
            print(f"   tokens: in={result.input_tokens}, out={result.output_tokens}")
        else:
            print(f"❌ 失败: {result.error}")
            print(f"   耗时: {latency:.3f}s")
    
    except Exception as e:
        latency = time.time() - start_time
        print(f"❌ 异常: {str(e)}")
        print(f"   耗时: {latency:.3f}s")

if __name__ == "__main__":
    print("=" * 60)
    print("DeepSeek 模型连通性测试")
    print("=" * 60)
    
    # 测试deepseek-v4-flash
    test_model("deepseek-v4-flash", with_thinking=False)
    test_model("deepseek-v4-flash", with_thinking=True)
    
    # 测试deepseek-v4-pro
    test_model("deepseek-v4-pro", with_thinking=False)
    test_model("deepseek-v4-pro", with_thinking=True)
    
    # 对比测试doubao
    print("\n" + "=" * 60)
    print("对比测试 Doubao 模型")
    print("=" * 60)
    test_model("doubao-lite", with_thinking=False)
    test_model("doubao-mini", with_thinking=False)
    
    print("\n测试完成！")
