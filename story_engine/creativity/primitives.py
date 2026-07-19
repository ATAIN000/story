"""8 核心叙事原语 + PrimitiveComposite（Module 4.1，Phase 3 决策5）

每个原语实现 `apply(state_view) -> StateDelta`：
- state_view 是 WorldState 的轻量只读投影（goals/facts/relations/characters）
- 原语只读 state_view，不修改它，也不直接写库
- 调用方（P3.6 planner）拿到 StateDelta 后经 to_event_effects() 走 kernel.commit_event

本层为确定性最小编排逻辑（demo 级，无 LLM）：每个原语从 state_view 中
选取目标并产出语义方向正确的 StateDelta。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..types import Goal, Fact, StateDelta


@dataclass(frozen=True)
class StateView:
    """WorldState 的轻量只读投影（原语的唯一输入）。

    relations 元素形状：{"key": "A|B", "type": str, "intensity": float}
    （与 WorldState.relationships / effects["relations"] 的键结构一致）
    """
    goals: tuple[Goal, ...] = ()
    facts: tuple[Fact, ...] = ()
    characters: tuple[str, ...] = ()
    relations: tuple[dict, ...] = ()


# ---------- 原语内部小工具 ----------

def _active_goals(view: StateView) -> list[Goal]:
    return [g for g in view.goals if g.status == "active"]


def _holders(goals: list[Goal]) -> list[str]:
    seen: list[str] = []
    for g in goals:
        if g.holder not in seen:
            seen.append(g.holder)
    return seen


def _neg_relation(a: str, b: str, note: str) -> dict:
    return {"key": f"{a}|{b}", "type": "敌对", "intensity": 0.8, "note": note}


def _pos_relation(a: str, b: str, note: str) -> dict:
    return {"key": f"{a}|{b}", "type": "信任", "intensity": 0.9, "note": note}


# ---------- 8 原语 ----------

class Conflict:
    """冲突：两个持有者的活跃目标对立 → 关系负向 + 双方知晓的冲突事实"""

    def apply(self, state_view: StateView) -> StateDelta:
        holders = _holders(_active_goals(state_view))
        if len(holders) < 2:
            return StateDelta()
        a, b = holders[0], holders[1]
        return StateDelta(
            new_facts=[Fact(id=f"conflict:{a}|{b}",
                            proposition=f"{a}与{b}的目标正面冲突",
                            known_by=(a, b))],
            relation_changes=[_neg_relation(a, b, "目标冲突")],
        )


class Suspense:
    """悬念：埋下一个无人知晓的隐患事实 + 回收前必须揭示的约束"""

    def apply(self, state_view: StateView) -> StateDelta:
        who = state_view.characters[0] if state_view.characters else "world"
        fid = f"suspense:{who}"
        return StateDelta(
            new_facts=[Fact(id=fid, proposition=f"逼近{who}的隐患（尚未有人察觉）",
                            known_by=())],
            new_constraints=[f"悬念{fid}必须在回收前揭示"],
        )


class TurningPoint:
    """转折：最高优先级活跃目标被迫放弃 → 状态翻转 + 派生新目标"""

    def apply(self, state_view: StateView) -> StateDelta:
        active = _active_goals(state_view)
        if not active:
            return StateDelta()
        top = min(active, key=lambda g: g.priority)
        return StateDelta(
            goal_updates={top.id: "abandoned"},
            new_goals=[Goal(id=f"{top.id}:replan", holder=top.holder,
                            desc=f"「{top.desc}」受挫后的重新谋划",
                            priority=top.priority)],
        )


class Revelation:
    """揭示：无人知晓的事实被首个角色获知 → new_facts + knows 关系"""

    def apply(self, state_view: StateView) -> StateDelta:
        hidden = next((f for f in state_view.facts if not f.known_by), None)
        if hidden is None or not state_view.characters:
            return StateDelta()
        cid = state_view.characters[0]
        return StateDelta(
            new_facts=[Fact(id=f"reveal:{hidden.id}:{cid}",
                            proposition=f"{cid}揭开了「{hidden.proposition}」",
                            known_by=(cid,))],
        )


class Sacrifice:
    """牺牲：角色放弃自己的目标成全他人 → goal abandoned + 关系正向"""

    def apply(self, state_view: StateView) -> StateDelta:
        active = [g for g in _active_goals(state_view) if g.holder != "world"]
        if not active:
            return StateDelta()
        mine = active[0]
        others = [h for h in _holders(active) if h != mine.holder]
        other = others[0] if others else "world"
        return StateDelta(
            goal_updates={mine.id: "abandoned"},
            relation_changes=[_pos_relation(mine.holder, other, "牺牲成全")],
        )


class Betrayal:
    """背叛：关系负向 + 被背叛方所信事实被撤回（信任基础崩塌）"""

    def apply(self, state_view: StateView) -> StateDelta:
        holders = _holders(_active_goals(state_view))
        if len(holders) < 2:
            return StateDelta()
        betrayer, victim = holders[1], holders[0]
        retracted = [f.id for f in state_view.facts if victim in f.known_by][:1]
        return StateDelta(
            relation_changes=[_neg_relation(betrayer, victim, "背叛")],
            retracted_facts=retracted,
        )


class Recognition:
    """识破：双方共享一个识别事实 → new_facts（双方知晓）+ 既有关系重估"""

    def apply(self, state_view: StateView) -> StateDelta:
        rel = state_view.relations[0] if state_view.relations else None
        if rel is None:
            return StateDelta()
        a, b = rel["key"].split("|", 1)
        return StateDelta(
            new_facts=[Fact(id=f"recog:{rel['key']}",
                            proposition=f"{a}识破了{b}的真实意图",
                            known_by=(a, b))],
            relation_changes=[{"key": rel["key"], "type": rel["type"],
                               "intensity": min(1.0, rel["intensity"] + 0.2),
                               "note": "识破后的关系重估"}],
        )


class GoalFormation:
    """目标形成：为首个角色（或 world）形成一个新的活跃目标 → new_goals"""

    def apply(self, state_view: StateView) -> StateDelta:
        holder = state_view.characters[0] if state_view.characters else "world"
        abandoned = next((g for g in state_view.goals if g.status == "abandoned"), None)
        desc = (f"弥补「{abandoned.desc}」的遗憾" if abandoned
                else f"{holder}立下的新志向")
        gid = f"goal:{holder}:{len(state_view.goals) + 1}"
        return StateDelta(
            new_goals=[Goal(id=gid, holder=holder, desc=desc)],
        )


ALL_PRIMITIVES = (Conflict, Suspense, TurningPoint, Revelation,
                  Sacrifice, Betrayal, Recognition, GoalFormation)


class PrimitiveComposite:
    """组合多个原语：apply 时依序 apply 并 merge 所有 StateDelta"""

    def __init__(self, primitives: list):
        self.primitives = list(primitives)

    def apply(self, state_view: StateView) -> StateDelta:
        delta = StateDelta()
        for p in self.primitives:
            delta = delta.merge(p.apply(state_view))
        return delta
