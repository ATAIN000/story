"""ActorScheduler — Agent 进程管理（Module 0.1 + Phase 2 真异步）

Phase 2：spawn 时创建 CharacterActor + asyncio.Queue mailbox + Task；
提供 tick_all() 让 Showrunner/Engine 并行推进所有角色。
"""
from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from .actor import ActorRef, CharacterConfig, GenreBundle, CriticConfig


class ActorScheduler:
    """Agent 调度器 — Phase 2 真异步实现"""

    def __init__(self):
        self._actors: dict[str, dict[str, Any]] = {}
        self._context_budgets: dict[str, int] = {}
        # character_id → CharacterActor 实例（仅 character 类型）
        self._character_actors: dict[str, Any] = {}
        # 兼容旧 stub 测试：list mailbox
        self._mailboxes: dict[str, list] = {}

    def spawn_character(self, config: CharacterConfig, *,
                        actor_instance: Any = None) -> ActorRef:
        """spawn 角色。若传入 actor_instance（CharacterActor），启动其 receive 循环。"""
        ref = self._spawn("character", config.character_id, config.context_budget)
        if actor_instance is not None:
            self._character_actors[ref.actor_id] = actor_instance
            actor_instance.start()
        return ref

    def spawn_director(self, config: GenreBundle) -> ActorRef:
        return self._spawn("director", f"director:{config.genre}:{config.culture}", 16384)

    def spawn_evaluator(self, config: CriticConfig) -> ActorRef:
        return self._spawn("evaluator", f"evaluator:{uuid4().hex[:6]}", 8192)

    def _spawn(self, actor_type: str, suggested_id: str, budget: int) -> ActorRef:
        actor_id = suggested_id or f"{actor_type}:{uuid4().hex[:8]}"
        if actor_id in self._actors:
            actor_id = f"{actor_id}:{uuid4().hex[:4]}"
        ref = ActorRef(actor_id=actor_id, actor_type=actor_type, mailbox_addr=f"mb://{actor_id}")
        self._actors[actor_id] = {"ref": ref, "type": actor_type}
        self._context_budgets[actor_id] = budget
        self._mailboxes[actor_id] = []
        return ref

    def send(self, ref: ActorRef, message: dict) -> None:
        """同步入队（兼容旧 stub 测试）；真异步请用 send_async"""
        self._mailboxes.setdefault(ref.actor_id, []).append(message)

    async def send_async(self, ref: ActorRef, message: Any) -> None:
        actor = self._character_actors.get(ref.actor_id)
        if actor is not None:
            from ..character.actor import ActorMessage
            if not isinstance(message, ActorMessage):
                if isinstance(message, dict):
                    message = ActorMessage(
                        type=message.get("type", "world_tick"),
                        payload=message.get("payload", message),
                    )
                else:
                    message = ActorMessage(type="world_tick", payload=message)
            await actor.send(message)
        else:
            self.send(ref, message if isinstance(message, dict) else {"payload": message})

    def drain(self, ref: ActorRef) -> list[dict]:
        msgs = list(self._mailboxes.get(ref.actor_id, []))
        self._mailboxes[ref.actor_id] = []
        return msgs

    def set_context_budget(self, actor_id: str, max_tokens: int) -> None:
        if actor_id not in self._actors:
            raise KeyError(f"unknown actor: {actor_id}")
        self._context_budgets[actor_id] = max_tokens

    def get_context_budget(self, actor_id: str) -> int:
        return self._context_budgets.get(actor_id, 0)

    def list_actors(self) -> list[str]:
        return list(self._actors.keys())

    def get_character_actor(self, actor_id: str) -> Any:
        return self._character_actors.get(actor_id)

    async def tick_all(self, world_state: Any, *, chapter: int = 0,
                       timeout: float = 60.0) -> list[dict]:
        """向所有 CharacterActor 广播 world_tick，并行等待处理完成。

        返回各 actor 本 tick 提交的 last_actions 增量。
        """
        from ..character.actor import ActorMessage
        if not self._character_actors:
            return []
        # 确保 receive 循环已在当前 event loop 上启动
        await asyncio.gather(*[
            actor.ensure_started()
            for actor in self._character_actors.values()
        ])
        snapshots = {
            aid: len(actor.last_actions)
            for aid, actor in self._character_actors.items()
        }
        # 并行入队
        await asyncio.gather(*[
            actor.send(ActorMessage(
                type="world_tick",
                payload={"world_state": world_state, "chapter": chapter},
            ))
            for actor in self._character_actors.values()
        ])
        # 等到全部空闲（mailbox 空 + 当前消息处理完）
        await asyncio.gather(*[
            asyncio.wait_for(actor.wait_idle(timeout=timeout), timeout=timeout)
            for actor in self._character_actors.values()
        ], return_exceptions=True)

        results = []
        for aid, actor in self._character_actors.items():
            new_actions = actor.last_actions[snapshots[aid]:]
            results.extend({"actor_id": aid, **a} for a in new_actions)
        return results

    async def stop_all(self) -> None:
        for actor in list(self._character_actors.values()):
            try:
                await actor.stop()
            except Exception:
                pass
        self._character_actors.clear()
