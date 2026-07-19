"""CharacterActor — 角色 Actor + SOAR 决策循环（Module 2.1）

蓝图 docs/Story_Engine_工程蓝图.md:614-688。
每个角色 = 独立 Actor：异步消息、独立状态、故障隔离。

SOAR 五步（_on_tick）：
  1. recall   — kernel.recall / MemoryRetrieval
  2. propose  — LLM 一次生成候选行动（JSON 数组）
  3. evaluate — 规则评分（goal 一致性 + 关系强度），不调 LLM
  4. decide   — 选最高分
  5. apply    — kernel.commit_event + learn（写记忆）
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from ..kernel.actor import ActorRef, CharacterConfig
from ..types import WorldEvent, WorldState
from .memory_banks import SemanticMemoryBanks
from .retrieval import MemoryRetrieval
from .voice import VoiceProfile, ReflectionTrigger


@dataclass
class ActorMessage:
    type: str                          # world_tick / perceive_event / dialogue_request / author_intervention
    payload: Any = None
    sender: str = ""


@dataclass
class ActionCandidate:
    action: str
    summary: str = ""
    serves_goal: str = ""
    motivation: str = ""
    effects: dict = field(default_factory=dict)
    score: float = 0.0
    raw: dict = field(default_factory=dict)


@dataclass
class WorkingMemory:
    """工作记忆 — 简化为 list（蓝图 ~8K context）"""
    items: list[str] = field(default_factory=list)
    max_items: int = 32

    def update(self, texts: list[str]) -> None:
        self.items.extend(texts)
        if len(self.items) > self.max_items:
            self.items = self.items[-self.max_items:]

    def as_prompt(self) -> str:
        return "\n".join(f"- {t}" for t in self.items[-16:])


class CharacterActor:
    """角色 actor — 接收 world_tick，自主决策，提交事件"""

    def __init__(
        self,
        config: CharacterConfig,
        kernel,
        *,
        memory_banks: SemanticMemoryBanks | None = None,
        voice: VoiceProfile | None = None,
        persona: dict | None = None,
    ):
        self.id = config.character_id
        self.config = config
        self.kernel = kernel
        self.mailbox: asyncio.Queue = asyncio.Queue()
        self.persona = persona or {}
        self.voice = voice or VoiceProfile.from_seed(self.id, self.persona)
        self.working = WorkingMemory()
        self.goals = list(config.initial_goals) or list(
            (self.persona.get("goals") if isinstance(self.persona.get("goals"), list) else [])
            or []
        )
        self.memory_banks = memory_banks
        self.retrieval = (
            MemoryRetrieval(memory_banks, agent_id=self.id)
            if memory_banks is not None else None
        )
        self.reflection = ReflectionTrigger()
        self._alive = True
        self._task: asyncio.Task | None = None
        self._idle = asyncio.Event()
        self._idle.set()  # 初始空闲
        self.last_actions: list[dict] = []   # 最近提交的事件摘要（测试/汇总用）
        self.error_count = 0

    # ---------- lifecycle ----------
    def start(self) -> ActorRef:
        """注册 Actor；若已有 running loop 则立刻启动 receive，否则推迟到 ensure_started。"""
        try:
            loop = asyncio.get_running_loop()
            if self._task is None or self._task.done():
                self._task = loop.create_task(
                    self._loop(), name=f"actor:{self.id}")
        except RuntimeError:
            # 同步 spawn 时尚无 event loop（测试/Engine 构造期）— 延迟启动
            pass
        return ActorRef(
            actor_id=self.id, actor_type="character",
            mailbox_addr=f"mb://{self.id}",
        )

    async def ensure_started(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(
                self._loop(), name=f"actor:{self.id}")

    async def stop(self) -> None:
        self._alive = False
        await self.mailbox.put(ActorMessage(type="_stop"))
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()

    async def send(self, message: ActorMessage) -> None:
        await self.mailbox.put(message)

    async def wait_idle(self, timeout: float = 60.0) -> None:
        """等到 mailbox 空且当前消息处理完毕"""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if self.mailbox.empty() and self._idle.is_set():
                return
            await asyncio.sleep(0.02)
        raise asyncio.TimeoutError(f"actor {self.id} wait_idle timeout")

    async def _loop(self) -> None:
        while self._alive:
            try:
                msg = await self.mailbox.get()
                if msg.type == "_stop":
                    break
                self._idle.clear()
                try:
                    await self.receive(msg)
                finally:
                    self._idle.set()
            except Exception:
                self.error_count += 1
                self._idle.set()
                # let-it-crash：吞掉单条消息异常，不杀死循环
                continue

    async def receive(self, message: ActorMessage) -> None:
        match message.type:
            case "world_tick":
                await self._on_tick(message.payload)
            case "perceive_event":
                await self._on_perceive(message.payload)
            case "dialogue_request":
                await self._on_dialogue(message.payload)
            case "author_intervention":
                await self._on_intervention(message.payload)
            case _:
                pass

    # ---------- SOAR ----------
    async def _on_tick(self, payload: Any) -> None:
        """SOAR：propose→evaluate→decide→apply→learn"""
        world_state = payload.get("world_state") if isinstance(payload, dict) else payload
        chapter = payload.get("chapter", 0) if isinstance(payload, dict) else 0
        scene = ""
        if isinstance(world_state, WorldState):
            scene = world_state.narrative.current_scene or ""
        elif isinstance(world_state, dict):
            scene = (world_state.get("narrative") or {}).get("current_scene", "")

        # 1. recall
        context_texts: list[str] = []
        if self.retrieval is not None:
            try:
                items = await self.retrieval.retrieve(
                    scene or f"{self.id} 当前行动", top_k=8)
                context_texts = [it.content for it in items]
            except Exception:
                context_texts = []
        elif hasattr(self.kernel, "recall"):
            try:
                recalled = await self._safe_recall(scene or self.id)
                context_texts = [
                    (r.content if hasattr(r, "content") else str(r))
                    for r in (recalled or [])
                ]
            except Exception:
                context_texts = []
        self.working.update(context_texts)

        # 2. propose
        candidates = await self._propose_actions(world_state, chapter)
        if not candidates:
            return

        # 3. evaluate
        for c in candidates:
            c.score = self._evaluate_action(c, world_state)

        # 4. decide
        best = max(candidates, key=lambda x: x.score)

        # 5. apply + learn
        event = self._make_action_event(best, chapter)
        self.kernel.commit_event(event)
        self.last_actions.append({
            "event_id": event.event_id,
            "summary": best.summary or best.action,
            "score": best.score,
            "tick": event.world_tick,
        })
        await self._learn(best, event)

    async def _safe_recall(self, query: str) -> list:
        result = self.kernel.recall(self.id, query, budget=2048)
        if asyncio.iscoroutine(result):
            return await result
        return result

    async def _propose_actions(self, world_state: Any, chapter: int) -> list[ActionCandidate]:
        """LLM 一次生成候选行动；失败则用规则兜底"""
        goals = "、".join(self.goals) or "完成当前职责"
        scene = ""
        if isinstance(world_state, WorldState):
            scene = world_state.narrative.current_scene
        prompt = (
            f"你是角色「{self.id}」。{self.voice.prompt_snippet()}\n"
            f"活跃目标：{goals}\n"
            f"当前场景：{scene or '未知'}\n"
            f"工作记忆：\n{self.working.as_prompt() or '（空）'}\n\n"
            "请提出 2-3 个可能的下一步行动。只输出 JSON 数组，每项：\n"
            '{"action":"...","summary":"一句话","serves_goal":"...","motivation":"...",'
            '"effects":{"learn":{"角色":["事实"]}}}\n'
            "不要解释。"
        )
        try:
            resp = await self.kernel.llm_call(
                prompt, purpose=f"propose:{self.id}", temperature=0.6, max_tokens=1024)
            text = resp.text if hasattr(resp, "text") else str(resp)
            data = self._parse_json_array(text)
            out = []
            for d in data[:3]:
                if not isinstance(d, dict) or "action" not in d:
                    continue
                out.append(ActionCandidate(
                    action=str(d["action"]),
                    summary=str(d.get("summary") or d["action"]),
                    serves_goal=str(d.get("serves_goal") or (self.goals[0] if self.goals else "")),
                    motivation=str(d.get("motivation") or ""),
                    effects=d.get("effects") if isinstance(d.get("effects"), dict) else {},
                    raw=d,
                ))
            if out:
                return out
        except Exception:
            pass
        # 规则兜底：一个服务于第一个目标的默认行动
        goal = self.goals[0] if self.goals else "观察局势"
        return [ActionCandidate(
            action=f"{self.id}继续推进「{goal}」",
            summary=f"{self.id}围绕「{goal}」采取行动",
            serves_goal=goal,
            motivation=goal,
        )]

    def _evaluate_action(self, action: ActionCandidate, world_state: Any) -> float:
        """规则评分：goal 命中 +0.5，有 summary +0.2，有 effects +0.2，基线 0.1"""
        score = 0.1
        if action.serves_goal and action.serves_goal in self.goals:
            score += 0.5
        elif action.serves_goal:
            score += 0.2
        if action.summary:
            score += 0.2
        if action.effects:
            score += 0.2
        return score

    def _make_action_event(self, action: ActionCandidate, chapter: int) -> WorldEvent:
        tick = self.kernel.query_world("next_tick")
        payload = {
            "agent": self.id,
            "action": action.action,
            "summary": action.summary,
            "serves_goal": action.serves_goal,
            "motivation": action.motivation or action.serves_goal,
            "effects": action.effects,
            "chapter": chapter,
        }
        return WorldEvent(
            event_id=str(uuid4())[:8],
            event_type="character_action",
            timestamp=datetime.now().isoformat(timespec="seconds"),
            world_tick=tick,
            branch_id="main",
            payload=payload,
        )

    async def _learn(self, action: ActionCandidate, event: WorldEvent) -> None:
        """写入情景记忆；触发反思时写 semantic bank"""
        if self.memory_banks is None:
            return
        importance = 5 + (2 if action.serves_goal in self.goals else 0)
        item = await self.memory_banks.add(
            action.summary or action.action,
            bank="decision_log",
            agent_id=self.id,
            metadata={"event_id": event.event_id, "action": action.action},
            importance=importance,
        )
        if self.reflection.observe(importance):
            await self._reflect([item])

    async def _reflect(self, recent_items: list) -> None:
        """反思：把近期事件压缩成一条高层洞察，写入 continuity_facts"""
        if self.memory_banks is None:
            return
        texts = [getattr(it, "content", str(it)) for it in recent_items]
        summary = f"{self.id}反思：近期围绕「{'；'.join(texts[:3])}」"
        try:
            resp = await self.kernel.llm_call(
                f"用一句话总结角色「{self.id}」从这些事件中学到的洞察：\n"
                + "\n".join(f"- {t}" for t in texts),
                purpose=f"reflect:{self.id}", temperature=0.3, max_tokens=256)
            text = (resp.text if hasattr(resp, "text") else str(resp)).strip()
            if text:
                summary = text[:200]
        except Exception:
            pass
        await self.memory_banks.add(
            summary, bank="continuity_facts", agent_id=self.id,
            metadata={"kind": "reflection"}, importance=8,
        )
        if self.retrieval is not None:
            for it in recent_items:
                if getattr(it, "id", 0):
                    self.retrieval.mark_absorbed(it.id)
        self.reflection.reset()

    async def _on_perceive(self, payload: Any) -> None:
        """感知世界事件，存入情景记忆"""
        if self.memory_banks is None:
            return
        if isinstance(payload, WorldEvent):
            content = payload.payload.get("summary") or payload.event_type
            importance = 6
            event_id = payload.event_id
        elif isinstance(payload, dict):
            content = payload.get("summary") or payload.get("content") or str(payload)
            importance = int(payload.get("importance", 5))
            event_id = payload.get("event_id", "")
        else:
            content = str(payload)
            importance = 5
            event_id = ""
        item = await self.memory_banks.add(
            content, bank="working_set", agent_id=self.id,
            metadata={"event_id": event_id, "kind": "perceive"},
            importance=importance,
        )
        if self.reflection.observe(importance):
            await self._reflect([item])

    async def _on_dialogue(self, payload: Any) -> None:
        # Phase 3+ 对白系统；本次仅记入记忆
        await self._on_perceive(payload)

    async def _on_intervention(self, payload: Any) -> None:
        await self._on_perceive({"summary": f"作者介入：{payload}", "importance": 9})

    @staticmethod
    def _parse_json_array(text: str) -> list:
        text = (text or "").strip()
        if "```" in text:
            m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
            if m:
                text = m.group(1).strip()
        start, end = text.find("["), text.rfind("]")
        if start >= 0 and end > start:
            text = text[start:end + 1]
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            try:
                data = json.loads(re.sub(r",(\s*[}\]])", r"\1", text))
            except (json.JSONDecodeError, TypeError):
                return []
        return data if isinstance(data, list) else []
