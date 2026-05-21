"""
互动要点提示词 v1.7 验证脚本
Phase 2: smoke (6次) → Phase 3: A/B (24次) → Phase 4: 端到端 (8次)
"""
from __future__ import annotations
import sys, os, json, time, re
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SERVER_DIR = PROJECT_ROOT / "server"
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SERVER_DIR))

try:
    from dotenv import load_dotenv
    load_dotenv(SERVER_DIR / ".env")
except ImportError:
    pass

from services.model_adapter import ModelAdapter
from compare_switching_strategies import (
    load_excel_data, DEFAULT_CASE_XLSX,
    build_transcript_with_timestamp,
    build_short_system, build_long_system,
    wrap_user_input, split_switch_context,
    evaluate_output,
    generate_short_summary, generate_long_summary,
    EXTRACTOR_MODEL, LONG_TARGET_MODEL,
)

PROMPT_V16 = Path(r"E:\工作资料\产品资料\提示词资料\长文模式\摘要提示词\互动要点提示词_v1.6_20260420.md")
PROMPT_V17 = Path(r"E:\工作资料\产品资料\提示词资料\长文模式\摘要提示词\互动要点提示词_v1.7_20260515.md")
OUTPUT_BASE = Path(r"E:\提效工具\长文模式生成\output\mode_switching_switch_state\v17_interaction_points_eval_20260515")


def load_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def extract_points(adapter: ModelAdapter, prompt_text: str, history: list[dict]) -> tuple[str, float]:
    """调用模型提取互动要点，输入 20 轮 transcript"""
    transcript = build_transcript_with_timestamp(history, role_tag_style="english")
    full_prompt = prompt_text.replace("{conversation_text}", transcript)
    t0 = time.time()
    result = adapter.chat(
        model_id=EXTRACTOR_MODEL,
        messages=[{"role": "user", "content": full_prompt}],
        max_tokens=400,
    )
    latency = time.time() - t0
    return (result.content.strip() if result.success else ""), latency


def validate_v17_output(output: str) -> tuple[list[str], int]:
    """v1.7 输出格式检测"""
    issues = []
    # 旧格式残留检测
    if "【待接续线索】" in output:
        issues.append("残留：待接续线索")
    if "【最后场景】" in output:
        issues.append("残留：最后场景")
    if "=== 互动要点结束 ===" in output:
        issues.append("残留：旧结束标记")
    if "【最近互动要点（桥接迁移）】" in output:
        issues.append("残留：旧标题行")
    # 新头尾标记检测
    has_header = "【以下为近期对话内容】" in output
    has_footer = "=== 摘要===" in output
    if not has_header:
        issues.append("缺少头标：【以下为近期对话内容】")
    if not has_footer:
        issues.append("缺少尾标：=== 摘要===")
    # 条目计数
    numbered = re.findall(r"^\d+\.\s*\[", output, re.MULTILINE)
    if len(numbered) > 5:
        issues.append(f"条目超限({len(numbered)}>5)")
    # 时间戳格式检测
    # 正确格式: [MM-DD HH:mm]
    correct_ts = re.findall(r"\[\d{2}-\d{2}\s+\d{2}:\d{2}\]", output)
    # 错误：区间格式 [MM-DD HH:mm-HH:mm]
    interval_ts = re.findall(r"\[\d{2}-\d{2}\s+\d{2}:\d{2}-\d{2}:\d{2}\]", output)
    if interval_ts:
        issues.append(f"时间戳区间格式({len(interval_ts)}处)")
    # 错误：带秒数 [MM-DD HH:mm:ss]
    seconds_ts = re.findall(r"\[\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\]", output)
    if seconds_ts:
        issues.append(f"时间戳带秒数({len(seconds_ts)}处)")
    # 时间戳总数 vs 条目数（排除错误格式后）
    valid_ts = len(correct_ts) - len(seconds_ts)  # 秒数格式也匹配了 HH:mm 部分
    if numbered and valid_ts < len(numbered):
        issues.append(f"有效时间戳不足({valid_ts}/{len(numbered)})")
    return issues, len(numbered)


# ══════════════════════════════════════════════════════════════
# Phase 2: Smoke
# ══════════════════════════════════════════════════════════════

