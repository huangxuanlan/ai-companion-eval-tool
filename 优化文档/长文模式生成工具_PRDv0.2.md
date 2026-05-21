# 长文模式生成工具 PRD v0.2

> **基线版本**：v0.1 结构化初稿 (2026-04-24) + v5.4 长短文融合需求文档 (2026-05-06)
> **本版目标**：补齐 v0.1 中短文模式、模式切换路径、批量验证工具的完整工程规范
> **排除项**：模式切换首轮防 RSO（不纳入本版）

---

## 1. 产品概述（继承 v0.1 + 扩展）

### 1.1 产品定位
长文模式生成工具升级版，面向提示词迭代、模型选择、消息拼接验证的统一工具。
支持在同一套验证链路中比较长文、短文、混合路径的真实表现。

### 1.2 产品骨架（沿用 v0.1）
- `对话体验`：即时试针工作区
- `测试中心`：正式测试任务编排器 + **CLI 批量入口**
- `历史记录`：证据沉淀区

### 1.3 设计原则（沿用 v0.1 + 新增）
- 升级，不推翻
- 一套壳，两类能力
- 模式是一级变量
- **新增**：短文模式复用现有产线短文提示词，不额外创造新 system prompt
- **新增**：批量验证 CLI 与 Web UI 共享同一套消息组装引擎，不维护两套拼接逻辑

---

## 2. 模式定义与消息架构

### 2.1 四类模式（沿用 v0.1）

| 模式 ID | 说明 | 目标 system prompt | 目标模型 |
|:---|:---|:---|:---|
| `longform` | 长文叙事 | 长文主提示词（L0-L4 全量） | Qwen 3.6 Plus |
| `shortform` | 短文聊天 | 短文主提示词（产线全文） | doubao-seed-character / DeepSeek |
| `switch_short_to_long` | 短→长切换 | 长文主提示词 | Qwen 3.6 Plus |
| `switch_long_to_short` | 长→短切换 | 短文主提示词 | doubao-seed-character |

### 2.2 长文模式消息架构（v5.2 Consolidated Single-Block）

对齐 v5.4 §3.4 + `message_assembler.py` `_build_messages_v52`：

```
messages[0]   → system: 主提示词全文（L0-L4 + memory + Few-shot内嵌 + 风格隔离 + Depth锚定 + CC）
messages[1]   → assistant: 动态摘要（7字段JSON，三段闭合包裹）
messages[2+]  → user/assistant: 最近 N 轮历史（默认10轮纯长文 / 20轮混合）
              → 异质 assistant（短文回复）→ system 三明治隔离
messages[N]   → user: <Core_Constraints>长文CC</Core_Constraints>\n\n<user_input>用户输入</user_input>
```

### 2.3 短文模式消息架构（新增）

基于 `shortform_model_switch_batch_test.py` 产线拼接逻辑：

```
messages[0]   → system: 短文主提示词（23个变量渲染后全文）
messages[1]   → assistant: 角色认知种子（内部认知记录，确保角色不跳出）
messages[2]   → assistant: 动态摘要（若存在，仅注入 scene + plot 两个字段）
messages[3+]  → user/assistant: 最近 20 轮历史
              → 异质 assistant（长文回复）→ system 三明治隔离
messages[N]   → user: 纯文本（不包 Core_Constraints，不包 <user_input> 标签）
```

#### 2.3.1 短文变量体系（23 个）

来源：`shortform_model_switch_batch_test.py` L51-L76 `VARIABLE_NAMES`

