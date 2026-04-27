#!/usr/bin/env python3
"""
长文模式生成脚本 - 读取 Excel → 按消息架构白皮书拼接 messages → 调用豆包 API → 输出 Excel

用法:
  python generate.py input.xlsx                     # 基本用法
  python generate.py input.xlsx -o output.xlsx      # 指定输出
  python generate.py input.xlsx --dry-run           # 只打印消息结构，不调用 API
  python generate.py input.xlsx --workers 30        # 并发数
  python generate.py input.xlsx --prompt prompt/my_prompt.md  # 指定提示词文件

Excel 必填列: Role_Nickname, personality, personal_type, user_message
Excel 可选列: 见 --help 输出

消息架构 (v2.1, 移除 Greeting):
  messages[0]:    system     提示词全文 (L0-L5 变量填充后)
  messages[1-6]:  user/asst  Few-shot 示例 x3
  messages[7]:    system     分隔标记
  messages[8+]:   user/asst  对话历史 (conversation_history / session 链式)
  messages[N-1]:  system     <Core_Constraints> 重申
  messages[N]:    user       <user_input>当前输入</user_input>
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx
import pandas as pd

# ═══════════════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════════════

SCRIPT_DIR = Path(__file__).parent
DEFAULT_PROMPT = SCRIPT_DIR / "prompt" / "星朋友长文模式_提示词_v1.2.md"
DEFAULT_FEWSHOT = SCRIPT_DIR / "few_shot" / "长文模式_Few-shot示例库.md"

API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
MODEL = "doubao-seed-2-0-pro-260215"

SEPARATOR_CONTENT = (
    "---以上内容仅作为「文学写作风格」和「输出格式」的参考示例---\n"
    "【注意】上方示例为虚构情节，并非本次对话的实际历史。"
    "请勿引用示例中的任何人物、地点、事件。\n"
    "---以下才是真实的对话历史---"
)

CORE_CONSTRAINTS = (
    "<Core_Constraints>\n"
    "- 长度：600-800字完整叙事\n"
    "- 格式：旁白用*包裹，对白用「」包裹\n"
    "- 结尾：必须包含引导性钩子，禁止封闭式问句\n"
    "- 人设：使用锚点词，禁用禁用词\n"
    "</Core_Constraints>"
)

# 提示词中的所有模板变量
TEMPLATE_VARS = [
    "Role_Nickname", "gender", "age", "occupation", "background",
    "personality", "speaking_style", "personal_type", "hobby",
    "system_module8", "user_Nickname", "user_gender", "user_identity",
    "relation_calling", "relationship", "relation_info",
    "intimacy_boundary", "longform_persona", "longform_narrative_style",
    "currentTime", "timeperiod", "season", "current_scene",
    "dialogueStartPrompt", "dialogue_summary", "weekly_schedule",
    "system_Role_acting",
]

# 摘要策略 - 基于白皮书 §11.3
SUMMARY_SYSTEM_PROMPT = """你是一个对话摘要助手。请将以下对话历史精炼为结构化摘要。

输出格式（严格遵循，不要加其他内容）:
【第{start}-{end}轮摘要】
- 场景：{{当前对话发生的场景}}
- 剧情：{{关键剧情进展}}
- 情感进展：{{双方情感关系的变化}}
- 用户关键表达：{{用户表达的重要偏好或情感}}

