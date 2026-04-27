"""
修复路由顺序：将 /variables 移到 /{preset_id} 前面
"""
with open(r'E:\提效工具\长文模式生成\server\routers\presets.py', 'r', encoding='utf-8') as f:
    code = f.read()

# 提取 /variables 路由块
marker = '\n@router.get("/variables")'
if marker in code:
    idx = code.find(marker)
    variables_block = code[idx:]
    code_without = code[:idx]

    # 找到 /{preset_id} 路由位置
    insert_before = '@router.get("/{preset_id}")'
    insert_idx = code_without.find(insert_before)

    if insert_idx > 0:
        new_code = code_without[:insert_idx] + variables_block.strip() + '\n\n\n' + code_without[insert_idx:]
        with open(r'E:\提效工具\长文模式生成\server\routers\presets.py', 'w', encoding='utf-8') as f:
            f.write(new_code)
        print("Route order fixed!")
    else:
        print("/{preset_id} not found")
else:
    print("/variables not found in code")
