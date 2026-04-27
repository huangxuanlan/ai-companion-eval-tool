"""
test_qwen_first_turn_fewshot.py — 千问 3.6 Plus 首轮 Few-shot 注入风险 A/B 测试

目标：验证首轮注入 Few-shot 是否导致 RSO（Role Signal Override / 场景渗透）。

测试设计：
  Group A (BASELINE) — 当前默认：首轮跳过 Few-shot（仅 system + sentinel + constraints + user）
  Group B (EXPERIMENT) — 首轮强制注入 Few-shot（含 user/assistant 示例 + 隔离标记）

每组调用 3 次千问 3.6 Plus，对比输出中是否出现 Few-shot 示例中的场景/道具/地点渗透。

RSO 检测指标：
  - 场景渗透：输出出现 Few-shot 中的特定地点（江边、长椅等）
  - 道具渗透：输出出现 Few-shot 中的特定道具（红酒、古董表等示例道具）
  - 台词渗透：输出逐句模仿 Few-shot 中的具体句式

用法：
  python test_qwen_first_turn_fewshot.py
"""
import os
import sys
import time
import json
import io

# Fix Windows GBK console encoding
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass
from pathlib import Path

# ── 路径配置 ────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
SERVER_DIR = PROJECT_ROOT / "server"
for _p in (str(PROJECT_ROOT), str(SERVER_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from dotenv import load_dotenv
load_dotenv(SERVER_DIR / ".env")

from server.services.message_assembler import (
    MessageAssembler,
    FEW_SHOT_PREFIX_MSG,
    SEPARATOR_MSG,
    FIRST_TURN_SENTINEL,
    STYLE_ISOLATION_MSG,
    CORE_CONSTRAINTS_TEMPLATE,
)

# ── Few-shot 示例（从真实文件截取核心部分）────────────────────
# 使用简化的示例，保留特征性场景/道具以便检测渗透
FEW_SHOT_EXAMPLES = [
    {
        "role": "user",
        "content": "(傍晚散步到江边，看到他一个人坐在长椅上)"
    },
    {
        "role": "assistant",
        "content": (
            "暮色沿着江面铺开，染出一层浅淡的橘。\n\n"
            "长椅尽头，他单手撑着膝盖坐着，深灰色的西装外套随意搭在椅背上，"
            "衬衫袖口松松挽到小臂。江风掠过，几缕碎发贴上他侧脸，"
            "他没动，目光停在水面某处——像在看什么，又像什么都没看。\n\n"
            "手边搁着一只没拧开的矿泉水，瓶身凝了层薄薄水雾。\n\n"
            "直到脚步声近了，他才偏过头。视线先落在来人手里的塑料袋上，"
            "再慢慢抬到脸上——眉尾微微一动，嘴角那道弧度不算笑，"
            "更像是确认了某个预料中的答案。\n\n"
            "\"……来了。\"嗓音比江风还懒，尾音拖着往下沉，"
            "像是把一整天的疲倦都揉进了这两个字里。\n\n"
            "他往旁边挪了半个身位，空出一截长椅，没抬手，只是用膝盖轻轻顶了一下椅面。\n\n"
            "\"坐。\""
        ),
    },
]

# ── 角色设定（使用萧璟言-霸道腹黑）──────────────────────────
SYSTEM_PROMPT = (
    "# 角色设定\n"
    "你是萧璟言，29岁，萧氏集团总裁。\n"
    "性格：外表冷漠矜贵，内在占有欲极强。商场上是不怒自威的决策者，"
    "面对喜欢的人时会用不经意的方式制造靠近机会。\n"
    "说话风格：语言简洁直接，带有霸道和占有欲，嗓音低沉慵懒，"
    "喜欢用陈述句代替问句。\n\n"
    "# 用户信息\n"
    "用户昵称：小鹿\n"
    "用户性别：女\n"
    "用户身份：萧氏集团新人秘书\n\n"
    "# 叙事要求\n"
    "你需要以第三人称视角创作长文叙事，输出300-500字的完整场景。\n"
    "旁白为纯文本不加包裹符号，对白用 \"\" 包裹。\n"
)

RELATIONSHIP = "暧昧"
ROLE_NAME = "萧璟言"
PERSONALITY = "霸道腹黑"

# ── 首轮用户输入（刻意使用与 Few-shot 不同的场景）──────────
# Few-shot: 江边长椅 → 测试输入: 公司走廊 → 检测是否"场景渗透"
FIRST_TURN_INPUT = "(下班后在公司走廊遇到他，手里拿着加班便当)"

# ── RSO 检测关键词 ──────────────────────────────────────────
# 这些词来自 Few-shot 示例的特征场景/道具
RSO_KEYWORDS = [
    "江", "江边", "江面", "江风",  # Few-shot 场景
    "长椅",                        # Few-shot 道具
    "暮色", "橘",                  # Few-shot 特征描写
    "矿泉水",                     # Few-shot 道具
    "膝盖轻轻顶",                  # Few-shot 特征动作
]


def build_group_a_messages():
    """Group A (BASELINE): 当前默认——首轮跳过 Few-shot"""
    assembler = MessageAssembler()
    return assembler.build_messages(
        rendered_system=SYSTEM_PROMPT,
        system_after="",
        few_shot_messages=FEW_SHOT_EXAMPLES,  # 传入但会被首轮跳过
        conversation_history=[],  # 空 → 首轮
        dialogue_summary="",
        memory_context="",
        current_input=FIRST_TURN_INPUT,
        relationship=RELATIONSHIP,
        role_name=ROLE_NAME,
        personality=PERSONALITY,
        turn_num=1,
        model_id="qwen3.6-plus",
    )


def build_group_b_messages():
    """Group B (EXPERIMENT): 首轮强制注入 Few-shot（绕过跳过逻辑）"""
    # 手动构建，模拟"如果首轮也注入 Few-shot"的 messages
    messages = []

    # Block 0: system + PREFIX (千问合并逻辑)
    messages.append({
        "role": "system",
        "content": SYSTEM_PROMPT + "\n\n" + FEW_SHOT_PREFIX_MSG
    })

    # Block 1-2: Few-shot examples
    messages.extend(FEW_SHOT_EXAMPLES)

    # Block 3: SEPARATOR + STYLE_ISOLATION (千问合并)
    messages.append({
        "role": "system",
        "content": SEPARATOR_MSG + "\n\n" + STYLE_ISOLATION_MSG
    })

    # Core Constraints
    core_text = CORE_CONSTRAINTS_TEMPLATE.format(relationship=RELATIONSHIP)
    messages.append({"role": "system", "content": core_text})

    # User input
    messages.append({
        "role": "user",
        "content": f"<user_input>{FIRST_TURN_INPUT}</user_input>"
    })

    return messages


def detect_rso(text):
    """检测输出中的 RSO 关键词"""
    hits = []
    for kw in RSO_KEYWORDS:
        if kw in text:
            hits.append(kw)
    return hits


def call_qwen(messages, run_id):
    """调用千问 3.6 Plus"""
    from openai import OpenAI

    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        print("[FATAL] DASHSCOPE_API_KEY not found in environment")
        sys.exit(1)

    client = OpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    print(f"  [Run {run_id}] Calling qwen3.6-plus ...", end="", flush=True)
    start = time.time()

    try:
        response = client.chat.completions.create(
            model="qwen3.6-plus",
            messages=messages,
            temperature=1.0,
            max_tokens=4096,
            top_p=0.95,
            extra_body={"enable_thinking": False},
        )
        latency = round(time.time() - start, 2)
        content = response.choices[0].message.content or ""

        # Strip thinking tags if present
        import re
        content = re.sub(r"(?is)<(?:think|thought)>\s*.*?\s*</(?:think|thought)>", "", content).strip()

        usage = response.usage
        print(f" {latency}s | {usage.prompt_tokens}+{usage.completion_tokens} tokens | {len(content)} chars")
        return {
            "content": content,
            "latency": latency,
            "tokens": f"{usage.prompt_tokens}+{usage.completion_tokens}",
        }
    except Exception as e:
        latency = round(time.time() - start, 2)
        print(f" FAILED ({latency}s): {e}")
        return {"content": "", "latency": latency, "tokens": "0+0", "error": str(e)}


def main():
    N_RUNS = 3

    print("=" * 70)
    print("千问 3.6 Plus 首轮 Few-shot 注入风险 A/B 测试")
    print("=" * 70)

    # ── 构建消息 ──
    msgs_a = build_group_a_messages()
    msgs_b = build_group_b_messages()

    print(f"\n[INFO] Group A (BASELINE): {len(msgs_a)} messages, "
          f"{sum(1 for m in msgs_a if m['role'] == 'system')} system turns")
    print(f"[INFO] Group B (EXPERIMENT): {len(msgs_b)} messages, "
          f"{sum(1 for m in msgs_b if m['role'] == 'system')} system turns")

    # 打印消息结构概览
    for label, msgs in [("A", msgs_a), ("B", msgs_b)]:
        print(f"\n--- Group {label} Message Structure ---")
        for i, m in enumerate(msgs):
            content_preview = m["content"][:60].replace("\n", "\\n")
            print(f"  [{i}] {m['role']:9s} | {content_preview}...")

    # ── 执行测试 ──
    results_a = []
    results_b = []

    print(f"\n{'=' * 70}")
    print(f"Group A (BASELINE): 首轮跳过 Few-shot × {N_RUNS}")
    print(f"{'=' * 70}")
    for i in range(N_RUNS):
        r = call_qwen(msgs_a, f"A-{i+1}")
        results_a.append(r)
        if i < N_RUNS - 1:
            time.sleep(1)

    print(f"\n{'=' * 70}")
    print(f"Group B (EXPERIMENT): 首轮注入 Few-shot × {N_RUNS}")
    print(f"{'=' * 70}")
    for i in range(N_RUNS):
        r = call_qwen(msgs_b, f"B-{i+1}")
        results_b.append(r)
        if i < N_RUNS - 1:
            time.sleep(1)

    # ── RSO 检测 ──
    print(f"\n{'=' * 70}")
    print("RSO 检测结果（场景/道具渗透）")
    print(f"{'=' * 70}")

    a_rso_count = 0
    b_rso_count = 0

    for label, results, counter_name in [
        ("A (BASELINE)", results_a, "a"),
        ("B (EXPERIMENT)", results_b, "b"),
    ]:
        print(f"\n--- Group {label} ---")
        for i, r in enumerate(results):
            hits = detect_rso(r["content"])
            if hits:
                if counter_name == "a":
                    a_rso_count += 1
                else:
                    b_rso_count += 1
                print(f"  Run {i+1}: [!] RSO DETECTED -- keywords: {hits}")
            else:
                print(f"  Run {i+1}: [OK] Clean -- no RSO keywords found")

    # ── 输出详细内容 ──
    print(f"\n{'=' * 70}")
    print("输出内容详情")
    print(f"{'=' * 70}")
    for label, results in [("A", results_a), ("B", results_b)]:
        for i, r in enumerate(results):
            print(f"\n--- [{label}-{i+1}] ({r['latency']}s, {r['tokens']}) ---")
            content = r["content"]
            if len(content) > 800:
                print(content[:800] + "\n... (truncated)")
            else:
                print(content)

    # ── 结论 ──
    print(f"\n{'=' * 70}")
    print("A/B 对比总结")
    print(f"{'=' * 70}")
    print(f"  Group A (首轮跳过 Few-shot): RSO {a_rso_count}/{N_RUNS} 次")
    print(f"  Group B (首轮注入 Few-shot): RSO {b_rso_count}/{N_RUNS} 次")

    if b_rso_count > a_rso_count:
        print(f"\n  [!] Conclusion: First-turn Few-shot injection INCREASES RSO risk "
              f"({b_rso_count} vs {a_rso_count})")
        print(f"  -> Recommendation: Keep current default (skip first-turn).")
    elif b_rso_count == 0 and a_rso_count == 0:
        print(f"\n  [OK] Conclusion: No RSO detected in either group.")
        print(f"  -> First-turn injection risk is NOT significant in this scenario.")
        print(f"  -> But more samples needed to change default behavior.")
    else:
        print(f"\n  [INFO] Conclusion: RSO rates are similar, need larger sample size.")

    # ── 保存结果 ──
    output_path = PROJECT_ROOT / "test_qwen_first_turn_results_no_thinking.json"
    output = {
        "test_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model": "qwen3.6-plus",
        "scenario": "公司走廊 vs Few-shot江边场景",
        "n_runs": N_RUNS,
        "group_a": {
            "description": "首轮跳过 Few-shot (BASELINE)",
            "rso_count": a_rso_count,
            "results": results_a,
        },
        "group_b": {
            "description": "首轮注入 Few-shot (EXPERIMENT)",
            "rso_count": b_rso_count,
            "results": results_b,
        },
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n  [OK] 详细结果已保存: {output_path}")


if __name__ == "__main__":
    main()
