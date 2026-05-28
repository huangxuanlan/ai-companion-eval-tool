"""
model_adapter_lib — 多模型统一调用适配器

抽自 services/model_adapter.py + services/local_openai_provider.py（W0 ADR-005 / 2 人天）

公开 API：
- ModelAdapter — 多模型适配器主类（统一 chat() 接口、Provider 加载、Google Key 轮转）
- ChatResult — 模型调用结果统一容器
- LocalOpenAIProvider — OpenAI 兼容 provider（豆包 / DeepSeek / Qwen 等）

共享对象：长文 / 短文 / 桥接（覆盖所有 LLM 调用路径）
"""

from .adapter import (
    ChatResult,
    ModelAdapter,
)
from .openai_provider import LocalOpenAIProvider

__all__ = [
    "ChatResult",
    "ModelAdapter",
    "LocalOpenAIProvider",
]
