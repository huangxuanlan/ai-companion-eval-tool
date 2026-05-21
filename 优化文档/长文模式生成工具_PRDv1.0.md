# 长短文统一验证工具 PRD v1.0

> **前版**：v0.2 (2026-05-11)，保留于同目录作为历史存档
> **本版**：按「轻量 PRD + 可验证需求」（Atlassian/ISO 29148）重写，融合长文已有功能 + 短文 PRD v1.0
> **排除项**：模式切换首轮防 RSO 不纳入本版

---

## §1 目的与范围

### 1.1 产品定位

面向 AI 提示词工程师的**本地统一验证工具**，在同一套链路中验证长文、短文、混合切换路径的真实表现。

### 1.2 目标用户与收益

| 用户 | 收益 |
|:---|:---|
| 提示词工程师 | 一个工具覆盖所有模式的提示词迭代、A/B 对比、批量回归 |
| QA | 确定性校验 + LLM 评分双层质量门禁，可导出 Excel 证据 |
| 产品经理 | 通过对比报告量化提示词版本的质量差异 |

### 1.3 范围

**In**：
- Web UI 对话体验（即时试针）+ 测试中心（批量任务编排）+ 历史记录
- CLI 批量入口（`longform_multi_turn.py --mode <mode>`）
- 日志复放（短文 `systemPrompt + prompt` 双字段结构）
- 提示词 A/B/C 对比 + 缓存隔离
- 确定性校验（9 项）+ LLM-as-Judge 评分（长文 5 维 / 短文 6 维）
- Excel/JSON 导出

**Out**：
- 不做生产发布、灰度分流、线上配置下发
- 不替代 promptfoo-pipeline
- 不默认改写原始日志和提示词文件
- 不包含产品侧实现规则（摘要触发/画像抽取/违规重写等，由 v5.4 融合文档负责）

### 1.4 假设与约束

| 约束 | 说明 |
|:---|:---|
| 消息拼接权威来源 | 长文：`问题排查——长文/` 目录；短文：`问题排查——短文/` 目录 |
| 短文请求结构 | 线上采用 `systemPrompt + prompt` 双字段，非单一 `messages` 数组 |
| 模式是一级变量 | 所有功能按 `longform / shortform / switch_*` 四路路由 |
| CLI 与 Web 共享引擎 | 不维护两套拼接逻辑 |
| 字数不硬编码 | 长文 300-500 / 短文 30-90，均为用例级配置 |

---

## §2 用户故事与验收标准

### US-01 即时对话体验
**作为**提示词工程师，**我想**在 Web UI 中选择模式和提示词版本后即时对话，**以便**快速感知输出质量。
- AC：选择 `longform` / `shortform` 后首轮出文，消息结构符合对应架构

### US-02 多轮链式测试
**作为**提示词工程师，**我想**配置 N 轮链式对话自动跑完，**以便**观察长上下文退化。
- AC：`--turns 10` 跑完 10 轮，每轮输出含 word_count / tokens / latency

### US-03 日志复放
**作为** QA，**我想**导入线上问题排查日志原样复放，**以便**复现线上问题。
- AC：导入 `.md` / `.json` 后成功解析 `systemPrompt=1` + `prompt=40/41`；Id/id 不冲突

### US-04 提示词 A/B 对比
**作为**提示词工程师，**我想**同一批样本对比 2-3 个提示词版本，**以便**量化版本差异。
- AC：同 case 的 `prompt` 历史 hash 相同，`systemPrompt` hash 不同；默认缓存隔离

### US-05 批量回归
**作为** QA，**我想**从 Excel/JSONL 导入测试集一键跑完，**以便**回归验证。
- AC：批量结果可导出 Excel，含 30+ 列

### US-06 确定性校验
**作为**提示词工程师，**我想**输出先经过规则检查再做 LLM 评分，**以便**快速定位格式问题。
- AC：9 项检查全部执行（字数/格式/角色名/关系边界/记忆纪律/重复率/禁词/Emoji/人称）

### US-07 LLM 打分
**作为**提示词工程师，**我想**对输出做多维 LLM 评分，**以便**量化质量。
- AC：长文 5 维 / 短文 6 维评分输出 JSON，含 `total_score` + `dimension_scores`

### US-08 对比报告
**作为**产品经理，**我想**看到 A/B 输出并排 + 维度雷达 + 胜负判定，**以便**决策。
- AC：报告含胜出方、分差、hard_fail 标记

