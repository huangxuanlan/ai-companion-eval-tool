#!/usr/bin/env python3
"""
长文上下文压缩方案验证脚本 v1.0

验证假设：
  H1: 切换上下文 20→10 轮不会断裂
  H2: 摘要触发 5 轮比 10 轮更早控制重复
  H3: 摘要生效后重复率下降 ≥30%
  H4: 消息架构 100% 合规

用法：
  python scripts/verify_context_compression.py --dry-run --turns 15
  python scripts/verify_context_compression.py --turns 15 --repeat 2
  python scripts/verify_context_compression.py --replay "E:\...\测试日志-重复问题.md"
"""

import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# ── 路径设置 ──────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "server"))

# 加载 .env（ModelAdapter 依赖环境变量中的 API KEY）
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / "server" / ".env")
except ImportError:
    pass

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
    CORE_CONSTRAINTS_TEMPLATE,
    SUMMARY_INJECT_TEMPLATE,
)

# 统一多模型调用（替代原来的 call_api）
try:
    from services.model_adapter import ModelAdapter
    _adapter = ModelAdapter()
except Exception as _e:
    print(f"  [WARN] ModelAdapter 加载失败: {_e}，回退到 call_api")
    _adapter = None

init_console_io()

# ── 意象词表（复用 analyze_repetition.py）─────────────────────
TRACKED_MOTIFS = {
    "梧桐": "梧桐叶", "光斑": "光斑", "袜子": "袜子",
    "枕头": "枕头", "窗帘": "窗帘", "光脚": "光脚",
    "眼眶": "眼眶泛红", "蛋壳": "蛋壳炒蛋",
    "手机从指尖滑": "手机滑落", "手机滑落": "手机滑落",
    "盘腿坐": "盘腿坐", "棒棒糖": "棒棒糖",
    "便签": "便签", "糖纸": "糖纸",
}

# ── 模型配置 ──────────────────────────────────────────────────
# 模拟生产路径：日常pro → doubao-lite, 日常 → doubao-1.5-character
# 长文 → deepseek-v4-pro (thinking)
MODEL_PROFILES = {
    "doubao-lite": {
        "label": "豆包 2.0 Lite (日常Pro)",
        "model_id": "doubao-lite",
        "thinking": "disabled",
    },
    "doubao-1.5-character": {
        "label": "豆包 1.5 Character (日常)",
        "model_id": "doubao-1.5-character",
        "thinking": "disabled",
    },
    "deepseek-v4-pro": {
        "label": "DeepSeek V4 Pro (长文+思考)",
        "model_id": "deepseek-v4-pro",
        "thinking": "high",
    },
}
DEFAULT_GEN_MODEL = "deepseek-v4-pro"  # 默认长文生成模型
DEFAULT_SUMMARY_MODEL = "doubao-lite"   # 摘要固定用 lite

# ── 3 组对比配置 ──────────────────────────────────────────────
CONFIGS = {
    "baseline_20t_nosummary": {
        "label": "对照组: 20轮预加载 + 不摘要（模拟当前线上）",
        "preload_turns": 20,
        "summary_interval": 999,
    },
    "optimized_10t_5s": {
        "label": "方案A: 10轮预加载 + 每5轮摘要",
        "preload_turns": 10,
        "summary_interval": 5,
    },
    "optimized_10t_5s_prewarm": {
        "label": "方案B: 10轮预加载 + 每5轮摘要 + 异步预热",
        "preload_turns": 10,
        "summary_interval": 5,
        "prewarm_summary": True,
    },
}

# ── 默认用户输入序列（15轮）─────────────────────────────────
DEFAULT_USER_INPUTS = [
    "今天天气真好，出去走走吧",
    "你刚才看我的眼神好奇怪",
    "那你为什么一直跟着我",
    "嗯",
    "我有点累了，想回去了",
    "为什么突然对我这么好",
    "你…你干嘛离我这么近",
    "我不是害怕，只是…",
    "算了，不说了",
    "晚安",
    "其实我还没有睡着",
    "你还在吗",
    "我刚才做了一个梦",
    "嗯…梦到你了",
    "别笑我啊",
]

