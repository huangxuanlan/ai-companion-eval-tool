"""临时测试短文解析"""
import sys
sys.path.insert(0, "scripts")
sys.path.insert(0, "server")
from compare_interaction_points_extractors import parse_shortform_dialogue
import openpyxl

wb = openpyxl.load_workbook(
    "E:/工作资料/产品资料/提示词资料/模型切换/短文模式聊天批量测试用例.xlsx"
)
ws = wb.active
text = ws.cell(28, 2).value
history = parse_shortform_dialogue(str(text))
print(f"解析到 {len(history)} 条消息")
print("\n全部消息:")
for i, msg in enumerate(history):
    print(f"  {i+1}. [{msg['role']}] {msg['content'][:80]}")
