"""Kernel — 故事 OS 内核（Module 0.1）

蓝图原文（docs/Story_Engine_工程蓝图.md:81-134）：
上层所有模块通过 syscall 操作，不直接访问内部状态。
参考: AIOS(arXiv:2403.16971) + Eclipse Extension Point。

14 个 syscall 分 5 组：
  进程管理 (Agent Scheduler):  spawn_character / spawn_director / spawn_evaluator
  世界操作 (Event Sourced):     commit_event / query_world / snapshot /
                                rollback / branch_timeline / merge_branch
  记忆管理 (Context Manager):   recall / set_context_budget
  扩展系统:                     register_plugin / get_plugin
  HITL + LLM:                   request_human_input / llm_call

Phase 2 实现：
- 世界操作：完整工作（薄包装 EventStore）
- 进程管理：spawn 返回 ActorRef；spawn_character_actor 启动真实 CharacterActor
- 扩展系统：完整工作（薄包装 ExtensionRegistry）
- LLM：完整工作（薄包装 LLMPool）
- 记忆 recall：接 SemanticMemoryBanks + MemoryRetrieval（本地 embedding）
- branch_timeline / merge_branch / HITL：留 NotImplementedError（Phase 5）
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..types import (
    WorldEvent, WorldState, BranchID, SnapshotID, EventID,
    StoryEngineError,
)
from ..world.event_store import EventStore
from .registry import ExtensionRegistry, PluginManifest
from .llm_pool import LLMPool, LLMResponse
from .embedding import Embedder
from .actor_scheduler import ActorScheduler
from .actor import (
    ActorRef, CharacterConfig, GenreBundle, CriticConfig, HumanResponse,
)


# 蓝图 Module 0.1 列出的全部 syscall（供测试枚举校验）
SYSCALL_NAMES = [
    "spawn_character", "spawn_director", "spawn_evaluator",
    "commit_event", "query_world", "snapshot", "rollback",
    "branch_timeline", "merge_branch",
    "recall", "set_context_budget",
    "register_plugin", "get_plugin",
    "request_human_input", "llm_call",
]


class Kernel:
    """故事 OS 内核 — 不可插拔的核心"""

    def __init__(self, project_dir: str | Path,
                 initial_state_factory=None,
                 llm_pool: LLMPool | None = None,
                 embedder: Embedder | None = None,
                 plugin_dir: Path | None = None):
        self.project_dir = Path(project_dir)
        self.project_dir.mkdir(parents=True, exist_ok=True)

        self.registry = ExtensionRegistry()
        self.llm = llm_pool or LLMPool()
        # Phase 2：本地 Embedder（bge-small-zh via HF-Mirror）；测试可注入 mode=dummy
        self.embedder = embedder or Embedder()
        self.scheduler = ActorScheduler()
        self.store = EventStore(
            str(self.project_dir / "story.db"),
            initial_state_factory=initial_state_factory,
        )
        # 16-bank 记忆（与 EventStore 同库，独立表）；懒初始化
        self.memory_banks = None
        self._retrieval_by_agent: dict[str, Any] = {}

        # 自动加载插件（默认从 story_engine/plugins/ 递归找 *.yaml）
        if plugin_dir is not None:
            self._load_plugins(plugin_dir)

        self._human_input_handlers: list = []
        # branch registry：Phase 5 完整实现，先占位
        self._branches: dict[BranchID, SnapshotID] = {}

    def _load_plugins(self, plugin_dir: Path) -> None:
        for path in plugin_dir.rglob("*.yaml"):
            self.register_plugin(PluginManifest.load(path))

    # =========================================================
    # 进程管理 (Agent Scheduler)
    # =========================================================
    def spawn_character(self, config: CharacterConfig) -> ActorRef:
        """生成角色 actor，分配独立 mailbox 和上下文预算"""
        return self.scheduler.spawn_character(config)

    def spawn_director(self, config: GenreBundle) -> ActorRef:
        """生成 Showrunner agent，加载类型插件"""
        return self.scheduler.spawn_director(config)

    def spawn_evaluator(self, config: CriticConfig) -> ActorRef:
        """生成评估 critic agent"""
        return self.scheduler.spawn_evaluator(config)

    def set_context_budget(self, agent_id: str, max_tokens: int) -> None:
        """设置 agent 上下文预算（默认 8K）"""
        self.scheduler.set_context_budget(agent_id, max_tokens)

    # =========================================================
    # 世界操作 (Event Sourced)
    # =========================================================
    def commit_event(self, event: WorldEvent) -> EventID:
        """append 事件到日志，更新 projection"""
        return self.store.append(event)

    def query_world(self, predicate: str, **kwargs) -> Any:
        """CQRS 读侧：查询 projection（物化视图），不碰事件日志

        支持的 predicate:
          "current_state"   → WorldState（最新 projection）
          "head_tick"       → 当前 head tick
          "next_tick"       → 下一个可用 tick
          "all_events"      → 时间线视图全部事件（含 active 标记）
          "snapshots"       → 已打 snapshot 列表
          "raw_event"       → 按 event_id 单查（需 kwargs["event_id"]）
        """
        if predicate == "current_state":
            return self.store.current_state(kwargs.get("branch_id", "main"))
        if predicate == "head_tick":
            return self.store.head_tick(kwargs.get("branch_id", "main"))
        if predicate == "next_tick":
            return self.store.next_tick(kwargs.get("branch_id", "main"))
        if predicate == "all_events":
            return self.store.all_events(kwargs.get("branch_id", "main"))
        if predicate == "snapshots":
            return self.store.list_snapshots(kwargs.get("branch_id", "main"))
        if predicate == "raw_event":
            raise NotImplementedError("raw_event 查询 Phase 2 接入索引后实现")
        raise StoryEngineError(f"未知 query_world predicate: {predicate}")

    def snapshot(self, branch_id: BranchID = "main") -> SnapshotID:
        """打世界状态快照"""
        return self.store.snapshot(branch_id)

    def rollback(self, to: SnapshotID | EventID | int,
                 branch_id: BranchID = "main") -> None:
        """回滚到指定快照或事件点

        Phase 1 只支持 int（tick）；SnapshotID / EventID 留 Phase 5 完整实现。
        """
        if isinstance(to, int):
            return self.store.rollback(to, branch_id)
        raise NotImplementedError(
            f"rollback by {type(to).__name__} 是 Phase 5 任务，Phase 1 仅支持 int tick")

    def branch_timeline(self, from_: SnapshotID, name: str) -> BranchID:
        """git 式分支 — 作者实验用

        Phase 5 完整实现：拷贝快照+事件到新 branch_id；先抛 NotImplemented。
        """
        raise NotImplementedError("branch_timeline 是 Phase 5 任务")

    def merge_branch(self, branch: BranchID, strategy: str = "theirs") -> None:
        """合并分支（需定义合并策略）

        Phase 5 完整实现；先抛 NotImplemented。
        """
        raise NotImplementedError("merge_branch 是 Phase 5 任务")

    # =========================================================
    # 记忆管理 (Context Manager — L0 向量库)
    # =========================================================
    def _ensure_memory_banks(self):
        if self.memory_banks is not None:
            return self.memory_banks
        from ..character.memory_banks import SemanticMemoryBanks
        self.memory_banks = SemanticMemoryBanks(
            self.project_dir / "story.db",
            self.embedder,
        )
        return self.memory_banks

    async def recall(self, agent_id: str, query: str, budget: int = 4096) -> list:
        """从 L0 向量库召回（16-bank + 三因子 + 防膨胀）

        budget 按「大致 token 数」估算：每条记忆 ≈ 64 token → top_k ≈ budget/64。
        """
        banks = self._ensure_memory_banks()
        from ..character.retrieval import MemoryRetrieval
        if agent_id not in self._retrieval_by_agent:
            self._retrieval_by_agent[agent_id] = MemoryRetrieval(
                banks, agent_id=agent_id)
        retrieval = self._retrieval_by_agent[agent_id]
        top_k = max(3, min(30, budget // 64))
        return await retrieval.retrieve(query, top_k=top_k)

    def spawn_character_actor(self, config: CharacterConfig, *,
                              persona: dict | None = None) -> ActorRef:
        """Phase 2：spawn 真实 CharacterActor（含记忆 / SOAR）"""
        from ..character.actor import CharacterActor
        from ..character.voice import VoiceProfile
        banks = self._ensure_memory_banks()
        voice = VoiceProfile.from_seed(config.character_id, persona or {})
        actor = CharacterActor(
            config, self, memory_banks=banks, voice=voice, persona=persona)
        return self.scheduler.spawn_character(config, actor_instance=actor)

    # =========================================================
    # 扩展系统
    # =========================================================
    def register_plugin(self, manifest: PluginManifest) -> None:
        """注册插件到 Extension Point Registry"""
        self.registry.register(manifest)

    def get_plugin(self, extension_point: str, name: str,
                   context: dict | None = None) -> Any:
        """按扩展点+名称获取插件实例（lazy activation）"""
        return self.registry.get(extension_point, name, context)

    # =========================================================
    # HITL
    # =========================================================
    def request_human_input(self, prompt: str, context: dict) -> HumanResponse:
        """请求作者介入，返回介入结果+记录 AuthorIntervention 事件

        Phase 5（HITL）实现；先抛 NotImplemented。
        """
        raise NotImplementedError("request_human_input 是 Phase 5 任务（HITL）")

    # =========================================================
    # LLM 调用
    # =========================================================
    async def llm_call(self, prompt: str, *,
                       purpose: str = "generate",
                       temperature: float = 0.7,
                       max_tokens: int = 8192) -> LLMResponse:
        """统一 LLM 调用入口，多 provider 路由"""
        return await self.llm.call(
            prompt, purpose=purpose, temperature=temperature, max_tokens=max_tokens)

    # =========================================================
    # 内部辅助（非 syscall，但被 StoryEngine 用到）
    # =========================================================
    def close(self) -> None:
        self.store.close()
        if self.memory_banks is not None:
            try:
                self.memory_banks.close()
            except Exception:
                pass
        try:
            self.embedder.close()
        except Exception:
            pass