### US-09 请求详情审查
**作为**提示词工程师，**我想**查看原始日志、替换后请求、有效请求体的 diff，**以便**定位拼接问题。
- AC：展示 `original_request` / `effective_request` / diff

### US-10 提示词版本管理
**作为**提示词工程师，**我想**上传/粘贴提示词并保存版本、查看 diff、回滚，**以便**管理迭代。
- AC：支持完整替换 / 局部覆盖（需生成 diff）/ 原样复放 三种模式

### US-11 多模型适配
**作为**提示词工程师，**我想**在 Qwen / DeepSeek / Gemma / 本地模型间切换，**以便**对比模型表现。
- AC：通过 `model_adapter.py` 配置，支持 API key 轮转

### US-12 Dry-run 消息审查
**作为**开发者，**我想**用 `--dry-run` 只打印消息结构不调用 API，**以便**验证拼接正确性。
- AC：打印完整 messages 数组，变量无残留 `{{}}`

---

## §3 功能清单

### 3.1 对话体验（Web UI）
- 即时对话 + 流式输出（WebSocket）
- 模式选择（四类）
- 提示词版本切换
- 消息详情查看（原始/有效/diff）
- 摘要状态实时显示

### 3.2 测试中心（批量 + CLI）
- CLI 入口：`longform_multi_turn.py --mode <mode> --turns N`
- 支持 `--dry-run` 模式
- 批量任务编排：case × variant × repeat
- 任务队列 + 并发控制（自适应限流）
- 进度实时推送

### 3.3 日志复放与 A/B 对比
- 导入格式：`.md` / `.json` / JSONL / Excel
- 短文双字段解析（`systemPrompt` + `prompt` 二次 JSON 解析）
- A/B/C 版本隔离（默认禁用 `contextId/cacheId`）
- 胜负判定：明确胜出(≥0.3) / 不显著(<0.3) / 失败(hard_fail) / 需复跑

### 3.4 打分与质量门禁
- **确定性校验**（详见 §5.1）
- **LLM-as-Judge 评分**（详见 §5.2）
- 打分提示词版本化（`VersionedPromptStore`）
- 打分模型可切换 + thinking effort 可调
- 评分报告自动生成（总体统计/维度分析/Top3 优差/优化建议）

### 3.5 导出与历史
- JSON 日志：每轮 `user_input` / `ai_output` / `word_count` / tokens / latency / mode
- Excel 导出：30+ 列全量（详见 §6.3）
- 对话历史持久化（SQLite）
- 对比报告导出

### 3.6 提示词管理
- 版本化存储（对话/打分/报告三类提示词独立管理）
- 在线编辑 + diff 查看
- 版本回滚
- Few-shot 示例库管理

### 3.7 模型适配
- 统一适配层（`model_adapter.py`）
- 支持：Qwen / DeepSeek / Gemma / 本地 OpenAI 兼容 / Google Gemini
- API key 池 + 轮转
- 自适应并发降级（429 自动减半）

---

## §4 消息架构合同

> **权威来源**：长文拼接见 `问题排查——长文/` 目录，短文拼接见 `问题排查——短文/` 目录。
> 以下为精简规范，冲突时以权威来源为准。

### 4.1 四类模式消息层级

| 模式 | messages[0] system | messages[1] | messages[2+] | messages[N] user |
|:---|:---|:---|:---|:---|
| `longform` | L0-L4 全量 Consolidated Single-Block | assistant: 7字段摘要 | 最近10轮历史 | `<Core_Constraints>CC</Core_Constraints>\n\n<user_input>输入</user_input>` |
| `shortform` | 短文模板(23变量渲染) | assistant: 角色认知种子 → assistant: 摘要(scene+plot) | 最近20轮历史 | 纯文本 |
| `switch_s2l` | 长文 L0-L4 | assistant: 已有摘要(不新生成) | 最近20轮混合(短文assistant→隔离) | 长文格式 |
| `switch_l2s` | 短文模板 | assistant: 种子 → 已有摘要 | 最近20轮混合(长文assistant→隔离) | 纯文本 |

### 4.2 异质上下文隔离

- 短文 assistant → 长文请求：`❗[以下为短文模式回复记录…]` / `[短文模式记录结束]` system 三明治
- 长文 assistant → 短文请求：`❗[以下为长文模式回复记录…]` / `[长文模式记录结束]` system 三明治
- user 消息：**永远不做隔离包裹**
- Few-shot / 普通真实历史：**不包夹**