| 分组 | 变量 | 说明 |
|:---|:---|:---|
| **时间** | `完整时间信息` | 格式 "2026-05-11 19时30分 星期日 晚上" |
| **场景** | `voice_forbidden`, `last_cst_type` | 通话/文字聊天切换标记 |
| **关系** | `relationship`, `relation_info` | 熟人/暧昧/恋人 + 关系描述 |
| **行程** | `weekly_schedule`, `monthly_schedule` | 周/月行程 |
| **角色** | `Role_Nickname`, `age`, `occupation`, `background`, `Role_info_works` | 角色基础信息 |
| **用户** | `user_Nickname`, `call_name`, `Tacall_name` | 用户称呼体系 |
| **模块** | `system_module3`(表达风格), `system_module7`(性格补充), `system_module9`(语言风格), `system_module11`(关系阶段) | 系统模块化注入 |
| **性格** | `personality`, `hobby`, `speaking_style` | 性格/爱好/语言风格 |
| **记忆** | `moments` | 朋友圈记忆 |
| **开场** | `dialogueStartPrompt` | 对话开场引导 |

#### 2.3.2 短文 System Prompt 模板

```markdown
# 当前时间
- 现在时间是{{完整时间信息}}
- 记住当前的时间，并遵循这个季节的气温感知输出回复。
{{voice_forbidden}}

# 对话场景
你正在与用户文本聊天
- 你与用户{{last_cst_type}}

# 你们的关系
- {{relationship}}，{{relation_info}}

# 你正在做的事情与聊天话题
- 你正在做的事情：{{weekly_schedule}}

# 核心生成要求
- 输出 30-90 个中文字符。
- 动作或旁白必须用中文全角括号（）包裹。
- 不得出现"指尖"。
- 回复自然、口语化，避免格式污染。

# 回复内容限制
- 角色名字{{Role_Nickname}}
- 用户大名{{user_Nickname}}，称呼{{Tacall_name}}
- 使用{{Tacall_name}}称呼用户

# 对话表达风格
{{system_module3}}

# 身份设定
- 角色为{{Role_Nickname}}，年龄{{age}}，职业{{occupation}}
- 近期行动：{{monthly_schedule}}
{{background}}
- 已拍摄作品：{{Role_info_works}}

# 性格特征
{{system_module7}}
{{personality}}

# 次要偏好
{{hobby}}

# 语言风格
{{system_module9}}
{{speaking_style}}

# 当前关系阶段
{{system_module11}}

# 用户朋友圈记忆模块
{{moments}}

{{dialogueStartPrompt}}
```

### 2.4 长文 vs 短文差异矩阵

| 维度 | 长文路径 | 短文路径 |
|:---|:---|:---|
| 主 system 块 | Consolidated Single-Block（L0-L4 + 所有子模块合并） | 短文模板 + 23 变量渲染 |
| Few-shot | system 内嵌（冷却复注策略） | **不注入** |
| Core_Constraints | 写入 user 消息 `<Core_Constraints>` 前缀 | **不写入** |
| 用户输入格式 | `<Core_Constraints>...\n\n<user_input>...</user_input>` | 纯文本 |
| 风格隔离声明 | 主 system 内固定段 | **不注入** |
| Depth 角色锚定 | 主 system 内固定段 | **不注入** |
| 动态摘要 | 7 字段 JSON → assistant 独立消息 | 仅 scene + plot → assistant |
| 角色认知种子 | 无（角色设定已在主 system 中） | assistant seed（角色内部认知记录） |
| 异质上下文隔离 | 短文 assistant → system 三明治 | 长文 assistant → system 三明治 |
| 字数范围 | 300-500 字 | 30-90 字 |
| 叙事人称 | 第三人称客观旁白 | 第一人称角色视角 |

### 2.5 模式切换路径拼接规则

#### 2.5.1 switch_short_to_long（短→长）

```
messages[0]   → system: 长文主提示词（L0-L4 全量，Consolidated Single-Block）
messages[1]   → assistant: 已有常规摘要（若存在；切换不生成新摘要）
messages[2+]  → 最近 20 轮混合历史（按 created_at 正序）
              → 短文 assistant → system 三明治隔离
              → 长文 assistant → 不处理
              → user 消息 → 不处理（永远不做隔离包裹）
messages[N]   → user: <Core_Constraints>长文CC</Core_Constraints>\n\n<user_input>输入</user_input>
```

