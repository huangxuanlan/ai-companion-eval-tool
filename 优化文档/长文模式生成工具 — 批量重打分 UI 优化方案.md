# 长文模式生成工具 — 批量重打分 UI 优化方案

## 问题诊断

用户反馈三个核心痛点：
1. **不知道是否已开始** — 点击按钮后没有足够醒目的即时反馈
2. **没有进度感知** — 进度面板位于表格上方，滚动后不可见
3. **无法区分已打分/未打分** — 评分状态指示不够清晰、不持久

## 现有代码分析

| 模块 | 现状 | 问题 |
|------|------|------|
| 进度面板 `history-batch-rescore-progress` | 存在，有进度条、计数器、成功/失败徽章 | 位置固定在表格上方，滚动后不可见；无取消功能；无预估时间 |
| 行级状态 `_batchRescoreRowStatus` | 内存 Map，支持 `pending/scoring/success/failed` | 页面刷新后丢失；成功/失败动画 1.6s 后消失 |
| 分数列 `history-score-cell` | 有 `score-chip-scoring`(脉冲动画) 和 `score-chip-unscored`(斜体灰字) | 脉冲动画太微弱；"待打分"样式不够醒目；已评分无视觉强化 |
| 全选功能 | 无 | 无法一键勾选所有记录 |
| 评分筛选 | 有最低分/最高分数值筛选 | 无"未打分/已打分"快速筛选 |

## 调研总结

### 行业最佳实践（联网搜索 + KI 知识库）

| 设计原则 | 来源 | 应用方式 |
|----------|------|---------|
| **确定性进度条** | NNGroup / LogRocket / Apple HIG | 长任务必须用 determinate bar，禁用 spinner 独占 |
| **非阻塞工作流** | SaaS Dashboard 共识 | 进度面板应 sticky/floating，用户可继续操作 |
| **行级即时反馈** | Material Design / Eleken | 正在处理的行用背景色+行内 spinner；完成后用绿色对勾持久标记 |
| **Contextual Action Bar** | UXDWorld / Medium | 选中行后才显示操作栏；操作栏显示已选数量 |
| **微交互 100-300ms** | 前端设计审查 D7 | 状态切换动画 ≤300ms ease-out；尊重 `prefers-reduced-motion` |
| **触控目标 ≥48dp** | WCAG 2.2 / HIG | checkbox 和按钮需满足最小点击区域 |
| **5 秒法则** | Dashboard 最佳实践 D11 | 用户进入页面 5 秒内应能判断当前状态 |

### GitHub 高星项目参考

| 项目/库 | 关键设计模式 |
|---------|------------|
| **Shadcn UI** (60k+ ⭐) | Toast 组件 — 底部浮动通知，支持 action button + 自动消失 |
| **Ant Design** (93k+ ⭐) | Table 行选择 + 批量操作栏 + Progress 组件 |
| **Linear** (产品) | 批量操作后底部浮动进度条 + 行级状态标记 + 操作完成后 undo |
| **Vercel Dashboard** | 部署状态用色彩编码圆点（绿/黄/红/灰）+ 行级动画 |
| **Notion** | 批量操作选中后顶部蓝色操作栏 + 进度 toast |

---

## 设计方案：6 项优化

### 优化 1：浮动进度通知条（Floating Progress Bar）⭐ 核心

> **解决**：不知道是否开始 + 没有进度感知

**设计**：在视口底部固定一个浮动进度通知条，批量重打分启动后立即显示，全程可见。

```
┌──────────────────────────────────────────────────────────────┐
│ ⏳ 批量重打分: 3/10 完成 (2✓ 1✗)   ████████░░░░ 30%   [取消] │
│ ▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │
└──────────────────────────────────────────────────────────────┘
```

**交互细节**：
- **位置**：`position: fixed; bottom: 24px; left: 50%` — 水平居中浮动
- **出现时机**：用户确认对话框点击"确认重打分"的瞬间
- **入场动画**：`translateY(100%) → translateY(0)` + `opacity 0→1`，300ms ease-out
- **内容**：
  - 左侧：spinner + 标题文字 + 计数器 `3/10`
  - 中间：确定性进度条（determinate）
  - 右侧：取消按钮
  - 完成后：标题变为 `✅ 批量重打分完成` / `⚠️ 部分失败`，取消→关闭
