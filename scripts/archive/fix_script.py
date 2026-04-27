import re

with open('longform_multi_turn.py', 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Remove the duplicated build_messages_for_turn block
dup_pattern = re.compile(r'# ── 消息组装 ──.*?return messages\n', re.DOTALL)
matches = dup_pattern.findall(text)
if len(matches) > 1:
    # It matched the duplicate. We only want the first one to survive.
    # Wait, the duplication is exactly from "\n\n# ── 消息组装 ──────────────────────────────────────────────────\n\ndef build_messages_for_turn("
    # up to "return messages\n"
    pass

# Safer way to remove the duplicate block: find the duplicate string and replace the second occurrence only.
dup_block = re.search(r'# ── 消息组装 ──────────────────────────────────────────────────\n\ndef build_messages_for_turn.*?return messages\n', text, re.DOTALL)
if dup_block:
    dup_str = dup_block.group(0)
    # Split text into occurrences of dup_str
    parts = text.split(dup_str)
    if len(parts) >= 3:
        # Rejoin: first occurrence kept
        text = parts[0] + dup_str + parts[1] + parts[2]
        print('Removed duplicated build_messages_for_turn block.')

# 2. Fix build_variables and run_conversation_chain
broken_pattern = r'        "relation_info", "relation_rule4", "system_module11",\n        "current_scene",\n      3. 每 5 轮暂停：调用 mini → 生成摘要 → 注入变量 → 重新渲染 system prompt\n    """\n    # ── 1. 加载模板 ──'

fixed_replacement = '''        "relation_info", "relation_rule4", "system_module11",
        "current_scene",
    ]:
        variables[key] = ctx.get(key, "")

    # 系统模块变量
    modules = config.get("modules", {})
    for key in [
        "system_module8", "longform_persona", "longform_narrative_style",
        "system_Role_acting", "weekly_schedule", "dialogueStartPrompt",
        "longform_few_shot", "user_Nickname", "user_gender", "user_identity",
    ]:
        variables[key] = modules.get(key, ctx.get(key, char.get(key, "")))
    
    # dialogue_summary 初始为空（由脚本动态生成）
    variables.setdefault("dialogue_summary", "")

    # 合并额外的自定义变量（来自前端变量预览的编辑覆盖）
    custom_vars = config.get("custom_variables", {})
    if custom_vars:
        variables.update(custom_vars)
        
    return variables


def run_conversation_chain(config: dict, max_turns: int = None, dry_run: bool = False):
    """
    执行多轮对话链。

    核心流程：
      1. 加载模板 → 注入变量 → 得到 system prompt
      2. 逐轮执行：组装 messages → 调用 pro API → 拼接历史
      3. 每 5 轮暂停：调用 mini → 生成摘要 → 注入变量 → 重新渲染 system prompt
    """
    # ── 1. 加载模板 ──'''

if broken_pattern in text:
    text = text.replace(broken_pattern, fixed_replacement)
    print('Fixed build_variables and run_conversation_chain.')
else:
    print('Could not find the exact broken pattern.')

with open('longform_multi_turn.py', 'w', encoding='utf-8') as f:
    f.write(text)

