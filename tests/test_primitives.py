"""P3.5 核心测试：StateDelta merge / to_event_effects 桥 / 8 原语方向 / PrimitiveComposite

用户指令：只保留 4 个核心用例，不穷举边界。
"""
from __future__ import annotations

import tempfile

import pytest

from story_engine.types import Goal, Fact, StateDelta, WorldEvent
from story_engine.creativity import (
    StateView, Conflict, Suspense, TurningPoint, Revelation,
    Sacrifice, Betrayal, Recognition, GoalFormation, PrimitiveComposite,
)
from story_engine.kernel import Kernel
from story_engine.validator import ConsistencyValidator


def _view() -> StateView:
    return StateView(
        goals=(
            Goal(id="g1", holder="包拯", desc="查明真相"),
            Goal(id="g2", holder="公孙策", desc="保护证人"),
        ),
        facts=(
            Fact(id="f1", proposition="证词有漏洞", known_by=("包拯",)),
            Fact(id="f2", proposition="凶手另有其人", known_by=()),
        ),
        characters=("包拯", "公孙策"),
        relations=({"key": "包拯|公孙策", "type": "信任", "intensity": 0.6},),
    )


# ---------- 用例1：StateDelta.merge ----------

def test_merge_combines_and_later_goal_update_wins():
    d1 = StateDelta(
        new_goals=[Goal(id="g1", holder="包拯", desc="查案")],
        goal_updates={"g1": "abandoned"},
        new_facts=[Fact(id="f1", proposition="p")],
        retracted_facts=["f0"],
        new_constraints=["c1"],
        relation_changes=[{"key": "a|b", "type": "敌对", "intensity": 0.5}],
    )
    d2 = StateDelta(
        goal_updates={"g1": "achieved"},   # 后者覆盖前者
        new_facts=[Fact(id="f2", proposition="q")],
    )
    m = d1.merge(d2)
    assert m.goal_updates == {"g1": "achieved"}
    assert [f.id for f in m.new_facts] == ["f1", "f2"]
    assert len(m.new_goals) == 1 and m.retracted_facts == ["f0"]
    assert m.new_constraints == ["c1"] and len(m.relation_changes) == 1
    # merge 返回新对象，原 delta 不被污染
    assert d1.goal_updates == {"g1": "abandoned"} and len(d1.new_facts) == 1


# ---------- 用例2：to_event_effects 桥 → 真 kernel.commit_event + 7步验证 ----------

def test_to_event_effects_roundtrip_through_kernel():
    tmp = tempfile.mkdtemp()
    kernel = Kernel(tmp, plugin_dir=None)
    try:
        # 先埋一个将被撤回的 fact(f0)
        kernel.commit_event(WorldEvent(
            event_id="e0", event_type="character_action",
            timestamp="2026-07-19T00:00:00", world_tick=1, branch_id="main",
            payload={"agent": "包拯", "action": "立案",
                     "effects": {"set_fluents": ["fact(f0)"]}}))

        delta = StateDelta(
            new_goals=[Goal(id="g1", holder="包拯", desc="查明真相")],
            new_facts=[Fact(id="f1", proposition="凶手另有其人", known_by=("包拯",))],
            retracted_facts=["f0"],
            relation_changes=[{"key": "包拯|公孙策", "type": "敌对",
                               "intensity": 0.8, "note": "目标冲突"}],
        )
        effects = delta.to_event_effects()
        # 只产出现有协议键
        assert set(effects) <= {"set_fluents", "unset_fluents", "learn", "relations"}

        event = WorldEvent(
            event_id="e1", event_type="character_action",
            timestamp="2026-07-19T00:01:00", world_tick=2, branch_id="main",
            payload={"agent": "包拯", "action": "原语桥接", "effects": effects})
        # 7 步硬约束验证（真 ConsistencyValidator，以当前 WorldState 为基准）
        verdict = ConsistencyValidator().validate(
            event, kernel.query_world("current_state"))
        assert len(verdict.checks) == 7 and verdict.passed, verdict.failures

        kernel.commit_event(event)
        state = kernel.query_world("current_state")
        assert state.physical.get("goal(g1,包拯,active)") is True
        assert state.physical.get("fact(f1)") is True
        assert "fact(f0)" not in state.physical           # unset 生效
        assert state.minds["包拯"].beliefs.get("knows(包拯,f1)") is True
        rel = state.relationships["包拯|公孙策"]
        assert rel.type == "敌对" and rel.intensity == 0.8
        assert rel.history == ["目标冲突"]
    finally:
        kernel.close()


# ---------- 用例3：8 原语各 apply 一次，非空且语义方向正确、state_view 只读 ----------

_PRIMITIVE_DIRECTIONS = [
    (Conflict(),
     lambda d: any(rc["type"] == "敌对" for rc in d.relation_changes)
     and any(set(f.known_by) == {"包拯", "公孙策"} for f in d.new_facts)),
    (Suspense(),
     lambda d: d.new_facts and all(not f.known_by for f in d.new_facts)
     and len(d.new_constraints) > 0),
    (TurningPoint(),
     lambda d: "abandoned" in d.goal_updates.values() and len(d.new_goals) > 0),
    (Revelation(),
     lambda d: any(f.known_by for f in d.new_facts)),
    (Sacrifice(),
     lambda d: "abandoned" in d.goal_updates.values()
     and any(rc["type"] == "信任" for rc in d.relation_changes)),
    (Betrayal(),
     lambda d: any(rc["type"] == "敌对" for rc in d.relation_changes)
     and len(d.retracted_facts) > 0),
    (Recognition(),
     lambda d: any(len(f.known_by) == 2 for f in d.new_facts)
     and len(d.relation_changes) > 0),
    (GoalFormation(),
     lambda d: any(g.status == "active" for g in d.new_goals)),
]


@pytest.mark.parametrize("prim,direction", _PRIMITIVE_DIRECTIONS,
                         ids=[p.__class__.__name__ for p, _ in _PRIMITIVE_DIRECTIONS])
def test_primitive_direction(prim, direction):
    view = _view()
    snapshot = repr(view)
    delta = prim.apply(view)
    assert repr(view) == snapshot          # state_view 只读，未被修改
    assert delta != StateDelta()           # 非空
    assert direction(delta), f"{prim.__class__.__name__} 语义方向错误: {delta}"


# ---------- 用例4：PrimitiveComposite 依序 apply + merge ----------

def test_composite_applies_in_order_and_merges():
    view = _view()
    comp = PrimitiveComposite([GoalFormation(), Revelation(), Betrayal()])
    delta = comp.apply(view)
    assert any(g.holder == "包拯" for g in delta.new_goals)      # GoalFormation
    assert any(f.id.startswith("reveal:") for f in delta.new_facts)  # Revelation
    assert any(rc.get("note") == "背叛" for rc in delta.relation_changes)  # Betrayal
    assert delta.retracted_facts                                  # Betrayal 的撤回也保留

    class _Stub:
        def __init__(self, status):
            self.status = status

        def apply(self, sv):
            return StateDelta(goal_updates={"g1": self.status})

    # 依序 merge：同 key 的 goal_updates 后者覆盖前者
    ordered = PrimitiveComposite([_Stub("abandoned"), _Stub("achieved")]).apply(view)
    assert ordered.goal_updates == {"g1": "achieved"}