def run_smoke(adapter, roles, n_roles=2, n_runs=3):
    """Phase 2: 6 次 smoke"""
    prompt = load_prompt(PROMPT_V17)
    results = []
    for role in roles[:n_roles]:
        history = role.get("shortform_history", [])
        if not history:
            history = role.get("longform_history", [])
        for run in range(1, n_runs + 1):
            output, latency = extract_points(adapter, prompt, history)
            issues, n_items = validate_v17_output(output)
            r = {
                "phase": "smoke", "role": role["role_name"], "run": run,
                "output": output, "latency": round(latency, 2),
                "n_items": n_items, "char_count": len(output),
                "issues": issues, "pass": len(issues) == 0,
            }
            results.append(r)
            status = "PASS" if r["pass"] else f"FAIL: {issues}"
            print(f"  smoke {role['role_name']} run{run}: {n_items}条 {latency:.1f}s {status}")
    return results


# ══════════════════════════════════════════════════════════════
# Phase 3: A/B
# ══════════════════════════════════════════════════════════════

def run_ab(adapter, roles, n_roles=4, n_runs=3):
    """Phase 3: 24 次 A/B"""
    prompt_v16 = load_prompt(PROMPT_V16)
    prompt_v17 = load_prompt(PROMPT_V17)
    results = []
    for role in roles[:n_roles]:
        history = role.get("shortform_history", [])
        if not history:
            history = role.get("longform_history", [])
        for run in range(1, n_runs + 1):
            for version, prompt in [("v1.6", prompt_v16), ("v1.7", prompt_v17)]:
                output, latency = extract_points(adapter, prompt, history)
                issues_v17, n_items = validate_v17_output(output)
                r = {
                    "phase": "ab", "version": version,
                    "role": role["role_name"], "run": run,
                    "output": output, "latency": round(latency, 2),
                    "n_items": n_items, "char_count": len(output),
                    "has_pending": "【待接续线索】" in output,
                    "has_scene": "【最后场景】" in output,
                    "has_new_header": "【以下为近期对话内容】" in output,
                    "has_new_footer": "=== 摘要===" in output,
                }
                results.append(r)
                print(f"  ab {version} {role['role_name']} run{run}: {n_items}条 {len(output)}字 {latency:.1f}s")
    # 汇总
    v16_r = [r for r in results if r["version"] == "v1.6"]
    v17_r = [r for r in results if r["version"] == "v1.7"]
    v17_residual = sum(1 for r in v17_r if r["has_pending"] or r["has_scene"])
    v17_new_header = sum(1 for r in v17_r if r["has_new_header"])
    v17_new_footer = sum(1 for r in v17_r if r["has_new_footer"])
    print(f"\nA/B 汇总:")
    print(f"  v1.6: avg items={sum(r['n_items'] for r in v16_r)/len(v16_r):.1f}, avg chars={sum(r['char_count'] for r in v16_r)/len(v16_r):.0f}")
    print(f"  v1.7: avg items={sum(r['n_items'] for r in v17_r)/len(v17_r):.1f}, avg chars={sum(r['char_count'] for r in v17_r)/len(v17_r):.0f}")
    print(f"  v1.7 旧格式残留(待接续/场景): {v17_residual}/{len(v17_r)}")
    print(f"  v1.7 新头标命中: {v17_new_header}/{len(v17_r)}")
    print(f"  v1.7 新尾标命中: {v17_new_footer}/{len(v17_r)}")
    if v16_r and v17_r:
        saved = sum(r['char_count'] for r in v16_r)/len(v16_r) - sum(r['char_count'] for r in v17_r)/len(v17_r)
        print(f"  v1.7 平均节省: {saved:.0f} 字")
    return results


# ══════════════════════════════════════════════════════════════
# Phase 4: E2E
# ══════════════════════════════════════════════════════════════

