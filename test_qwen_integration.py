"""
test_qwen_integration.py — 千问 System 合并集成验证脚本
一次性运行，验证千问 vs 豆包的消息结构差异。
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "server"))

from services.message_assembler import MessageAssembler

assembler = MessageAssembler()
history = [
    {"role": "user", "content": "(在会议室等他)"},
    {"role": "assistant", "content": "会议室灯光偏暗...他推门走进来..."},
]
few_shot = [
    {"role": "user", "content": "(傍晚散步到江边)"},
    {"role": "assistant", "content": "江风卷起细碎的水汽...一个人坐在长椅上..."},
]
kwargs = dict(
    rendered_system="你是一个角色",
    system_after="",
    few_shot_messages=few_shot,
    conversation_history=history,
    dialogue_summary="",
    memory_context="用户画像: 喜欢猫",
    current_input="嗯哼",
    relationship="暧昧",
    role_name="测试角色",
    personality="霸道腹黑",
    turn_num=2,
)

qwen_msgs = assembler.build_messages(**kwargs, model_id="qwen3.6-plus")
doubao_msgs = assembler.build_messages(**kwargs, model_id="doubao-pro-32k")

def label(content):
    tags = []
    if "你是一个角色" in content: tags.append("MAIN")
    if "写作风格示例开始" in content: tags.append("PREFIX")
    if "风格示例结束" in content: tags.append("SEP")
    if "遵循System Prompt" in content: tags.append("STYLE")
    if "喜欢猫" in content: tags.append("MEM")
    if "Core_Constraints" in content: tags.append("CORE")
    return "+".join(tags) or "OTHER"

print("=== QWEN 3.6 Plus ===")
qsys = [(i, m) for i, m in enumerate(qwen_msgs) if m["role"] == "system"]
print(f"System count: {len(qsys)}")
for idx, msg in qsys:
    print(f"  [{idx}] {label(msg['content'])}  ({len(msg['content'])} chars)")

print("\n=== Doubao (Default) ===")
dsys = [(i, m) for i, m in enumerate(doubao_msgs) if m["role"] == "system"]
print(f"System count: {len(dsys)}")
for idx, msg in dsys:
    print(f"  [{idx}] {label(msg['content'])}  ({len(msg['content'])} chars)")

print("\n=== VERIFICATION ===")
ok = True

# V1
q_main = qwen_msgs[0]["content"]
v1 = "写作风格示例开始" in q_main and "你是一个角色" in q_main
print(f"[{'PASS' if v1 else 'FAIL'}] V1: Qwen PREFIX merged into main system")
ok = ok and v1

# V2
merged = [m for m in qwen_msgs if m["role"] == "system"
          and "风格示例结束" in m["content"]
          and "遵循System Prompt" in m["content"]
          and "喜欢猫" in m["content"]]
v2 = bool(merged)
print(f"[{'PASS' if v2 else 'FAIL'}] V2: Qwen SEP+STYLE+MEM merged")
ok = ok and v2

# V3
v3 = len(qsys) < len(dsys)
print(f"[{'PASS' if v3 else 'FAIL'}] V3: Qwen sys({len(qsys)}) < Doubao sys({len(dsys)})")
ok = ok and v3

# V4
standalone = [m for m in qwen_msgs if m["role"] == "system"
              and "风格示例结束" in m["content"]
              and "遵循System Prompt" not in m["content"]]
v4 = not standalone
print(f"[{'PASS' if v4 else 'FAIL'}] V4: No standalone SEPARATOR in Qwen")
ok = ok and v4

# V5
d_sep = [m for m in doubao_msgs if m["role"] == "system"
         and "风格示例结束" in m["content"]
         and "遵循System Prompt" not in m["content"]]
d_style = [m for m in doubao_msgs if m["role"] == "system"
           and "遵循System Prompt" in m["content"]
           and "喜欢猫" not in m["content"]]
v5 = bool(d_sep) and bool(d_style)
print(f"[{'PASS' if v5 else 'FAIL'}] V5: Doubao keeps SEP/STYLE separate (regression)")
ok = ok and v5

print(f"\nOVERALL: {'ALL PASSED' if ok else 'SOME FAILED'}")
sys.exit(0 if ok else 1)