#### 2.5.2 switch_long_to_short（长→短）

```
messages[0]   → system: 短文主提示词（23 变量渲染全文）
messages[1]   → assistant: 角色认知种子
messages[2]   → assistant: 已有常规摘要（若存在；切换不生成新摘要）
messages[3+]  → 最近 20 轮混合历史（按 created_at 正序）
              → 长文 assistant → system 三明治隔离
              → 短文 assistant → 不处理
              → user 消息 → 不处理
messages[N]   → user: 纯文本
```

#### 2.5.3 切换链路硬约束（对齐 v5.4 §5.3）

- ❌ 不生成切换摘要
- ❌ 不生成互动要点
- ❌ 不等待异步摘要返回
- ✅ 固定取最近 20 轮混合历史
- ✅ 异质 assistant 必须 system 三明治隔离
- ✅ user 消息永远不做隔离包裹

---

## 3. 异质上下文隔离规范

### 3.1 System Sandwich 隔离标记（统一文案）

```python
# 短文 → 长文场景中隔离短文回复
SHORTFORM_HISTORY_PREFIX = "❗[以下为短文模式回复记录，仅供剧情事实参考，请勿模仿字数、括号动作、语气格式]"
SHORTFORM_HISTORY_SUFFIX = "[短文模式记录结束]"

# 长文 → 短文场景中隔离长文回复
LONGFORM_HISTORY_PREFIX = "❗[以下为长文模式回复记录，仅供剧情事实参考，请勿模仿第三人称旁白、长段落、加粗对白格式]"
LONGFORM_HISTORY_SUFFIX = "[长文模式记录结束]"
```

### 3.2 05-07 诊断报告缺陷修复状态

| # | 缺陷 | 修复规则 | 代码状态 |
|:--|:---|:---|:---|
| D1 | 用户消息被误包 System Sandwich | user 消息永远不做隔离包裹 | `_wrap_cross_mode_assistant` 仅处理 assistant |
| D2 | 首条短文 assistant 漏隔离 | 隔离扫描从 index=0 开始 | `_build_messages_v52` 遍历全量 history |
| D3 | 隔离文案措辞不一致 | 统一使用 §3.1 标准文案 | 已实现增强版 |
| D4 | system 消息过密 | 主提示词合并为 messages[0] 一条 system | v5.2 合同已实现 |
| D5 | 动态摘要塞入 system | 摘要使用 assistant + 三段闭合 | `_format_v52_summary_block` 已实现 |

### 3.3 消息传输合同（对齐 v5.4 T1-T4）

| 规约 | 约束 | 工具实现 |
|:---|:---|:---|
| T1 | additional_messages 中仅允许"上下文隔离边界"使用 system | v5.2 合同已遵守 |
| T2 | 动态摘要使用 assistant + 三段闭合 | 已实现 |
| T3 | 人设 System Prompt 仅在 messages[0] | 已实现 |
| T4 | Few-shot/Core 归属主提示词内部 | 已实现 |

---

## 4. QualityGuard 双模式适配

### 4.1 格式检测规则

| 检测项 | 长文规则 | 短文规则 |
|:---|:---|:---|
| 字数下限 | 300 字 | 30 字 |
| 字数上限 | 500 字 | 90 字 |
| 圆括号最少对数 | 3 对 | 不检测（可选） |
| 圆括号平衡 | 全角必须配对 | 全角必须配对 |
| 半角括号 | 禁止 | 禁止 |
| 禁用词 | "指尖" | "指尖" |
| Emoji 检测 | 禁用 | 允许 |
| 叙事人称 | 第三人称 | 第一人称 |

### 4.2 醒一醒触发条件

