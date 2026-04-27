# 长文模式生成工具架构说明

## 当前目标

- 本项目是 `E:\提效工具` 单仓库下的一个子项目，不单独维护分支、tag 或仓库级保护策略。
- 本轮改造目标是拆小 `conversation_service.py` / `conversations.py`，同时保持 API、测试入口和 import 兼容。
- 本轮不做目录级大迁移，不引入 `server/modules`。

## 当前结构

```text
长文模式生成/
├── server/
│   ├── main.py
│   ├── config.py / database.py / models.py
│   ├── routers/
│   │   └── conversations.py
│   ├── services/
│   │   ├── conversation_service.py
│   │   ├── conversation_generation.py
│   │   ├── conversation_runtime.py
│   │   ├── conversation_summary.py
│   │   ├── conversation_store.py
│   │   ├── runtime_config.py
│   │   ├── model_adapter.py
│   │   ├── prompt_service.py
│   │   ├── message_assembler.py
│   │   └── token_trimmer.py
│   └── static/
├── scripts/
│   ├── archive/
│   ├── ci.py
│   └── manual_checks/
└── tests/
    ├── smoke/
    ├── unit/
    ├── integration/
    └── regression/
```

## Conversation 域职责拆分

### `conversation_service.py`

- 兼容门面。
- 保留 `ConversationService` 类、常量 re-export 和测试当前依赖的半公开方法。
- 负责装配内部组件，不再承载全部细节实现。

### `conversation_generation.py`

- 单轮生成执行。
- 请求快照构造。
- memory context 拼装。
- token trim 与主模型调用。

### `conversation_runtime.py`

- 摘要/画像后台任务状态。
- 运行时摘要选择与 fallback。
- 后台 job 调度、消费、等待和回填。

### `conversation_summary.py`

- 结构化摘要生成。
- 用户画像生成。
- 画像提示词模板读取。

### `conversation_store.py`

- conversation 域持久化薄封装。
- 只允许 `ConversationService` 内部使用。
- 不是公共基础设施，不是通用 repository，不允许路由或其他业务域直接 import 作为共享数据层。

## 兼容性约束

- 所有 `/api/conversations*` 和 `/ws/conversations/{conv_id}` 路径保持兼容。
- `services.conversation_service` 模块路径保持兼容。
- 以下常量继续从 `services.conversation_service` 导出：
  - `CORE_CONSTRAINTS_TEMPLATE`
  - `LONGFORM_WORD_RANGE`
  - `SEPARATOR_MSG`
  - `STYLE_ISOLATION_MSG`
  - `SUMMARY_INJECT_TEMPLATE`
  - `MEMORY_WAIT_TIMEOUT_S`
- 以下 helper 继续从 `routers.conversations` 可见：
  - `_get_conv_service`
  - `_resolve_requested_prompt`
  - `_build_runtime_config`
  - `_merge_runtime_sampling_config`
  - `_prepare_batch_runtime`
  - `_apply_conversation_channel_context`
  - `reconcile_conversation_runtime_state`

## 已知债务

### `_conv_service` 是测试耦合热点

- `routers.conversations` 当前使用模块级 `_conv_service` 懒加载单例。
- 多个测试会直接替换 `_conv_service`、`_running_conversations`、`_queued_conversations`、`_ws_connections`。
- 这让测试可控，但也让路由实现与测试夹具强绑定。
- 后续如果切换到更标准的依赖注入，必须先重构测试策略，否则会出现大面积回归。

### CLI 与服务层存在常量副本债务

- 长文约束类常量与注入模板存在“定义于底层 / 由兼容门面再导出 / CLI 也持有相似概念”的历史债务。
- 当前策略是优先保持兼容，不在本轮合并常量来源。
- 后续应把 CLI 与服务层的共享常量收敛到明确的单一来源。

## 局部 Git 约束

- 本项目只维护子项目级文档和开发约束。
- 不在本轮内要求单独分支、tag 或仓库级保护策略。
- 运行时产物、数据库、日志和测试输出继续通过 `.gitignore` 控制。
