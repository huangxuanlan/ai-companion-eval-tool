# 长文模式批量测试工具 — PRD 梳理报告

> **基于**: 源码 [generate.py](file:///E:/%E6%8F%90%E6%95%88%E5%B7%A5%E5%85%B7/%E9%95%BF%E6%96%87%E6%A8%A1%E5%BC%8F%E7%94%9F%E6%88%90/generate.py)(v1) + [longform_multi_turn.py](file:///E:/%E6%8F%90%E6%95%88%E5%B7%A5%E5%85%B7/%E9%95%BF%E6%96%87%E6%A8%A1%E5%BC%8F%E7%94%9F%E6%88%90/longform_multi_turn.py)(v2) + README.md + 测试脚本 + 需求白皮书v2.8 + 框架结构白皮书v1.7
> **梳理时间**: 2026-03-11

---

## 一、工具定位与演进

本工具是**独立的命令行批量测试工具**，不依赖前后端 Web 服务。它的核心使命是：

> **读取提示词模板 + 角色配置 → 按消息架构白皮书组装 messages → 批量调用大模型 API → 输出多轮长文对话结果**

### 版本演进

| 版本 | 文件 | 输入格式 | 消息架构 | 核心差异 |
|:-----|:-----|:---------|:---------|:---------|
| **v1** | [generate.py](file:///E:/%E6%8F%90%E6%95%88%E5%B7%A5%E5%85%B7/%E9%95%BF%E6%96%87%E6%A8%A1%E5%BC%8F%E7%94%9F%E6%88%90/generate.py) | Excel (.xlsx) | v2.1 | 方案A并发+方案B链式；3组Few-shot；摘要为4字段文本格式 |
| **v2** | [longform_multi_turn.py](file:///E:/%E6%8F%90%E6%95%88%E5%B7%A5%E5%85%B7/%E9%95%BF%E6%96%87%E6%A8%A1%E5%BC%8F%E7%94%9F%E6%88%90/longform_multi_turn.py) | JSON 配置 | v1.6+ | 纯链式多轮；Few-shot冷却复注；深度注入锚定；7字段YAML摘要；风格隔离声明；Core_Constraints动态渲染 |

---

## 二、v1 [generate.py](file:///E:/%E6%8F%90%E6%95%88%E5%B7%A5%E5%85%B7/%E9%95%BF%E6%96%87%E6%A8%A1%E5%BC%8F%E7%94%9F%E6%88%90/generate.py) PRD 要点

### 2.1 核心能力

1. **提示词模板渲染**：加载 [.md](file:///C:/Users/ADMIN/.gemini/antigravity/brain/d88b3819-d28a-4263-94fc-46cf4a075ef4/task.md) 提示词 → `{{variable}}` 全局替换 → 残留变量清理
2. **消息架构组装**（v2.1）：[system(提示词) → Few-shot×3 → 分隔标记 → 对话历史 → Core_Constraints → user_input](file:///E:/%E6%8F%90%E6%95%88%E5%B7%A5%E5%85%B7/%E9%95%BF%E6%96%87%E6%A8%A1%E5%BC%8F%E7%94%9F%E6%88%90/longform_multi_turn.py#142-160)
3. **两种多轮模式混用**：
   - **方案A**（每行独立）：[conversation_history](file:///E:/%E6%8F%90%E6%95%88%E5%B7%A5%E5%85%B7/%E9%95%BF%E6%96%87%E6%A8%A1%E5%BC%8F%E7%94%9F%E6%88%90/generate.py#204-215) 列给定 JSON，并发处理（默认20并发）
   - **方案B**（链式串行）：`session_id` + `turn_order`、自动累积历史、每5轮生成摘要
4. **Few-shot 路由**：`longform_few_shot`列手动JSON > `personal_type`自动匹配示例库 > 不注入
5. **自动摘要**（方案B）：每5轮调用 Pro 模型生成4字段文本摘要，追加到提示词末尾
6. **结果输出**：原始 Excel 追加 `AI输出` / `input_tokens` / `output_tokens` / `latency` / `error`

### 2.2 命令行参数

```
python generate.py input.xlsx [OPTIONS]
  -o, --output PATH      输出路径
  -w, --workers N         并发数 (默认20)
  --prompt PATH           提示词文件
  --fewshot PATH          Few-shot示例库
  --dry-run               只打印消息结构
  --no-summary            禁用自动摘要
```

### 2.3 局限（v2 修复）

- ❌ 无风格隔离声明
- ❌ 无深度注入角色锚定
- ❌ Few-shot无冷却复注策略
- ❌ 摘要为文本格式，非结构化YAML
- ❌ Core_Constraints 模板硬编码，无变量渲染
- ❌ 无 Excel 导出（30列全量变量）
- ❌ 无质量保障流水线

---

## 三、v2 [longform_multi_turn.py](file:///E:/%E6%8F%90%E6%95%88%E5%B7%A5%E5%85%B7/%E9%95%BF%E6%96%87%E6%A8%A1%E5%BC%8F%E7%94%9F%E6%88%90/longform_multi_turn.py) PRD 要点

### 3.1 核心能力（4项，见 docstring）

| # | 能力 | 状态 |
|:--|:-----|:-----|
| 1 | 读取v2.0提示词模板，自动注入 `{{variable}}` 变量 | ✅ [build_variables()](file:///E:/%E6%8F%90%E6%95%88%E5%B7%A5%E5%85%B7/%E9%95%BF%E6%96%87%E6%A8%A1%E5%BC%8F%E7%94%9F%E6%88%90/longform_multi_turn.py#572-610) + [render_template()](file:///E:/%E6%8F%90%E6%95%88%E5%B7%A5%E5%85%B7/%E9%95%BF%E6%96%87%E6%A8%A1%E5%BC%8F%E7%94%9F%E6%88%90/longform_multi_turn.py#107-117) |
| 2 | 按白皮书v1.6消息架构组装 messages 数组 | ✅ [build_messages_for_turn()](file:///E:/%E6%8F%90%E6%95%88%E5%B7%A5%E5%85%B7/%E9%95%BF%E6%96%87%E6%A8%A1%E5%BC%8F%E7%94%9F%E6%88%90/longform_multi_turn.py#365-453) |
| 3 | 每轮AI回复自动拼接为下一轮的 conversation_history | ✅ 主循环串行累积 |
| 4 | 每5轮调用 mini 模型生成7字段 dialogue_summary → 注入模板 | ✅ `generate_summary()` |

### 3.2 消息架构（9层）

```
messages[0]    → system: 提示词全文（L0-L5 变量已填充）
messages[1-4]  → Few-shot 示例×2组（首轮注入，冷却期不注入）
messages[5]    → system: 增强分隔标记（三行防御指令）
messages[6]    → system: 风格隔离声明（有历史/摘要时始终注入）
messages[7]    → system: dialogue_summary（Turn5后独立消息）
messages[7+]   → user/assistant: 历史对话
               + system: 深度注入角色锚定（≥8轮, depth=4）
messages[N-1]  → system: Core_Constraints 重申（动态渲染变量）
messages[N]    → user: <user_input>当前输入</user_input>
```

### 3.3 变量注入体系

| 分组 | 变量 | JSON配置路径 |
|:-----|:-----|:-------------|
| **角色** | `Role_Nickname`, `gender`, [age](file:///E:/%E6%8F%90%E6%95%88%E5%B7%A5%E5%85%B7/%E9%95%BF%E6%96%87%E6%A8%A1%E5%BC%8F%E7%94%9F%E6%88%90/generate.py#270-325), `occupation`, `personality`, `speaking_style`, `personal_type`, `background`, `hobby` | `character.*` |
| **用户** | `user_Nickname`, `user_gender`, `user_identity` | `modules.*` |
| **关系** | `relationship`, `relation_info`, `intimacy_boundary`, `relation_calling` | `context.*` |
| **时空** | `currentTime`, `weekDay`, `timeperiod`, `season`, `current_scene` | `context.*` |
| **叙事** | `longform_narrative_style`, `longform_persona` | `modules.*` |
| **系统** | `dialogueStartPrompt`, `weekly_schedule`, `system_module8`, `system_Role_acting` | `modules.*` |
| **运行时** | [dialogue_summary](file:///E:/%E6%8F%90%E6%95%88%E5%B7%A5%E5%85%B7/%E9%95%BF%E6%96%87%E6%A8%A1%E5%BC%8F%E7%94%9F%E6%88%90/longform_multi_turn.py#277-361) | 每5轮由mini模型生成 |

### 3.4 Few-shot 冷却复注策略

| 轮次范围 | 行为 |
|:---------|:-----|
| Turn 1 | 注入全部 2 组 Few-shot（4条消息） |
| Turn 2-15 | 冷却期不注入 |
| Turn 16+ | 复注第1组示例（2条消息） |

### 3.5 摘要生成（7字段结构化YAML）

每 `SUMMARY_INTERVAL`（默认5）轮调用 mini 模型生成：
- `scene_description` / `plot_summary` / `pending_hooks`
- `character_emotion` / `user_emotion`
- `relationship_shift` / `user_profile_signals`

### 3.6 深度注入角色锚定

- **触发条件**: `turn ≥ 8` 且 `history ≥ 16条`
- **注入方式**: 在 `depth=4` 位置插入 system 消息
- **内容**: "请记住，你是{role_name}，性格特征：{personality}"

### 3.7 输入/输出规格

**输入**：JSON 配置文件（见 `test_conversation_萧璟言.json` 示例）
```json
{
  "prompt_file": "提示词文件路径",
  "character": { /* 角色变量 */ },
  "context": { /* 上下文变量 */ },
  "modules": { /* 系统模块变量 */ },
  "turns": ["用户输入1", "用户输入2", ..., "用户输入N"]
}
```

**输出**：
- JSON 日志（含每轮 `user_input` / `ai_output` / `word_count` / tokens / latency / 摘要状态）
- Excel 导出（30列全量变量 + AI输出 + 性能指标）

### 3.8 命令行参数

```
python longform_multi_turn.py config.json [OPTIONS]
  --dry-run               只打印消息结构
  --turns N               只跑前N轮
```

---

## 四、与白皮书的对齐关系

| 白皮书章节 | PRD要求 | generate.py(v1) | longform_multi_turn.py(v2) |
|:-----------|:--------|:---------------:|:--------------------------:|
| 框架v1.7 §3.1-§3.5 L0-L4层级 | 提示词全文作为system消息 | ✅ | ✅ |
| 框架v1.7 §3.6 Few-shot冷却复注 | Turn1全注入/冷却/T16+复注 | ❌(始终注入3组) | ✅ |
| 框架v1.7 §3.7 分隔标记 | 三行防御指令 | ✅ | ✅ |
| 框架v1.7 §3.8 Core_Constraints | 每轮N-1注入，动态渲染 | ⚠️(硬编码) | ✅ |
| 框架v1.7 §3.9 深度注入 | ≥8轮,depth=4 | ❌ | ✅ |
| 框架v1.7 §4.1 风格隔离声明 | 有历史/摘要时始终注入 | ❌ | ✅ |
| 需求v2.8 §4.1 变量统一 | intimacy_boundary统一 | ⚠️(旧变量) | ✅ |
| 需求v2.8 §9.5 摘要V2.0 | 7字段结构化YAML | ❌(4字段文本) | ✅ |

---

## 五、现有测试覆盖

### [test_all_layers.py](file:///E:/%E6%8F%90%E6%95%88%E5%B7%A5%E5%85%B7/%E9%95%BF%E6%96%87%E6%A8%A1%E5%BC%8F%E7%94%9F%E6%88%90/test_all_layers.py) — 5层测试

| 层级 | 测试内容 | 测试数 |
|:-----|:---------|:-------|
| Layer 1 | 变量注入（[build_variables](file:///E:/%E6%8F%90%E6%95%88%E5%B7%A5%E5%85%B7/%E9%95%BF%E6%96%87%E6%A8%A1%E5%BC%8F%E7%94%9F%E6%88%90/longform_multi_turn.py#572-610) + [render_template](file:///E:/%E6%8F%90%E6%95%88%E5%B7%A5%E5%85%B7/%E9%95%BF%E6%96%87%E6%A8%A1%E5%BC%8F%E7%94%9F%E6%88%90/longform_multi_turn.py#107-117)） | 3项 |
| Layer 2 | 消息拼接结构（首轮/有历史+摘要/深度注入） | 4项 |
| Layer 3 | Excel列名 vs 打分提示词变量对齐 | 1项 |
| Layer 4 | Few-shot冷却复注策略（Turn1/Turn5/Turn16+） | 3项 |
| Layer 5 | QualityGuard质量保障（字数过短/Emoji移除） | 2项 |

> **缺失覆盖**：风格隔离声明注入条件 / Core_Constraints动态渲染 / 摘要7字段结构 / Excel导出完整性 / dry-run模式 / `--turns` 参数截断

---

## 六、关键问题与差距

> [!IMPORTANT]
> 以下差距来自历史对话中的 v5.1 深度诊断报告

| # | 级别 | 问题 | 影响 |
|:--|:-----|:-----|:-----|
| 1 | P0 | **双引擎分裂**：[generate.py](file:///E:/%E6%8F%90%E6%95%88%E5%B7%A5%E5%85%B7/%E9%95%BF%E6%96%87%E6%A8%A1%E5%BC%8F%E7%94%9F%E6%88%90/generate.py)(v1) 与 [longform_multi_turn.py](file:///E:/%E6%8F%90%E6%95%88%E5%B7%A5%E5%85%B7/%E9%95%BF%E6%96%87%E6%A8%A1%E5%BC%8F%E7%94%9F%E6%88%90/longform_multi_turn.py)(v2) 并存，消息架构不一致 | 维护成本高、测试基线不统一 |
| 2 | P0 | v1 缺少 Few-shot 冷却复注/风格隔离/深度注入等关键架构增强 | v1 生成质量低于 v2 |
| 3 | P1 | [longform_multi_turn.py](file:///E:/%E6%8F%90%E6%95%88%E5%B7%A5%E5%85%B7/%E9%95%BF%E6%96%87%E6%A8%A1%E5%BC%8F%E7%94%9F%E6%88%90/longform_multi_turn.py) 的 Few-shot 文件路径可能硬编码 | 切换提示词版本时 Few-shot 不联动 |
| 4 | P1 | QualityGuard 仅在 server 端实现，CLI 工具未集成 | CLI 直接调用无质量保障 |
| 5 | P2 | 测试覆盖不完整（缺少风格隔离/CC渲染/摘要结构等） | 回归风险 |

---

## 七、下一步：按此 PRD 进行测试

基于本 PRD 梳理，后续测试将覆盖以下维度：

1. **变量注入完整性**（§3.3）：所有 23 个变量是否正确注入，残留 `{{}}` 是否清理
2. **消息架构正确性**（§3.2）：9层结构是否按白皮书v1.7顺序组装
3. **Few-shot冷却复注**（§3.4）：3个阶段行为是否正确
4. **摘要生成格式**（§3.5）：是否输出7字段YAML
5. **深度注入触发**（§3.6）：≥8轮时是否在depth=4注入
6. **风格隔离注入条件**：有历史/摘要时是否始终注入
7. **Core_Constraints动态渲染**：`{{Role_Nickname}}`/`{{relationship}}` 是否替换
8. **Excel导出完整性**：30列是否全覆盖
