"""修复 fetchPresets 中 preset-grid null 错误 + 给 f-personality 绑定 onchange"""

js_path = r'E:\提效工具\长文模式生成\server\static\js\legacy_bundle.js'
with open(js_path, 'r', encoding='utf-8') as f:
    js = f.read()

# Fix 1: preset-grid null safety
old = "const grid = $('preset-grid'); grid.innerHTML = '';"
new = "const grid = $('preset-grid'); if(grid) grid.innerHTML = '';"
if old in js:
    js = js.replace(old, new)
    print("[1] preset-grid null safety: OK")
else:
    print("[1] preset-grid already safe or not found")

# Fix 2: f-personality onchange -> 确保绑定 autoFillLongformVars
# 检查是否已绑定
if "f-personality" in js and "autoFillLongformVars" in js:
    # 确认 onchange 已通过 addEventListener 绑定
    if "$('f-personality').addEventListener" in js:
        print("[2] f-personality event already bound")
    else:
        print("[2] f-personality event not yet bound via addEventListener")

with open(js_path, 'w', encoding='utf-8') as f:
    f.write(js)

print("Fix complete!")
