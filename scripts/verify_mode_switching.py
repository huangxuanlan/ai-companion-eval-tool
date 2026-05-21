#!/usr/bin/env python3
"""
MECE 切换场景验证脚本 v1.1

验证目标：优化方案（切换上下文20→10轮 + 摘要触发10→5轮）在 MECE 核心路径下是否稳健。

覆盖场景：
  S4  纯长文≥10轮（摘要触发验证）
  S5  短→长切换（混合历史 + §3.8异质包夹）
  S6  长→短切换
  S8  短→长→短快速往返
  S14 短→长后摘要延迟，混合短文历史持续影响长文窗口

A/B 对比：
  baseline:  20轮切换上下文 + 10轮摘要触发（当前线上）
  optimized: 10轮切换上下文 + 5轮摘要触发（优化方案）

验证指标：
  - n-gram 重复率
  - v5.4 Format Leakage（字数、圆括号、模板泄漏、长短文格式污染）
  - 摘要触发证据（是否生成、耗时、裁剪前后历史长度）
  - 桥接取数证据（请求轮数、实际消息数、异质 assistant 包夹数）
  - 架构合规性
"""
import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# ── 路径 ──────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "server"))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / "server" / ".env")
except ImportError:
    pass

if not os.environ.get("DOUBAO_API_KEY") and os.environ.get("VOLCENGINE_API_KEY"):
    os.environ["DOUBAO_API_KEY"] = os.environ["VOLCENGINE_API_KEY"]

from services.model_adapter import ModelAdapter
from services.message_assembler import (
    SHORTFORM_HISTORY_PREFIX, SHORTFORM_HISTORY_SUFFIX,
    LONGFORM_HISTORY_PREFIX, LONGFORM_HISTORY_SUFFIX,
)

# 长文引擎——复用 verify_context_compression.py 中已验证的调用链
from longform_multi_turn import (
    build_messages_for_turn,
    build_variables,
    extract_system_prompt,
    generate_dialogue_summary,
    init_console_io,
    load_few_shot_examples,
    load_prompt_template,
    render_template,
    split_fewshot_from_system,
)

init_console_io()
_adapter = ModelAdapter()

# ── A/B 配置 ──────────────────────────────────────────────────
AB_CONFIGS = {
    "baseline": {
        "label": "线上基线 (切换20轮/摘要10轮)",
        "bridge_turns": 20,       # 切换时带入的混合上下文轮数
        "summary_interval": 10,   # 长文摘要触发间隔
    },
    "optimized": {
        "label": "优化方案 (切换10轮/摘要5轮)",
        "bridge_turns": 10,
        "summary_interval": 5,
    },
}

# ── 模型定义 ──────────────────────────────────────────────────
SHORTFORM_MODEL = {"model_id": "doubao-lite", "thinking": "disabled", "label": "doubao-lite"}
LONGFORM_MODEL = {"model_id": "deepseek-v4-pro", "thinking": "high", "label": "deepseek-v4-pro"}

# ── 短文提示词 ────────────────────────────────────────────────
SHORTFORM_SYSTEM = """你是{Role_Nickname}，{personality}。

## 角色信息
性别：{gender} | 职业：{occupation} | 类型：{personal_type}

## 说话风格
{speaking_style}
回复30-100字，口语化短句。可用（括号动作）表达情绪。不用markdown。"""

# ── 角色配置（复用 verify_context_compression 中已验证的结构）───
CHAR_CONFIG = {
    "prompt_file": "星朋友长文模式_提示词_v2.0.md",
    "character": {
        "Role_Nickname": "萧璟言", "gender": "男", "age": "29",
        "occupation": "萧氏集团总裁",
        "personality": "外表冷漠矜贵，内在占有欲极强",
        "speaking_style": "语言简洁直接，带有霸道和占有欲",
        "personal_type": "霸道腹黑", "background": "萧氏集团总裁",
        "hobby": "收藏古董表，品鉴红酒",
    },
    "context": {
        "relationship": "暧昧", "currentTime": "2026-03-04 20:30:00",
        "weekDay": "星期三", "timeperiod": "深夜", "season": "春",
        "intimacy_boundary": "允许轻微肢体接触，禁止越界",
        "relation_calling": "直呼名字",
        "relation_info": "暧昧阶段：双方有好感但未确认关系",
        "current_scene": "公司楼下花园散步",
    },
    "modules": {
        "user_Nickname": "小鹿", "user_gender": "女",
        "user_identity": "萧氏集团新人秘书",
        "longform_persona": "霸道腹黑型·男性行为画像",
        "longform_narrative_style": "锚点词: 掌控、占有、审视",
        "dialogueStartPrompt": "用户偏好：喜欢被保护的感觉",
    },
}

