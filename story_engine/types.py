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

# LLM 产出 effects 的 learn 字段形态归一（热修复 2026-07-20：
# 真实 GLM 偶发把 learn 写成 ["包拯得知…", "公孙策得知…"] 平铺 list 而非
# {"角色": ["事实"]} dict，fold 在 .items() 处崩溃 → plan/generate 500）
_LEARN_PREFIX_RE = None


def normalize_learn(effects, agent: str, known: set[str] | None = None) -> dict:
    """把 effects["learn"] 归一为 dict[who, list[str]]。

    - dict：值统一包成 list
    - list[str]：按「X得知/知道/获悉/听闻/听说」前缀归属（known 非空时校验），
      无前缀或归属失败 → 计入 agent
    - 其他：忽略该键
    """
    global _LEARN_PREFIX_RE
    if not isinstance(effects, dict):
        return {}
    out = dict(effects)
    learn = effects.get("learn")
    if learn is None:
        return out
    if isinstance(learn, dict):
        out["learn"] = {w: (v if isinstance(v, list) else [v])
                        for w, v in learn.items()}
        return out
    if isinstance(learn, list):
        import re
        if _LEARN_PREFIX_RE is None:
            _LEARN_PREFIX_RE = re.compile(
                r"^(.{2,4}?)(?:得知|知道|获悉|听闻|听说)")
        merged: dict[str, list] = {}
        for item in learn:
            if not isinstance(item, str):
                continue
            m = _LEARN_PREFIX_RE.match(item)
            if m and (known is None or m.group(1) in known):
                who, fact = m.group(1), item[m.end():]
            else:
                who, fact = agent, item
            merged.setdefault(who, []).append(fact)
        out["learn"] = merged
        return out
    out.pop("learn", None)
    return out


def _h_character_action(state: WorldState, p: dict) -> None:
    agent = p.get("agent")
    effects = normalize_learn(p.get("effects", {}), agent or "world")
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


@dataclass
class GenreBundle:
    """Showrunner/Director Agent 配置（权威定义 — Phase 3 自 kernel/actor.py 迁入）

    genre_params / culture_params 是已解析的插件 params（PluginInstance.params）。
    """
    genre: str                       # 题材插件名
    culture: str                     # 文化插件名
    language: str = "zh"
    target_length: int = 12          # 集数/章数
    platform: str = "novel"
    genre_params: dict[str, Any] = field(default_factory=dict)
    culture_params: dict[str, Any] = field(default_factory=dict)


# ============ Phase 3 决策5：Goal/Fact/StateDelta + 到事件体系的桥 ============

@dataclass(frozen=True)
class Goal:
    id: str
    holder: str          # character_id 或 "world"
    desc: str
    priority: int = 5
    status: str = "active"   # active / achieved / abandoned


@dataclass(frozen=True)
class Fact:
    id: str
    proposition: str
    known_by: tuple[str, ...] = ()


@dataclass
class StateDelta:
    """原语产出的小说状态增量 — 不直接写库，经 to_event_effects() 桥接到事件体系"""
    new_goals: list[Goal] = field(default_factory=list)
    goal_updates: dict[str, str] = field(default_factory=dict)   # goal_id → new status
    new_facts: list[Fact] = field(default_factory=list)
    retracted_facts: list[str] = field(default_factory=list)     # fact_id
    new_constraints: list[str] = field(default_factory=list)
    relation_changes: list[dict] = field(default_factory=list)

    def merge(self, other: "StateDelta") -> "StateDelta":
        """合并两个 delta，返回新对象（原对象不变）；goal_updates 后者覆盖前者"""
        return StateDelta(
            new_goals=[*self.new_goals, *other.new_goals],
            goal_updates={**self.goal_updates, **other.goal_updates},
            new_facts=[*self.new_facts, *other.new_facts],
            retracted_facts=[*self.retracted_facts, *other.retracted_facts],
            new_constraints=[*self.new_constraints, *other.new_constraints],
            relation_changes=[*self.relation_changes, *other.relation_changes],
        )

    def to_event_effects(self, state_view=None) -> dict:
        """桥接：翻译成现有 effects 协议（set_fluents/unset_fluents/learn/relations），
        使 kernel.commit_event + 7步验证可以直接复用。

        持久化形式（决策5）：goal(<id>,<holder>,<status>) / fact(<id>)
        + knows(<cid>,<fact_id>)，fold 复用现有 set/unset/learn 逻辑，不新增事件类型。

        【P3.6 修复 goal fluent arity 并存问题】goal_updates 本身不含 holder：
        传入 state_view（任何带 .goals 的只读投影，如 creativity.StateView）时按
        goal_id 查到 holder 与旧 status，产三元 fluent 并 unset 旧状态 fluent
        （连同可能残留的旧二元形式），保证同一 goal 状态翻转后 projection 里只有
        最新状态；查不到（或省略 state_view）时退回旧二元 goal(<id>,<status>) 兜底。
        只产出非空键。
        """
        goals_by_id: dict[str, Goal] = {}
        if state_view is not None:
            goals_by_id = {g.id: g for g in getattr(state_view, "goals", ())}

        set_fluents: list[str] = []
        unset_fluents: list[str] = []
        learn: dict[str, list[str]] = {}
        relations: dict[str, dict] = {}

        for g in self.new_goals:
            set_fluents.append(f"goal({g.id},{g.holder},{g.status})")
        for goal_id, status in self.goal_updates.items():
            prev = goals_by_id.get(goal_id)
            if prev is None:
                # 无上下文：退回旧二元形式（行为与 P3.5 一致）
                set_fluents.append(f"goal({goal_id},{status})")
                continue
            set_fluents.append(f"goal({goal_id},{prev.holder},{status})")
            if prev.status != status:
                unset_fluents.append(f"goal({goal_id},{prev.holder},{prev.status})")
                # 防御：清掉历史桥接可能留下的二元旧形式（fold 的 pop 容忍不存在）
                unset_fluents.append(f"goal({goal_id},{prev.status})")
        for f in self.new_facts:
            set_fluents.append(f"fact({f.id})")
            for cid in f.known_by:
                learn.setdefault(cid, []).append(f"knows({cid},{f.id})")
        for fact_id in self.retracted_facts:
            unset_fluents.append(f"fact({fact_id})")
        for c in self.new_constraints:
            set_fluents.append(f"constraint({c})")
        for rc in self.relation_changes:
            rel = {"type": rc["type"], "intensity": rc["intensity"]}
            if rc.get("note"):
                rel["note"] = rc["note"]
            relations[rc["key"]] = rel

        effects: dict[str, Any] = {}
        if set_fluents:
            effects["set_fluents"] = set_fluents
        if unset_fluents:
            effects["unset_fluents"] = unset_fluents
        if learn:
            effects["learn"] = learn
        if relations:
            effects["relations"] = relations
        return effects