- **完成后**：自动 8 秒后淡出，或用户点击关闭
- **样式**：glassmorphism 风格 — `backdrop-filter: blur(16px)` + 深色半透明背景 + 圆角 16px + 阴影

#### [MODIFY] [index.html](file:///e:/提效工具/长文模式生成/server/static/index.html)
- 在 `</body>` 前追加浮动进度条 HTML 容器

#### [MODIFY] [main.css](file:///e:/提效工具/长文模式生成/server/static/css/main.css)
- 新增 `.batch-rescore-float-bar` 系列样式

#### [MODIFY] [legacy_bundle.js](file:///e:/提效工具/长文模式生成/server/static/js/legacy_bundle.js)
- 修改 `batchRescoreSelectedHistoryConversations()` 在确认后立即显示浮动条
- 新增 `showBatchRescoreFloatBar()` / `updateBatchRescoreFloatBar()` / `hideBatchRescoreFloatBar()` 函数
- 新增取消功能 `cancelBatchRescore()` — 设置 `_batchRescoreCancelled` flag

---

### 优化 2：持久化行级评分状态标记 ⭐ 核心

> **解决**：怎么知道哪些已经重打分或者没有打分

**设计**：在分数列用色彩编码的状态 Chip 持久标记评分状态，不依赖内存 Map。

| 状态 | 样式 | 触发条件 |
|------|------|---------|
| **已评分** | `7.8` 绿色粗体 + 小绿点 | `score_avg` 有值且 `scored_turns > 0` |
| **打分中** | 🔵 蓝色脉冲 + "打分中…" | `_batchRescoreRowStatus` === `scoring` |
| **打分失败** | 🔴 红色 + "✗ 失败" + 重试按钮 | `failed_turns > 0` 且无有效均分 |
| **待打分** | ⚪ 灰色虚线圆 + "待打分" | `status === completed` 且无 `score_avg` |
| **部分完成** | 🟡 黄色 + 分数 + `3/10` | 有 `score_avg` 但 `scored_turns < total_turns` |
| **不适用** | `—` 灰色 | `status !== completed` |

**视觉设计**：
```
[●  7.8]     — 绿色圆点 + 粗体分数（全部评分完成）
[● 6.2 ⚠3/10] — 黄色圆点 + 分数 + 部分完成标记
[◌ 待打分]    — 灰色虚线圆 + 斜体灰字
[⟳ 打分中…]   — 蓝色旋转 + 脉冲文字
[✗ 失败]      — 红色 + 可点击重试
```

#### [MODIFY] [legacy_bundle.js](file:///e:/提效工具/长文模式生成/server/static/js/legacy_bundle.js)
- 重构 `renderHistory()` 中的 `scoreCellHtml` 生成逻辑
- 新增 `buildScoreStatusChip()` 辅助函数

#### [MODIFY] [main.css](file:///e:/提效工具/长文模式生成/server/static/css/main.css)
- 新增 `.score-status-dot`、`.score-status-chip` 等样式
- 增强 `.score-chip-scoring` 加入 inline spinner

---

### 优化 3：表头全选 Checkbox

> **提升效率**：当前必须逐条勾选

**设计**：在表头"选择"列添加全选 checkbox，支持：
- 勾选 → 选中当前筛选结果中的所有行
- 取消 → 清空所有选择
- 部分选中时显示 indeterminate 状态

#### [MODIFY] [index.html](file:///e:/提效工具/长文模式生成/server/static/index.html)
- 将 `<th>选择</th>` 改为 `<th><input type="checkbox" id="history-select-all"></th>`

#### [MODIFY] [legacy_bundle.js](file:///e:/提效工具/长文模式生成/server/static/js/legacy_bundle.js)
- 新增 `toggleSelectAllHistory()` 函数
- 在 `renderHistory()` 末尾同步全选框状态

---

### 优化 4：评分状态快速筛选按钮