# ── 默认角色配置 ──────────────────────────────────────────────
DEFAULT_CONFIG = {
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
    "turns": DEFAULT_USER_INPUTS,
}


# ═══════════════════════════════════════════════════════════════
# 确定性检测函数
# ═══════════════════════════════════════════════════════════════

def detect_motifs(text: str) -> dict[str, int]:
    """检测文本中出现的意象，返回 {意象名: 出现次数}。"""
    found = Counter()
    for keyword, motif_name in TRACKED_MOTIFS.items():
        count = text.count(keyword)
        if count > 0:
            found[motif_name] += count
    return dict(found)


def motif_repetition_rate(current_motifs: dict, history_motifs: Counter) -> float:
    """当前轮使用了多少个已出现≥2次的意象，占当前意象总数的比例。"""
    if not current_motifs:
        return 0.0
    repeated = sum(1 for m in current_motifs if history_motifs[m] >= 2)
    return round(repeated / len(current_motifs), 3)


def ngram_repetition_score(current: str, previous_outputs: list, n: int = 4) -> float:
    """当前轮与所有之前轮次的 n-gram 重复比例。"""
    if not previous_outputs or len(current) < n:
        return 0.0
    current_ngrams = set()
    for i in range(len(current) - n + 1):
        current_ngrams.add(current[i:i + n])
    if not current_ngrams:
        return 0.0
    all_prev = "".join(previous_outputs)
    prev_ngrams = set()
    for i in range(len(all_prev) - n + 1):
        prev_ngrams.add(all_prev[i:i + n])
    overlap = current_ngrams & prev_ngrams
    return round(len(overlap) / len(current_ngrams), 3)


def check_message_architecture(messages: list) -> dict:
    """验证白皮书 v1.6 §4.1 消息架构合规性。"""
    result = {
        "system_at_0": messages[0]["role"] == "system" if messages else False,
        "user_input_at_n": messages[-1]["role"] == "user" if messages else False,
        "core_constraints_at_n1": False,
        "summary_exists": False,
        "total_messages": len(messages),
        "all_pass": False,
    }
    if len(messages) >= 2:
        n1 = messages[-2]
        result["core_constraints_at_n1"] = (
            n1["role"] == "system" and "Core_Constraints" in n1["content"]
        )
    for m in messages:
        if m["role"] == "system" and "之前剧情摘要" in m.get("content", ""):
            result["summary_exists"] = True
            break
    result["all_pass"] = all([
        result["system_at_0"],
        result["user_input_at_n"],
        result["core_constraints_at_n1"],
    ])
    return result


def check_output_quality(text: str) -> dict:
    """输出基础质量检查。"""
    char_count = len(text)
    narration_count = len(re.findall(r"（[^）]+）", text))
    dialogue_count = len(re.findall(r"\u201c[^\u201d]*\u201d", text))
    emoji_count = len(re.findall(
        r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF]",
        text
    ))
    return {
        "char_count": char_count,
        "length_ok": 200 <= char_count <= 600,
        "narration_count": narration_count,
        "dialogue_count": dialogue_count,
        "emoji_count": emoji_count,
        "emoji_ok": emoji_count == 0,
    }


# ═══════════════════════════════════════════════════════════════
# 预加载历史裁剪
# ═══════════════════════════════════════════════════════════════

def build_preloaded_history(full_history: list, preload_turns: int) -> list:
    """模拟后端预加载上下文裁剪。1轮=2条消息(user+assistant)。"""
    keep_messages = preload_turns * 2
    if len(full_history) <= keep_messages:
        return list(full_history)
    return list(full_history[-keep_messages:])


# ═══════════════════════════════════════════════════════════════
# 日志复放解析
# ═══════════════════════════════════════════════════════════════

