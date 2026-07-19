"""Kernel 数据类 — Actor 系统的类型契约（Module 0.1 占位）

蓝图原文（docs/Story_Engine_工程蓝图.md:81-134）：
- spawn_character(CharacterConfig) → ActorRef
- spawn_director(GenreBundle) → ActorRef
- spawn_evaluator(CriticConfig) → ActorRef

这些数据类在 Phase 1 只是接口契约；Phase 2 接 CharacterActor 时会填充真实字段。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..types import GenreBundle  # 权威定义在 types.py（Phase 3 统一）；此处 re-export 兼容旧 import 路径


@dataclass
class CharacterConfig:
    """角色 Actor 配置（Phase 2 接 CharacterActor 时使用）"""
    character_id: str
    archetype: str = ""              # 原型 ID（来自 story.character.archetype 插件）
    voice_profile: dict[str, Any] = field(default_factory=dict)  # 声音档案
    initial_goals: list[str] = field(default_factory=list)
    context_budget: int = 8192       # 上下文 token 预算


@dataclass
class CriticConfig:
    """评估 Critic Agent 配置"""
    active_critics: list[str] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)
    iteration_rounds: int = 2        # best-of-K 轮数


@dataclass
class ActorRef:
    """Actor 引用 — 通过它给 actor 发消息（Phase 2 实现 mailbox）"""
    actor_id: str
    actor_type: str                  # "character" / "director" / "evaluator"
    mailbox_addr: str = ""           # Phase 2 接真实 mailbox 后填


@dataclass
class HumanResponse:
    """HITL 介入结果（Phase 5 接真实 HITL）"""
    accepted: bool
    payload: dict[str, Any] = field(default_factory=dict)
    note: str = ""