> **解决**：快速找出未打分的记录

**设计**：在筛选栏下方或旁边添加一组 pill 按钮：

```
[全部] [✅ 已打分] [⬜ 未打分] [❌ 打分失败]
```

- 点击后快速筛选历史表格
- 与现有筛选条件叠加

#### [MODIFY] [index.html](file:///e:/提效工具/长文模式生成/server/static/index.html)
- 在筛选栏后追加快速筛选 pill 按钮组

#### [MODIFY] [legacy_bundle.js](file:///e:/提效工具/长文模式生成/server/static/js/legacy_bundle.js)
- 新增 `setScoreQuickFilter()` 函数
- 修改 `filterHistoryItems()` 支持评分状态维度

---

### 优化 5：自动滚动到进度区域 + 确认启动 Toast

> **解决**：不知道是否已开始

**设计**：
1. 确认后立即弹出成功 Toast："✅ 已开始批量重打分 (10 条记录)"
2. 同时 smooth scroll 到进度面板位置（如果在历史页面）
3. 浮动进度条同步出现

#### [MODIFY] [legacy_bundle.js](file:///e:/提效工具/长文模式生成/server/static/js/legacy_bundle.js)
- 在 `batchRescoreSelectedHistoryConversations()` 确认后添加 Toast + scrollIntoView

---

### 优化 6：进度面板增强（Sticky + 取消 + 预估时间）

> **提升**：让原有进度面板更实用

**设计**：
1. 进度面板改为 `position: sticky; top: 0`，滚动时始终可见
2. 添加取消按钮
3. 显示预估剩余时间（基于已完成任务的平均耗时）
4. 完成后显示总耗时

#### [MODIFY] [index.html](file:///e:/提效工具/长文模式生成/server/static/index.html)
- 在进度面板内添加取消按钮 + 预估时间 span

#### [MODIFY] [main.css](file:///e:/提效工具/长文模式生成/server/static/css/main.css)
- `.history-batch-rescore-progress` 添加 `position: sticky; top: 0; z-index: 10`

#### [MODIFY] [legacy_bundle.js](file:///e:/提效工具/长文模式生成/server/static/js/legacy_bundle.js)
- 新增 `_batchRescoreStartTime` 变量
- 在 `updateBatchRescoreProgress()` 中计算预估时间
- 新增 `cancelBatchRescore()` 函数

---

## 改动文件汇总

| 文件 | 改动量 | 涉及优化项 |
|------|--------|-----------|
| `server/static/index.html` | ~30 行 | 1,3,4,6 |
| `server/static/css/main.css` | ~120 行 | 1,2,6 |
| `server/static/js/legacy_bundle.js` | ~200 行 | 1,2,3,4,5,6 |

## 优先级排序

| 优先级 | 优化项 | 理由 |
|--------|--------|------|
| **P0** | 优化 1：浮动进度条 | 直接解决"不知道是否开始 + 无进度"两大核心痛点 |
| **P0** | 优化 2：持久化评分状态 | 直接解决"无法区分已打分/未打分" |
| **P1** | 优化 5：启动 Toast + 自动滚动 | 增强即时反馈，实现简单 |
| **P1** | 优化 3：全选 Checkbox | 高频操作效率提升 |
| **P2** | 优化 4：评分快速筛选 | 方便查找目标记录 |
| **P2** | 优化 6：进度面板增强 | 锦上添花 |

## 验证计划

### 浏览器测试
1. 启动 `python server/main.py`
2. 打开历史记录页，勾选多条记录
3. 验证浮动进度条出现 + 行级状态变化 + 完成后持久标记
4. 刷新页面后验证评分状态仍正确显示
5. 测试全选/取消全选
6. 测试评分快速筛选
7. 测试取消功能

### 回归测试
```bash
cd 长文模式生成 && pytest test_v51_regression.py -v
```

> [!IMPORTANT]
> 所有改动均为前端纯 UI 层（HTML/CSS/JS），不涉及后端 API 和数据库，风险可控。评分状态的判断完全基于已有的 `score_avg` / `scored_turns` / `failed_turns` 等字段，无需新增后端接口。
