# Changelog

## Phase 1 - 治理文件

- 新增 `ARCHITECTURE.md`
- 新增 `CHANGELOG.md`
- 新增 `.gitattributes`
- 新增 `pyproject.toml`
- 新增 `requirements-dev.txt`
- 新增 `.pre-commit-config.yaml`
- 更新 `README.md`

## Phase 1.5 - 测试安全网

- 明确基线验证命令和核心依赖视图
- 为兼容门面增加常量 re-export 存在性校验
- 为路由 helper 增加显式回归测试
- 将 `test_concurrency_settings.py` 纳入拆分必跑清单

## Phase 2 - 对话域拆分

- 新增 `conversation_generation.py`
- 新增 `conversation_runtime.py`
- 新增 `conversation_summary.py`
- 新增 `conversation_store.py`
- `conversation_service.py` 调整为兼容门面
- `conversations.py` 收缩为路由协议层 + service 调用层

## Phase 3 - 测试与脚本整理

- 新增 `scripts/ci.py`
- 整理手工检查脚本到 `scripts/manual_checks/`
- 测试迁入 `tests/` 分层目录
- 清理历史 `collect_ignore`
