/**
 * 双模式融合工具 — 全局模式控制器
 */

window.currentMode = 'longform'; // 'longform', 'shortform', 'bridge'

// --- 1. 全局 Fetch 拦截代理 ---
(function() {
  const originalFetch = window.fetch;
  window.fetch = function(input, init) {
    let url = typeof input === 'string' ? input : (input instanceof Request ? input.url : String(input));
    
    // 仅拦截 /api/ 开头的请求，且排除 /api/bridge/
    if (url.startsWith('/api/') && !url.includes('/api/bridge/') && window.currentMode) {
      const dbMode = window.currentMode === 'shortform' ? 'short' : (window.currentMode === 'longform' ? 'long' : null);
      
      if (dbMode) {
        let method = 'GET';
        if (init && init.method) method = init.method.toUpperCase();
        else if (input instanceof Request && input.method) method = input.method.toUpperCase();
        
        // GET 请求：注入 Query Parameter "?mode=..."
        if (method === 'GET') {
          try {
            const urlObj = new URL(url, window.location.origin);
            if (!urlObj.searchParams.has('mode')) {
              urlObj.searchParams.set('mode', dbMode);
              if (typeof input === 'string') {
                input = urlObj.pathname + urlObj.search;
              } else if (input instanceof Request) {
                input = new Request(urlObj.href, input);
              }
            }
          } catch (e) {
            console.error('Fetch intercept GET error:', e);
          }
        }
        
        // POST 请求：如果 Body 是 JSON，注入 mode 属性
        if (method === 'POST') {
          if (!init) init = {};
          let bodyText = '';
          if (typeof init.body === 'string') {
            bodyText = init.body;
          }
          
          if (bodyText) {
            try {
              const bodyObj = JSON.parse(bodyText);
              if (bodyObj && typeof bodyObj === 'object' && !bodyObj.hasOwnProperty('mode')) {
                bodyObj.mode = dbMode;
                init.body = JSON.stringify(bodyObj);
              }
            } catch (e) {
              // Body 不是 JSON，忽略
            }
          }
        }
      }
    }
    
    return originalFetch.call(this, input, init);
  };
})();

// --- 2. 懒加载 JavaScript 模块 ---
function lazyLoadScript(src, id) {
  return new Promise((resolve, reject) => {
    if (document.getElementById(id)) {
      resolve();
      return;
    }
    const script = document.createElement('script');
    script.src = src;
    script.id = id;
    script.defer = true;
    script.onload = () => {
      console.log(`[ModeController] 成功加载模块: ${src}`);
      resolve();
    };
    script.onerror = (err) => {
      console.error(`[ModeController] 模块加载失败: ${src}`, err);
      reject(err);
    };
    document.body.appendChild(script);
  });
}

// --- 3. 模式切换核心逻辑 ---
window.setMode = function(mode, updateHash = true) {
  if (mode === window.currentMode) return;
  
  console.log(`[ModeController] 切换模式: ${window.currentMode} -> ${mode}`);
  window.currentMode = mode;
  
  // 更新导航选项卡 UI
  document.querySelectorAll('.mode-tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.mode === mode);
  });
  
  if (updateHash) {
    window.location.hash = `#/${mode}`;
  }
  
  // 执行具体的切页及按需加载
  if (mode === 'longform') {
    // 隐藏短文与桥接容器
    const sfPage = document.getElementById('page-shortform');
    const bridgePage = document.getElementById('page-bridge');
    if (sfPage) {
      sfPage.classList.remove('active');
      sfPage.style.display = 'none';
    }
    if (bridgePage) {
      bridgePage.classList.remove('active');
      bridgePage.style.display = 'none';
    }
    
    // 恢复长文的侧边栏与页面
    document.querySelectorAll('.sidebar .nav-item').forEach(el => {
      el.style.display = '';
    });
    
    // 调用 legacy_bundle 的 switchPage 回到之前激活的页面，默认 chat
    if (typeof window.switchPage === 'function' && typeof window.getCurrentPageName === 'function') {
      window.switchPage(window.getCurrentPageName() || 'chat');
    } else {
      const defaultPage = document.getElementById('page-chat');
      if (defaultPage) {
        defaultPage.classList.add('active');
        defaultPage.style.display = 'flex';
      }
    }
    
    // 触发长文历史加载，刷新列表
    if (typeof window.loadHistory === 'function') {
      window.loadHistory();
    }
  } 
  else if (mode === 'shortform') {
    // 隐藏所有长文页面及桥接页面
    document.querySelectorAll('.main-workspace > .page').forEach(p => {
      if (p.id !== 'page-shortform') {
        p.classList.remove('active');
        p.style.display = 'none';
      }
    });
    
    const sfPage = document.getElementById('page-shortform');
    if (sfPage) {
      sfPage.classList.add('active');
      sfPage.style.display = 'flex';
    }
    
    // 隐藏长文独有的侧边栏入口 (只留下历史记录)
    document.querySelectorAll('.sidebar .nav-item').forEach(el => {
      if (el.dataset.page !== 'history') {
        el.style.display = 'none';
      } else {
        el.style.display = '';
      }
    });
    
    // 加载并初始化短文模块
    lazyLoadScript('js/shortform_module.js?v=1', 'script-shortform-module')
      .then(() => {
        if (typeof window.initShortformModule === 'function') {
          window.initShortformModule();
        }
      });
  } 
  else if (mode === 'bridge') {
    // 隐藏所有长文页面及短文页面
    document.querySelectorAll('.main-workspace > .page').forEach(p => {
      if (p.id !== 'page-bridge') {
        p.classList.remove('active');
        p.style.display = 'none';
      }
    });
    
    const bridgePage = document.getElementById('page-bridge');
    if (bridgePage) {
      bridgePage.classList.add('active');
      bridgePage.style.display = 'flex';
    }
    
    // 隐藏长文侧边栏入口 (同样保留历史记录)
    document.querySelectorAll('.sidebar .nav-item').forEach(el => {
      if (el.dataset.page !== 'history') {
        el.style.display = 'none';
      } else {
        el.style.display = '';
      }
    });
    
    // 加载并初始化桥接模块
    lazyLoadScript('js/bridge_panel.js?v=1', 'script-bridge-panel')
      .then(() => {
        if (typeof window.initBridgePanel === 'function') {
          window.initBridgePanel();
        }
      });
  }
};

// --- 4. 路由哈希变化解析 ---
function handleHashRouting() {
  const hash = window.location.hash;
  if (hash === '#/shortform') {
    window.setMode('shortform', false);
  } else if (hash === '#/bridge') {
    window.setMode('bridge', false);
  } else {
    window.setMode('longform', false);
  }
}

// 首次加载或刷新时路由解析
document.addEventListener('DOMContentLoaded', () => {
  handleHashRouting();
});
