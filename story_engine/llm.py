"""[向后兼容 shim] llm 已迁移到 story_engine.kernel.llm_pool

旧代码 `from story_engine.llm import LLMClient, LLMError` 仍可用。
新代码请用 `from story_engine.kernel.llm_pool import LLMPool`。
"""
from .kernel.llm_pool import LLMPool, LLMResponse, LLMError, KIMI_CODE_UA

# 向后兼容
LLMClient = LLMPool

__all__ = ["LLMPool", "LLMClient", "LLMResponse", "LLMError", "KIMI_CODE_UA"]
