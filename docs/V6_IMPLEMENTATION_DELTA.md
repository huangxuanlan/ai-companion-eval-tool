# 双模式融合工具 v6.0 实施差异文档

> 维护：开发团队 / 最后更新：2026-05-28
> 用途：记录 v6.0 实际实施与 PRD 文档（README v2.4 / 桥接 API v0.1 / 短文 PRD v1.8 / 长文 PRD v5.9）的偏差点
> 状态：F4 补齐输出 / Stage 3 测试报告输入 / 待 PM 审批后回写各 PRD 章节

---

## 1. 偏差矩阵速览

| ID | 模块 | PRD 期望 | 实际实施 | 偏差等级 | 状态 |
|----|------|---------|---------|---------|------|
| D1 | DB 命名 | `ops_v6.db`（README ADR-001） | `longform.db`（生产保留）+ `ops_v6.db`（hardlink） | 🟡 兼容 | ✅ 已对齐 |
| D2 | 共享 library | `server/lib/` 4 个 lib（ADR-005） | 4 个 lib 已抽取 + services shim 保留向后兼容 | 🟢 一致 | ✅ 完成 |
| D3 | 桥接端点数 | 8 个（API v0.1 §1.0） | 9 个（新增 `GET /scenarios`） | 🟢 增强 | ✅ F3 补齐 |
| ~~D4~~ | ~~前端 mode 切换~~ | ~~复用 longform `index.html` + Tab + URL hash（ADR-007）~~ | ~~一致~~ | � **原判推翻** | **2026-05-28 复审合并到 D11** |
| ~~D5~~ | ~~短文前端规范~~ | ~~v1.8 §附录 B 仅作 UI mock 参考~~ | ~~已实现独立 `page-shortform` 子工具~~ | � **原判推翻** | **2026-05-28 复审误判，合并到 D11** |
| D6 | scoring 端点拆分 | 长文 v5.9 / 短文 v1.8 各自独立 | scoring.py 单文件承载 30+ 端点（长短共用） | 🟡 待重构 | 📋 v6.x 跟踪 |
| D7 | 桥接 scenarios tags | API v0.1 §2.6 含 `tags` 字段 | 实现未提供 `tags`（保留 `name` + `phases`） | 🟢 兼容 | 📌 v6.1 补 |
| **D11** | **F4 前端融合整体未接入**（2026-05-28 复审发现） | ADR-007 顶部 3 Tab + script 引用 + page-shortform/page-bridge 容器 + setMode 生效 | **0% 实施**：index.html 未改 + 5 个新文件 100% untracked + DOM 全部缺失 | 🔴 **严重** | ✅ v6.0 cd7f186+1 清理死代码，F4 顺延 v6.1 |

---

## 2. 偏差详述

### D1: DB 命名兼容（已对齐）

**PRD 期望**：README v2.4 ADR-001 要求 v6.0 起使用 `ops_v6.db` 作为新 DB 文件名。

**实际实施**：
- 物理文件保留 `server/longform.db`（404 MB 生产数据）
- 创建 hardlink `server/ops_v6.db` 指向同一 inode（零复制）
- `config.py:DB_PATH` 默认值切到 `ops_v6.db`
- 双环境变量兼容：`OPS_V6_DB_PATH`（新）> `LONGFORM_DB_PATH`（旧）
- 一次性 migration 脚本：`scripts/migrate_db_rename.py`（幂等 + 可回滚）

**结论**：100% 等价于 PRD 期望，且零迁移成本、零生产风险。

### D2: 共享 library 抽取（已完成）

**PRD 期望**：ADR-005 在 `server/lib/` 下抽 4 个共享 library。

**实际实施**（每步均有回归测试 356/359 PASS）：
| Lib | 源文件 | 目标 | 行数 |
|-----|-------|------|------|
| `format_lint_lib` | `services/format_lint_core.py` | `lib/format_lint_lib/core.py` | 102 |
| `model_adapter_lib` | `services/model_adapter.py` + `local_openai_provider.py` | `lib/model_adapter_lib/{adapter,openai_provider}.py` | ~700 |
| `prompt_template_lib` | `services/prompt_service.py` + `prompt_version_service.py` | `lib/prompt_template_lib/{service,version}.py` | ~1230 |
| `prompt_scoring_lib` | `services/scoring_service.py` + `live_scoring_dispatcher.py` | `lib/prompt_scoring_lib/{service,dispatcher}.py` | ~2480 |