### 4.3 传输合同（T1-T4）

| 规约 | 约束 |
|:---|:---|
| T1 | additional_messages 中仅允许"上下文隔离边界"使用 system |
| T2 | 动态摘要使用 assistant + 三段闭合 |
| T3 | 人设 System Prompt 仅在 messages[0] |
| T4 | Few-shot/Core 归属主提示词内部 |

### 4.4 上下文窗口

| 场景 | 历史轮数 | 摘要触发 |
|:---|:---|:---|
| 纯长文 | 最近10轮 | 每5轮 |
| 纯短文 | 最近20轮 | 每20轮 |
| 切换首轮 | 最近20轮混合 | 不触发 |

---

## §5 质量门禁

### 5.1 确定性校验（9 项）

| 检查项 | 长文 | 短文 |
|:---|:---|:---|
| 字数 | 300-500 | 用例级配置，默认30-90 |
| 格式/括号 | 全角≥3对，禁半角 | 全角配对，禁半角 |
| 禁词 | "指尖" | "指尖" + 用例级禁词 |
| 角色名混淆 | 不得混淆角色名和用户称呼 | 同左 |
| 关系边界 | 不得越过当前关系阶段 | 同左 |
| 记忆纪律 | 不得主动引用用户未提及信息 | 同左 |
| n-gram重复率 | 与最近3条assistant检测 | 同左 |
| Emoji | 禁用 | 允许 |
| 叙事人称 | 第三人称 | 第一人称 |

### 5.2 LLM-as-Judge 评分

**长文（5 维）**：叙事沉浸感(0.25) / 角色一致性(0.25) / 上下文连贯(0.20) / 格式规范(0.20) / 安全合规(0.10)

**短文（6 维）**：当前输入回应度(20%) / 人设一致性(20%) / 上下文连续性(15%) / 短文格式与节奏(15%) / 记忆克制(15%) / 安全与边界(15%)

### 5.3 A/B 胜负判定

| 结果 | 规则 |
|:---|:---|
| 明确胜出 | 均分高≥0.3 且确定性错误更少 |
| 不显著 | 分差<0.3 或样本<5 |
| 失败 | 安全/边界硬失败，即使均分高也不胜出 |
| 需复跑 | T≥0.8 且单样本分差大但不稳定 |

---

## §6 技术架构

### 6.1 系统组件

> 详见 [ARCHITECTURE.md](../ARCHITECTURE.md)，此处仅列核心组件。

| 组件 | 职责 |
|:---|:---|
| `message_assembler.py` | 消息拼接引擎（v5.2 Consolidated Single-Block） |
| `conversation_service.py` | 兼容门面 + 组件装配 |
| `conversation_generation.py` | 单轮生成执行 |
| `conversation_runtime.py` | 摘要/画像后台任务 |
| `scoring_service.py` | 打分管道（支持多模型/版本化提示词/自适应并发） |
| `quality_guard.py` | 确定性校验 |
| `model_adapter.py` | 多模型适配层 |
| `prompt_service.py` | 提示词版本管理 |
| `export_service.py` | Excel/JSON 导出 |
| `longform_multi_turn.py` | CLI 批量入口 |

### 6.2 API 接口

| 方法 | 路径 | 说明 |
|:---|:---|:---|
| POST | `/api/cases/import` | 导入日志/JSONL/Excel |
| GET | `/api/cases` | 用例列表（mode 筛选） |
| GET | `/api/cases/:id` | 用例详情 |
| POST | `/api/prompts` | 创建提示词版本 |
| GET | `/api/prompts` | 列出版本 |
| POST | `/api/runs` | 创建批量任务 |
| GET | `/api/runs/:id` | 任务状态 |
| GET | `/api/runs/:id/export` | 导出 Excel |
| GET | `/api/runs/:id/request/:case_id/:variant` | 有效请求体 |
| POST | `/api/conversations` | 创建对话 |
| WS | `/ws/conversations/:id` | 流式对话 |

### 6.3 导出字段

