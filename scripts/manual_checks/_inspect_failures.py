"""手动检查失败样本 - 输出到文件"""
import json
from pathlib import Path

rows = [json.loads(l) for l in open(
    r"E:\提效工具\长文模式生成\output\mode_switching_switch_state\strategy_ab_compare_full_20260514\results.jsonl",
    encoding="utf-8"
)]

out = Path(r"E:\提效工具\长文模式生成\output\mode_switching_switch_state\strategy_ab_compare_full_20260514\_failure_inspection.txt")

with out.open("w", encoding="utf-8") as f:
    # 1) 短→长方向全部失败样本
    f.write("=" * 70 + "\n")
    f.write("  短→长方向 全部失败样本（方案A + 方案B）\n")
    f.write("=" * 70 + "\n")
    for r in rows:
        if r["direction"] == "短→长" and not r["format_pass"]:
            f.write(f"\n--- {r['strategy']} | {r['role_name']} | {r['target_model']} | run{r.get('run',1)} ---\n")
            f.write(f"原issues: {r['issues']}\n")
            f.write(f"char_count: {r['char_count']}\n")
            f.write(f"OUTPUT:\n{r['output'][:600]}\n")
            if len(r["output"]) > 600:
                f.write("...(截断)\n")

    # 2) 长→短方向全部失败样本
    f.write("\n\n" + "=" * 70 + "\n")
    f.write("  长→短方向 全部失败样本（方案A + 方案B）\n")
    f.write("=" * 70 + "\n")
    for r in rows:
        if r["direction"] == "长→短" and not r["format_pass"]:
            f.write(f"\n--- {r['strategy']} | {r['role_name']} | {r['target_model']} | run{r.get('run',1)} ---\n")
            f.write(f"原issues: {r['issues']}\n")
            f.write(f"char_count: {r['char_count']}\n")
            f.write(f"OUTPUT:\n{r['output'][:500]}\n")
            if len(r["output"]) > 500:
                f.write("...(截断)\n")

print(f"已写入: {out}")
print(f"文件大小: {out.stat().st_size} bytes")
