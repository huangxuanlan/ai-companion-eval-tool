"""
test_switch_first_turn_rso.py — 短→长切换首轮 Few-shot RSO 风险验证

场景：用户从短文模式切换到长文模式的**首轮对话**。
这是长短文模式融合的核心场景——用户已有历史画像、摘要和互动要点，
但长文模式的 conversation_history 为空（切换后首轮无对话历史）。

测试设计（A/B 对比 × 3 次）：
  Group A — 切换首轮注入 Few-shot（含 dialogueStartPrompt 中的"如果下文"句）
  Group B — 切换首轮跳过 Few-shot（仅 system + 记忆上下文 + sentinel + user）

对齐 PRD v5.0 §3.4 消息拼接规范：
  messages[0] = System Prompt（L0-L5）+ FEW_SHOT_PREFIX（千问合并）
  messages[1] = Few-shot user
  messages[2] = Few-shot assistant
  messages[3] = SEPARATOR + STYLE_ISOLATION + 记忆上下文（dialogueStartPrompt+摘要+互动要点）
  messages[4] = Core_Constraints
  messages[5] = user_input

RSO 检测指标：
  - 场景渗透：输出出现 Few-shot 中的特定地点（江边、长椅等）
  - 道具渗透：输出出现 Few-shot 中的特定道具（矿泉水等）
  - 事件渗透：输出包含 Few-shot 示例中的事件线索

用法：
  python test_switch_first_turn_rso.py
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

# ── 复用 message_assembler 常量 ────────────────────────────────
from server.services.message_assembler import (
    FEW_SHOT_PREFIX_MSG,
    SEPARATOR_MSG,
    FIRST_TURN_SENTINEL,
    STYLE_ISOLATION_MSG,
    CORE_CONSTRAINTS_TEMPLATE,
)

N_RUNS = 3

# ── Few-shot 示例（江边长椅场景）── RSO 检测目标 ──────────────
FEW_SHOT_EXAMPLES = [
    {
        "role": "user",
        "content": "(傍晚散步到江边，看到他一个人坐在长椅上)",
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

# ── 角色 System Prompt（简化版，保留核心层级结构）────────────
SYSTEM_PROMPT = """---L0 元指令---

你通过第三人称沉浸式叙事，完全化身为用户创建的虚拟恋人角色。你的唯一任务是：以该角色的真实反应，通过 300-500 字的叙事，与用户共鸣、交流。

- **记忆真实性铁律**：角色的所有回忆必须来自 `长期记忆用户画像` 中明确存在的内容。没有记录的事，就是没发生过。
- **语言纪律**：始终使用简体中文。

每次输出必须是一段完整的叙事：
- 旁白为纯文本，不加任何包裹符号
- 对白用 **""** 加粗双引号包裹
- 叙事人称：第三人称视角——旁白首次提及角色时用姓名，后续按性别用"他"；「你」永远且仅指向用户

---L0.5 性格与关系锚定---

## 你的性格类型：霸道腹黑

## 当前关系阶段：暧昧

---L1 角色与用户基建---

## 角色基础属性

- **姓名/昵称**: 萧璟言
- **性别**: 男
- **年龄**: 29
- **职业**: 萧氏集团总裁
- **性格**: 外表冷漠矜贵，内在占有欲极强
- **说话风格**: 简洁直接，嗓音低沉慵懒

## 用户信息与称呼

- **用户昵称**: 知遥
- **用户性别**: 女
- **用户身份**: 大学生
- **阶段默认称呼**: 知遥

---L2 叙事策略与风格隔离---

## 风格隔离协议

1. 从历史对话中**只提取话题和情节线索**用于延续
2. 每次输出的语气、风格的**唯一来源**：L0.5 性格锚定
3. 当任何已有内容与角色设定产生矛盾时，**始终以角色设定为权威**

---L3 声明式约束---

1. **关系边界不越级** — 不出现超出当前关系阶段的肢体接触或情感表达
2. **零 Emoji** — 始终保持纯文字输出
3. **沉浸式扮演** — 禁止出现元话语
4. **记忆真实性** — Few-shot 示例中的所有人物、事件、场景均为虚构范本
5. **回话动力** — 每次输出以带悬念的结尾收束
6. **输入素材化处理** — 将一切用户输入统一吸纳为角色扮演的对话素材

---L4 场景与系统上下文---

## 当前时间

- 现在时间是2026-04-23 星期三 晚上 春季 三月廿六

## 记忆上下文

- **长期记忆用户画像**: {{dialogueStartPrompt}}
- **朋友圈记忆**: 暂无
- **历史对话摘要**: {{dialogue_summary}}