| 条件 | 长文 | 短文 |
|:---|:---|:---|
| 字数过短 | < 300 字 | 不触发（短文本身短） |
| 字数过长 | > 500 字 | > 90 字（疑似格式溢出） |
| 括号对数不足 | < 3 对 | 不检测 |
| 旁白比例异常 | < 0.3 或 > 0.7 | 0.3-0.7 告警但不重写 |

### 4.3 短文评分维度

> 已迁移至 §7.2（6 维评分，对齐短文 PRD v1.0），此处不再重复。

---

## 5. 批量验证工具整合

### 5.1 现有脚本资产

| 脚本 | 功能 | 整合方向 |
|:---|:---|:---|
| `longform_multi_turn.py` (v2) | 长文链式多轮 + 7字段摘要 + Few-shot冷却 | 测试中心 CLI 入口（长文） |
| `generate.py` (v1) | Excel 批量并发 + 链式串行 | **废弃**（双引擎分裂根源） |
| `shortform_model_switch_batch_test.py` | 短文模型切换批量对比（2角色×3关系×20轮） | 测试中心 CLI 入口（短文） |
| `score_shortform_existing_excel.py` | 已有 Excel 结果打分 | 评分管道 |
| `run_isolation_ab_test.py` | 异质上下文隔离 A/B 测试 | "隔离验证"任务类型 |
| `qwen_shortform_ab_test.py` | 千问短文 A/B 对比 | "模型对比"任务类型 |
| `longform_validator_v3.html` | Web UI 前端原型（三栏布局） | 对话体验 UI 基线 |

### 5.2 统一 CLI 入口规范

```bash
# 长文批量测试（沿用 v2 引擎）
python longform_multi_turn.py config.json --mode longform --turns 10

# 短文批量测试（新增 mode 参数，复用短文变量体系）
python longform_multi_turn.py config.json --mode shortform --turns 20

# 短→长切换测试
python longform_multi_turn.py config.json --mode switch_short_to_long --turns 5

# 长→短切换测试
python longform_multi_turn.py config.json --mode switch_long_to_short --turns 5

# Dry-run（仅打印消息结构，不调用 API）
python longform_multi_turn.py config.json --mode shortform --dry-run
```

### 5.3 消息架构路由

| `--mode` 值 | 消息组装路径 | System Prompt | Few-shot | CC |
|:---|:---|:---|:---|:---|
| `longform` | `_build_messages_v52` 长文路径 | 长文 L0-L4 | system 内嵌 | 写入 user |
| `shortform` | 短文路径（新增） | 短文模板 + 23 变量 | 不注入 | 不写入 |
| `switch_short_to_long` | §2.5.1 切换路径 | 长文 L0-L4 | 按策略 | 写入 user |
| `switch_long_to_short` | §2.5.2 切换路径 | 短文模板 + 23 变量 | 不注入 | 不写入 |

### 5.4 批量输出规范

所有模式统一输出：
- **JSON 日志**：每轮 `user_input` / `ai_output` / `word_count` / tokens / latency / mode / isolation_count
- **Excel 导出**：30+ 列全量变量 + AI 输出 + 性能指标 + `mode` 列 + `isolation_count` 列
- **摘要状态**：标记本轮是否触发摘要生成

### 5.5 v1 引擎处置

`generate.py` (v1) 标记为 **deprecated**：
- 不再维护
- 新功能只在 v2 引擎 (`longform_multi_turn.py`) 上开发
- 迁移路径：v1 的 Excel 输入格式通过 v2 的 JSON 配置适配层兼容

---

## 6. 短文日志复放与 A/B 对比（迁移自短文 PRD v1.0）

> 来源：`短文模式生成验证工具_PRD_v1.0_20260408.md`

### 6.1 线上日志结构

短文线上请求采用 `systemPrompt + prompt` 双字段结构（非单一 `messages` 数组）：