规则:
- 保留: 关键剧情进展、情感高潮点、当前场景状态、用户偏好/厌恶
- 丢弃: 冗长环境描写、重复情感表达、过渡性对话
- 不要记录"已用元素"（避免粉红大象效应）
"""

# ═══════════════════════════════════════════════════════════════════
# Few-shot 解析
# ═══════════════════════════════════════════════════════════════════

def parse_fewshot_library(fewshot_path: Path) -> dict[str, list[dict]]:
    """
    解析 Few-shot 示例库 markdown 文件。
    返回: {"温暖陪伴": [{"user": "...", "assistant": "..."}, ...], ...}
    """
    text = fewshot_path.read_text(encoding="utf-8")
    result: dict[str, list[dict]] = {}

    # 按性格类型分节: ## 温暖陪伴型 / ## 霸道腹黑型 / ## 可爱活泼型 / ## 理性沉稳型
    type_pattern = re.compile(r"^## (.+?)型\s*$", re.MULTILINE)
    type_matches = list(type_pattern.finditer(text))

    for i, m in enumerate(type_matches):
        type_name = m.group(1).strip()  # e.g. "温暖陪伴"
        start = m.end()
        end = type_matches[i + 1].start() if i + 1 < len(type_matches) else len(text)
        section = text[start:end]

        # 提取每个 [User] / [Assistant] 对
        examples = []
        # 分割示例：按 ### 示例
        example_blocks = re.split(r"###\s+示例\s+\d+", section)
        for block in example_blocks:
            if not block.strip():
                continue
            user_match = re.search(
                r"\*\*\[User\]\*\*:\s*(.+?)(?=\n\n\*\*\[Assistant\]\*\*:)",
                block, re.DOTALL
            )
            asst_match = re.search(
                r"\*\*\[Assistant\]\*\*:\s*\n\n(.+?)(?=\n---|\Z)",
                block, re.DOTALL
            )
            if user_match and asst_match:
                examples.append({
                    "user": user_match.group(1).strip(),
                    "assistant": asst_match.group(1).strip(),
                })
        result[type_name] = examples

    return result


def get_fewshot_messages(
    personal_type: str,
    fewshot_library: dict[str, list[dict]],
    manual_fewshot: str | None = None,
) -> list[dict]:
    """
    构造 Few-shot 消息列表。

    优先级：
    1. manual_fewshot 列有值 → 解析 JSON (list of {role, content})
    2. personal_type 匹配 → 从示例库自动选择 3 组
    3. 都没有 → 返回空
    """
    if manual_fewshot and str(manual_fewshot).strip():
        try:
            return json.loads(str(manual_fewshot))
        except json.JSONDecodeError:
            print(f"  ⚠ longform_few_shot 列 JSON 解析失败，回退到自动路由")

    # 自动路由
    # 兼容：personal_type 可能是 "霸道腹黑型" 或 "霸道腹黑"
    clean_type = personal_type.replace("型", "") if personal_type else ""
    examples = fewshot_library.get(clean_type, [])

    if not examples:
        return []

    messages = []
    for ex in examples[:3]:  # 最多 3 组
        messages.append({"role": "user", "content": ex["user"]})
        messages.append({"role": "assistant", "content": ex["assistant"]})
    return messages


# ═══════════════════════════════════════════════════════════════════
# 提示词模板处理
# ═══════════════════════════════════════════════════════════════════

def load_prompt_template(prompt_path: Path) -> str:
    """加载提示词文件，去掉末尾的注释块（消息架构拼接说明）"""
    text = prompt_path.read_text(encoding="utf-8")
    # 去掉 <!-- ======================== 以上为 messages[0] ... 之后的内容
    marker = "<!-- ======================== 以上为 messages[0]"
    idx = text.find(marker)
    if idx != -1:
        text = text[:idx].rstrip()
    return text


def fill_template(template: str, row: pd.Series) -> str:
    """将提示词模板中的 {{variable}} 替换为 Excel 行中的值"""
    result = template
    for var in TEMPLATE_VARS:
        placeholder = "{{" + var + "}}"
        if placeholder in result:
            value = str(row.get(var, "")) if pd.notna(row.get(var, None)) else ""
            result = result.replace(placeholder, value)
    # 清理残留的未替换变量
    result = re.sub(r"\{\{[^}]+\}\}", "", result)
    return result


# ═══════════════════════════════════════════════════════════════════
# 对话历史与摘要
# ═══════════════════════════════════════════════════════════════════

def parse_conversation_history(raw: str | None) -> list[dict]:
    """解析 conversation_history 列（JSON 字符串）"""
    if not raw or (isinstance(raw, float) and pd.isna(raw)):
        return []
    try:
        history = json.loads(str(raw))
        if isinstance(history, list):
            return history
    except (json.JSONDecodeError, TypeError):
        pass
    return []


async def summarize_history(
    history: list[dict],
    api_key: str,
    client: httpx.AsyncClient,
    turn_start: int = 1,
) -> str:
    """
    使用模型对对话历史进行摘要。
    基于白皮书 §11.3 摘要策略。
    """
    if not history:
        return ""

    turn_count = sum(1 for m in history if m.get("role") == "user")
    turn_end = turn_start + turn_count - 1

    # 构造摘要请求
    history_text = ""
    for msg in history:
        role_label = "用户" if msg["role"] == "user" else "AI"
        history_text += f"[{role_label}]: {msg['content']}\n\n"

    summary_prompt = SUMMARY_SYSTEM_PROMPT.replace("{start}", str(turn_start)).replace(
        "{end}", str(turn_end)
    )

    try:
        resp = await client.post(
            API_URL,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": summary_prompt},
                    {"role": "user", "content": history_text},
                ],
            },
            timeout=60,
        )
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"  ⚠ 摘要生成失败: {e}")
        return ""


# ═══════════════════════════════════════════════════════════════════
# 消息拼接 (核心)
# ═══════════════════════════════════════════════════════════════════

def build_messages(
    row: pd.Series,
    prompt_template: str,
    fewshot_library: dict[str, list[dict]],
    dialogue_summary_text: str = "",
) -> list[dict]:
    """
    按消息架构白皮书 v2.1 拼接 messages 数组。

    结构:
      [0]    system     提示词全文 (L0-L5, 变量已填充)
      [1-6]  user/asst  Few-shot 示例 x3
      [7]    system     分隔标记
      [8+]   user/asst  对话历史
      [N-1]  system     <Core_Constraints> 重申
      [N]    user       <user_input>当前输入</user_input>
    """
    messages = []

    # ── [0] System: 提示词全文 ──
    filled_prompt = fill_template(prompt_template, row)
    # 如果有摘要，替换 dialogue_summary 变量（可能在模板中已经被清空了）
    if dialogue_summary_text:
        # 尝试在已填充的提示词中找到 dialogue_summary 的位置
        # 如果模板中有这个变量但 Excel 没值，它已被替换为空字符串
        # 我们需要在适当位置注入摘要
        if "dialogue_summary" in filled_prompt.lower() or not filled_prompt:
            pass  # 已在 fill_template 中处理
        # 追加到提示词末尾的记忆部分
        filled_prompt += f"\n\n## 近期对话摘要\n{dialogue_summary_text}"
    messages.append({"role": "system", "content": filled_prompt})

    # ── [1-6] Few-shot 示例 ──
    manual_fewshot = row.get("longform_few_shot", None)
    personal_type = str(row.get("personal_type", "")) if pd.notna(row.get("personal_type", None)) else ""
    fewshot_msgs = get_fewshot_messages(personal_type, fewshot_library, manual_fewshot)
    messages.extend(fewshot_msgs)

    # ── [7] 分隔标记 ──
    if fewshot_msgs:
        messages.append({"role": "system", "content": SEPARATOR_CONTENT})

    # ── [8+] 对话历史 ──
    conv_history = parse_conversation_history(row.get("conversation_history", None))
    if conv_history:
        messages.extend(conv_history)

    # ── [N-1] Core_Constraints 重申 ──
    messages.append({"role": "system", "content": CORE_CONSTRAINTS})

    # ── [N] 用户输入 ──
    user_msg = str(row.get("user_message", ""))
    messages.append({"role": "user", "content": f"<user_input>{user_msg}</user_input>"})

    return messages


# ═══════════════════════════════════════════════════════════════════
# API 调用
# ═══════════════════════════════════════════════════════════════════

async def call_api(
    messages: list[dict],
    api_key: str,
    client: httpx.AsyncClient,
) -> dict:
    """调用豆包 API，返回 {output, input_tokens, output_tokens, latency, error}"""
    t0 = time.perf_counter()
    try:
        resp = await client.post(
            API_URL,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            json={"model": MODEL, "messages": messages},
            timeout=120,
        )
        latency = round(time.perf_counter() - t0, 2)

        if resp.status_code != 200:
            return {
                "output": "",
                "input_tokens": 0,
                "output_tokens": 0,
                "latency": latency,
                "error": f"HTTP {resp.status_code}: {resp.text[:300]}",
            }

        data = resp.json()
        choice = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})

        return {
            "output": choice,
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "latency": latency,
            "error": "",
        }
    except Exception as e:
        latency = round(time.perf_counter() - t0, 2)
        return {
            "output": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "latency": latency,
            "error": str(e),
        }


# ═══════════════════════════════════════════════════════════════════
# 多轮链式处理 (方案 B: session_id)
# ═══════════════════════════════════════════════════════════════════

async def process_session(
    session_rows: list[tuple[int, pd.Series]],
    prompt_template: str,
    fewshot_library: dict[str, list[dict]],
    api_key: str,
    client: httpx.AsyncClient,
    results: dict,
    dry_run: bool = False,
    auto_summary: bool = True,
):
    """
    串行处理同一 session_id 的多轮对话。
    自动将前轮输出拼接为后轮的 conversation_history。
    每 5 轮自动生成摘要替换到 dialogue_summary。
    """
    accumulated_history: list[dict] = []
    summary_text = ""

    for turn_idx, (row_idx, row) in enumerate(session_rows):
        turn_num = turn_idx + 1
        print(f"  Session {row.get('session_id', '?')} Turn {turn_num}/{len(session_rows)}")

        # 每 5 轮生成摘要
        if auto_summary and turn_num > 1 and (turn_num - 1) % 5 == 0 and accumulated_history:
            print(f"    → 触发摘要 (轮次 {turn_num - 5 + 1}-{turn_num - 1})")
            new_summary = await summarize_history(
                accumulated_history[-10:],  # 最近 10 条消息 (5轮)
                api_key, client,
                turn_start=max(1, turn_num - 5),
            )
            if new_summary:
                summary_text = (summary_text + "\n\n" + new_summary).strip() if summary_text else new_summary
            # 滑动窗口：摘要后只保留最近 10 轮历史
            if len(accumulated_history) > 20:
                accumulated_history = accumulated_history[-20:]

        # 构造当前行的 row, 注入累积的对话历史
        row_copy = row.copy()
        if accumulated_history:
            row_copy["conversation_history"] = json.dumps(accumulated_history, ensure_ascii=False)

        messages = build_messages(row_copy, prompt_template, fewshot_library, summary_text)

        if dry_run:
            results[row_idx] = {
                "output": "[DRY-RUN] 消息结构见控制台",
                "input_tokens": 0, "output_tokens": 0, "latency": 0, "error": "",
            }
            print(f"    Messages count: {len(messages)}")
            for i, m in enumerate(messages):
                role = m["role"]
                preview = m["content"][:80].replace("\n", "\\n")
                print(f"      [{i}] {role}: {preview}...")
            continue

        result = await call_api(messages, api_key, client)
        results[row_idx] = result

        # 累积历史
        user_msg = str(row.get("user_message", ""))
        accumulated_history.append({"role": "user", "content": user_msg})
        if result["output"]:
            accumulated_history.append({"role": "assistant", "content": result["output"]})

        status = "✓" if not result["error"] else f"✗ {result['error'][:50]}"
        print(f"    {status} | {result['input_tokens']}+{result['output_tokens']} tokens | {result['latency']}s")


# ═══════════════════════════════════════════════════════════════════
# 独立行处理 (方案 A: 无 session_id)
# ═══════════════════════════════════════════════════════════════════

async def process_independent_row(
    row_idx: int,
    row: pd.Series,
    prompt_template: str,
    fewshot_library: dict[str, list[dict]],
    api_key: str,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    results: dict,
    dry_run: bool = False,
):
    """并发处理独立行（方案 A）"""
    async with semaphore:
        messages = build_messages(row, prompt_template, fewshot_library)

        if dry_run:
            results[row_idx] = {
                "output": "[DRY-RUN] 消息结构见控制台",
                "input_tokens": 0, "output_tokens": 0, "latency": 0, "error": "",
            }
            print(f"  Row {row_idx}: Messages count = {len(messages)}")
            for i, m in enumerate(messages):
                role = m["role"]
                preview = m["content"][:80].replace("\n", "\\n")
                print(f"    [{i}] {role}: {preview}...")
            return

        result = await call_api(messages, api_key, client)
        results[row_idx] = result

        name = row.get("Role_Nickname", f"Row{row_idx}")
        status = "✓" if not result["error"] else f"✗ {result['error'][:50]}"
        print(f"  [{row_idx}] {name} | {status} | {result['input_tokens']}+{result['output_tokens']} tokens | {result['latency']}s")


# ═══════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════

async def main_async(args):
    # ── 1. 环境检查 ──
    api_key = os.environ.get("ARK_API_KEY", "")
    if not api_key and not args.dry_run:
        print("❌ 请设置环境变量 ARK_API_KEY")
        print('   $env:ARK_API_KEY = "your-api-key"')
        sys.exit(1)

    # ── 2. 加载提示词 ──
    prompt_path = Path(args.prompt)
    if not prompt_path.exists():
        print(f"❌ 提示词文件不存在: {prompt_path}")
        sys.exit(1)
    prompt_template = load_prompt_template(prompt_path)
    print(f"✓ 提示词: {prompt_path.name} ({len(prompt_template)} chars)")

    # ── 3. 加载 Few-shot 示例库 ──
    fewshot_path = Path(args.fewshot)
    fewshot_library: dict[str, list[dict]] = {}
    if fewshot_path.exists():
        fewshot_library = parse_fewshot_library(fewshot_path)
        for k, v in fewshot_library.items():
            print(f"  Few-shot [{k}]: {len(v)} 组示例")
    else:
        print(f"⚠ Few-shot 示例库不存在: {fewshot_path}（将跳过自动路由）")

    # ── 4. 读取 Excel ──
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"❌ 输入文件不存在: {input_path}")
        sys.exit(1)

    df = pd.read_excel(input_path)
    print(f"✓ 输入: {input_path.name} ({len(df)} 行, {len(df.columns)} 列)")

    # 检查必填列
    required = ["user_message"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        print(f"❌ 缺少必填列: {missing}")
        sys.exit(1)

    # ── 5. 分组: session 模式 vs 独立模式 ──
    has_session = "session_id" in df.columns and "turn_order" in df.columns
    results: dict[int, dict] = {}

    async with httpx.AsyncClient() as client:
        if has_session:
            # 找出有 session_id 的行和没有的行
            session_mask = df["session_id"].notna()
            session_rows = df[session_mask]
            independent_rows = df[~session_mask]

            # 方案 B: 按 session_id 分组，串行处理
            if not session_rows.empty:
                sessions = session_rows.groupby("session_id")
                print(f"\n═══ 方案 B: {len(sessions)} 个会话（串行）═══")
                for sid, group in sessions:
                    sorted_group = group.sort_values("turn_order")
                    print(f"\n─── Session {sid} ({len(sorted_group)} 轮) ───")
                    await process_session(
                        list(sorted_group.iterrows()),
                        prompt_template, fewshot_library,
                        api_key, client, results,
                        dry_run=args.dry_run,
                        auto_summary=not args.no_summary,
                    )

            # 方案 A: 独立行并发处理
            if not independent_rows.empty:
                print(f"\n═══ 方案 A: {len(independent_rows)} 行（并发 {args.workers}）═══")
                sem = asyncio.Semaphore(args.workers)
                tasks = [
                    process_independent_row(
                        idx, row, prompt_template, fewshot_library,
                        api_key, client, sem, results,
                        dry_run=args.dry_run,
                    )
                    for idx, row in independent_rows.iterrows()
                ]
                await asyncio.gather(*tasks)
        else:
            # 全部独立行
            print(f"\n═══ 方案 A: {len(df)} 行（并发 {args.workers}）═══")
            sem = asyncio.Semaphore(args.workers)
            tasks = [
                process_independent_row(
                    idx, row, prompt_template, fewshot_library,
                    api_key, client, sem, results,
                    dry_run=args.dry_run,
                )
                for idx, row in df.iterrows()
            ]
            await asyncio.gather(*tasks)

    # ── 6. 输出 Excel ──
    for idx in df.index:
        r = results.get(idx, {"output": "", "input_tokens": 0, "output_tokens": 0, "latency": 0, "error": "未处理"})
        df.at[idx, "AI输出"] = r["output"]
        df.at[idx, "input_tokens"] = r["input_tokens"]
        df.at[idx, "output_tokens"] = r["output_tokens"]
        df.at[idx, "latency"] = r["latency"]
        df.at[idx, "error"] = r["error"]

    output_path = Path(args.output) if args.output else input_path.with_stem(input_path.stem + "_output")
    df.to_excel(output_path, index=False)
    print(f"\n✓ 输出: {output_path}")

    # ── 7. 统计 ──
    success = sum(1 for r in results.values() if not r.get("error"))
    failed = len(results) - success
    total_in = sum(r.get("input_tokens", 0) for r in results.values())
    total_out = sum(r.get("output_tokens", 0) for r in results.values())
    avg_latency = (
        sum(r.get("latency", 0) for r in results.values()) / len(results)
        if results else 0
    )
    print(f"\n{'═' * 50}")
    print(f"  成功: {success} | 失败: {failed}")
    print(f"  总 Token: {total_in} (输入) + {total_out} (输出) = {total_in + total_out}")
    print(f"  平均延迟: {avg_latency:.1f}s")
    print(f"{'═' * 50}")


def main():
    parser = argparse.ArgumentParser(
        description="长文模式生成脚本 - 按消息架构白皮书拼接 messages 并调用豆包 API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Excel 列说明:
  必填列:
    user_message          当前轮用户输入

  角色变量列 (对应提示词中的 {{变量}}):
    Role_Nickname         角色姓名/昵称
    gender                角色性别
    age                   角色年龄
    occupation            角色职业
    background            角色背景
    personality           角色性格
    speaking_style        说话风格
    personal_type         性格类型 (霸道腹黑/温暖陪伴/可爱活泼/理性沉稳)
    hobby                 兴趣爱好
    user_Nickname         用户昵称
    user_gender           用户性别
    user_identity         用户自设身份
    relationship          关系阶段
    relation_info         阶段说明
    intimacy_boundary     亲密边界规则
    ...                   (其他提示词中的变量同名列)

  多轮对话列:
    conversation_history  JSON 字符串: [{role, content}, ...]  (方案 A)
    session_id            会话 ID  (方案 B)
    turn_order            会话内轮次序号  (方案 B)

  Few-shot 列:
    longform_few_shot     手动注入 JSON: [{role, content}, ...]
    personal_type         自动路由 (从示例库匹配)

示例:
  python generate.py tests/长文测试.xlsx
  python generate.py tests/长文测试.xlsx --dry-run
  python generate.py tests/长文测试.xlsx -w 30 -o result.xlsx
""",
    )
    parser.add_argument("input", help="输入 Excel 文件路径")
    parser.add_argument("-o", "--output", help="输出 Excel 文件路径 (默认: {input}_output.xlsx)")
    parser.add_argument("-w", "--workers", type=int, default=20, help="并发数 (默认: 20)")
    parser.add_argument("--prompt", default=str(DEFAULT_PROMPT), help="提示词文件路径")
    parser.add_argument("--fewshot", default=str(DEFAULT_FEWSHOT), help="Few-shot 示例库路径")
    parser.add_argument("--dry-run", action="store_true", help="只打印消息结构，不调用 API")
    parser.add_argument("--no-summary", action="store_true", help="禁用自动摘要 (方案 B)")

    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