def run_e2e(adapter, roles, n_roles=2, n_runs=2):
    """Phase 4: 8 次端到端"""
    prompt_v17 = load_prompt(PROMPT_V17)
    results = []
    for role in roles[:n_roles]:
        short_history = role.get("shortform_history", [])
        long_history = role.get("longform_history", [])

        for direction in ["short_to_long", "long_to_short"]:
            source_history = short_history if direction == "short_to_long" else long_history
            if not source_history:
                print(f"  e2e {direction} {role['role_name']}: 无源历史，跳过")
                continue

            # 生成 v1.7 互动要点
            ip_output, ip_latency = extract_points(adapter, prompt_v17, source_history)
            ctx = split_switch_context(source_history)

            for run in range(1, n_runs + 1):
                if direction == "short_to_long":
                    system = build_long_system(role)
                    target_model = LONG_TARGET_MODEL
                    target_mode = "long"
                else:
                    system = build_short_system(role)
                    target_model = "doubao-1.5-character"
                    target_mode = "short"

                # 摘要
                if direction == "short_to_long":
                    summary = generate_short_summary(adapter, source_history)
                else:
                    summary = generate_long_summary(adapter, source_history)

                # 拼接：旧摘要 + 互动要点 + user
                summary_content = f"（以下为角色内部认知记录。）\n=== 动态摘要 ===\n{summary}\n=== 摘要结束 ==="
                ip_content = f"（以下为互动要点，仅供事实参考，不是回复格式示例；当前用户输入优先。）\n{ip_output}"

                messages = [
                    {"role": "system", "content": system},
                    {"role": "assistant", "content": summary_content},
                    {"role": "assistant", "content": ip_content},
                    {"role": "user", "content": wrap_user_input(ctx.current_user, target_mode)},
                ]

                # 消除连续 assistant
                final_messages = [messages[0]]
                for msg in messages[1:]:
                    if final_messages[-1]["role"] == msg["role"]:
                        final_messages[-1]["content"] += "\n\n" + msg["content"]
                    else:
                        final_messages.append(msg)

                t0 = time.time()
                result = adapter.chat(model_id=target_model, messages=final_messages, max_tokens=1200)
                latency = time.time() - t0
                output = result.content.strip() if result.success else ""
                eval_out = evaluate_output(output, target_mode)

                r = {
                    "phase": "e2e", "direction": direction,
                    "role": role["role_name"], "run": run,
                    "ip_output": ip_output, "final_output": output,
                    "latency": round(latency, 2),
                    **eval_out,
                }
                results.append(r)
                verdict = "PASS" if eval_out["format_pass"] else f"FAIL: {eval_out['issues']}"
                print(f"  e2e {direction} {role['role_name']} run{run}: {eval_out['char_count']}字 {latency:.1f}s {verdict}")
    # 汇总
    s2l = [r for r in results if r["direction"] == "short_to_long"]
    l2s = [r for r in results if r["direction"] == "long_to_short"]
    if s2l:
        print(f"\nE2E 短→长: {sum(1 for r in s2l if r['format_pass'])}/{len(s2l)} pass, avg {sum(r['char_count'] for r in s2l)/len(s2l):.0f}字")
    if l2s:
        print(f"E2E 长→短: {sum(1 for r in l2s if r['format_pass'])}/{len(l2s)} pass, avg {sum(r['char_count'] for r in l2s)/len(l2s):.0f}字")
    return results


def save_results(results, filename):
    path = OUTPUT_BASE / filename
    OUTPUT_BASE.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  → 保存: {path}")


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "smoke"
    roles = load_excel_data(DEFAULT_CASE_XLSX)
    adapter = ModelAdapter()

    if phase == "smoke":
        print("=== Phase 2: Smoke (6 calls) ===")
        results = run_smoke(adapter, roles, n_roles=2, n_runs=3)
        save_results(results, "smoke_results.jsonl")
    elif phase == "ab":
        print("=== Phase 3: A/B (24 calls) ===")
        results = run_ab(adapter, roles, n_roles=4, n_runs=3)
        save_results(results, "ab_results.jsonl")
    elif phase == "e2e":
        print("=== Phase 4: E2E (8 calls) ===")
        results = run_e2e(adapter, roles, n_roles=2, n_runs=2)
        save_results(results, "e2e_results.jsonl")
    elif phase == "all":
        print("=== Phase 2: Smoke ===")
        smoke = run_smoke(adapter, roles, n_roles=2, n_runs=3)
        save_results(smoke, "smoke_results.jsonl")
        if not all(r["pass"] for r in smoke):
            print("Smoke failed, stopping.")
            sys.exit(1)
        print("\n=== Phase 3: A/B ===")
        ab = run_ab(adapter, roles, n_roles=4, n_runs=3)
        save_results(ab, "ab_results.jsonl")
        print("\n=== Phase 4: E2E ===")
        e2e = run_e2e(adapter, roles, n_roles=2, n_runs=2)
        save_results(e2e, "e2e_results.jsonl")