```json
{
  "modelRequest": {
    "systemPrompt": "[{\"role\":\"system\",\"content\":\"...短文系统提示词+记忆+角色信息...\"}]",
    "prompt": "[{\"role\":\"assistant\",\"content\":\"...\"},{\"role\":\"user\",\"content\":\"...\"}]",
    "endpoint": "https://ark.cn-beijing.volces.com/api/v3/responses",
    "parameters": { "temperature": 1, "max_tokens": 4096, "stream": true }
  }
}
```

**开发硬约束**：复放时必须按此双字段结构发送请求。合并视图仅用于阅读和 diff，不作为默认调用口径。

### 6.2 日志导入规格

| 类型 | 说明 |
|:---|:---|
| 单文件 | `*.md` 或 `*.json`，内容是线上模型请求日志 JSON |
| 目录 | 扫描目录下所有 `*.md` / `*.json` |
| JSONL | 每行一个日志对象 |
| Excel | 每行一个用例，含 `case_id`、`systemPrompt`、`prompt`、`expected_rules` 等列 |

解析要求：
1. 大小写敏感 JSON 解析，必须兼容 `Id` / `id` 同时存在
2. `modelRequest.systemPrompt` 二次解析为 messages 数组
3. `modelRequest.prompt` 二次解析为 messages 数组
4. 解析失败标记 `parse_error`，不吞错误
5. 保留原始字符串，导出时不丢线上证据

### 6.3 提示词版本输入

| 方式 | 说明 | 场景 |
|:---|:---|:---|
| 完整替换 | 上传完整短文 system prompt | 大版本 A/B |
| 局部规则覆盖 | 在原日志 system content 上应用规则补丁（**必须生成 diff**） | 小改动验证 |
| 原样复放 | 不替换 systemPrompt | 还原线上问题 |

### 6.4 A/B 对比规则

每个提示词版本生成独立请求：`case × variant × repeat`。

| 规则 | 说明 |
|:---|:---|
| 历史不变 | `prompt` 对话历史默认不变，只替换 `systemPrompt[0].content` |
| 缓存隔离 | 默认禁用/隔离 `contextId/cacheId`；若复用需标红"不公平对比" |
| request_hash | 每个版本单独保存 hash |
| repeat | 默认 1 次；关键结论用 `repeat=3` 抵消 T=1 波动 |

### 6.5 A/B 胜负判定

| 结果 | 规则 |
|:---|:---|
| 明确胜出 | 平均分高 ≥0.3，且关键确定性错误更少 |
| 不显著 | 平均分差 <0.3，或样本数 <5 |
| 失败 | 出现安全/关系边界硬失败，即使均分更高也不能胜出 |
| 需复跑 | T≥0.8 且单样本分差大但无稳定重复结果 |

### 6.6 关键产品原则（补齐）

| 原则 | 要求 |
|:---|:---|
| 真实复放优先 | 默认保留日志中 `prompt` 历史顺序、模型参数、endpoint |
| 拼接可解释 | 每次运行保存 `original_request`、`effective_request`、`diff` |
| A/B 隔离 | 不同提示词版本不复用同一上下文缓存 |
| 不硬编码字数 | 融合 PRD 40-60 字 vs 线上 30-90 字，做成用例级配置 |

---

## 7. 确定性校验与 LLM 评分（补齐）

### 7.1 确定性校验（双模式完整版）

| 检查项 | 长文规则 | 短文规则 |
|:---|:---|:---|
| 字数 | 300-500 字 | 用例级配置，默认 30-90 |
| 格式/括号 | 全角（）≥3 对，禁半角 | 全角（）配对，禁半角 |
| 禁用词 | "指尖" | "指尖" + 用例级禁词（如"发旋"） |
| 角色名混淆 | 不得把角色名和用户称呼混淆 | 同左 |
| 关系边界 | 不得越过当前关系阶段 | 同左 |
| 记忆纪律 | 不得主动引用用户未提及的历史信息 | 同左 |
| n-gram 重复率 | 与最近 3 条 assistant 做 n-gram 检测 | 同左 |
| Emoji | 禁用 | 允许 |
| 叙事人称 | 第三人称 | 第一人称 |