USER_INPUTS_SHORT = [
    "今天天气真好，出去走走？", "你在看什么呀，眼神怪怪的",
    "别跟着我了啦", "有点累了，想回去了", "帮我挡一下风好不好",
    "你说的那个餐厅在哪？", "我不太饿，你自己吃吧",
    "好吧好吧，陪你去", "这个味道还不错诶", "你为什么对我这么好？",
]
USER_INPUTS_LONG = [
    "散完步后回到了家里，坐在沙发上发呆",
    "想起了之前他说的话，心里有点酸酸的",
    "手机响了一声，是他发来的消息",
    "要不要回他呢，纠结了一下还是打开了",
    "窗外的月光洒进来，有点想见他",
    "明天见面的时候该说什么呢",
    "翻来覆去睡不着，干脆看会手机",
    "突然看到他的朋友圈更新了",
    "好奇他在干什么，点进去看了看",
    "算了不看了，关灯睡觉",
    "你刚才看我的眼神好奇怪",
    "嗯", "我有点累了",
    "你…你干嘛离我这么近",
    "晚安",
]


# ── 检测函数 ──────────────────────────────────────────────────
TEMPLATE_LEAK_PATTERNS = [
    "以下为", "记录结束", "动态摘要", "摘要结束", "内部认知记录",
    "Core_Constraints", "system", "System Prompt", "user_input",
]

EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U00002600-\U000026FF]"
)


def calc_ngram_overlap(prev: str, curr: str, n: int = 4) -> float:
    if not prev or not curr or len(curr) < n:
        return 0.0
    g_prev = set(prev[i:i+n] for i in range(len(prev) - n + 1))
    g_curr = set(curr[i:i+n] for i in range(len(curr) - n + 1))
    if not g_curr:
        return 0.0
    return len(g_prev & g_curr) / len(g_curr)


def count_cjk_chars(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text or ""))


def count_paren_pairs(text: str) -> int:
    return min(text.count("（"), text.count("）"))


def detect_format_leakage(text: str, target_mode: str) -> list[str]:
    issues = []
    cjk_chars = count_cjk_chars(text)
    if target_mode == "long":
        if cjk_chars < 300:
            issues.append(f"长文字数不足({cjk_chars}字)")
        if cjk_chars > 500:
            issues.append(f"长文字数超标({cjk_chars}字)")
        if count_paren_pairs(text) < 3:
            issues.append(f"圆括号不足({count_paren_pairs(text)}对)")
        if EMOJI_RE.search(text):
            issues.append("含Emoji")
        for pattern in TEMPLATE_LEAK_PATTERNS:
            if pattern in text:
                issues.append(f"模板泄漏({pattern})")
                break
    elif target_mode == "short":
        if cjk_chars < 20:
            issues.append(f"短文字数过少({cjk_chars}字)")
        if cjk_chars > 120:
            issues.append(f"短文字数过多({cjk_chars}字)")
        if "**" in text:
            issues.append("含加粗标记")
        if count_paren_pairs(text) >= 3 and cjk_chars > 80:
            issues.append("疑似长文旁白括号污染")
        if text.count("。") > 6:
            issues.append("短文句号过多")
        for pattern in (LONGFORM_HISTORY_PREFIX, LONGFORM_HISTORY_SUFFIX, "第三人称", "长文模式记录"):
            if pattern in text:
                issues.append("长文模板泄漏")
                break
    return issues


