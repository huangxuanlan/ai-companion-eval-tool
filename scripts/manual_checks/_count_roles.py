import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "server"))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "server" / ".env")
except ImportError:
    pass

from compare_switching_strategies import load_excel_data, DEFAULT_CASE_XLSX

roles = load_excel_data(DEFAULT_CASE_XLSX)
print(f"roles count: {len(roles)}")
for r in roles:
    print(
        f"  {r['label']}: {r['role_name']} | "
        f"long={len(r['longform_history'])} | "
        f"short={len(r['shortform_history'])}"
    )

# 估算 API 调用次数
n = len(roles)
# 短文模型 3 个 + 长文模型 1 个，每方向都跑 2 个方案
# 长→短：n * 3 * 2 * runs = 6n * runs
# 短→长：n * 1 * 2 * runs = 2n * runs
runs = 3
target_calls = (6 * n + 2 * n) * runs
summary_calls = n * 2  # 长文摘要 + 短文摘要
points_calls = n * 2  # 长向 + 短向 各 1 次（extractor 每方向都生成）
total = target_calls + summary_calls + points_calls
print(f"\n=== 估算（runs={runs}） ===")
print(f"目标模型调用: {target_calls} 次")
print(f"摘要调用:    {summary_calls} 次")
print(f"互动要点:    {points_calls} 次")
print(f"总计:        {total} 次")
print(f"预估时间:    {total * 8 // 60} - {total * 15 // 60} 分钟（假设每次 8-15s）")