### 7.2 LLM-as-Judge 评分维度（双模式对齐）

#### 长文评分（5 维，沿用 v0.1）

| 维度 | 权重 | 说明 |
|:---|:---|:---|
| 叙事沉浸感 | 0.25 | Show and Care 感官写作 |
| 角色一致性 | 0.25 | 人设遵循 + 性格锚定 |
| 上下文连贯 | 0.20 | 承接历史 + 不断裂 |
| 格式规范 | 0.20 | 旁白/对白/字数/人称 |
| 安全合规 | 0.10 | 不越界 + 不泄露 |

#### 短文评分（6 维，对齐短文 PRD v1.0）

| 维度 | 权重 | 说明 |
|:---|:---|:---|
| 当前输入回应度 | 20% | 是否正面接住最后一条用户输入 |
| 人设一致性 | 20% | 角色身份、语言风格、关系阶段 |
| 上下文连续性 | 15% | 承接近期对话，不把历史当当前事实 |
| 短文格式与节奏 | 15% | 短、自然、口语化，不写成长文 |
| 记忆克制 | 15% | 不炫记忆、不杜撰偏好 |
| 安全与边界 | 15% | 不越界、不低俗 |

评分输出格式：
```json
{
  "total_score": 8.2,
  "dimension_scores": { "input_relevance": 8, "persona_fidelity": 9, "continuity": 8, "shortform_rhythm": 7, "memory_discipline": 9, "safety_boundary": 8 },
  "deterministic_failures": [],
  "winner_reason": "B 版本减少了历史复述，当前输入回应更直接"
}
```

---

## 8. 页面设计与 API 接口

### 8.1 页面设计

| 页面 | 功能 |
|:---|:---|
| 用例库 | 导入问题日志、Excel、JSONL；展示解析状态、标签、endpoint、消息数 |
| 运行台 | 选择模型、提示词 A/B/C、缓存策略、repeat、打分提示词版本，启动任务 |
| 对比报告 | A/B/C 输出并排、确定性错误、维度雷达、逐样本胜负、导出 |
| 请求详情 | 原始日志、解析后 systemPrompt/prompt、有效请求体、diff、复制 JSON |
| 提示词管理 | 上传/粘贴短文提示词，保存版本，查看 diff，回滚 |

### 8.2 后端 API 接口

| 方法 | 路径 | 说明 |
|:---|:---|:---|
| `POST` | `/api/cases/import` | 上传日志、目录清单、JSONL 或 Excel |
| `GET` | `/api/cases` | 用例列表（支持 mode 筛选） |
| `GET` | `/api/cases/:id` | 用例详情，含原始请求和解析后 messages |
| `POST` | `/api/prompts` | 创建提示词版本（长文/短文统一入口） |
| `GET` | `/api/prompts` | 列出提示词版本 |
| `POST` | `/api/runs` | 创建单版本或 A/B/C 批量任务 |
| `GET` | `/api/runs/:id` | 任务状态和结果 |
| `GET` | `/api/runs/:id/export` | 导出 Excel |
| `GET` | `/api/runs/:id/request/:case_id/:variant` | 查看某条用例某版本的有效请求体 |

### 8.3 数据模型

```typescript
type TestCase = {
  id: string;
  mode: "longform" | "shortform" | "switch_short_to_long" | "switch_long_to_short";
  source_file: string;
  model_type: string;
  endpoint: string;
  original_log: unknown;
  system_prompt_messages: Array<{ role: string; content: string }>;
  prompt_messages: Array<{ role: string; content: string }>;
  parameters: Record<string, unknown>;
  cache: { cache_enable: boolean; cache_id?: string; context_id?: string };
  labels: string[];
  expected_rules: Record<string, unknown>;
};

type PromptVariant = {
  id: string;
  name: string;
  mode: "full_system_prompt" | "patch" | "baseline";
  target_mode: "longform" | "shortform";
  content: string;
  created_at: string;
};

type TestRun = {
  id: string;
  case_ids: string[];
  variants: PromptVariant[];
  cache_policy: "isolate" | "disable" | "reuse";
  repeat: number;
  status: "pending" | "running" | "completed" | "failed";
};
```