# ── 桥接函数（§3.8 异质隔离）──────────────────────────────────
def bridge_history(full_history: list[dict], target_mode: str, max_turns: int) -> tuple[list[dict], dict]:
    recent = full_history[-(max_turns * 2):] if len(full_history) > max_turns * 2 else list(full_history)
    bridged = []
    wrapped = 0
    source_counts: dict[str, int] = {}
    for msg in recent:
        role, content = msg["role"], msg["content"]
        src = msg.get("source_mode", "")
        source_counts[src or "unknown"] = source_counts.get(src or "unknown", 0) + 1
        if role == "assistant" and src and src != target_mode:
            if src == "short":
                content = f"{SHORTFORM_HISTORY_PREFIX}\n{content}\n{SHORTFORM_HISTORY_SUFFIX}"
                wrapped += 1
            elif src == "long":
                content = f"{LONGFORM_HISTORY_PREFIX}\n{content}\n{LONGFORM_HISTORY_SUFFIX}"
                wrapped += 1
        bridged.append({"role": role, "content": content})
    meta = {
        "bridge_turns_requested": max_turns,
        "bridge_messages": len(bridged),
        "bridge_effective_turns": len(bridged) // 2,
        "bridge_total_available_messages": len(full_history),
        "bridge_total_available_turns": len(full_history) // 2,
        "hetero_assistant_wrapped": wrapped,
        "source_message_counts": source_counts,
    }
    return bridged, meta


# ── 模型调用 ──────────────────────────────────────────────────
def call_model(model_id: str, messages: list, thinking: str = "disabled",
               max_tokens: int = 4096) -> dict:
    r = _adapter.chat(model_id=model_id, messages=messages,
                      max_tokens=max_tokens, thinking_effort=thinking)
    return {"content": r.content, "latency": r.latency_s,
            "in_tok": r.input_tokens, "out_tok": r.output_tokens,
            "success": r.success, "error": r.error}


# ── 长文提示词加载（缓存）──────────────────────────────────────
_lf_cache = {}

def get_longform_prompt_materials():
    if _lf_cache:
        return _lf_cache
    template_raw = load_prompt_template(CHAR_CONFIG["prompt_file"])
    system_template = extract_system_prompt(template_raw)
    system_before, system_after = split_fewshot_from_system(system_template)
    variables = build_variables(CHAR_CONFIG)
    rendered_sys = render_template(system_before, variables, clean_residual=True)
    rendered_after = render_template(system_after, variables, clean_residual=True) if system_after else ""
    char = CHAR_CONFIG["character"]
    ctx = CHAR_CONFIG["context"]
    few_shot = load_few_shot_examples(
        CHAR_CONFIG.get("few_shot_file", ""),
        personal_type=char.get("personal_type", ""),
        relationship=ctx.get("relationship", ""),
        gender=char.get("gender", ""),
    )
    _lf_cache.update({
        "rendered_sys": rendered_sys, "rendered_after": rendered_after,
        "few_shot": few_shot, "variables": variables,
    })
    return _lf_cache