**关键技术**：所有 services shim 用 `sys.modules` 别名替换技巧，让 `monkeypatch.setattr(services.local_openai_provider, "OpenAI", FakeOpenAI)` 真的作用到 lib 生产代码（避免 re-export shim 失效）。

```python
# server/services/local_openai_provider.py（shim 模板）
import sys as _sys
from lib.model_adapter_lib import openai_provider as _real_module
_sys.modules[__name__] = _real_module
```

### D3: 桥接端点数（F3 补齐）

**PRD 期望**：API v0.1 §1.0 列出 8 个端点。

**实际实施**：新增 `GET /api/bridge/scenarios`（共 9 个）。

**新增端点签名**：
```
GET /api/bridge/scenarios?sf_turns=5&lf_turns=12
→ {
    "scenarios": [...],          # 复用 scripts/verify_mode_switching.define_scenarios
    "ab_configs": {
      "baseline":  {"label": "线上基线", "bridge_turns": 20, "summary_interval": 10},
      "optimized": {"label": "优化方案", "bridge_turns": 10, "summary_interval": 5}
    },
    "params": {"sf_turns": 5, "lf_turns": 12}
  }
```

**测试**：`tests/unit/test_bridge_api.py::test_get_scenarios_*` 共 3 个用例 PASS。

### D5～D4: 短文前端规范（原判推翻—合并到 D11）

> **2026-05-28 复审结论**：原 D4「前端 mode 切换 🟢 一致」与原 D5「短文为独立 page 🟡 部分采纳」都是误判。实际 v6.0 cd7f186 提交未动 `index.html`，5 个新增前端文件 100% untracked，未被静态 HTML 引用，DOM 容器不存在，**F4 前端融合实际是 0% 实施**（详见 D11）。

**PRD 期望**：README ADR-007 「短文 v1.8 §附录 B 前端规范仅作 UI mock 参考，不作为重写依据」。

**实际实施**：
- ✅ 复用 `index.html` + 顶部 Tab（一致）
- ✅ URL hash 路由（`#shortform` / `#bridge`）（一致）
- ✅ Fetch 拦截器自动注入 `mode` 参数（一致）
- ✅ 独立 `page-shortform` 子工具结构（5 个子 Tab：用例库 / 运行台 / 任务监控 / 对比报告 / 基准对比）
- ⚠️ 短文 v1.8 §附录 B 的 Reset 按钮、对话历史栈视图未完整实现（取决于业务优先级）

**建议**：~~在短文 v1.8 §附录 B 加注脚说明 v6.0 实施差异~~ → **原判误判，D5 推翻。与 D11 合并处理：v6.0 不需回写 PRD，v6.1 全新实施 F4 后达成 ADR-007 一致。**

### D6: scoring router 拆分（v6.x 跟踪）

**当前状况**：`server/routers/scoring.py` 共 2000+ 行，承载 30+ 端点（长文 / 短文 / 桥接共用）。

**潜在风险**：随 v6.x 业务扩展可能成为单点。

**建议**：v6.1+ 按 mode 拆分（`scoring_longform.py` / `scoring_shortform.py` / `scoring_shared.py`），但需评估对前端调用路径的影响。

### D11: F4 前端融合整体未接入（2026-05-28 复审发现 · 严重）

**发现背景**：v6.0 复审中深调 D5（原判「短文独立化」）时，在验证 ADR-007 「复用同一组组件」原则后发现：不仅 D5 是误判，**整个 F4 前端融合都从来没有被接入 `index.html`**。

**铁证三连**：

1. **git 层**：`git diff cd7f186^ cd7f186 --stat -- server/static/` 返回空输出、`git ls-files server/static/js/mode_controller.js` 报 `did not match any file` — v6.0 提交完全未动前端。
2. **文件层**：5 个新增前端文件（`mode_controller.js` / `shortform_module.js` / `bridge_panel.js` / `shortform.css` / `bridge.css`）在 `git status --short` 中全部是 `??`（untracked）。
3. **HTML 层**：`index.html` 全文 grep `shortform` / `bridge` / `mode_controller` / `page-shortform` / `mode-tab-btn` 都返回 **0 处匹配**；DOM 容器从未被创建。

