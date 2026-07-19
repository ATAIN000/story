"""NarrativePlanner — HTN 意图规划器（Module 4.2，Phase 3 决策6，纯规则无 LLM）

蓝图 4.2 的可运行实现：
1. root：Todorov 5 态（equilibrium→disruption→recognition→repair→new_equilibrium）
2. genre yaml 的 `phase_beats` 把每态特化为 beat 序列（HTN methods）；
   缺 phase_beats 的题材退回通用 5 态骨架（DEFAULT_PHASE_BEATS），不崩
3. `_beat_to_primitives`：beat.primitive → 8 原语类的查表映射
4. 累积验证：scratch StateView 上逐原语 apply 并演化，剔除矛盾的 goal 状态更新
   （同一 goal 到终态 achieved/abandoned 后不得回退 active）
5. IPOL 轨迹检查：每角色 goal 链必须连通（新 goal 的 trigger 能追到已有
   goal/fact），孤儿 intention → `_repair_plan`（重排或插 GoalFormation）

本模块不调 LLM、不引入第三方库；输出的原语序列由调用方（Showrunner）挂载到
决策卡 beats / plan_goals，StateDelta 经 to_event_effects() 走 kernel.commit_event。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from ..types import Goal, Fact, StateDelta, WorldState, GenreBundle
from .primitives import StateView, GoalFormation, Conflict, Revelation, ALL_PRIMITIVES

# Todorov 5 态（root task；与 showrunner.decision.TODOROV_PHASES 同源，
# creativity 层自持一份以避免 creativity ← showrunner 的反向依赖）
TODOROV_PHASES = ["equilibrium", "disruption", "recognition", "repair", "new_equilibrium"]

TERMINAL_STATUS = ("achieved", "abandoned")

# 缺 phase_beats 时的通用 Todorov 5 态骨架（wuxia 等未配题材的兜底）
DEFAULT_PHASE_BEATS: dict[str, tuple[dict, ...]] = {
    "equilibrium":     ({"id": "setup",       "desc": "铺垫现状（通用骨架）", "primitive": "GoalFormation"},),
    "disruption":      ({"id": "inciting",    "desc": "扰动突发（通用骨架）", "primitive": "Conflict"},),
    "recognition":     ({"id": "awareness",   "desc": "察觉真相（通用骨架）", "primitive": "Recognition"},),
    "repair":          ({"id": "countermove", "desc": "修复行动（通用骨架）", "primitive": "TurningPoint"},),
    "new_equilibrium": ({"id": "resolution",  "desc": "新平衡收束（通用骨架）", "primitive": "Suspense"},),
}

# beat.primitive → 原语类查表（类名为主键；另收蓝图 4.2 示例的语义别名）
PRIMITIVE_TABLE: dict[str, type] = {cls.__name__: cls for cls in ALL_PRIMITIVES}
PRIMITIVE_TABLE.update({
    "confrontation": Conflict,      # 决策6 示例：confrontation → Conflict
    "clue_reveal": Revelation,      # 决策6 示例：clue_reveal → Revelation
})


@dataclass(frozen=True)
class AuthorIntent:
    """章级创作意图 — plan() 的输入（代码库此前无此类型，按任务最小定义）。

    text 为意图陈述（由决策卡步骤 1 按 advance 轨道构造）；holder 可选；
    metadata 携带 episode/macro_phase 等调度上下文。
    """
    text: str
    holder: str | None = None
    metadata: dict = field(default_factory=dict)


# ---------- WorldState → StateView 投影 / scratch 演化 ----------

_GOAL3_RE = re.compile(r"goal\(([^,]+),([^,]+),([^,]+)\)")
_GOAL2_RE = re.compile(r"goal\(([^,]+),([^,]+)\)")
_FACT_RE = re.compile(r"fact\(([^,]+)\)")
_KNOWS_RE = re.compile(r"knows\(([^,]+),([^,]+)\)")


def state_view_from_world(state: WorldState) -> StateView:
    """从 WorldState 投影出原语/planner 用的只读 StateView。

    goal/fact fluent 来自 StateDelta.to_event_effects() 的持久化形式：
    三元 goal(id,holder,status) 优先；旧二元 goal(id,status) 兜底（holder 记 world）。
    knows(cid,fact_id) 从各角色 beliefs 回填 Fact.known_by。
    """
    goals: dict[str, Goal] = {}
    facts: dict[str, Fact] = {}
    for fluent in state.physical:
        m = _GOAL3_RE.fullmatch(fluent)
        if m:
            gid, holder, status = m.groups()
            goals[gid] = Goal(id=gid, holder=holder, desc=gid, status=status)
            continue
        m = _GOAL2_RE.fullmatch(fluent)
        if m:
            gid, status = m.groups()
            goals.setdefault(gid, Goal(id=gid, holder="world", desc=gid, status=status))
            continue
        m = _FACT_RE.fullmatch(fluent)
        if m:
            facts.setdefault(m.group(1), Fact(id=m.group(1), proposition=m.group(1)))
    for cid, mind in state.minds.items():
        for belief, on in mind.beliefs.items():
            if not on:
                continue
            m = _KNOWS_RE.fullmatch(belief)
            if m and m.group(1) == cid:
                fid = m.group(2)
                f = facts.get(fid, Fact(id=fid, proposition=fid))
                if cid not in f.known_by:
                    facts[fid] = replace(f, known_by=(*f.known_by, cid))
    relations = tuple({"key": k, "type": r.type, "intensity": r.intensity}
                      for k, r in state.relationships.items())
    characters = tuple(state.characters.keys()) or tuple(state.minds.keys())
    return StateView(goals=tuple(goals.values()), facts=tuple(facts.values()),
                     characters=characters, relations=relations)


def apply_delta_to_view(view: StateView, delta: StateDelta) -> StateView:
    """scratch 演化：把 StateDelta 累积进 StateView，返回新 StateView（只进不出）"""
    goals = {g.id: g for g in view.goals}
    for g in delta.new_goals:
        goals[g.id] = g
    for gid, status in delta.goal_updates.items():
        prev = goals.get(gid)
        goals[gid] = (replace(prev, status=status) if prev
                      else Goal(id=gid, holder="world", desc=gid, status=status))
    facts = {f.id: f for f in view.facts}
    for f in delta.new_facts:
        facts[f.id] = f
    for fid in delta.retracted_facts:
        facts.pop(fid, None)
    relations = {r["key"]: dict(r) for r in view.relations}
    for rc in delta.relation_changes:
        relations[rc["key"]] = dict(rc)
    return StateView(goals=tuple(goals.values()), facts=tuple(facts.values()),
                     characters=view.characters, relations=tuple(relations.values()))


# ---------- HTN 意图规划器 ----------

class NarrativePlanner:
    """HTN 式分解 + Riedl 式意图规划（决策6；propose 不调 LLM）"""

    def plan(self, intent: AuthorIntent, bundle: GenreBundle,
             state_view: StateView | None = None) -> list:
        """蓝图 4.2 签名：Todorov 5 态 root → genre 分解 → 原语映射 → 验证修复。
        返回原语实例列表（每个实例带 .phase 标记其所属 Todorov 态）。"""
        primitives, _trace = self.plan_with_trace(intent, bundle, state_view)
        return primitives

    def plan_with_trace(self, intent: AuthorIntent, bundle: GenreBundle,
                        state_view: StateView | None = None) -> tuple[list, dict]:
        """plan() + 规划痕迹（goals 轨迹 / 孤儿检测与修复计数），供决策卡挂载"""
        view = state_view or StateView()
        primitives = [p for _, _, p in self._decompose(intent, bundle)]
        orphans = self._check_intention_trajectory(primitives, view)
        detected = len(orphans)
        if orphans:
            primitives = self._repair_plan(primitives, orphans, view)
        introduced, scratch = self._cumulative_validate(primitives, view)
        remaining = self._check_intention_trajectory(primitives, view)
        final_goals = {g.id: g for g in scratch.goals}
        goals_trace, seen = [], set()
        for g in introduced:
            if g.id in seen:
                continue
            seen.add(g.id)
            final = final_goals.get(g.id, g)
            goals_trace.append({"id": final.id, "holder": final.holder,
                                "desc": final.desc, "priority": final.priority,
                                "status": final.status})
        trace = {"intent": intent.text,
                 "orphans_detected": detected,
                 "orphans_repaired": detected - len(remaining),
                 "goals": goals_trace}
        return primitives, trace

    # ---- HTN 分解：Todorov root → genre phase_beats → 原语 ----
    def _decompose(self, intent: AuthorIntent, bundle: GenreBundle
                   ) -> list[tuple[str, dict, object]]:
        phase_beats = (getattr(bundle, "genre_params", None) or {}).get("phase_beats") or {}
        steps = []
        for phase in TODOROV_PHASES:
            beats = phase_beats.get(phase) or DEFAULT_PHASE_BEATS[phase]
            for beat in beats:
                for prim in self._beat_to_primitives(beat):
                    prim.phase = phase       # 标记所属 Todorov 态（决策卡按 phase 摘要）
                    steps.append((phase, beat, prim))
        return steps

    def _beat_to_primitives(self, beat: dict) -> list:
        """beat.primitive → 原语类查表；未知名 graceful 跳过（该 beat 不产原语）"""
        name = (beat or {}).get("primitive", "")
        cls = PRIMITIVE_TABLE.get(name)
        return [cls()] if cls else []

    # ---- 累积验证：scratch StateView 逐原语 apply，剔除矛盾状态更新 ----
    def _cumulative_validate(self, primitives: list, view: StateView
                             ) -> tuple[list[Goal], StateView]:
        """逐原语 apply 并演化 scratch；同一 goal 到终态后不得回退 active，
        矛盾的目标状态更新从该步 delta 中剔除（原语保留，仅修剪其产出）"""
        scratch = view
        status_of = {g.id: g.status for g in view.goals}
        introduced: list[Goal] = []
        for p in primitives:
            delta = self._filter_contradictions(p.apply(scratch), status_of)
            for g in delta.new_goals:
                status_of[g.id] = g.status
                introduced.append(g)
            for gid, status in delta.goal_updates.items():
                status_of[gid] = status
            scratch = apply_delta_to_view(scratch, delta)
        return introduced, scratch

    @staticmethod
    def _filter_contradictions(delta: StateDelta, status_of: dict[str, str]) -> StateDelta:
        good_new = [g for g in delta.new_goals
                    if not (status_of.get(g.id) in TERMINAL_STATUS
                            and g.status == "active")]
        good_updates = {gid: s for gid, s in delta.goal_updates.items()
                        if not (status_of.get(gid) in TERMINAL_STATUS
                                and s == "active")}
        if len(good_new) == len(delta.new_goals) and len(good_updates) == len(delta.goal_updates):
            return delta
        return StateDelta(new_goals=good_new, goal_updates=good_updates,
                          new_facts=delta.new_facts,
                          retracted_facts=delta.retracted_facts,
                          new_constraints=delta.new_constraints,
                          relation_changes=delta.relation_changes)

    # ---- IPOL 轨迹检查 ----
    def _check_intention_trajectory(self, primitives: list, view: StateView) -> list[dict]:
        """每角色 goal 链必须连通；返回孤儿 intention 列表 [{index, goal}]（空=全连通）。

        连通判据（任一）：计划首个 new_goal（初始 intention 前提豁免）/
        GoalFormation 产出（IPOCL 的 intention-injection 算子，视为前提性注入，
        否则 _repair_plan 插 GoalFormation 会无限回归）/ 派生目标（<id>:replan
        可追到既有 goal）/ holder 已有目标 / holder 已获知事实 / holder == "world"。
        """
        scratch = view
        orphans: list[dict] = []
        seen_first_goal = False
        for i, p in enumerate(primitives):
            delta = p.apply(scratch)
            if not isinstance(p, GoalFormation):
                for g in delta.new_goals:
                    if not seen_first_goal:
                        seen_first_goal = True
                        continue
                    if not self._goal_connected(g, scratch):
                        orphans.append({"index": i, "goal": g})
            scratch = apply_delta_to_view(scratch, delta)
        return orphans

    @staticmethod
    def _goal_connected(goal: Goal, view: StateView) -> bool:
        if goal.holder == "world":
            return True
        if goal.id.endswith(":replan") and any(
                g.id == goal.id[:-len(":replan")] for g in view.goals):
            return True
        if any(g.holder == goal.holder for g in view.goals):
            return True
        return any(goal.holder in f.known_by for f in view.facts)

    # ---- 孤儿修复 ----
    def _repair_plan(self, primitives: list, orphans: list[dict], view: StateView) -> list:
        """孤儿 intention 修复（决策6：插 GoalFormation 或重排）。

        优先重排：若后续某步能为 holder 建立触发（让其获知事实或先有目标），
        把孤儿步骤移到该步之后；找不到触发源则在该步前插 GoalFormation
        （为 holder 先行注入目标链）。逐个修复，每修一个重查一次轨迹。
        """
        repaired = list(primitives)
        for _ in orphans:
            current = self._check_intention_trajectory(repaired, view)
            if not current:
                break
            orphan = current[0]
            idx, holder = orphan["index"], orphan["goal"].holder
            j = self._find_trigger_step(repaired, idx, holder, view)
            if j is not None:
                step = repaired.pop(idx)
                repaired.insert(j, step)   # pop 后原 j 步前移到 j-1，插 j 即紧随其后
            else:
                trigger = GoalFormation()
                trigger.phase = getattr(repaired[idx], "phase", None)
                repaired.insert(idx, trigger)
        return repaired

    @staticmethod
    def _find_trigger_step(primitives: list, idx: int, holder: str,
                           view: StateView) -> int | None:
        """在 idx 之后找能为 holder 建立 intention 触发的步骤下标（找不到返回 None）"""
        scratch = view
        for i, p in enumerate(primitives):
            delta = p.apply(scratch)
            if i > idx:
                if any(holder in f.known_by for f in delta.new_facts):
                    return i
                if any(g.holder == holder for g in delta.new_goals):
                    return i
            scratch = apply_delta_to_view(scratch, delta)
        return None
