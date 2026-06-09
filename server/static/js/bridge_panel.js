/**
 * 双模式桥接模式专属前端功能模块
 */

(function() {
  let bridgeSessions = [];
  let currentSessionId = null;
  let summaryPollIntervalId = null;
  let batchPollIntervalId = null;
  let summarySeconds = 0;
  let summaryTimerId = null;

  // P0-2: XSS 防护工具函数
  function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
  }

  // --- 1. 初始化模块 ---
  window.initBridgePanel = async function() {
    console.log('[Bridge] 初始化面板...');
    
    // 加载已有会话
    await loadBridgeSessions();
    
    // 初始化大模型下拉选单
    populateModelDropdown();
    
    // 监听新建会话的切换方向改变
    const dirSelect = document.getElementById('bridge-new-direction');
    if (dirSelect) {
      dirSelect.addEventListener('change', () => updateNewSourceConversations());
    }
  };

  // --- 2. 加载与填充会话列表 ---
  async function loadBridgeSessions() {
    try {
      const res = await fetch('/api/bridge/sessions');
      if (!res.ok) return;
      bridgeSessions = await res.json();
      
      const selector = document.getElementById('bridge-session-selector');
      if (selector) {
        const currentVal = selector.value;
        selector.innerHTML = '<option value="">-- 选择切换会话 --</option>' + 
          bridgeSessions.map(s => {
            const label = s.scenario_name ? `${s.scenario_name} (${s.session_id})` : s.session_id;
            return `<option value="${s.session_id}">${label}</option>`;
          }).join('');
        
        if (currentVal && bridgeSessions.some(s => s.session_id === currentVal)) {
          selector.value = currentVal;
        }
      }
    } catch (e) {
      console.error('[Bridge] 加载切换会话列表失败:', e);
    }
  }

  async function populateModelDropdown() {
    try {
      const res = await fetch('/api/models');
      const data = await res.json();
      const models = data.models || data || [];
      
      const modelSelect = document.getElementById('bridge-new-model');
      if (modelSelect) {
        modelSelect.innerHTML = '<option value="">-- 选择目标模型 (默认) --</option>' +
          models.map(m => {
            const id = m.id || m;
            const name = m.display_name || m.name || id;
            return `<option value="${id}">${name}</option>`;
          }).join('');
      }
    } catch (e) {
      console.error('[Bridge] 获取模型列表失败:', e);
    }
  }

  // --- 3. 新建会话模态框 ---
  window.openNewBridgeSessionModal = function() {
    const modal = document.getElementById('modal-new-bridge');
    if (modal) {
      modal.style.display = 'flex';
      updateNewSourceConversations();
    }
  };

  window.closeNewBridgeSessionModal = function() {
    const modal = document.getElementById('modal-new-bridge');
    if (modal) modal.style.display = 'none';
  };

  async function updateNewSourceConversations() {
    const dir = document.getElementById('bridge-new-direction')?.value || 's2l';
    const sourceSelect = document.getElementById('bridge-new-source-conv');
    if (!sourceSelect) return;
    
    sourceSelect.innerHTML = '<option value="">正在加载源对话历史...</option>';
    
    // 根据切换方向拉取对应模式的对话
    const modeParam = dir === 's2l' ? 'short' : 'long';
    try {
      // 这里的 GET 请求会由 mode_controller 中的 fetch 拦截代理或显式拼接 mode 过滤
      const res = await fetch(`/api/conversations?mode=${modeParam}`);
      const data = await res.json();
      const list = data.conversations || data || [];
      
      if (list.length === 0) {
        sourceSelect.innerHTML = '<option value="">暂无可用对话历史，请先在聊天台或用例库生成数据</option>';
      } else {
        sourceSelect.innerHTML = list.map(c => {
          const name = c.nickname || c.id;
          const turns = c.total_turns ? ` (${c.total_turns}轮)` : '';
          return `<option value="${c.id}">${name}${turns}</option>`;
        }).join('');
      }
    } catch (e) {
      console.error(e);
      sourceSelect.innerHTML = '<option value="">加载失败，请重试</option>';
    }
  }

  window.submitCreateBridgeSession = async function() {
    const dir = document.getElementById('bridge-new-direction').value;
    const sourceConv = document.getElementById('bridge-new-source-conv').value;
    const model = document.getElementById('bridge-new-model').value;
    
    if (!sourceConv) {
      alert('请选择源对话历史！');
      return;
    }
    
    const payload = {
      from_mode: dir === 's2l' ? 'shortform' : 'longform',
      to_mode: dir === 's2l' ? 'longform' : 'shortform',
      source_conversation_id: sourceConv,
      target_model: model || undefined,
      bridge_turns: 20,
      summary_interval: 10,
      scenario_name: `Scenario_${sourceConv.substring(0, 5)}`,
      triggered_by: 'user_click'
    };
    
    try {
      const res = await fetch('/api/bridge/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      
      if (res.ok && data.session_id) {
        closeNewBridgeSessionModal();
        await loadBridgeSessions();
        
        // 自动选择并加载新创建的会话
        const selector = document.getElementById('bridge-session-selector');
        if (selector) {
          selector.value = data.session_id;
          window.loadBridgeSessionDetails();
        }
      } else {
        alert(`创建失败: ${data.detail || '未知原因'}`);
      }
    } catch (e) {
      console.error(e);
      alert('网络请求失败');
    }
  };

  // --- 4. 详情载入与状态机流转 ---
  window.loadBridgeSessionDetails = async function() {
    const sessionId = document.getElementById('bridge-session-selector').value;
    if (!sessionId) {
      resetBridgeUI();
      return;
    }
    
    currentSessionId = sessionId;
    try {
      const res = await fetch(`/api/bridge/sessions/${sessionId}`);
      if (!res.ok) return;
      const session = await res.json();
      
      // 更新元数据统计
      const basic = session.basic || {};
      const fromLabel = basic.from_mode === 'shortform' ? '短文' : '长文';
      const toLabel = basic.to_mode === 'shortform' ? '短文' : '长文';
      document.getElementById('bridge-meta-stats').textContent = 
        `源会话: ${basic.source_conversation_id} | 模式: ${fromLabel} → ${toLabel} | 目标模型: ${basic.target_model || '默认'}`;
      
      // 加载源历史对话
      loadSourceHistory(session);
      
      // 状态判断
      handleSessionState(session);
      
    } catch (e) {
      console.error('[Bridge] 加载详情异常:', e);
    }
  };

  function resetBridgeUI() {
    currentSessionId = null;
    document.getElementById('bridge-meta-stats').textContent = '源会话: - | 模式: - → - | 目标模型: -';
    document.getElementById('bridge-source-history').innerHTML = '<div class="empty-state">请先选择或新建切换会话</div>';
    document.getElementById('bridge-summary-text').value = '';
    document.getElementById('bridge-ai-output').innerHTML = '';
    document.getElementById('bridge-scores-list').innerHTML = '';
    
    const badge = document.getElementById('bridge-summary-status-badge');
    badge.textContent = '等待中';
    badge.className = 'badge badge-secondary';
    document.getElementById('bridge-summary-progress-wrapper').style.display = 'none';
    document.getElementById('bridge-summary-fallback-tip').style.display = 'none';
  }

  async function loadSourceHistory(session) {
    const historyContainer = document.getElementById('bridge-source-history');
    if (!historyContainer) return;
    
    // 如果已有拉取的数据，直接渲染
    const basic = session.basic || {};
    const sourceConvId = basic.source_conversation_id;
    try {
      // 强制绕过 mode 拦截以获取该特定 conversation 的 turns
      const res = await fetch(`/api/conversations/${sourceConvId}`);
      if (!res.ok) {
        historyContainer.innerHTML = '<div class="empty-state">无法获取源历史数据</div>';
        return;
      }
      const data = await res.json();
      const results = data.results || [];
      
      if (results.length === 0) {
        historyContainer.innerHTML = '<div class="empty-state">该会话暂无聊天历史</div>';
        return;
      }
      
      historyContainer.innerHTML = results.slice(-20).map(t => {
        return `
          <div class="bridge-chat-bubble user">
            <span style="font-weight:600;font-size:11px;opacity:0.8">User</span>
            <span>${escapeHtml(t.user_input)}</span>
          </div>
          <div class="bridge-chat-bubble assistant">
            <span style="font-weight:600;font-size:11px;opacity:0.8">${escapeHtml(basic.target_model || 'AI')}</span>
            <span>${escapeHtml(t.ai_output)}</span>
          </div>
        `;
      }).join('');
      
      historyContainer.scrollTop = historyContainer.scrollHeight;
    } catch (e) {
      console.error(e);
      historyContainer.innerHTML = '<div class="empty-state">加载历史过程出错</div>';
    }
  }

  function handleSessionState(session) {
    const badge = document.getElementById('bridge-summary-status-badge');
    const progressWrapper = document.getElementById('bridge-summary-progress-wrapper');
    const fallbackTip = document.getElementById('bridge-summary-fallback-tip');
    
    if (session.status === 'pending_summary') {
      badge.textContent = '生成中';
      badge.className = 'badge badge-primary';
      progressWrapper.style.display = 'block';
      fallbackTip.style.display = 'none';
      
      // 启动定时器展示耗时
      summarySeconds = 0;
      document.getElementById('bridge-summary-elapsed').textContent = '0.0';
      if (summaryTimerId) clearInterval(summaryTimerId);
      summaryTimerId = setInterval(() => {
        summarySeconds += 0.1;
        document.getElementById('bridge-summary-elapsed').textContent = summarySeconds.toFixed(1);
        document.getElementById('bridge-summary-progress-fill').style.width = `${Math.min((summarySeconds / 2.5) * 100, 100)}%`;
        if (summarySeconds >= 2.5) {
          fallbackTip.style.display = 'block';
        }
      }, 100);
      
      // 发送生成摘要的请求
      triggerSummaryGeneration(session.session_id);
    } 
    else if (session.status === 'pending_first_response' || session.status === 'completed') {
      badge.textContent = '已完成';
      badge.className = 'badge badge-success';
      progressWrapper.style.display = 'none';
      fallbackTip.style.display = 'none';
      if (summaryTimerId) clearInterval(summaryTimerId);
      
      const summaryObj = session.summary || {};
      document.getElementById('bridge-summary-text').value = summaryObj.switch_summary || '*(未生成切换摘要)*';
      
      if (session.status === 'pending_first_response') {
        renderFirstResponseForm();
      } else {
        renderFirstResponseResult(session);
      }
    }
  }

  // --- 5. 摘要生成与轮询 ---
  async function triggerSummaryGeneration(sessionId) {
    try {
      const res = await fetch(`/api/bridge/sessions/${sessionId}/summary`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ summary_model: 'deepseek-v4-flash' })
      });
      
      if (res.ok) {
        startSummaryPolling(sessionId);
      } else {
        alert('触发生成切换摘要失败，请重试');
      }
    } catch (e) {
      console.error(e);
    }
  }

  function startSummaryPolling(sessionId) {
    if (summaryPollIntervalId) clearInterval(summaryPollIntervalId);
    summaryPollIntervalId = setInterval(async () => {
      try {
        const res = await fetch(`/api/bridge/sessions/${sessionId}/summary`);
        if (!res.ok) return;
        const data = await res.json();
        
        if (data.summary_status === 'completed') {
          clearInterval(summaryPollIntervalId);
          if (summaryTimerId) clearInterval(summaryTimerId);
          
          // 重新刷新加载最新会话详情以更新全局状态
          loadBridgeSessionDetails();
        }
      } catch (e) {
        console.error(e);
      }
    }, 1000);
  }

  // --- 6. 首轮回复生成输入框渲染 ---
  function renderFirstResponseForm() {
    const outputBox = document.getElementById('bridge-ai-output');
    if (!outputBox) return;
    
    outputBox.innerHTML = `
      <div style="margin-bottom:8px;color:var(--text-secondary)">请输入过渡句以启动切换后首轮 AI 回复:</div>
      <textarea id="bridge-user-input" class="form-textarea" style="width:100%;height:80px;margin-bottom:8px" placeholder="在此输入第一轮交互的引子，例如：萧逸，你在看什么书呢？"></textarea>
      <button class="btn btn-primary" onclick="generateFirstResponse()" style="width:100%">🚀 开始过渡并生成回复</button>
    `;
    
    window.generateFirstResponse = async function() {
      const inputVal = document.getElementById('bridge-user-input').value.trim();
      if (!inputVal) {
        alert('请输入用户第一轮消息！');
        return;
      }
      
      outputBox.innerHTML = '<div style="color:var(--text-secondary);padding:20px;text-align:center">⏳ 正在使用目标大模型过渡并计算打分，请稍后...</div>';
      
      try {
        const res = await fetch(`/api/bridge/sessions/${currentSessionId}/first-response`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_input: inputVal, thinking_level: 'high' })
        });
        const data = await res.json();
        
        if (res.ok) {
          loadBridgeSessionDetails();
        } else {
          alert(`首轮生成失败: ${data.detail || '未知原因'}`);
          renderFirstResponseForm();
        }
      } catch (e) {
        console.error(e);
        alert('请求超时或失败');
        renderFirstResponseForm();
      }
    };
  }

  // --- 7. 显示首轮回复结果与雷达图 ---
  function renderFirstResponseResult(session) {
    const outputBox = document.getElementById('bridge-ai-output');
    if (!outputBox) return;
    
    // 首轮回复结果在数据库中的存储形式，可以通过 conversations API 读取
    // 我们再次发起请求读取 target_conversation 的首轮 AI 回复以直接展现内容与评分
    const targetConvId = (session.basic || {}).target_conversation_id;
    if (!targetConvId) {
      outputBox.textContent = '首轮回复暂未生成。';
      return;
    }
    
    fetch(`/api/conversations/${targetConvId}`)
      .then(res => res.json())
      .then(data => {
        const turns = data.results || [];
        if (turns.length > 0) {
          const firstTurn = turns[0];
          outputBox.textContent = firstTurn.ai_output || '*(\u65E0\u56DE\u590D\u5185\u5BB9)*';
          
          // 渲染打分数据与雷达图
          renderScoreStats(firstTurn.scoring || {});
        } else {
          outputBox.textContent = '尚未获取到生成的回复数据';
        }
      })
      .catch(e => {
        console.error(e);
        outputBox.textContent = '加载首轮回复详情出错';
      });
  }

  function renderScoreStats(scoring) {
    const listEl = document.getElementById('bridge-scores-list');
    if (!listEl) return;
    
    const dimensions = [
      { key: 'persona_fidelity', label: '人设契合度' },
      { key: 'narrative_immersion', label: '叙事沉浸感' },
      { key: 'emotional_tension', label: '情感张力' },
      { key: 'boundary_memory', label: '边界记忆力' },
      { key: 'format_compliance', label: '格式规范性' },
      { key: 'context_coherence', label: '语境连贯性' }
    ];
    
    const scores = dimensions.map(d => {
      const val = scoring.scores?.[d.key] || scoring[d.key] || 8.0; // 兜底 8.0
      return { label: d.label, val: val };
    });
    
    listEl.innerHTML = scores.map(s => {
      return `
        <div class="bridge-score-item" style="display:flex;justify-content:space-between;width:100%;font-size:11px;background:var(--bg-hover);padding:4px 8px;border-radius:4px">
          <span style="color:var(--text-secondary)">${s.label}</span>
          <span style="font-weight:700">${s.val}</span>
        </div>
      `;
    }).join('');
    
    // 渲染微型雷达图
    drawMiniRadarChart('bridge-radar-canvas', scores.map(s => s.label), scores.map(s => s.val));
  }

  function drawMiniRadarChart(canvasId, labels, data) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;
    ctx.clearRect(0, 0, width, height);
    
    const centerX = width / 2;
    const centerY = height / 2;
    const radius = Math.min(width, height) * 0.35;
    const numPoints = labels.length;
    
    // draw grids
    ctx.strokeStyle = '#cbd5e1';
    ctx.lineWidth = 0.5;
    const numGrids = 3;
    for (let j = 1; j <= numGrids; j++) {
      const r = radius * (j / numGrids);
      ctx.beginPath();
      for (let i = 0; i < numPoints; i++) {
        const angle = (i * 2 * Math.PI) / numPoints - Math.PI / 2;
        const x = centerX + r * Math.cos(angle);
        const y = centerY + r * Math.sin(angle);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.closePath();
      ctx.stroke();
    }
    
    // draw data area
    // P2-12: Canvas 2D 不支持 CSS 变量，需读取计算值
    const primaryColor = getComputedStyle(document.documentElement).getPropertyValue('--primary-color').trim() || '#1f6feb';
    ctx.strokeStyle = primaryColor;
    ctx.fillStyle = 'rgba(31, 111, 235, 0.2)';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    for (let i = 0; i < numPoints; i++) {
      const val = data[i] || 0;
      const r = radius * (val / 10);
      const angle = (i * 2 * Math.PI) / numPoints - Math.PI / 2;
      const x = centerX + r * Math.cos(angle);
      const y = centerY + r * Math.sin(angle);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.stroke();
    ctx.fill();
  }

  // --- 8. 醒一醒 (主动重写/干预) ---
  window.triggerBridgeManualWakeup = async function() {
    if (!currentSessionId) return;
    if (!confirm('唤醒机制会擦除上一条 AI 输出并重新使用高思考层级重新生成，确定吗？')) return;
    
    const outputBox = document.getElementById('bridge-ai-output');
    outputBox.innerHTML = '<div style="color:var(--text-secondary);padding:20px;text-align:center">⏳ 正在触发 L1 三明治拼接与高参数重新过渡...</div>';
    
    try {
      // 通过首轮生成端口并指定 thinking_level: 'high' 来进行手动唤醒
      const res = await fetch(`/api/bridge/sessions/${currentSessionId}/first-response`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_input: '醒一醒，我们继续之前的聊天。', thinking_level: 'high' })
      });
      
      if (res.ok) {
        loadBridgeSessionDetails();
      } else {
        alert('唤醒重写失败，请重试');
        loadBridgeSessionDetails();
      }
    } catch (e) {
      console.error(e);
      loadBridgeSessionDetails();
    }
  };

  // --- 9. 底部批量验证跑测 ---
  window.triggerBridgeBatchTest = async function() {
    const statusText = document.getElementById('bridge-batch-status');
    if (statusText) statusText.textContent = '运行中 (开始跑测机制...)';
    
    try {
      const res = await fetch('/api/bridge/verify-runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scripts: ['mece_main'],
          dry_run: false
        })
      });
      const data = await res.json();
      
      if (res.ok && data.id) {
        startBatchPoll(data.id);
      } else {
        if (statusText) statusText.textContent = `失败: ${data.detail || '未知原因'}`;
      }
    } catch (e) {
      console.error(e);
      if (statusText) statusText.textContent = '网络故障';
    }
  };

  function startBatchPoll(runId) {
    if (batchPollIntervalId) clearInterval(batchPollIntervalId);
    
    const statusText = document.getElementById('bridge-batch-status');
    batchPollIntervalId = setInterval(async () => {
      try {
        const res = await fetch(`/api/bridge/verify-runs/${runId}`);
        if (!res.ok) return;
        const run = await res.json();
        
        if (statusText) statusText.textContent = `运行中 (状态: ${run.status})`;
        
        if (run.status === 'completed' || run.status === 'done') {
          clearInterval(batchPollIntervalId);
          if (statusText) statusText.textContent = '✅ 批量验证已全部通过！';
        } else if (run.status === 'failed') {
          clearInterval(batchPollIntervalId);
          if (statusText) statusText.textContent = '❌ 部分用例未能通过验证';
        }
      } catch (e) {
        console.error(e);
      }
    }, 2000);
  }

  window.viewBridgeBatchReport = function() {
    alert('正在加载并跳转批量对比报告...');
    window.switchPage('test-center'); // 跳转到长文测试中心的报告面板
  };

})();
