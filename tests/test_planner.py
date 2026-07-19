"""P3.6 核心测试：NarrativePlanner（蓝图 Module 4 验收）+ goal fluent arity 回归

用户指令：只保留 3 个核心用例 + 1 个 P3.5 遗留 arity 回归用例，不穷举边界。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from story_engine.types import Goal, StateDelta, WorldEvent, GenreBundle
from story_engine.creativity import (
    StateView, GoalFormation, AuthorIntent, NarrativePlanner,
    state_view_from_world, apply_delta_to_view,
)
from story_engine.kernel import Kernel

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "story_engine" / "plugins"


def _load_bundle(genre: str) -> GenreBundle:
    """加载真实 genre 插件 params（验证真实 yaml 内容，而非测试内复制品）"""
    kernel = Kernel(tempfile.mkdtemp(), plugin_dir=PLUGIN_DIR)
    try:
        params = kernel.registry.get_params("story.genre", genre)
    finally:
        kernel.close()
    return GenreBundle(genre=genre, culture="confucian_officialdom",
                       genre_params=params)


# ---------- 用例1：蓝图 Module 4 验收 ----------

def test_blueprint_acceptance_revelation_recognition_and_connected_trajectory():
    """intent="侦探发现真凶是恩师" → 原语序列含 Revelation + Recognition；
    scratch StateView 累积 apply 后 intention 轨迹连通、状态变化连贯"""
    bundle = _load_bundle("mystery")
    view = StateView(
        characters=("包拯", "展昭"),
        relations=({"key": "包拯|展昭", "type": "信任", "intensity": 0.7},),
    )
    planner = NarrativePlanner()
    primitives, trace = planner.plan_with_trace(
        AuthorIntent(text="侦探发现真凶是恩师"), bundle, state_view=view)

    # 序列含 Revelation 与 Recognition，且 Revelation 先于 Recognition（揭示→识破）
    names = [p.__class__.__name__ for p in primitives]
    assert "Revelation" in names and "Recognition" in names
    assert names.index("Revelation") < names.index("Recognition")

    # IPOL 轨迹连通：无孤儿 intention
    assert trace["orphans_detected"] == 0
    assert planner._check_intention_trajectory(primitives, view) == []

    # 状态变化连贯：目标形成后被转折放弃并派生延续目标；悬念事实埋下后被揭示获知
    scratch = view
    for p in primitives:
        scratch = apply_delta_to_view(scratch, p.apply(scratch))
    statuses = {g.id: g.status for g in scratch.goals}
    assert "abandoned" in statuses.values()                    # TurningPoint 翻转
    assert any(g.id.endswith(":replan") and g.status == "active"
               for g in scratch.goals)                         # 派生目标延续 intention 链
    assert any(f.known_by for f in scratch.facts)              # Revelation 让事实被获知
    assert trace["goals"], "plan_goals 轨迹应非空"


# ---------- 用例2：换 genre beat/原语序列真实不同 ----------

def test_genre_switch_produces_different_primitive_sequence():
    intent = AuthorIntent(text="同一章级意图：真相逼近")
    view = StateView(
        characters=("甲", "乙"),
        relations=({"key": "甲|乙", "type": "信任", "intensity": 0.5},),
    )
    planner = NarrativePlanner()
    mystery = [p.__class__.__name__ for p in planner.plan(
        intent, _load_bundle("mystery"), state_view=view)]
    romance = [p.__class__.__name__ for p in planner.plan(
        intent, _load_bundle("romance"), state_view=view)]

    assert mystery != romance, "换 genre 序列必须不同（本阶段核心验收）"
    # 结构性差异：言情有 Sacrifice 悬疑没有；悬疑双 Revelation 收束言情没有
    assert "Sacrifice" in romance and "Sacrifice" not in mystery
    assert mystery.count("Revelation") > romance.count("Revelation")


# ---------- 用例3：孤儿 intention 检测 + _repair_plan 修复 ----------

class _SeedGoal:
    """测试桩：绕过 GoalFormation 直接注入目标（模拟无 trigger 链的目标形成）"""

    def __init__(self, gid: str, holder: str):
        self._goal = Goal(id=gid, holder=holder, desc="stub 注入")

    def apply(self, view):
        return StateDelta(new_goals=[self._goal])


def test_orphan_intention_detected_and_repaired():
    view = StateView(characters=("包拯", "展昭"))
    planner = NarrativePlanner()
    # 展昭先占「初始 intention」豁免位；随后包拯的目标无 trigger 链 → 孤儿
    plan = [_SeedGoal("g-z", "展昭"), _SeedGoal("g-b", "包拯")]

    orphans = planner._check_intention_trajectory(plan, view)
    assert [o["goal"].id for o in orphans] == ["g-b"]

    repaired = planner._repair_plan(plan, orphans, view)
    # 修复手段：孤儿步前插 GoalFormation（为包拯先建立目标链）
    assert any(isinstance(p, GoalFormation) for p in repaired)
    assert planner._check_intention_trajectory(repaired, view) == [], \
        "修复后轨迹必须连通"


# ---------- 用例4：P3.5 遗留 — goal fluent arity 修复回归 ----------

def test_goal_status_update_bridge_leaves_no_contradiction():
    """同一 goal 先 active 后 achieved 的事件序列 fold 后，projection 里只有
    最新状态（三元桥接 + unset 旧 fluent，无矛盾并存）"""
    kernel = Kernel(tempfile.mkdtemp(), plugin_dir=None)
    try:
        def commit(effects, tick):
            kernel.commit_event(WorldEvent(
                event_id=f"e{tick}", event_type="character_action",
                timestamp="2026-07-19T00:00:00", world_tick=tick, branch_id="main",
                payload={"agent": "包拯", "action": "目标演化", "effects": effects}))

        # e1：new_goals → 三元 goal(g1,包拯,active)
        commit(StateDelta(
            new_goals=[Goal(id="g1", holder="包拯", desc="查明真相")]
        ).to_event_effects(), tick=1)

        # e2：goal_updates 带 state_view 上下文 → 三元 achieved + unset 旧 active
        view = state_view_from_world(kernel.query_world("current_state"))
        effects = StateDelta(goal_updates={"g1": "achieved"}) \
            .to_event_effects(state_view=view)
        assert "goal(g1,包拯,achieved)" in effects["set_fluents"]
        assert "goal(g1,包拯,active)" in effects["unset_fluents"]
        commit(effects, tick=2)

        physical = kernel.query_world("current_state").physical
        assert physical.get("goal(g1,包拯,achieved)") is True
        assert "goal(g1,包拯,active)" not in physical     # 旧状态已撤下
        assert "goal(g1,active)" not in physical          # 无二元残留
    finally:
        kernel.close()
