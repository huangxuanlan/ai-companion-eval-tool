"""
prompt_template_lib — 提示词模板加载 / 渲染 / 版本管理

抽自 services/prompt_service.py + services/prompt_version_service.py（W0 ADR-005 / 1 人天）

公开 API：
- PromptService — 提示词模板加载 / 渲染 / 变量注入主类
- VersionedPromptStore — 摘要 / 打分提示词版本管理（list / load / save / activate）
- list_chat_prompts — 聊天提示词清单工具函数

共享对象：长文 / 短文 / 桥接（覆盖所有 prompt 加载路径）
"""

from .service import PromptService
from .version import VersionedPromptStore, list_chat_prompts

__all__ = [
    "PromptService",
    "VersionedPromptStore",
    "list_chat_prompts",
]