**影响**：

- 用户打开 `http://127.0.0.1:8000/` 看到的仍是纯长文 5 page UI（chat / freechat / history / test-center / prompts），未感受到 v6.0 任何前端融合变化。
- `V6_TEST_REPORT §4.2` 原标 13/13 PASS 是测试方法学错误：把「文件能通过 HTTP `/static/...` 返回 200」误等于「前端已接入」。
- ADR-006 桥接 5 区视图 · ADR-007 顶部 3 Tab · setMode 路由 · fetch 拦截器 · mode 隐含注入 五个关键能力都未生效。

**v6.0 cd7f186+1 处置**（本次提交）：

1. 删除 5 个 untracked 死代码文件（避免将来被误读为「已实施」）。
2. 修正 `V6_TEST_REPORT §4.2 / §4.4.1 / §6 / §9 / §10` 虚假声明。
3. 使 v6.0 GA 声明限定为「**后端融合 100%；ADR-007 前端顺延 v6.1**」。

**v6.1 sprint backlog**（预估 5-7 人天）：

- 在 `index.html` 添加顶部 3 Tab DOM（`<nav class="mode-tabs">`）与 script/link 引用。
- 重写 mode_controller.js，**按 ADR-007**「复用同一组组件」原则让长文 5 page 根据 `window.currentMode` 动态适配 UI 配置（字数限制 / 括号规则 / 默认模型）。
- 重写 bridge_panel.js + page-bridge 独立容器（ADR-006 允许）。
- 不使用独立 `page-shortform` 容器（避免重犯 D5 原型错误）。
- 补 Playwright E2E 三模式 UI 冒烟（避免“文件 200 = 接入”误判再现）。

**测试设计教训**：HTTP 探测 `/static/...` 能 200 不能证明前端已接入。必须同时验证：

- index.html 静态 grep 含 script/link 引用。
- DOM 容器可被 Playwright `page.locator('#xxx').count() > 0` 抢到。
- setMode / fetch 拦截器在 console 有预期日志。

### D7: 桥接 scenarios tags（v6.1 补）

**PRD 期望**：API v0.1 §2.6 Response schema 中含 `tags: ["核心路径", "异质包夹"]`。

**实际实施**：`define_scenarios` 函数返回 `{name, phases}`，未含 `tags`。

**影响**：低 — 前端可基于 name 推导分类。

**建议**：v6.1 在 `verify_mode_switching.py:define_scenarios` 内补 `tags` 字段，向后兼容。

---

## 3. 等级说明

- 🟢 **一致 / 增强**：实施≥PRD，无后续动作
- 🟡 **部分采纳 / 兼容**：差异已记录，需 PM 审批是否回写 PRD 或安排 v6.x 跟进
- 🔴 **冲突 / 严重未实施**：实施与 PRD 不一致且无兼容路径（2026-05-28 复审从 0 项增加 D11 本项）

## 4. 后续动作

| 偏差 ID | 推荐动作 | Owner | 时机 |
|--------|---------|-------|------|
| ~~D5~~ | ~~PM 审批 → 回写短文 v1.8 §附录 B 注脚~~ | ~~PM~~ | 🔴 **原判误判推翻，合并到 D11** |
| **D11** | **清理 5 个 untracked 死代码 + 修正测试报告 + 顺延 v6.1** | 前端 + QA | ✅ v6.0 cd7f186+1 本提交 |
| D6 | 评估 scoring router 拆分 ROI | 后端 lead | v6.1 sprint planning |
| D7 | `define_scenarios` 补 `tags` 字段 | 后端 | v6.1 |
| **F4 重做** | **全新实施 ADR-007 前端融合 + Playwright E2E 真验证**（5-7 人天）| 前端 + QA | v6.1 sprint |

## 5. 关联资产

- 测试日志：`output/test_v6_full/stage{0,1}_*_pytest.log`
- Migration 脚本：`scripts/migrate_db_rename.py`
- Lib 索引：`server/lib/__init__.py`
