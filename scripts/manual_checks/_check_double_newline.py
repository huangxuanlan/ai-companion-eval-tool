"""检查短→长方向通过样本的旁白与对白之间是否有双换行"""
import json, re
from pathlib import Path

rows = [json.loads(l) for l in Path(
    r"E:\提效工具\长文模式生成\output\mode_switching_switch_state\strategy_ab_compare_full_20260514\results.jsonl"
).open(encoding="utf-8")]

out = Path(r"E:\提效工具\长文模式生成\output\mode_switching_switch_state\strategy_ab_compare_full_20260514\_newline_check.txt")

with out.open("w", encoding="utf-8") as f:
    # 短→长方向全部样本（通过+未通过）
    f.write("=" * 70 + "\n")
    f.write("  短→长方向：旁白与对白之间换行符检查\n")
    f.write("=" * 70 + "\n\n")
    
    for r in rows:
        if r["direction"] != "短→长":
            continue
        
        output = r["output"]
        strategy = r["strategy"]
        role = r["role_name"]
        model = r["target_model"]
        run = r.get("run", 1)
        passed = r["format_pass"]
        
        # 分析换行模式
        # 找旁白（）和对白 **""** 之间的分隔
        # 正常长文格式：（旁白）\n\n**"对白"**
        
        has_double_nl = "\n\n" in output
        
        # 统计具体模式
        # 1. （...）后面紧跟\n\n**" 
        pattern_ok = len(re.findall(r'）\n\n\*\*[""「]', output))
        # 2. （...）后面紧跟\n**" (单换行)
        pattern_single = len(re.findall(r'）\n\*\*[""「]', output))
        # 3. **"..."**后面紧跟\n\n（ (对白后双换行接旁白)
        pattern_ok2 = len(re.findall(r'[""」]\*\*\n\n（', output))
        # 4. **"..."**后面紧跟\n（ (单换行)
        pattern_single2 = len(re.findall(r'[""」]\*\*\n（', output))
        
        # 裸叙述后接对白（无括号）
        # 例：叙述段落\n\n**"对白"**
        pattern_bare_to_dial = len(re.findall(r'[。！？…]\n\n\*\*[""「]', output))
        pattern_bare_to_dial_single = len(re.findall(r'[。！？…]\n\*\*[""「]', output))
        
        total_transitions = pattern_ok + pattern_single + pattern_ok2 + pattern_single2
        
        f.write(f"--- {strategy} | {role} | {model} | run{run} | {'PASS' if passed else 'FAIL'} ---\n")
        f.write(f"  双换行: {'有' if has_double_nl else '无'}\n")
        f.write(f"  ）→\\n\\n→对白: {pattern_ok}  |  ）→\\n→对白(单): {pattern_single}\n")
        f.write(f"  对白→\\n\\n→（: {pattern_ok2}  |  对白→\\n→（(单): {pattern_single2}\n")
        if pattern_bare_to_dial or pattern_bare_to_dial_single:
            f.write(f"  裸叙述→\\n\\n→对白: {pattern_bare_to_dial}  |  裸叙述→\\n→对白(单): {pattern_bare_to_dial_single}\n")
        f.write(f"  OUTPUT前200字:\n  {repr(output[:200])}\n\n")

    # 汇总统计
    f.write("\n" + "=" * 70 + "\n")
    f.write("  汇总统计\n")
    f.write("=" * 70 + "\n\n")
    
    for strat in ["A_互动要点", "B_三明治兜底"]:
        subset = [r for r in rows if r["direction"] == "短→长" and r["strategy"] == strat]
        has_double = sum(1 for r in subset if "\n\n" in r["output"])
        
        # 统计旁白→对白的双换行比例
        total_ok = 0
        total_single = 0
        total_ok2 = 0
        total_single2 = 0
        for r in subset:
            o = r["output"]
            total_ok += len(re.findall(r'）\n\n\*\*[""「]', o))
            total_single += len(re.findall(r'）\n\*\*[""「]', o))
            total_ok2 += len(re.findall(r'[""」]\*\*\n\n（', o))
            total_single2 += len(re.findall(r'[""」]\*\*\n（', o))
        
        f.write(f"  {strat}:\n")
        f.write(f"    含双换行的样本: {has_double}/{len(subset)}\n")
        f.write(f"    ）→\\n\\n→对白 正确转换: {total_ok} 次\n")
        f.write(f"    ）→\\n→对白 单换行(异常): {total_single} 次\n")
        f.write(f"    对白→\\n\\n→（ 正确转换: {total_ok2} 次\n")
        f.write(f"    对白→\\n→（ 单换行(异常): {total_single2} 次\n\n")

print(f"已写入: {out}")