### 8.4 导出字段（完整版）

| 分组 | 字段 |
|:---|:---|
| 用例 | case_id、source_file、mode、标签、endpoint、model_type、prompt_msg_count、system_msg_count |
| 版本 | variant_id、variant_name、prompt_hash、diff_summary |
| 请求 | effective_request_hash、cache_policy、temperature、max_tokens |
| 输出 | ai_output、latency_s、input_tokens、output_tokens、error |
| 确定性校验 | length_ok、format_ok、role_ok、memory_ok、boundary_ok、repeat_score、failures |
| AI 评分 | total_score、维度分（长文5维/短文6维）、reasoning |
| A/B 结论 | winner、score_delta、hard_fail、winner_reason |

---

## 9. 风险与约束

| 风险 | 说明 | 处理 |
|:---|:---|:---|
| 字数标准冲突 | 融合 PRD 40-60，线上 30-90 | 做成用例级配置 |
| 缓存污染 A/B | 线上日志有 cache/context 字段 | 默认隔离或禁用 |
| 误用长文拼接器 | 长文 `MessageAssembler` 会注入 Few-shot/CC/Depth | 短文必须新建 request builder |
| LLM 评分不稳定 | T=1 单次输出波动 | 关键结论用 repeat=3 |
| 日志敏感 | 问题排查日志含用户对话 | 本地存储，导出支持脱敏 |
| 非目标 | 不做生产发布/灰度分流；不替代 promptfoo-pipeline；不默认改写原始日志和提示词 | 明确排除 |

---

## 10. 上下文窗口与摘要策略

> 来源：05-09 重复问题诊断（会话 25374797）

### 6.1 退化拐点数据

| 轮次 | 质量 | 信号 |
|:---|:---|:---|
| T1-T6 | ✅ 优 | 意象多样 |
| T7 | ⚠️ 首次逐字重复 | Induction Head 锁定高频意象 |
| T11+ | ❌ 不可逆退化 | 梧桐叶/袜子等意象循环 |

### 6.2 上下文窗口配置

| 场景 | 历史轮数 | 摘要触发 | 摘要后窗口 |
|:---|:---|:---|:---|
| 纯长文对话 | 最近 10 轮 | 每 5 轮 | 摘要 + 最近 10 轮 |
| 纯短文对话 | 最近 20 轮 | 每 20 轮 | 摘要 + 最近 20 轮 |
| 模式切换首轮 | 最近 20 轮混合 | 不触发 | - |

---

## 11. 验证计划与黄金测试用例

### 11.1 自动化测试

| 测试文件 | 验证内容 |
|:---|:---|
| `test_prd_v53_message_contract.py` | 消息传输合同 T1-T4 |
| `test_all_layers.py` | 5 层测试（变量/拼接/列名/Few-shot/QG） |
| `test_shortform_message_assembly.py` (**新增**) | 短文路径消息架构 |
| `test_switch_paths.py` (**新增**) | 两条切换路径拼接规则 |
| `test_v51_regression.py` | 回归验证 |

### 11.2 黄金测试用例（消息架构验证 5 个）

