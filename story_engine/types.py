"""全局类型系统 — 接口规范 Part 1 的可运行实现（demo 级精简）

所有 Module 共享的核心数据结构。约定：
- WorldEvent 不可变（frozen dataclass），是所有状态变化的唯一合法途径
- WorldState 是事件流 fold 出来的只读 projection
- 所有实体用 str 类型 ID
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Literal, NewType

CharacterID = str
EventID = str
SnapshotID = str
BranchID = str
Tick = int
PluginName = str

EventType = Literal[
    "character_action",   # 角色行动
    "world_change",       # 世界变化
    "narrative_beat",     # 叙事节拍
    "dialogue",           # 对话
    "scene_transition",   # 场景转换
    "author_intervention",# 作者介入
    "branch_fork",        # 分支创建
]


class StoryEngineError(Exception):
    """所有领域异常的基类"""


class ConsistencyViolationError(StoryEngineError):
    """硬约束验证失败"""
    def __init__(self, failures: dict[str, str]):
        self.failures = failures
        super().__init__(f"一致性验证失败: {failures}")


class PluginNotFoundError(StoryEngineError):
    def __init__(self, extension_point: str, name: str):
        super().__init__(f"插件未找到: {extension_point}/{name}")


@dataclass(frozen=True)
class WorldEvent:
    """不可变事件 — 事件溯源的核心单元"""
    event_id: EventID
    event_type: str
    timestamp: str          # ISO 格式
    world_tick: Tick
    branch_id: BranchID
    payload: dict[str, Any]
    schema_version: int = 1
    timeline: int = 0       # 时间线编号：回滚后递增（同 tick 最新 timeline 生效）

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "WorldEvent":
        return cls(**d)


@dataclass
class Relation:
    """角色间关系（CiF 式数值化）"""
    type: str               # 敌对/信任/上下级/...
    intensity: float        # 0-1
    history: list[str] = field(default_factory=list)


@dataclass
class Intention:
    """IPOCL 承诺框架的一个步骤 <character, goal, intention_step>"""
    character: CharacterID
    goal: str
    step_index: int = 0
    satisfied: bool = False


@dataclass
class CharacterMind:
    """角色心智状态（Epistemic EC + IPOCL + 情感）"""
    character_id: CharacterID
    beliefs: dict[str, bool] = field(default_factory=dict)   # knows(X, fact)
    secrets: list[str] = field(default_factory=list)          # 角色自己持有的秘密
    goals: list[str] = field(default_factory=list)            # 活跃目标（概念ID）
    affect: dict[str, float] = field(default_factory=dict)    # {anger: 0.7, ...}


@dataclass
class ForeshadowTriple:
    """CFPG: Foreshadow-Trigger-Payoff 伏笔三元组"""
    foreshadow_id: str
    content: str                  # 伏笔内容
    planted_at_tick: Tick
    planted_chapter: int
    trigger_condition: str        # 什么时候触发回报
    payoff: str                   # 回报内容
    payed_off: bool = False
    payed_at_chapter: int | None = None
    required: bool = True


@dataclass
class NarrativeState:
    """叙事层状态"""
    act: int = 1
    chapter: int = 0
    tension: float = 0.3
    current_scene: str = ""
    foreshadow_pool: list[ForeshadowTriple] = field(default_factory=list)
    track_progress: dict[str, float] = field(default_factory=dict)
    causal_links: list[str] = field(default_factory=list)     # 已确立的因果链节点
    last_story_time: str = ""                                 # 故事内时间（时序检查基准）


@dataclass
class WorldState:
    """世界状态 — 事件流的 fold 结果（CQRS 读侧 projection）"""
    tick: Tick = 0
    branch_id: BranchID = "main"
    physical: dict[str, Any] = field(default_factory=dict)     # {"at(包拯,开封府)": True, ...}
    relationships: dict[str, Relation] = field(default_factory=dict)  # "包拯|展昭" -> Relation
    minds: dict[CharacterID, CharacterMind] = field(default_factory=dict)
    narrative: NarrativeState = field(default_factory=NarrativeState)
    characters: dict[str, dict] = field(default_factory=dict)  # 角色静态档案

    # ---- 序列化 ----
    def to_dict(self) -> dict:
        return {
            "tick": self.tick,
            "branch_id": self.branch_id,
            "physical": self.physical,
            "relationships": {k: asdict(v) for k, v in self.relationships.items()},
            "minds": {k: asdict(v) for k, v in self.minds.items()},
            "narrative": {
                **{f: getattr(self.narrative, f) for f in
                   ("act", "chapter", "tension", "current_scene",
                    "track_progress", "causal_links", "last_story_time")},
                "foreshadow_pool": [asdict(fs) for fs in self.narrative.foreshadow_pool],
            },
            "characters": self.characters,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WorldState":
        n = d["narrative"]
        narrative = NarrativeState(
            act=n["act"], chapter=n["chapter"], tension=n["tension"],
            current_scene=n["current_scene"],
            foreshadow_pool=[ForeshadowTriple(**fs) for fs in n["foreshadow_pool"]],
            track_progress=n["track_progress"],
            causal_links=n["causal_links"],
            last_story_time=n.get("last_story_time", ""),
        )
        return cls(
            tick=d["tick"], branch_id=d["branch_id"],
            physical=d["physical"],
            relationships={k: Relation(**v) for k, v in d["relationships"].items()},
            minds={k: CharacterMind(**v) for k, v in d["minds"].items()},
            narrative=narrative,
            characters=d.get("characters", {}),
        )

    # ---- fold ----
    def apply(self, event: WorldEvent) -> None:
        """把事件 fold 进 projection（事件溯源的状态推进）"""
        self.tick = event.world_tick
        handler = EVENT_HANDLERS.get(event.event_type)
        if handler:
            handler(self, event.payload)


# ============ 事件 → 状态 的 fold 逻辑 ============

def _h_character_action(state: WorldState, p: dict) -> None:
    agent = p.get("agent")
    effects = p.get("effects", {})
    # 物理效果：set_fluents / unset_fluents
    for f in effects.get("set_fluents", []):
        state.physical[f] = True
    for f in effects.get("unset_fluents", []):
        state.physical.pop(f, None)
    # 认知效果：agent 或他人获知事实
    for who, facts in effects.get("learn", {}).items():
        mind = state.minds.setdefault(who, CharacterMind(who))
        for fact in facts:
            mind.beliefs[fact] = True
    # 关系效果
    for rel_key, rel in effects.get("relations", {}).items():
        r = state.relationships.setdefault(rel_key, Relation(rel["type"], rel["intensity"]))
        r.type = rel["type"]
        r.intensity = rel["intensity"]
        if rel.get("note"):
            r.history.append(rel["note"])
    # 因果链
    if p.get("motivation"):
        link = f"{p['motivation']}→{p.get('action', '')}"
        if link not in state.narrative.causal_links:
            state.narrative.causal_links.append(link)
    if p.get("establishes_cause"):
        for c in p["establishes_cause"]:
            if c not in state.narrative.causal_links:
                state.narrative.causal_links.append(c)


def _h_world_change(state: WorldState, p: dict) -> None:
    if p.get("field") == "story_time":
        state.narrative.last_story_time = p["new_value"]
    else:
        state.physical[f"{p.get('field')}={p.get('new_value')}"] = True


def _h_narrative_beat(state: WorldState, p: dict) -> None:
    state.narrative.current_scene = p.get("scene", state.narrative.current_scene)
    state.narrative.tension = p.get("tension", state.narrative.tension)
    if p.get("chapter"):
        state.narrative.chapter = p["chapter"]
    if p.get("act"):
        state.narrative.act = p["act"]
    for track, prog in p.get("track_progress", {}).items():
        state.narrative.track_progress[track] = prog
    if "foreshadow_sync" in p:
        # CFPG 伏笔池整池同步（种新伏笔/标记回收由 pipeline 计算后随事件持久化）
        state.narrative.foreshadow_pool = [
            ForeshadowTriple(**fs) for fs in p["foreshadow_sync"]]


def _h_dialogue(state: WorldState, p: dict) -> None:
    pass  # 对话内容进章节文本，状态不变（认知变化走 character_action 的 learn）


def _h_scene_transition(state: WorldState, p: dict) -> None:
    state.narrative.current_scene = p.get("scene", state.narrative.current_scene)


def _h_author_intervention(state: WorldState, p: dict) -> None:
    pass


def _h_branch_fork(state: WorldState, p: dict) -> None:
    pass


EVENT_HANDLERS = {
    "character_action": _h_character_action,
    "world_change": _h_world_change,
    "narrative_beat": _h_narrative_beat,
    "dialogue": _h_dialogue,
    "scene_transition": _h_scene_transition,
    "author_intervention": _h_author_intervention,
    "branch_fork": _h_branch_fork,
}


@dataclass
class Check:
    """单步验证结果"""
    name: str
    label: str
    passed: bool
    reason: str = ""


@dataclass
class Verdict:
    """7 步验证总结果"""
    passed: bool
    checks: list[Check]

    @property
    def failures(self) -> dict[str, str]:
        return {c.name: c.reason for c in self.checks if not c.passed}
