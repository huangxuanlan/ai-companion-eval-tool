#!/usr/bin/env python3
"""分析原格式互动要点Excel批量验证的进度"""
import json
from pathlib import Path
from collections import defaultdict

results_file = Path("output/mode_switching_switch_state/interaction_points_excel_batch_real_20260513_v3/results.jsonl")

if not results_file.exists():
    print(f"结果文件不存在: {results_file}")
    exit(1)

data = []
with open(results_file, encoding='utf-8') as f:
    for line in f:
        data.append(json.loads(line))

print(f"已完成: {len(data)}/112 ({len(data)/112*100:.1f}%)")

success = [d for d in data if d['success']]
print(f"API成功: {len(success)}/{len(data)} ({len(success)/len(data)*100:.1f}%)")

fmt_pass = [d for d in success if d['metrics'].get('format_pass', False)]
print(f"格式通过: {len(fmt_pass)}/{len(success)} ({len(fmt_pass)/len(success)*100:.1f}%)")

points_ok = [d for d in data if d['points_format_pass']]
print(f"互动要点格式通过: {len(points_ok)}/{len(data)} ({len(points_ok)/len(data)*100:.1f}%)")

print(f"\n按模型统计:")
stats = defaultdict(lambda: {'total': 0, 'success': 0, 'fmt_ok': 0})
for d in data:
    m = d['target_model']
    stats[m]['total'] += 1
    if d['success']:
        stats[m]['success'] += 1
        if d['metrics'].get('format_pass', False):
            stats[m]['fmt_ok'] += 1

for m, s in sorted(stats.items()):
    if s['success'] > 0:
        print(f"{m}: {s['fmt_ok']}/{s['success']} 格式通过 ({s['fmt_ok']/s['success']*100:.1f}%), API {s['success']}/{s['total']}")
    else:
        print(f"{m}: API全部失败 0/{s['total']}")

print(f"\n互动要点延迟统计:")
ext_latencies = [d['extractor_latency'] for d in data]
if ext_latencies:
    print(f"平均: {sum(ext_latencies)/len(ext_latencies):.3f}s")
    print(f"最小: {min(ext_latencies):.3f}s")
    print(f"最大: {max(ext_latencies):.3f}s")
