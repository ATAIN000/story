"""Kernel 子包 — 故事 OS 内核（Module 0.1/0.2/0.4/Phase 2 L0 向量层）

公开 API：
  Kernel              — 内核类，15 个 syscall 入口
  ExtensionRegistry   — 扩展点注册表
  PluginManifest      — 插件清单
  PluginInstance      — 插件实例（懒加载后）
  LLMPool             — LLM 调用池
  Embedder            — 本地文本向量（bge-small-zh via HF-Mirror；测试可用 dummy）
  ActorScheduler      — Agent 调度器
  ActorRef/CharacterConfig/GenreBundle/CriticConfig — Actor 配置数据类
"""
from .syscalls import Kernel, SYSCALL_NAMES
from .registry import (
    EXTENSION_POINTS, ExtensionRegistry, PluginManifest, PluginInstance,
)
from .llm_pool import LLMPool, LLMResponse, LLMError, KIMI_CODE_UA
from .embedding import Embedder, EmbedderError
from .actor_scheduler import ActorScheduler
from .actor import (
    ActorRef, CharacterConfig, GenreBundle, CriticConfig, HumanResponse,
)

# 向后兼容：旧代码 `from story_engine.llm import LLMClient`
LLMClient = LLMPool

__all__ = [
    "Kernel", "SYSCALL_NAMES",
    "EXTENSION_POINTS", "ExtensionRegistry", "PluginManifest", "PluginInstance",
    "LLMPool", "LLMClient", "LLMResponse", "LLMError", "KIMI_CODE_UA",
    "Embedder", "EmbedderError",
    "ActorScheduler",
    "ActorRef", "CharacterConfig", "GenreBundle", "CriticConfig", "HumanResponse",
]
