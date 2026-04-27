"""Fix index.html - restore chat page + inject freechat section."""
path = r"E:\提效工具\长文模式生成\server\static\index.html"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Find </header> tag regardless of line ending style
idx_header_tag = content.find("</header>")
if idx_header_tag < 0:
    print("FAIL: </header> not found"); exit(1)

# Find the end of the line containing </header>
idx_after_header = content.find("\n", idx_header_tag)
if idx_after_header < 0:
    idx_after_header = idx_header_tag + len("</header>")
else:
    idx_after_header += 1  # include the \n

# Find the scoring button (first thing after the broken gap)
scoring_btn_text = 'onclick="$(\'modal-scoring\').style.display=\'none\'">×</button>'
idx_scoring_btn_line = content.find(scoring_btn_text)
if idx_scoring_btn_line < 0:
    print("FAIL: scoring button not found"); exit(1)

# Find the start of that line
idx_line_start = content.rfind("\n", 0, idx_scoring_btn_line)
if idx_line_start < 0: idx_line_start = 0
else: idx_line_start += 1

print(f"header ends at char {idx_after_header}")
print(f"scoring btn line starts at char {idx_line_start}")
print(f"Gap size: {idx_line_start - idx_after_header} chars")

insert = """
    <!-- P1: 对话页 -->
    <section id="page-chat" class="page active" style="flex:1;display:flex;flex-direction:column">
      <div id="chat-progress" class="chat-progress">
        <span class="chat-progress-text" id="chat-progress-text">Turn 0/0</span>
        <div class="chat-progress-bar">
          <div class="chat-progress-fill" id="chat-progress-fill"></div>
        </div>
        <span class="chat-progress-pct" id="chat-progress-pct">0%</span>
        <span id="chat-status-text" style="font-size:12px;color:var(--text-tertiary)">就绪</span>
      </div>
      <div class="chat-container" id="chat-area">
        <div class="empty-state" id="chat-empty">
          <div class="title">欢迎来到长文验证工具</div>
          <p>在右侧面板选择预设角色，配置参数后开始测试</p>
          <button class="btn btn-primary" style="margin-top:16px" onclick="document.getElementById('rightPanel').style.display='flex'">打开配置面板</button>
        </div>
      </div>
      <div id="chat-typing" class="typing-indicator" style="display:none;margin:0 8%">
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
      </div>
      <div class="btn-group" id="chat-nav" style="display:none;justify-content:center;padding:12px 8%">
        <button class="btn btn-secondary" id="btn-view-msgs">📋 查看消息结构</button>
        <button class="btn btn-secondary" id="btn-export-excel">📥 导出 Excel</button>
        <button class="btn btn-primary" id="btn-score-conv" style="background:linear-gradient(135deg,#f59e0b,#ef4444)">⭐ 一键打分</button>
      </div>
    </section>

    <!-- P-freechat: 火山方舟风格列式模型对比 -->
    <section id="page-freechat" class="page" style="flex:1;display:flex;flex-direction:column">
      <div style="padding:10px 24px;border-bottom:1px solid var(--border-light);display:flex;align-items:center;gap:0;background:var(--bg-surface)">
        <div style="font-weight:600;font-size:13px;color:var(--text-secondary);margin-right:16px;white-space:nowrap">⚡ 模型对比</div>
        <div id="freechat-model-slots" style="display:flex;flex:1;gap:0"></div>
        <button class="btn btn-secondary" id="btn-add-model-slot" onclick="addModelSlot()" style="font-size:12px;padding:4px 14px;white-space:nowrap;margin-left:12px">+ 添加模型</button>
      </div>
      <div id="freechat-area" class="chat-container" style="flex:1;overflow-y:auto;padding:24px 8%;display:flex;flex-direction:column;gap:16px">
        <div class="empty-state" id="freechat-empty">
          <div class="title">自由聊天</div>
          <p>选择 1-3 个模型，发送消息查看多模型并行输出对比。</p>
        </div>
      </div>
      <div style="padding:12px 8%;border-top:1px solid var(--border-light);display:flex;gap:8px">
        <textarea id="freechat-input" class="form-control" style="flex:1;min-height:44px;max-height:120px;resize:vertical;font-family:var(--font)" placeholder="输入消息..."></textarea>
        <button class="btn btn-primary" id="btn-freechat-send" style="padding:0 24px" onclick="sendFreeChat()">发送</button>
        <button class="btn btn-secondary" onclick="clearFreeChat()" title="清空对话">🗑️</button>
      </div>
    </section>

    <!-- P2: 打分可视化视图 (原 page-scoring，转为 Modal) -->
    <div id="modal-scoring" class="modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:999;align-items:center;justify-content:center;padding:20px;">
      <div style="background:var(--bg-surface);width:90%;max-width:900px;max-height:90vh;border-radius:12px;overflow-y:auto;display:flex;flex-direction:column;box-shadow:0 10px 30px rgba(0,0,0,0.1)">
        <div style="padding:16px 24px;border-bottom:1px solid var(--border-light);display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;background:var(--bg-surface);z-index:10;">
          <h3 style="margin:0;font-weight:600">⭐ 对话打分核查</h3>
"""

new_content = content[:idx_after_header] + insert + content[idx_line_start:]

with open(path, "w", encoding="utf-8") as f:
    f.write(new_content)

print("OK: HTML restored successfully")
