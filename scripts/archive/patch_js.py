import os

filepath = r'E:\提效工具\长文模式生成\server\static\js\legacy_bundle.js'

with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

old_func = """    function toggleCompareMode() {
      _compareModeActive = !_compareModeActive;
      if (_compareModeActive) {
        switchPage('freechat');
        initFreeChatPage();
        $('btn-toggle-compare').style.background = 'var(--primary-color)';
        $('btn-toggle-compare').style.color = 'white';
      } else {
        switchPage('chat');
        $('btn-toggle-compare').style.background = '';
        $('btn-toggle-compare').style.color = '';
      }
    }"""

new_func = """    function toggleCompareMode() {
      _compareModeActive = !_compareModeActive;
      const roleSelect = $('header-role-select');
      const roleContainer = roleSelect ? roleSelect.parentElement : null;
      if (_compareModeActive) {
        switchPage('freechat');
        initFreeChatPage();
        $('btn-toggle-compare').style.background = 'var(--primary-color)';
        $('btn-toggle-compare').style.color = 'white';
        if (roleContainer) roleContainer.style.display = 'none';
      } else {
        switchPage('chat');
        $('btn-toggle-compare').style.background = '';
        $('btn-toggle-compare').style.color = '';
        if (roleContainer) roleContainer.style.display = 'flex';
      }
    }"""

if old_func in text:
    new_text = text.replace(old_func, new_func)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_text)
    print("JS Replacement Complete")
else:
    print("Function not found, finding alternative...")
    s_idx = text.find('function toggleCompareMode() {')
    e_idx = text.find('}', s_idx)
    if s_idx != -1 and e_idx != -1:
        extracted = text[s_idx:e_idx+1]
        print(f"Found something else:\n{extracted}")
        new_text = text.replace(extracted, new_func)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_text)
        print("Alternative JS Replacement Complete")
    else:
        print("Completely not found")