# ── 场景执行器 ────────────────────────────────────────────────
def run_scenario(scenario: dict, ab_config: dict, dry_run: bool, repeat: int = 1) -> dict:
    name = scenario["name"]
    phases = scenario["phases"]
    bridge_turns = ab_config["bridge_turns"]
    summary_interval = ab_config["summary_interval"]

    print(f"\n{'='*60}")
    print(f"  {name} | {ab_config['label']} | repeat={repeat}")
    print(f"  桥接轮数: {bridge_turns} | 摘要间隔: {summary_interval}")
    for i, p in enumerate(phases):
        print(f"  Phase {chr(65+i)}: {p['label']} | {p['mode']} | {p['turns']}轮")
    print(f"{'='*60}")

    full_history = []  # 带 source_mode
    session_history = []  # 纯 role/content
    turn_results = []
    prev_output = ""
    input_idx = 0
    dialogue_summary = ""
    longform_turns_since_summary = 0
    longform_phase_turn = 0
    active_bridge_meta = {}

    for phase_idx, phase in enumerate(phases):
        phase_name = chr(65 + phase_idx)
        mode = phase["mode"]
        turns = phase["turns"]
        model_id = phase["model_id"]
        thinking = phase.get("thinking", "disabled")

        delay_summary_until_turn = int(phase.get("delay_summary_until_turn", 0) or 0)

        # 模式切换 → 桥接
        if phase_idx > 0 and phases[phase_idx - 1]["mode"] != mode:
            bridged, active_bridge_meta = bridge_history(full_history, mode, bridge_turns)
            prev_mode = phases[phase_idx - 1]["mode"]
            print(f"  >>> 切换 {prev_mode}→{mode} | "
                  f"桥接 {active_bridge_meta['bridge_effective_turns']}/"
                  f"{active_bridge_meta['bridge_total_available_turns']} 轮 "
                  f"(max={bridge_turns}轮, wrapped={active_bridge_meta['hetero_assistant_wrapped']}) <<<")
            session_history = bridged
            longform_turns_since_summary = 0
            longform_phase_turn = 0
        elif phase_idx == 0:
            session_history = []
            active_bridge_meta = {}
            longform_phase_turn = 0

        # 预加载长文素材
        if mode == "long":
            lf = get_longform_prompt_materials()

        for turn_i in range(turns):
            user_inputs = USER_INPUTS_LONG if mode == "long" else USER_INPUTS_SHORT
            user_input = user_inputs[input_idx % len(user_inputs)]
            input_idx += 1
            global_turn = len(turn_results) + 1

            # 构建消息
            if mode == "short":
                char = CHAR_CONFIG["character"]
                sys_prompt = SHORTFORM_SYSTEM.format(**char)
                messages = [{"role": "system", "content": sys_prompt}]
                messages.extend(session_history)
                messages.append({"role": "user", "content": user_input})
            else:
                lf = get_longform_prompt_materials()
                messages = build_messages_for_turn(
                    rendered_system=lf["rendered_sys"],
                    system_after=lf["rendered_after"],
                    few_shot_messages=lf["few_shot"],
                    conversation_history=session_history,
                    dialogue_summary=dialogue_summary,
                    current_input=user_input,
                    relationship=CHAR_CONFIG["context"]["relationship"],
                    role_name=CHAR_CONFIG["character"]["Role_Nickname"],
                    personality=CHAR_CONFIG["character"]["personality"],
                    turn_num=longform_turns_since_summary + 1,
                )

            # 调用
            if dry_run:
                if mode == "short":
                    output = f"（微微一笑）好啊，一起走。[dry T{global_turn}]"
                else:
                    output = ("（春风拂面）" * 5 + f"**走吧。** [dry T{global_turn}]") * 2
                latency = in_tok = out_tok = 0
            else:
                r = call_model(model_id, messages, thinking,
                               max_tokens=4096 if mode == "long" else 200)
                output = r["content"]
                latency, in_tok, out_tok = r["latency"], r["in_tok"], r["out_tok"]
                if not r["success"]:
                    print(f"  [ERR] T{global_turn}: {r['error'][:80]}")

            # 更新历史
            history_len_before_append = len(session_history)
            full_history.append({"role": "user", "content": user_input, "source_mode": mode})
            full_history.append({"role": "assistant", "content": output, "source_mode": mode})
            session_history.append({"role": "user", "content": user_input})
            session_history.append({"role": "assistant", "content": output})

            # 长文摘要触发
            summary_event = {
                "summary_due": False,
                "summary_generated": False,
                "summary_delayed": False,
                "summary_error": "",
                "summary_chars": 0,
                "summary_latency": 0.0,
                "history_len_before_summary": len(session_history),
                "history_len_after_summary": len(session_history),
            }
            if mode == "long":
                longform_phase_turn += 1
                longform_turns_since_summary += 1
                if longform_turns_since_summary >= summary_interval:
                    summary_event["summary_due"] = True
                if (
                    longform_turns_since_summary >= summary_interval
                    and delay_summary_until_turn
                    and longform_phase_turn <= delay_summary_until_turn
                ):
                    summary_event["summary_delayed"] = True
                    print(
                        f"  >>> T{global_turn}: 摘要到期但按场景延迟 "
                        f"(long_turn={longform_phase_turn}, until={delay_summary_until_turn}) <<<"
                    )
                elif longform_turns_since_summary >= summary_interval and dry_run:
                    summary_event["summary_generated"] = True
                    summary_event["summary_chars"] = 12
                    session_history = session_history[-(summary_interval * 2):]
                    summary_event["history_len_after_summary"] = len(session_history)
                    longform_turns_since_summary = 0
                elif longform_turns_since_summary >= summary_interval:
                    print(f"  >>> T{global_turn}: 触发摘要 (每{summary_interval}轮) <<<")
                    try:
                        summary_started = time.perf_counter()
                        before_summary_len = len(session_history)
                        dialogue_summary = generate_dialogue_summary(
                            session_history[-summary_interval * 2:],
                            role_name=CHAR_CONFIG["character"]["Role_Nickname"],
                            personal_type=CHAR_CONFIG["character"]["personal_type"],
                            relationship=CHAR_CONFIG["context"]["relationship"],
                        )
                        summary_event["summary_latency"] = round(time.perf_counter() - summary_started, 3)
                        summary_event["summary_generated"] = True
                        summary_event["summary_chars"] = len(dialogue_summary or "")
                        summary_event["history_len_before_summary"] = before_summary_len
                        # 摘要后裁剪历史
                        session_history = session_history[-(summary_interval * 2):]
                        summary_event["history_len_after_summary"] = len(session_history)
                        longform_turns_since_summary = 0
                        print(f"  [OK] 摘要生成完成，保留 {len(session_history)} 条历史")
                    except Exception as e:
                        summary_event["summary_error"] = str(e)
                        print(f"  [WARN] 摘要生成失败: {e}")

            # 检测
            ngram = calc_ngram_overlap(prev_output, output)
            leakage = detect_format_leakage(output, mode)
            prev_output = output

            result = {
                "repeat": repeat, "turn": global_turn, "phase": phase_name, "mode": mode,
                "chars": len(output), "msgs": len(messages),
                "cjk_chars": count_cjk_chars(output),
                "paren_pairs": count_paren_pairs(output),
                "ngram_pct": round(ngram * 100, 1),
                "leakage": leakage, "latency": latency,
                "input_tokens": in_tok, "output_tokens": out_tok,
                "history_len_before_append": history_len_before_append,
                "history_len_after_turn": len(session_history),
                **summary_event,
                **active_bridge_meta,
            }
            turn_results.append(result)

            leak_flag = f" ⚠️{len(leakage)}" if leakage else ""
            print(f"  T{global_turn:2d} [{phase_name}|{mode:5s}] "
                  f"msg:{len(messages):2d} 字:{len(output):4d} "
                  f"ngram:{ngram*100:4.0f}%{leak_flag}")

    return {
        "scenario": name,
        "config": ab_config["label"],
        "repeat": repeat,
        "bridge_turns": bridge_turns,
        "summary_interval": summary_interval,
        "turns": turn_results,
    }