| 分组 | 字段 |
|:---|:---|
| 用例 | case_id / source_file / mode / 标签 / endpoint / model_type / msg_count |
| 版本 | variant_id / variant_name / prompt_hash / diff_summary |
| 请求 | effective_request_hash / cache_policy / temperature / max_tokens |
| 输出 | ai_output / latency_s / input_tokens / output_tokens / error |
| 校验 | length_ok / format_ok / role_ok / memory_ok / boundary_ok / repeat_score / failures |
| 评分 | total_score / 维度分(长5/短6) / reasoning |
| A/B | winner / score_delta / hard_fail / winner_reason |

---

## §7 风险与开放问题

| 风险 | 处理 |
|:---|:---|
| 字数标准冲突（40-60 vs 30-90） | 用例级配置，不硬编码 |
| 缓存污染 A/B | 默认隔离/禁用 |
| 误用长文拼接器处理短文 | 短文必须走独立 request builder |
| LLM 评分不稳定 | 关键结论 repeat=3 |
| 日志敏感 | 本地存储，导出支持脱敏 |

**开放问题**：
1. Depth Injection 在 `message_assembler.py` 中尚未实现，PRD 标记为 planned
2. `scoring_service.py` 的评分维度从 pipeline config 动态加载，需确认与 §5.2 对齐

---

## §8 验收计划

### 8.1 黄金测试用例（10 个）

| # | 场景 | 预期 |
|:--|:---|:---|
| G1 | 短文首轮无历史 | messages: system + seed + user；无 Few-shot/CC |
| G2 | 长文带5条短文历史 | 短文 assistant 全部 system 三明治；user 不包裹 |
| G3 | switch_s2l 首轮 | 主 system 长文；20轮混合；短文 assistant 隔离；不生成切换摘要 |
| G4 | 短文 QualityGuard | 25字→过短告警；100字→过长告警 |
| G5 | CLI `--mode shortform --dry-run` | 23变量全渲染，无 `{{}}` 残留 |
| G6 | 日志解析 | 导入发旋问题日志成功解析；Id/id 不冲突 |
| G7 | A/B 隔离 | prompt hash 相同，systemPrompt hash 不同，cacheId 隔离 |
| G8 | 字数口径切换 | 同一输出按 30-90 / 40-60 分别校验给出不同结果 |
| G9 | 记忆克制 | 用户未提及历史事件但输出复述→标记 memory_overuse |
| G10 | 批量对比 | 6日志 × A/B → 12条结果 + 汇总报告 + Excel 导出 |

### 8.2 验收标准（6 条）

1. 导入问题排查下 6 个日志全部成功解析
2. 单条日志原样复放，展示原始与有效请求体，字段不丢失
3. A/B 测试时同 case 的 prompt 历史一致，只有 systemPrompt 变化
4. 默认 A/B 不复用 contextId/cacheId
5. 批量运行可导出 Excel，含全部 §6.3 字段
6. 局部覆盖时工具展示 diff

---

## 附录

### A. 修订记录

| 版本 | 日期 | 变更 |
|:---|:---|:---|
| v0.1 | 2026-04-24 | 结构化初稿 |
| v0.2 | 2026-05-11 | 补齐短文架构+切换路径+批量工具+日志复放+A/B+评分+页面/API |
| **v1.0** | **2026-05-13** | **按 Atlassian/ISO 29148 重写；融合长文已有功能（Web UI/打分/模型适配/导出）；消除 v0.2 重复章节；消息拼接权威来源改为问题排查目录** |

### B. 关联文档索引

| 文档 | 路径 |
|:---|:---|
| v5.4 融合需求文档 | `e:\工作资料\产品资料\提示词资料\长文模式\需求文档\长短文模式融合_需求文档_v5.4_20260506_feishu.md` |
| 长文拼接权威来源 | `e:\工作资料\产品资料\提示词资料\问题排查——长文\` |
| 短文拼接权威来源 | `e:\工作资料\产品资料\提示词资料\问题排查——短文\` |
| 短文验证工具 PRD v1.0 | `e:\工作资料\产品资料\提示词资料\短文模式\需求文档\短文模式生成验证工具_PRD_v1.0_20260408.md` |
| 工具架构 | `e:\提效工具\长文模式生成\ARCHITECTURE.md` |
| CLI 入口 | `e:\提效工具\长文模式生成\longform_multi_turn.py` |
| 消息拼接引擎 | `e:\提效工具\长文模式生成\server\services\message_assembler.py` |
| PRD v0.2（历史存档） | `e:\提效工具\长文模式生成\优化文档\长文模式生成工具_PRDv0.2.md` |
