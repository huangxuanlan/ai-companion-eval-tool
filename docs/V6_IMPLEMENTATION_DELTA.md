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
| D4 | 前端 mode 切换 | 复用 longform `index.html` + Tab + URL hash（ADR-007） | 一致 | 🟢 一致 | ✅ 完成 |
| D5 | 短文前端规范 | v1.8 §附录 B 仅作 UI mock 参考 | 已实现独立 `page-shortform` 子工具，复用部分规范 | 🟡 部分采纳 | 📌 待 PM 审 |
| D6 | scoring 端点拆分 | 长文 v5.9 / 短文 v1.8 各自独立 | scoring.py 单文件承载 30+ 端点（长短共用） | 🟡 待重构 | 📋 v6.x 跟踪 |
| D7 | 桥接 scenarios tags | API v0.1 §2.6 含 `tags` 字段 | 实现未提供 `tags`（保留 `name` + `phases`） | 🟢 兼容 | 📌 v6.1 补 |

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

### D5: 短文前端规范（部分采纳）

**PRD 期望**：README ADR-007 「短文 v1.8 §附录 B 前端规范仅作 UI mock 参考，不作为重写依据」。

**实际实施**：
- ✅ 复用 `index.html` + 顶部 Tab（一致）
- ✅ URL hash 路由（`#shortform` / `#bridge`）（一致）
- ✅ Fetch 拦截器自动注入 `mode` 参数（一致）
- ✅ 独立 `page-shortform` 子工具结构（5 个子 Tab：用例库 / 运行台 / 任务监控 / 对比报告 / 基准对比）
- ⚠️ 短文 v1.8 §附录 B 的 Reset 按钮、对话历史栈视图未完整实现（取决于业务优先级）

**建议**：在短文 v1.8 §附录 B 加注脚说明 v6.0 实施差异。

### D6: scoring router 拆分（v6.x 跟踪）

**当前状况**：`server/routers/scoring.py` 共 2000+ 行，承载 30+ 端点（长文 / 短文 / 桥接共用）。

**潜在风险**：随 v6.x 业务扩展可能成为单点。

**建议**：v6.1+ 按 mode 拆分（`scoring_longform.py` / `scoring_shortform.py` / `scoring_shared.py`），但需评估对前端调用路径的影响。

### D7: 桥接 scenarios tags（v6.1 补）

**PRD 期望**：API v0.1 §2.6 Response schema 中含 `tags: ["核心路径", "异质包夹"]`。

**实际实施**：`define_scenarios` 函数返回 `{name, phases}`，未含 `tags`。

**影响**：低 — 前端可基于 name 推导分类。

**建议**：v6.1 在 `verify_mode_switching.py:define_scenarios` 内补 `tags` 字段，向后兼容。

---

## 3. 等级说明

- 🟢 **一致 / 增强**：实施≥PRD，无后续动作
- 🟡 **部分采纳 / 兼容**：差异已记录，需 PM 审批是否回写 PRD 或安排 v6.x 跟进
- 🔴 **冲突**：实施与 PRD 不一致且无兼容路径（本表无此项）

## 4. 后续动作

| 偏差 ID | 推荐动作 | Owner | 时机 |
|--------|---------|-------|------|
| D5 | PM 审批 → 回写短文 v1.8 §附录 B 注脚 | PM | v6.0 复盘会 |
| D6 | 评估 scoring router 拆分 ROI | 后端 lead | v6.1 sprint planning |
| D7 | `define_scenarios` 补 `tags` 字段 | 后端 | v6.1 |

## 5. 关联资产

- 测试日志：`output/test_v6_full/stage{0,1}_*_pytest.log`
- Migration 脚本：`scripts/migrate_db_rename.py`
- Lib 索引：`server/lib/__init__.py`