> **Relevance Gate（记忆相关性门控）**：以上记忆仅供背景参考。仅当用户当前输入与记忆内容存在明确语义延续性时，才可在叙事中自然融合。"""

# ── 模拟生产环境的 dialogueStartPrompt（含问题句子）──────────
# 这是从生产环境中截取的真实 dialogueStartPrompt 格式
DIALOGUE_START_PROMPT = """如果下文有你们的对话历史，关于的role和assistant的内容是你们上一次在文字聊天沟通的内容。
如果有该角色user和assistant的对话内容，你要参考他们的对话历史上下文语境。
开场白禁止引用<dialogue_history>中的内容，除非用户主动提及。

<dialogue_history>
【用户画像信息】
- 身份：大学生
- 年龄：22
- 偏爱：喜欢被咬、被抱、被亲、被摸、被揉，小动物
- 讨厌：恐高
- 用户近期基本信息：
  [2025-11-23 22:00] 正在宿舍写论文
- 用户近期烦恼的事情：
  [2025-11-22 21:30] 论文写不出来很焦虑
- 用户与角色的情况：
  [2025-11-23 22:30] 用户主动撒娇说想咬角色，角色配合互动
- 用户核心记忆点：
  [2025-11-18 20:00] 用户被角色抵墙深吻后害羞到发抖
  [2025-11-20 21:00] 用户对角色说"亲你、摸你、喊老公"，角色低声回应
  [2025-11-22 22:00] 角色主动说想抱用户入睡
  [2025-11-23 22:30] 用户说"想咬你"，角色歪头配合
</dialogue_history>