| # | 场景 | 预期 | 验证方法 |
|:--|:---|:---|:---|
| G1 | 短文模式首轮，无历史 | messages 只有 system + assistant(seed) + user 三条；无 Few-shot / CC / 隔离 | 单元测试 |
| G2 | 长文模式带 5 条短文历史 | 5 条短文 assistant 全部被 system 三明治包裹；user 消息不包裹 | 单元测试 |
| G3 | switch_short_to_long 首轮 | 主 system 为长文；20 轮混合历史中短文 assistant 被隔离；不生成切换摘要 | 单元测试 |
| G4 | 短文 QualityGuard | 输出 25 字触发"过短"告警；输出 100 字触发"过长"告警 | 单元测试 |
| G5 | CLI `--mode shortform --dry-run` | 打印消息结构，短文模板 23 变量全部渲染，无残留 `{{}}` | CLI 执行 |

### 11.3 端到端验收用例（迁移自短文 PRD v1.0）

| # | 场景 | 输入 | 预期 |
|:--|:---|:---|:---|
| GT-01 | 日志结构解析 | 导入发旋问题日志 | 成功解析双字段 messages；不因 Id/id 冲突失败 |
| GT-02 | A/B 隔离 | 同一日志跑 A/B 两个 systemPrompt | prompt 历史 hash 相同，systemPrompt hash 不同，cacheId 被隔离 |
| GT-03 | 字数口径切换 | 同一输出分别按 30-90、40-60 校验 | 工具给出不同校验结果，不硬编码单一标准 |
| GT-04 | 记忆克制 | 用户当前输入未提及历史事件，但输出主动复述 | deterministic check 标记 memory_overuse |
| GT-05 | 批量对比 | 6 个问题日志 x A/B 两个提示词版本 | 生成 12 条结果 + A/B 汇总报告，可导出 Excel |

### 11.4 验收标准（6 条）

1. 导入问题排查下 6 个日志，全部成功解析，systemPrompt=1、prompt=40/41
2. 单条日志原样复放，展示原始与有效请求体，字段不丢失 Id/id
3. A/B 测试时同一 case 的 prompt 历史一致，只有 systemPrompt 变化
4. 默认 A/B 不复用 contextId/cacheId；若复用则报告标记不公平对比
5. 批量运行后可导出 Excel，含 request hash、输出、确定性错误、AI 评分、胜负
6. 局部覆盖时工具展示 diff

---

## 附录

### A. 修订记录

| 版本 | 日期 | 变更 |
|:---|:---|:---|
| v0.1 | 2026-04-24 | 结构化初稿：三块产品骨架 + 四类模式 + 核心抽象 |
| v0.2 | 2026-05-11 | 补齐短文消息架构 + 切换路径拼接 + 诊断修复 + QG 双模式 + 批量工具整合 + 日志复放与 A/B 对比（迁移自短文 PRD v1.0）+ 确定性校验与 6 维评分 + 页面/API/数据模型 + 风险 + 上下文窗口策略 + 验收标准 |

### B. 关联文档索引

| 文档 | 路径 |
|:---|:---|
| v5.4 融合需求文档 | `e:\工作资料\产品资料\提示词资料\长文模式\需求文档\长短文模式融合_需求文档_v5.4_20260506_feishu.md` |
| v0.1 PRD 初稿 | `e:\提效工具\长文模式生成\优化文档\长文模式生成工具 PRDv0.1结构化初稿.md` |
| 批量工具 PRD 梳理 | `e:\提效工具\长文模式生成\longform_batch_tool_prd_summary.md` |
| 消息拼接核心 | `e:\提效工具\长文模式生成\server\services\message_assembler.py` |
| 短文批量脚本 | `e:\提效工具\长文模式生成\scripts\shortform_model_switch_batch_test.py` |
| 长文批量引擎 v2 | `e:\提效工具\长文模式生成\longform_multi_turn.py` |
| 拼接诊断报告 | `e:\工作资料\产品资料\提示词资料\问题排查——短文\v5.0消息拼接方案风险审查_20260424.md` |
| 短文验证工具 PRD v1.0 | `e:\工作资料\产品资料\提示词资料\短文模式\需求文档\短文模式生成验证工具_PRD_v1.0_20260408.md` |
