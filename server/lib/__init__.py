"""
server.lib — 双模式融合工具 v6.0 共享 library 集合（W0 ADR-005）

按 README v2.4 ADR-005 抽取自原 services/，长文 / 短文 / 桥接共享：

| Library | 来源 | 共享对象 |
|:---|:---|:---|
| format_lint_lib | services/format_lint_core.py | 桥接（主用）+ 长 / 短 |
| model_adapter_lib | services/model_adapter.py + local_openai_provider.py | 长 / 短 / 桥接 |
| prompt_template_lib | services/prompt_service.py + prompt_version_service.py | 长 / 短 / 桥接 |
| prompt_scoring_lib | services/scoring_service.py + live_scoring_dispatcher.py | 长 / 短 / 桥接 |

向后兼容期：services/ 下保留 shim re-export，1 个 Sprint 后由 W0.1 评估清理。
"""
