# 长文模式统一版工具

## 当前定位

- 本项目是 `E:\提效工具` 单仓库下的长文模式子项目，不单独维护仓库级分支和 tag。
- Web 工具入口是 `launcher.py` / `start.bat` / `start.command`。
- CLI 多轮链路入口仍然是 `longform_multi_turn.py`。
- 当前架构重点见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 快速开始

```powershell
# Web 工具
python launcher.py

# 直接启动后端
python server/main.py

# JSON 模式
python longform_multi_turn.py test_conversation_萧璟言.json

# dry-run（只看消息结构）
python longform_multi_turn.py test_conversation_萧璟言.json --dry-run --turns 2
```

## 项目结构

```text
长文模式生成/
├── server/
│   ├── main.py
│   ├── routers/
│   │   └── conversations.py
│   ├── services/
│   │   ├── conversation_service.py
│   │   ├── conversation_generation.py
│   │   ├── conversation_runtime.py
│   │   ├── conversation_summary.py
│   │   ├── conversation_store.py
│   │   └── ...
│   └── static/
├── scripts/
│   ├── archive/
│   ├── ci.py
│   └── manual_checks/
├── tests/
│   ├── smoke/
│   ├── unit/
│   ├── integration/
│   └── regression/
├── longform_multi_turn.py
└── prompt/ few_shot/ output/
```

## 运行与验证

### 核心测试

```powershell
python -m pytest --collect-only -q
python -m pytest -q tests\smoke
python -m pytest -q tests\unit
python -m pytest -q tests\integration
python -m pytest -q tests\regression
```

### 统一入口

```powershell
python scripts/ci.py --smoke
python scripts/ci.py --full
```

### 手工检查脚本

```powershell
python scripts/manual_checks/test_all_layers.py
python scripts/manual_checks/test_8dim_comprehensive.py
python scripts/manual_checks/run_ui_completeness.py
```

## 兼容层说明

- `server/services/conversation_service.py` 是兼容门面。
- 以下常量继续从该模块导出：
  - `CORE_CONSTRAINTS_TEMPLATE`
  - `LONGFORM_WORD_RANGE`
  - `SEPARATOR_MSG`
  - `STYLE_ISOLATION_MSG`
  - `SUMMARY_INJECT_TEMPLATE`
  - `MEMORY_WAIT_TIMEOUT_S`
- `server/routers/conversations.py` 会继续保留测试依赖的 helper：
  - `_get_conv_service`
  - `_resolve_requested_prompt`
  - `_build_runtime_config`
  - `_merge_runtime_sampling_config`
  - `_prepare_batch_runtime`
  - `_apply_conversation_channel_context`
  - `reconcile_conversation_runtime_state`

## 局部开发约束

- 运行依赖在 `server/requirements.txt`。
- 开发依赖在 `requirements-dev.txt`。
- `conversation_store.py` 只允许 service 内部使用，不作为公共数据层暴露给路由或其他业务域。
- `.env`、数据库、日志、输出文件都属于运行时产物，不应提交。

## 输入与默认行为

- `prompt_file` 支持文件名或绝对路径，默认优先命中仓内 `prompt/`
- `few_shot_file` 未提供时默认使用仓内示例库
- 摘要默认按运行时配置周期生成
- 真实输出会经过 `server/services/quality_guard.py` 后处理

如果你还在参考旧的 `generate.py` 文档或旧 API key 说明，那不是当前主链路现状。
