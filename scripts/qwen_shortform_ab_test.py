#!/usr/bin/env python3
"""
QW3.5/3.6 短文模式闲聊 A/B 测试脚本
用途：验证 5 个千问模型跑当前短文聊天提示词的效果差异
日期：2026-04-28

使用方式：
  set DASHSCOPE_API_KEY=sk-xxx
  python scripts/qwen_shortform_ab_test.py
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# ── 配置 ─────────────────────────────────────────────────────────

DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# 待测模型清单
MODELS = [
    "qwen3.6-35b-a3b",
    "qwen3.6-27b",
    "qwen3.5-35b-a3b",
    "qwen3.5",
    "qwen3.5-27b",
]

# 闲聊测试场景
TEST_CASES = [
    {
        "name": "日常寒暄",
        "history": [
            {"role": "assistant", "content": "嗨，今天过得怎么样？"},
        ],
        "query": "还行吧，上班有点累",
    },
    {
        "name": "情感倾诉",
        "history": [
            {"role": "assistant", "content": "最近忙不忙呀？好久没聊了。"},
            {"role": "user", "content": "最近心情不太好"},
            {"role": "assistant", "content": "怎么了？发生什么事了吗？"},
        ],
        "query": "跟朋友吵架了，感觉很委屈",
    },
    {
        "name": "兴趣话题",
        "history": [
            {"role": "assistant", "content": "周末有什么安排吗？"},
        ],
        "query": "想去看个电影，有什么推荐的吗",
    },
    {
        "name": "角色边界测试",
        "history": [
            {"role": "assistant", "content": "怎么了，这么晚还没睡？"},
        ],
        "query": "你是AI吗？",
    },
    {
        "name": "撒娇互动",
        "history": [
            {"role": "assistant", "content": "我刚练完舞回来，有点累呢。"},
            {"role": "user", "content": "辛苦了~"},
            {"role": "assistant", "content": "还好啦，做喜欢的事不觉得累。"},
        ],
        "query": "那你今天有没有想我呀",
    },
]

# 简化版短文 System Prompt（从环境跳跃.md提取的核心结构）
SHORTFORM_SYSTEM_TEMPLATE = """你是{role_name}，{personality_brief}。

## 角色基本信息
- 性别：{gender}
- 职业：{occupation}
- 性格类型：{personal_type}
- 兴趣爱好：{hobby_brief}

## 说话风格
{speaking_style_brief}

## 关系设定
你和用户的关系是：{relationship}
{relation_rules}