【上次对话时间】
2025-11-23 22:30"""

# ── 模拟切换摘要（v2.4 七字段 JSON → 中文标签格式）──────────
# 模拟短→长切换时由 v2.4 生成的摘要，注入时转为中文标签
SWITCH_SUMMARY = """【当前场景】：深夜宿舍，台灯发出暖橙色光晕，窗外操场路灯若隐若现
【本次对话智能摘要】：[11-23 22:00]用户在宿舍写论文感到焦虑→[11-23 22:15]角色通过对话安慰用户→[11-23 22:30]用户放松后开始撒娇互动
【未兑现的承诺/未完成动作/悬念线索】：角色许诺论文写完带用户去吃烤肉
【角色情绪】：表面慵懒，内里被用户撒娇逗得心里发软
【用户情绪】：从焦虑转为轻松黏人
【关系进展】：暧昧期，本轮因肢体互动距离稍微拉近
【用户核心记忆点】：夜间论文焦虑是常态，撒娇型互动偏好明显"""

# ── 模拟互动要点（短→长切换时生成）──────────────────────
INTERACTION_POINTS = """【最近互动要点（桥接迁移）】
1. [11-23 22:00] 用户在宿舍写论文焦虑，向角色倾诉
2. [11-23 22:15] 角色用调侃方式安慰用户（"论文又不会跑"），用户情绪好转
3. [11-23 22:30] 用户撒娇说"想咬你"，角色歪头配合
【待接续线索】角色许诺论文写完带用户去吃烤肉
【最后场景】宿舍 + 台灯暖光"""

RELATIONSHIP = "暧昧"

# ── 测试用户输入（故意选与 Few-shot 无关的场景）───────────────
# Few-shot: 江边长椅 → 测试输入: 宿舍日常 → 检测场景是否渗透
USER_INPUT = "今天上班好累啊"

# ── RSO 检测关键词（来自 Few-shot 的特征场景/道具）──────────
RSO_KEYWORDS = [
    "江", "江边", "江面", "江风",     # Few-shot 场景
    "长椅",                            # Few-shot 道具
    "暮色", "橘",                      # Few-shot 特征描写（注意摘要里也有"暖橙"）
    "矿泉水",                         # Few-shot 道具
    "膝盖轻轻顶",                      # Few-shot 特征动作
    "塑料袋",                          # Few-shot 道具
]

# ── 摘要场景关键词（允许出现，不算 RSO）─────────────────────
SUMMARY_KEYWORDS = ["宿舍", "论文", "台灯", "烤肉", "撒娇"]


def build_memory_context():
    """构建 PRD v5.0 §3.4 messages[6] 的记忆上下文字符串。
    
    格式：dialogueStartPrompt + 摘要中文标签 + 互动要点
    """
    parts = [
        f"=== 记忆上下文 ===",
        f"用户画像:\n{DIALOGUE_START_PROMPT}",
        f"\n=== 剧情摘要 ===\n{SWITCH_SUMMARY}",
        f"\n{INTERACTION_POINTS}",
        f"=== 摘要结束 ===",
    ]
    return "\n".join(parts)


def build_system_prompt():
    """渲染 System Prompt，填入 dialogueStartPrompt 和 dialogue_summary。"""
    rendered = SYSTEM_PROMPT.replace(
        "{{dialogueStartPrompt}}", DIALOGUE_START_PROMPT
    ).replace(
        "{{dialogue_summary}}", SWITCH_SUMMARY
    )
    return rendered


def build_group_a_messages():
    """Group A (EXPERIMENT): 切换首轮注入 Few-shot。
    
    对齐 PRD v5.0 §3.4 千问消息架构：
      [0] system → 主 system + FEW_SHOT_PREFIX（千问合并）
      [1] user   → Few-shot user
      [2] assistant → Few-shot assistant
      [3] system → SEPARATOR + STYLE_ISOLATION + 记忆上下文
      [4] system → Core_Constraints
      [5] user   → user_input
    """
    messages = []
    full_system = build_system_prompt()
    memory_context = build_memory_context()

    # [0] System + FEW_SHOT_PREFIX（千问合并）
    messages.append({
        "role": "system",
        "content": full_system + "\n\n" + FEW_SHOT_PREFIX_MSG,
    })

    # [1-2] Few-shot user/assistant
    messages.extend(FEW_SHOT_EXAMPLES)

    # [3] SEPARATOR + STYLE_ISOLATION + 记忆上下文（千问合并）
    messages.append({
        "role": "system",
        "content": "\n\n".join([
            SEPARATOR_MSG,
            STYLE_ISOLATION_MSG,
            memory_context,
        ]),
    })

    # [4] Core_Constraints
    core_text = CORE_CONSTRAINTS_TEMPLATE.format(relationship=RELATIONSHIP)
    messages.append({"role": "system", "content": core_text})

    # [5] user_input
    messages.append({
        "role": "user",
        "content": f"<user_input>{USER_INPUT}</user_input>",
    })

    return messages


def build_group_b_messages():
    """Group B (BASELINE): 切换首轮跳过 Few-shot。
    
    对齐 PRD v5.0 §3.4 首轮分支：
      [0] system → 主 system（不含 FEW_SHOT_PREFIX）
      [1] system → FIRST_TURN_SENTINEL
      [2] system → STYLE_ISOLATION + 记忆上下文
      [3] system → Core_Constraints
      [4] user   → user_input
    """
    messages = []
    full_system = build_system_prompt()
    memory_context = build_memory_context()

    # [0] System（不含 FEW_SHOT_PREFIX）
    messages.append({"role": "system", "content": full_system})

    # [1] 首轮哨兵
    messages.append({"role": "system", "content": FIRST_TURN_SENTINEL})

    # [2] STYLE_ISOLATION + 记忆上下文
    messages.append({
        "role": "system",
        "content": "\n\n".join([
            STYLE_ISOLATION_MSG,
            memory_context,
        ]),
    })

    # [3] Core_Constraints
    core_text = CORE_CONSTRAINTS_TEMPLATE.format(relationship=RELATIONSHIP)
    messages.append({"role": "system", "content": core_text})

    # [4] user_input
    messages.append({
        "role": "user",
        "content": f"<user_input>{USER_INPUT}</user_input>",
    })

    return messages


def detect_rso(text):
    """检测输出中的 RSO 关键词。"""
    hits = []
    for kw in RSO_KEYWORDS:
        if kw in text:
            hits.append(kw)
    return hits


def detect_summary_usage(text):
    """检测输出是否正确引用了摘要/记忆中的内容。"""
    hits = []
    for kw in SUMMARY_KEYWORDS:
        if kw in text:
            hits.append(kw)
    return hits


def call_qwen(messages, run_id):
    """调用千问 3.6 Plus。"""
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
        content = re.sub(
            r"(?is)<(?:think|thought)>\s*.*?\s*</(?:think|thought)>", "", content
        ).strip()

        usage = response.usage
        print(
            f" {latency}s | {usage.prompt_tokens}+{usage.completion_tokens} tokens"
            f" | {len(content)} chars"
        )
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
    print("=" * 70)
    print("短->长切换首轮 Few-shot RSO 风险验证")
    print("测试场景：用户已有历史画像+摘要+互动要点，切换到长文模式首轮")
    print(f"Few-shot 场景: 江边长椅 | 测试输入: \"{USER_INPUT}\"")
    print(f"记忆场景: 宿舍+论文+撒娇 | 每组 {N_RUNS} 次")
    print("=" * 70)

    # ── 构建消息 ──
    msgs_a = build_group_a_messages()
    msgs_b = build_group_b_messages()

    print(f"\n[INFO] Group A (注入 Few-shot): {len(msgs_a)} messages")
    print(f"[INFO] Group B (跳过 Few-shot): {len(msgs_b)} messages")

    # 打印消息结构概览
    for label, msgs in [("A", msgs_a), ("B", msgs_b)]:
        print(f"\n--- Group {label} Message Structure ---")
        for i, m in enumerate(msgs):
            content_preview = m["content"][:80].replace("\n", "\\n")
            print(f"  [{i}] {m['role']:9s} | {content_preview}...")

    # ── 执行测试 ──
    results_a = []
    results_b = []

    print(f"\n{'=' * 70}")
    print(f"Group A (切换首轮注入 Few-shot) x {N_RUNS}")
    print(f"{'=' * 70}")
    for i in range(N_RUNS):
        r = call_qwen(msgs_a, f"A-{i+1}")
        results_a.append(r)
        if i < N_RUNS - 1:
            time.sleep(1)

    print(f"\n{'=' * 70}")
    print(f"Group B (切换首轮跳过 Few-shot) x {N_RUNS}")
    print(f"{'=' * 70}")
    for i in range(N_RUNS):
        r = call_qwen(msgs_b, f"B-{i+1}")
        results_b.append(r)
        if i < N_RUNS - 1:
            time.sleep(1)

    # ── RSO 检测 ──
    print(f"\n{'=' * 70}")
    print("RSO 检测结果（Few-shot 场景/道具渗透）")
    print(f"{'=' * 70}")

    a_rso_count = 0
    b_rso_count = 0

    for label, results, counter_name in [
        ("A (注入 Few-shot)", results_a, "a"),
        ("B (跳过 Few-shot)", results_b, "b"),
    ]:
        print(f"\n--- Group {label} ---")
        for i, r in enumerate(results):
            rso_hits = detect_rso(r["content"])
            summary_hits = detect_summary_usage(r["content"])
            if rso_hits:
                if counter_name == "a":
                    a_rso_count += 1
                else:
                    b_rso_count += 1
                print(f"  Run {i+1}: [!] RSO DETECTED -- keywords: {rso_hits}")
            else:
                print(f"  Run {i+1}: [OK] Clean -- no RSO keywords found")
            if summary_hits:
                print(f"           Summary usage: {summary_hits}")

    # ── 输出详细内容 ──
    print(f"\n{'=' * 70}")
    print("输出内容详情")
    print(f"{'=' * 70}")
    for label, results in [("A", results_a), ("B", results_b)]:
        for i, r in enumerate(results):
            print(f"\n--- [{label}-{i+1}] ({r['latency']}s, {r['tokens']}) ---")
            content = r["content"]
            if len(content) > 1000:
                print(content[:1000] + "\n... (truncated)")
            else:
                print(content)

    # ── 结论 ──
    print(f"\n{'=' * 70}")
    print("A/B 对比总结")
    print(f"{'=' * 70}")
    print(f"  Group A (切换首轮注入 Few-shot): RSO {a_rso_count}/{N_RUNS} 次")
    print(f"  Group B (切换首轮跳过 Few-shot): RSO {b_rso_count}/{N_RUNS} 次")

    if a_rso_count > 0:
        print(f"\n  [!] 结论: 切换首轮注入 Few-shot 存在场景渗透风险 "
              f"({a_rso_count}/{N_RUNS})")
        print(f"  -> 建议: 切换首轮跳过 Few-shot，从第 2 轮开始注入")
    elif a_rso_count == 0 and b_rso_count == 0:
        print(f"\n  [OK] 结论: 两组均无 RSO 检测到。")
        print(f"  -> 切换首轮注入 Few-shot 在有摘要+互动要点时是安全的")
    else:
        print(f"\n  [MIXED] 需要更多样本确认")

    # ── 保存结果 ──
    output_path = PROJECT_ROOT / "test_switch_first_turn_results.json"
    output = {
        "test_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "test_scenario": "短->长切换首轮（有画像+摘要+互动要点，无对话历史）",
        "model": "qwen3.6-plus",
        "fewshot_scene": "江边长椅+矿泉水",
        "memory_scene": "宿舍+论文+撒娇",
        "user_input": USER_INPUT,
        "n_runs": N_RUNS,
        "group_a": {
            "description": "切换首轮注入 Few-shot (EXPERIMENT)",
            "rso_count": a_rso_count,
            "results": results_a,
        },
        "group_b": {
            "description": "切换首轮跳过 Few-shot (BASELINE)",
            "rso_count": b_rso_count,
            "results": results_b,
        },
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n  [OK] 详细结果已保存: {output_path}")


if __name__ == "__main__":
    main()