# ── 场景定义 ──────────────────────────────────────────────────
# MECE 矩阵完整覆盖 (S1-S14):
#   S1/S2: 纯短文 — 不涉及长文优化，跳过
#   S3: 纯长文<10轮 — S4 子集，无需独立测
#   S13: 摘要延迟(纯长文) — 需时序模拟，暂用 S14 覆盖延迟逻辑
def define_scenarios(sf_turns: int, lf_turns: int) -> list[dict]:
    sf, lf = SHORTFORM_MODEL, LONGFORM_MODEL
    # 短文轮数限制在合理范围，长文阶段关闭前轮数取较小值
    close_lf = min(4, lf_turns - 1)  # S7: 切换后不到摘要就关闭
    close_sf = min(8, sf_turns)       # S9: 切换后不到20轮就关闭
    return [
        # ── S4: 纯长文≥10轮 ──
        {"name": f"S4_纯长文{lf_turns}轮", "phases": [
            {"mode": "long", "turns": lf_turns, **lf},
        ]},

        # ── S5: 短→长 ──
        {"name": f"S5_短{sf_turns}→长{lf_turns}", "phases": [
            {"mode": "short", "turns": sf_turns, **sf},
            {"mode": "long", "turns": lf_turns, **lf},
        ]},

        # ── S6: 长→短 ──
        {"name": f"S6_长{lf_turns}→短{sf_turns}", "phases": [
            {"mode": "long", "turns": lf_turns, **lf},
            {"mode": "short", "turns": sf_turns, **sf},
        ]},

        # ── S7: 短→长，<10轮关闭，跨会话续接 ──
        # 模拟：短文5轮 → 切换长文4轮 → "关闭"(清空session) → 重新桥接长文续接5轮
        {"name": f"S7_短{sf_turns}→长{close_lf}_关闭→续接长5", "phases": [
            {"mode": "short", "turns": sf_turns, **sf},
            {"mode": "long", "turns": close_lf, **lf},
            # 第三段"重开"：同模式(long→long)不会触发bridge，
            # 但实际跨会话需要重新加载。用 short 0轮夹一下触发桥接。
            {"mode": "short", "turns": 0, **sf},
            {"mode": "long", "turns": 5, **lf},
        ]},

        # ── S8: 短→长→短 ──
        {"name": f"S8_短{sf_turns}→长5→短{sf_turns}", "phases": [
            {"mode": "short", "turns": sf_turns, **sf},
            {"mode": "long", "turns": lf_turns, **lf},
            {"mode": "short", "turns": sf_turns, **sf},
        ]},

        # ── S9: 长→短，<20轮关闭，跨会话续接 ──
        # 模拟：长文8轮 → 切换短文5轮 → "关闭" → 重新桥接短文续接5轮
        {"name": f"S9_长{lf_turns}→短{sf_turns}_关闭→续接短5", "phases": [
            {"mode": "long", "turns": lf_turns, **lf},
            {"mode": "short", "turns": sf_turns, **sf},
            # 用 long 0轮触发桥接
            {"mode": "long", "turns": 0, **lf},
            {"mode": "short", "turns": 5, **sf},
        ]},

        # ── S10: 长→短→长（S8 镜像）──
        {"name": f"S10_长{lf_turns}→短{sf_turns}→长{lf_turns}", "phases": [
            {"mode": "long", "turns": lf_turns, **lf},
            {"mode": "short", "turns": sf_turns, **sf},
            {"mode": "long", "turns": lf_turns, **lf},
        ]},

        # ── S11: 频繁切换≥3次（短3→长3→短3→长3→短3）──
        {"name": "S11_频繁切换_短3长3x4段", "phases": [
            {"mode": "short", "turns": 3, **sf},
            {"mode": "long", "turns": 3, **lf},
            {"mode": "short", "turns": 3, **sf},
            {"mode": "long", "turns": 3, **lf},
            {"mode": "short", "turns": 3, **sf},
            {"mode": "long", "turns": 3, **lf},
            {"mode": "short", "turns": 3, **sf},
            {"mode": "long", "turns": 3, **lf},
        ]},

        # ── S12: 开新会话（纯长文后关闭→新会话长文）──
        # 模拟：长文8轮 → "关闭" → 新会话用桥接历史重新开始长文
        {"name": f"S12_长{lf_turns}_关闭→新会话长{lf_turns}", "phases": [
            {"mode": "long", "turns": lf_turns, **lf},
            {"mode": "short", "turns": 0, **sf},  # 触发桥接
            {"mode": "long", "turns": lf_turns, **lf},
        ]},

        # ── S14: 短→长后摘要延迟（跨模式混合取数）──
        {"name": f"S14_短{sf_turns}→长{lf_turns}_摘要延迟", "phases": [
            {"mode": "short", "turns": sf_turns, **sf},
            {
                "mode": "long",
                "turns": lf_turns,
                "delay_summary_until_turn": min(10, lf_turns),
                **lf,
            },
        ]},
    ]