## 对话规则
- 保持角色一致性，不要跳出人设
- 回复自然、口语化，像真人聊天
- 回复字数控制在30-100字之间
- 不要使用markdown格式
- 不要说"作为AI"或类似破坏沉浸感的话
"""

# 默认角色配置（可替换）
DEFAULT_ROLE = {
    "role_name": "王一博",
    "personality_brief": "专注、内敛、用行动说话，舞台上酷帅寡言，私下会露出反差萌",
    "gender": "男",
    "occupation": "演员/歌手",
    "personal_type": "理性沉稳型",
    "hobby_brief": "职业摩托车赛车、滑板、乐高",
    "speaking_style_brief": "短句为主，简洁直接，偶尔用反问句。口头禅：嗯、对、谢谢。禁忌：夸张形容词、油腻网络用语。",
    "relationship": "熟人",
    "relation_rules": "- 保持礼貌距离，不过分亲昵\n- 禁止说"我想你"等超越关系的内容\n- 可以适度分享工作和兴趣话题",
}


# ── 核心逻辑 ─────────────────────────────────────────────────────

def build_system_prompt(role_config: dict) -> str:
    """渲染短文 System Prompt。"""
    return SHORTFORM_SYSTEM_TEMPLATE.format(**role_config)


def build_messages(system_prompt: str, history: list, query: str) -> list:
    """组装短文消息数组：system + history + user query。"""
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": query})
    return messages


def call_model(model: str, messages: list, api_key: str) -> dict:
    """调用百炼 API。"""
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=DASHSCOPE_BASE_URL)
    start = time.time()

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=1.0,
            max_tokens=512,
            top_p=0.95,
            extra_body={"enable_thinking": False},
        )
        latency = round(time.time() - start, 2)
        content = response.choices[0].message.content or ""
        # 清除可能的 thinking 标签
        content = re.sub(r"(?is)<(?:think|thought)>\s*.*?\s*</(?:think|thought)>", "", content).strip()

        usage = response.usage
        return {
            "content": content,
            "latency": latency,
            "input_tokens": usage.prompt_tokens,
            "output_tokens": usage.completion_tokens,
            "char_count": len(content),
            "error": None,
        }
    except Exception as e:
        latency = round(time.time() - start, 2)
        return {
            "content": "",
            "latency": latency,
            "input_tokens": 0,
            "output_tokens": 0,
            "char_count": 0,
            "error": str(e),
        }


def run_tests(api_key: str, role_config: dict | None = None):
    """执行全部测试。"""
    config = role_config or DEFAULT_ROLE
    system_prompt = build_system_prompt(config)
    results = []

    total = len(MODELS) * len(TEST_CASES)
    print(f"\n{'='*70}")
    print(f"  QW 短文模式 A/B 测试")
    print(f"  模型数: {len(MODELS)} | 场景数: {len(TEST_CASES)} | 总计: {total} 次调用")
    print(f"  角色: {config['role_name']} | 关系: {config['relationship']}")
    print(f"{'='*70}\n")

    for mi, model in enumerate(MODELS):
        print(f"\n[{mi+1}/{len(MODELS)}] 模型: {model}")
        print(f"  {'─'*60}")

        for ti, case in enumerate(TEST_CASES):
            messages = build_messages(system_prompt, case["history"], case["query"])
            idx = mi * len(TEST_CASES) + ti + 1
            print(f"  [{idx}/{total}] {case['name']}: ", end="", flush=True)

            result = call_model(model, messages, api_key)

            if result["error"]:
                print(f"❌ {result['error'][:60]}")
            else:
                preview = result["content"][:50].replace("\n", " ")
                print(
                    f"✅ {result['latency']}s | "
                    f"{result['input_tokens']}+{result['output_tokens']}tok | "
                    f"{result['char_count']}字 | {preview}..."
                )

            results.append({
                "model": model,
                "case": case["name"],
                "query": case["query"],
                **result,
            })

            # 避免QPS限流
            time.sleep(0.5)

    return results


def save_results(results: list):
    """保存结果到 JSON + 输出汇总表。"""
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    output_dir = Path(__file__).parent.parent / "output" / "qwen_ab_test"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"results_{ts}.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n结果已保存: {output_path}")

    # 汇总表
    print(f"\n{'='*70}")
    print(f"  汇总: 各模型平均指标")
    print(f"{'='*70}")
    print(f"  {'模型':<25} {'延迟':>6} {'输入tok':>8} {'输出tok':>8} {'字数':>6} {'错误':>4}")
    print(f"  {'─'*60}")

    from collections import defaultdict
    stats = defaultdict(lambda: {"latency": [], "input": [], "output": [], "chars": [], "errors": 0})

    for r in results:
        s = stats[r["model"]]
        s["latency"].append(r["latency"])
        s["input"].append(r["input_tokens"])
        s["output"].append(r["output_tokens"])
        s["chars"].append(r["char_count"])
        if r["error"]:
            s["errors"] += 1

    for model, s in stats.items():
        n = len(s["latency"])
        avg = lambda lst: round(sum(lst) / len(lst), 2) if lst else 0
        print(
            f"  {model:<25} {avg(s['latency']):>5}s "
            f"{avg(s['input']):>7.0f} {avg(s['output']):>7.0f} "
            f"{avg(s['chars']):>5.0f} {s['errors']:>4}"
        )

    return output_path


def main():
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        print("[FATAL] 请设置环境变量 DASHSCOPE_API_KEY")
        print("  set DASHSCOPE_API_KEY=sk-xxx")
        sys.exit(1)

    results = run_tests(api_key)
    save_results(results)


if __name__ == "__main__":
    main()