def parse_replay_log(log_path: str) -> dict:
    """从现网日志提取 system prompt 和用户输入序列。"""
    with open(log_path, "r", encoding="utf-8") as f:
        content = f.read()
    outer = json.loads(content)
    messages = json.loads(outer["prompt"])

    system_prompt = ""
    user_inputs = []
    preload_history = []

    for msg in messages:
        role = msg.get("role", "")
        text = msg.get("content", "")
        if role == "system" and not system_prompt:
            system_prompt = text
        elif role == "user":
            user_inputs.append(text)
        elif role == "assistant":
            preload_history.append(msg)

    return {
        "system_prompt": system_prompt,
        "user_inputs": user_inputs,
        "preload_history": preload_history,
        "total_messages": len(messages),
    }


# ═══════════════════════════════════════════════════════════════
# 核心执行引擎
# ═══════════════════════════════════════════════════════════════

def run_single_config(
    config_name: str,
    test_config: dict,
    char_config: dict,
    user_inputs: list,
    total_turns: int,
    dry_run: bool = False,
) -> list:
    """
    执行单个配置的多轮对话，返回逐轮分析结果。
    """
    preload_turns = test_config["preload_turns"]
    summary_interval = test_config["summary_interval"]
    prewarm = test_config.get("prewarm_summary", False)

    print(f"\n{'='*60}")
    print(f"  配置: {test_config['label']}")
    print(f"  预加载: {preload_turns}轮 | 摘要间隔: {summary_interval}轮")
    print(f"  总轮数: {total_turns} | dry-run: {dry_run}")
    print(f"{'='*60}")

    # 加载提示词模板
    prompt_file = char_config["prompt_file"]
    template_raw = load_prompt_template(prompt_file)
    system_template = extract_system_prompt(template_raw)
    system_before, system_after = split_fewshot_from_system(system_template)

    # 加载变量和 Few-shot
    variables = build_variables(char_config)
    rendered_system = render_template(system_before, variables, clean_residual=True)
    rendered_after = render_template(system_after, variables, clean_residual=True) if system_after else ""

    character = char_config.get("character", {})
    context = char_config.get("context", {})
    few_shot_messages = load_few_shot_examples(
        char_config.get("few_shot_file", ""),
        personal_type=character.get("personal_type", ""),
        relationship=context.get("relationship", ""),
        gender=character.get("gender", ""),
    )

    relationship = context.get("relationship", "暧昧")
    role_name = character.get("Role_Nickname", "unknown")
    personal_type = character.get("personal_type", "")

    # 状态
    conversation_history = []
    dialogue_summary = ""
    all_outputs = []
    cumulative_motifs = Counter()
    results = []

    # 方案B：模拟异步预热摘要（第1轮前生成空摘要占位）
    if prewarm and not dry_run:
        print("  [INFO] 异步预热摘要：模拟会话创建时生成初始摘要...")
        # 实际中这里会用预加载历史调 mini 模型
        # dry-run 时跳过

    for i in range(min(total_turns, len(user_inputs))):
        turn_num = i + 1
        user_input = user_inputs[i]

        # 组装消息
        messages = build_messages_for_turn(
            rendered_system=rendered_system,
            system_after=rendered_after,
            few_shot_messages=few_shot_messages,
            conversation_history=conversation_history,
            dialogue_summary=dialogue_summary,
            current_input=user_input,
            relationship=relationship,
            role_name=role_name,
            personality=character.get("personality", ""),
            turn_num=turn_num,
        )

        # 架构合规
        arch = check_message_architecture(messages)

        if dry_run:
            ai_output = f"[dry-run T{turn_num}] 模拟叙事内容（300-500字），包含场景描写和对话。"
            latency = 0
            in_tok = out_tok = 0
        else:
            # 使用 ModelAdapter 统一调用
            gen_model = test_config.get("gen_model", DEFAULT_GEN_MODEL)
            gen_profile = MODEL_PROFILES.get(gen_model, {})
            gen_model_id = gen_profile.get("model_id", gen_model)
            gen_thinking = gen_profile.get("thinking", "disabled")
            if _adapter:
                result = _adapter.chat(
                    model_id=gen_model_id,
                    messages=messages,
                    max_tokens=4096,
                    thinking_effort=gen_thinking,
                )
                ai_output = result.content
                latency = result.latency_s
                in_tok = result.input_tokens
                out_tok = result.output_tokens
                if not result.success:
                    print(f"  [ERROR] {gen_model_id}: {result.error[:80]}")
            else:
                from longform_multi_turn import call_api
                response = call_api(messages)
                ai_output = response["output"]
                latency = response["latency_s"]
                in_tok = response["input_tokens"]
                out_tok = response["output_tokens"]

        # 确定性检测
        motifs = detect_motifs(ai_output)
        motif_rate = motif_repetition_rate(motifs, cumulative_motifs)
        ngram_rate = ngram_repetition_score(ai_output, all_outputs)
        quality = check_output_quality(ai_output)

        # 累计
        for m, c in motifs.items():
            cumulative_motifs[m] += c
        all_outputs.append(ai_output)

        turn_result = {
            "turn": turn_num,
            "config": config_name,
            "user_input": user_input[:50],
            "msg_count": len(messages),
            "history_pairs": len(conversation_history) // 2,
            "has_summary": bool(dialogue_summary),
            "arch": arch,
            "motifs_this_turn": motifs,
            "motif_repeat_rate": motif_rate,
            "ngram_repeat_rate": ngram_rate,
            "quality": quality,
            "latency_s": latency,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
        }
        results.append(turn_result)

        # 打印进度
        arch_mark = "[OK]" if arch["all_pass"] else "[FAIL]"
        print(
            f"  T{turn_num:>2} | msg:{len(messages):>2} | "
            f"motif:{motif_rate:.0%} | ngram:{ngram_rate:.0%} | "
            f"字:{quality['char_count']:>3} | 架构:{arch_mark}"
        )

        # 更新历史
        conversation_history.append({"role": "user", "content": user_input})
        conversation_history.append({"role": "assistant", "content": ai_output})

        # 摘要触发
        if turn_num % summary_interval == 0 and turn_num < total_turns:
            print(f"  >>> 第{turn_num}轮触发摘要生成 <<<")
            dialogue_summary = generate_dialogue_summary(
                conversation_history=conversation_history,
                role_name=role_name,
                personal_type=personal_type,
                relationship=relationship,
                dry_run=dry_run,
            )
            # 摘要后裁剪：删除已摘要的上下文
            conversation_history = conversation_history[-summary_interval * 2:]
            print(f"  >>> 摘要后保留 {len(conversation_history)//2} 轮历史 <<<")

        if not dry_run and i < total_turns - 1:
            time.sleep(0.5)

    return results