# ── 报告 ──────────────────────────────────────────────────────
def generate_report(results: list[dict], out_dir: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"switching_report_{ts}.md"
    lines = [
        "# MECE 模式切换验证报告",
        f"\n> 生成时间: {datetime.now().isoformat()}",
        "\n## 验证目标",
        "验证优化方案（切换上下文20→10轮 + 摘要触发10→5轮）在 MECE 核心路径下的稳健性。\n",
    ]
    # 按场景分组对比
    grouped = defaultdict(list)
    for r in results:
        grouped[r["scenario"]].append(r)

    for scenario_name, runs in grouped.items():
        lines.append(f"\n## {scenario_name}\n")
        # 表头
        headers = ["轮次", "阶段", "模式"]
        for run in runs:
            headers.append(run["config"].split("(")[0].strip())
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join([":----:"] * len(headers)) + "|")

        max_turns = max(len(r["turns"]) for r in runs)
        for i in range(max_turns):
            row = []
            ref_turn = runs[0]["turns"][i] if i < len(runs[0]["turns"]) else None
            if ref_turn:
                row.extend([f"T{ref_turn['turn']}", ref_turn["phase"], ref_turn["mode"]])
            else:
                row.extend(["", "", ""])
            for run in runs:
                if i < len(run["turns"]):
                    t = run["turns"][i]
                    leak = "⚠️" if t["leakage"] else "✅"
                    row.append(f"{t['chars']}字 ngram:{t['ngram_pct']}% {leak}")
                else:
                    row.append("-")
            lines.append("| " + " | ".join(row) + " |")

        # 汇总
        for run in runs:
            avg_ngram = sum(t["ngram_pct"] for t in run["turns"]) / len(run["turns"]) if run["turns"] else 0
            max_ngram = max((t["ngram_pct"] for t in run["turns"]), default=0)
            total_leak = sum(len(t["leakage"]) for t in run["turns"])
            summary_generated = sum(1 for t in run["turns"] if t.get("summary_generated"))
            summary_delayed = sum(1 for t in run["turns"] if t.get("summary_delayed"))
            max_bridge = max((t.get("bridge_effective_turns", 0) for t in run["turns"]), default=0)
            lines.append(
                f"\n**{run['config']} / repeat {run.get('repeat', 1)}**: "
                f"平均ngram={avg_ngram:.1f}% | 峰值ngram={max_ngram:.1f}% | "
                f"格式问题={total_leak} | 摘要生成={summary_generated} | "
                f"摘要延迟={summary_delayed} | 最大桥接={max_bridge}轮"
            )

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ── Main ──────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="MECE 模式切换 A/B 验证 v1.1")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sf-turns", type=int, default=5, help="短文阶段轮数")
    parser.add_argument("--lf-turns", type=int, default=10, help="长文阶段轮数")
    parser.add_argument("--scenarios", nargs="*", default=None,
                        help="MECE场景过滤 (S4/S5/S6/S7/S8/S9/S10/S11/S12/S14)")
    parser.add_argument("--ab", nargs="*", default=None,
                        help="A/B 配置 (baseline/optimized，默认全部)")
    parser.add_argument("--repeat", type=int, default=1, help="每个场景/配置重复次数")
    parser.add_argument("-o", "--output-dir", default=None)
    args = parser.parse_args()

    out = Path(args.output_dir) if args.output_dir else PROJECT_ROOT / "output" / "mode_switching"
    out.mkdir(parents=True, exist_ok=True)

    scenarios = define_scenarios(args.sf_turns, args.lf_turns)
    if args.scenarios:
        keep = {s.upper() for s in args.scenarios}
        scenarios = [s for s in scenarios if any(s["name"].startswith(k) for k in keep)]

    ab_configs = {k: v for k, v in AB_CONFIGS.items()
                  if not args.ab or k in args.ab}

    total = len(scenarios) * len(ab_configs) * args.repeat
    print(f"\n{'='*60}")
    print(f"  MECE 切换验证 v1.1 (A/B)")
    print(f"  场景: {len(scenarios)} × A/B配置: {len(ab_configs)} × repeat:{args.repeat} = {total} 组")
    print(f"  短文轮数: {args.sf_turns} | 长文轮数: {args.lf_turns}")
    print(f"  dry-run: {args.dry_run}")
    print(f"{'='*60}")

    all_results = []
    for repeat_idx in range(1, args.repeat + 1):
        for ab_name, ab_cfg in ab_configs.items():
            for scenario in scenarios:
                result = run_scenario(scenario, ab_cfg, args.dry_run, repeat=repeat_idx)
                all_results.append(result)

    # 保存
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out / f"switching_results_{ts}.json"
    json_path.write_text(json.dumps(all_results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n  [OK] 数据: {json_path}")

    report = generate_report(all_results, out)
    print(f"  [OK] 报告: {report}")
    print(f"\n{'='*60}\n  验证完成!\n{'='*60}")


if __name__ == "__main__":
    main()
