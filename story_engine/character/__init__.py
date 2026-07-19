"""Character 子包 — 角色代理系统（蓝图 Module 2.x）

Phase 2 实现：
  memory_banks — 16-bank 语义记忆（Module 2.2）
  retrieval    — 三因子检索 + 防膨胀八层（Module 2.3）
  actor        — CharacterActor + SOAR 5 步决策循环（Module 2.1）
  voice        — VoiceProfile + 反思机制（Module 2.4/2.5）
"""
from .memory_banks import (
    MEMORY_BANKS, MEMORY_BANK_LAYERS, MemoryItem, SemanticMemoryBanks,
)
from .retrieval import (
    MemoryRetrieval, RetrievalConfig,
    WEIGHT_RECENCY, WEIGHT_RELEVANCE, WEIGHT_IMPORTANCE,
)
from .actor import CharacterActor, ActorMessage, ActionCandidate, WorkingMemory
from .voice import VoiceProfile, ReflectionTrigger

__all__ = [
    "MEMORY_BANKS", "MEMORY_BANK_LAYERS",
    "MemoryItem", "SemanticMemoryBanks",
    "MemoryRetrieval", "RetrievalConfig",
    "WEIGHT_RECENCY", "WEIGHT_RELEVANCE", "WEIGHT_IMPORTANCE",
    "CharacterActor", "ActorMessage", "ActionCandidate", "WorkingMemory",
    "VoiceProfile", "ReflectionTrigger",
]