# ═══════════════════════════════════════════════════════════════
# 报告生成
# ═══════════════════════════════════════════════════════════════

def generate_report(all_results: dict, output_dir: Path) -> Path:
    """生成 Markdown 对比报告。"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"report_{ts}.md"

    lines = ["# 上下文压缩方案验证报告\n"]
    lines.append(f"> 生成时间: {datetime.now().isoformat()}\n")

    # 逐轮对比表
    lines.append("## 逐轮对比\n")
    configs = list(all_results.keys())
    header = "| 轮次 | " + " | ".join(f"{c}" for c in configs) + " |"
    sep = "|:-----|" + "|".join(":------|" for _ in configs)
    lines.append(header)
    lines.append(sep)

    max_turns = max(len(v) for v in all_results.values())
    for t in range(max_turns):
        row = f"| T{t+1} |"
        for cfg in configs:
            res_list = all_results[cfg]
            if t < len(res_list):
                r = res_list[t]
                row += (
                    f" msg:{r['msg_count']} "
                    f"motif:{r['motif_repeat_rate']:.0%} "
                    f"ngram:{r['ngram_repeat_rate']:.0%} |"
                )
            else:
                row += " - |"
        lines.append(row)

    # 汇总统计
    lines.append("\n## 汇总统计\n")
    for cfg, res_list in all_results.items():
        label = CONFIGS.get(cfg, {}).get("label", cfg)
        lines.append(f"### {label}\n")
        avg_motif = sum(r["motif_repeat_rate"] for r in res_list) / len(res_list)
        avg_ngram = sum(r["ngram_repeat_rate"] for r in res_list) / len(res_list)
        peak_msg = max(r["msg_count"] for r in res_list)
        arch_pass = sum(1 for r in res_list if r["arch"]["all_pass"])
        first_repeat = next(
            (r["turn"] for r in res_list if r["motif_repeat_rate"] > 0.3),
            "未触发"
        )
        lines.append(f"- 峰值消息数: **{peak_msg}**")
        lines.append(f"- 平均意象重复率: **{avg_motif:.1%}**")
        lines.append(f"- 平均 n-gram 重复率: **{avg_ngram:.1%}**")
        lines.append(f"- 架构合规: **{arch_pass}/{len(res_list)}**")
        lines.append(f"- 首次重复率>30%轮次: **{first_repeat}**\n")

    report_content = "\n".join(lines)
    report_path.write_text(report_content, encoding="utf-8")
    print(f"\n  [OK] 报告: {report_path}")
    return report_path


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="长文上下文压缩方案验证脚本 v1.1 (多模型)",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="仅验证架构，不调用 API")
    parser.add_argument("--turns", "-t", type=int, default=15,
                        help="每配置跑的轮数 (默认15)")
    parser.add_argument("--repeat", "-r", type=int, default=1,
                        help="每配置重复次数 (默认1)")
    parser.add_argument("--replay", default=None,
                        help="现网日志文件路径（复放模式）")
    parser.add_argument("--configs", nargs="*", default=None,
                        help="只跑指定上下文配置 (默认全部)")
    parser.add_argument("--models", nargs="*", default=None,
                        help="指定生成模型 (可选: doubao-lite doubao-1.5-character deepseek-v4-pro，默认全部)")
    parser.add_argument("--output-dir", "-o", default=None,
                        help="输出目录")
    args = parser.parse_args()

    output_dir = Path(args.output_dir) if args.output_dir else (
        PROJECT_ROOT / "output" / "context_compression"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    # 确定要跑的上下文配置
    if args.configs:
        run_configs = {k: v for k, v in CONFIGS.items() if k in args.configs}
    else:
        run_configs = CONFIGS

    # 确定要跑的模型
    if args.models:
        run_models = [m for m in args.models if m in MODEL_PROFILES]
    else:
        run_models = list(MODEL_PROFILES.keys())

    # 确定用户输入和角色配置
    char_config = DEFAULT_CONFIG.copy()
    user_inputs = DEFAULT_USER_INPUTS

    if args.replay:
        print(f"  [INFO] 日志复放模式: {args.replay}")
        replay_data = parse_replay_log(args.replay)
        user_inputs = replay_data["user_inputs"]
        print(f"  [OK] 提取 {len(user_inputs)} 条用户输入")

    total_runs = len(run_configs) * len(run_models) * args.repeat
    print(f"\n{'='*60}")
    print(f"  上下文压缩方案验证 v1.1 (多模型)")
    print(f"  上下文配置: {len(run_configs)} | 模型: {len(run_models)} | 总运行: {total_runs}")
    print(f"  模型列表: {', '.join(run_models)}")
    print(f"  轮数: {args.turns} | 重复: {args.repeat} | dry-run: {args.dry_run}")
    print(f"{'='*60}")

    all_results = {}
    for model_key in run_models:
        model_profile = MODEL_PROFILES[model_key]
        for config_name, test_config in run_configs.items():
            # 将模型信息注入到 test_config
            enriched = {**test_config, "gen_model": model_key}
            for rep in range(args.repeat):
                key = f"{model_key}__{config_name}"
                if args.repeat > 1:
                    key += f"_r{rep+1}"
                label = f"{model_profile['label']} | {test_config['label']}"
                enriched_with_label = {**enriched, "label": label}
                results = run_single_config(
                    config_name=key,
                    test_config=enriched_with_label,
                    char_config=char_config,
                    user_inputs=user_inputs,
                    total_turns=args.turns,
                    dry_run=args.dry_run,
                )
                all_results[key] = results

    # 保存原始数据
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"results_{ts}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)
    print(f"  [OK] 结果: {json_path}")

    # 生成报告
    generate_report(all_results, output_dir)

    print(f"\n{'='*60}")
    print(f"  验证完成!")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
