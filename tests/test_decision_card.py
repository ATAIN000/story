"""P3.3：showrunner 子包重构 + 10 步 control loop 补全的聚焦测试

覆盖决策3表格的新逻辑：
  Step 3  CFPG 池上限 + 债务老化（overdue/priority）
  Step 4  Sternberg 硬约束（同集唯一 / 同轨道连续两集不同 / >3 取前 3）
  Step 5  Yorke 分形 beat（macro_phase + micro_phase 双尺度）
  Step 6  CONCOCT concreteness_curve（rising/valley/peak）
  Step 7  McKee gap 规则模板（按 archetype，非占位）
  Step 8  Snyder 读 target_length
  Step 9  满池排队 queued_foreshadows + pool_stats
以及子包 re-export 兼容与 DecisionCard 只增不改。
"""
from __future__ import annotations

import json

from story_engine.showrunner import Showrunner, Track, DecisionCard
from story_engine.showrunner import STERNBERG_MODES, TODOROV_PHASES
from story_engine.types import GenreBundle, WorldState, ForeshadowTriple

TRACKS = [
    {"id": "A", "name": "主线", "arc_type": "Serialized", "archetype": "Quest"},
    {"id": "B", "name": "副线B", "arc_type": "Serialized", "archetype": "Tragedy"},
    {"id": "C", "name": "副线C", "arc_type": "Serialized", "archetype": "Rebirth"},
    {"id": "D", "name": "单元", "arc_type": "Anthology", "archetype": "Monster",
     "min_main_progress": 0.7},
    {"id": "E", "name": "主题", "arc_type": "Serialized", "archetype": "Quest"},
]


def make_bundle(genre_overrides: dict | None = None, **bundle_kw) -> GenreBundle:
    genre_params = {
        "main_track": "A", "theme_track": "E",
        "payoff_window": 2, "beats_per_chapter": 4,
        "emotion_arcs": ["man_in_hole", "cinderella"],
        "tracks": [dict(t) for t in TRACKS],
        "foreshadow_templates": [
            {"content": "证词矛盾", "trigger": "质询", "payoff": "破绽"},
            {"content": "异常物件", "trigger": "复勘", "payoff": "归属"},
        ],
    }
    if genre_overrides:
        genre_params.update(genre_overrides)
    return GenreBundle(
        genre=bundle_kw.get("genre", "mystery"),
        culture=bundle_kw.get("culture", "confucian_officialdom"),
        target_length=bundle_kw.get("target_length", 12),
        genre_params=genre_params,
        culture_params={"cliffhanger_cycle": ["明扣", "暗扣"]},
    )


def make_state(foreshadows: list[ForeshadowTriple] | None = None) -> WorldState:
    ws = WorldState()
    ws.narrative.foreshadow_pool = foreshadows or []
    return ws


def make_fs(i: int, planted: int, payed_off: bool = False) -> ForeshadowTriple:
    return ForeshadowTriple(
        foreshadow_id=f"F{i}", content=f"伏笔{i}", planted_at_tick=i,
        planted_chapter=planted, trigger_condition="触发", payoff="回报",
        payed_off=payed_off)


# ---------- 子包结构 / 兼容 ----------

def test_subpackage_reexports_compat():
    import story_engine.showrunner as pkg
    from story_engine.showrunner.tracks import Track as Track2
    from story_engine.showrunner.decision import Showrunner as SR2, DecisionCard as DC2
    assert pkg.Track is Track2
    assert pkg.Showrunner is SR2
    assert pkg.DecisionCard is DC2
    # engine.py 的既有 import 路径不变
    from story_engine.engine import StoryEngine  # noqa: F401


def test_decision_card_fields_only_added():
    """旧字段名/语义不动，新字段带默认值（只增不改）"""
    sr = Showrunner(make_bundle())
    card = sr.generate_decision_card(1, make_state())
    old_fields = {"episode", "advance", "seed", "mid_touch", "dormant",
                  "sternberg_distribution", "active_payoffs", "beats",
                  "snyder_coverage", "target_arc", "gaps", "ending_hook",
                  "theme_touch", "new_foreshadows"}
    assert old_fields <= set(card.to_dict())
    # 新字段：concreteness_curve/pool_stats 真填；pacing/creative_seeds 仅默认
    assert card.pacing is None
    assert card.creative_seeds == []
    # Step 1（P3.6 已接 planner）：plan_goals 挂 goal 轨迹，元素为可序列化 dict
    assert isinstance(card.plan_goals, list)
    assert all(isinstance(g, dict) and "id" in g and "status" in g
               for g in card.plan_goals)
    assert card.queued_foreshadows == []
    assert isinstance(card.concreteness_curve, list)
    assert isinstance(card.pool_stats, dict)
    # to_dict 可 JSON 序列化（engine 落盘）
    json.dumps(card.to_dict(), ensure_ascii=False)


# ---------- Step 3：CFPG 查询 + 债务老化 ----------

def test_cfpg_overdue_aging():
    """种下 >2×payoff_window 未回收 → priority 升级 + overdue:true"""
    state = make_state([
        make_fs(1, planted=1),   # ep6 时年龄 5 > 2*2=4 → overdue
        make_fs(2, planted=4),   # 年龄 2：到期但未老化
        make_fs(3, planted=5),   # 年龄 1：未到期
    ])
    card = Showrunner(make_bundle()).generate_decision_card(6, state)
    by_id = {p["foreshadow_id"]: p for p in card.active_payoffs}
    assert set(by_id) == {"F1", "F2"}            # 未到期的不进列表
    assert by_id["F1"]["overdue"] is True
    assert by_id["F1"]["priority"] == "high"
    assert by_id["F2"]["overdue"] is False
    assert by_id["F2"]["priority"] == "normal"


# ---------- Step 4：Sternberg 硬约束 ----------

def test_sternberg_unique_within_episode():
    card = Showrunner(make_bundle()).generate_decision_card(1, make_state())
    dist = card.sternberg_distribution
    modes = list(dist.values())
    assert len(modes) == len(set(modes)), "同集内模式必须唯一"
    assert set(dist) <= set(card.advance + card.mid_touch)
    assert len(dist) <= 3
    assert set(modes) <= set(STERNBERG_MODES)


def test_sternberg_no_repeat_consecutive_episodes():
    """同轨道连续两集不得同模式（历史来自同一 Showrunner 的上一张卡）"""
    sr = Showrunner(make_bundle())
    card1 = sr.generate_decision_card(1, make_state())
    card2 = sr.generate_decision_card(2, make_state())
    common = set(card1.sternberg_distribution) & set(card2.sternberg_distribution)
    assert common, "测试前提：应有轨道连续两集参与调度"
    for tid in common:
        assert card1.sternberg_distribution[tid] != card2.sternberg_distribution[tid], \
            f"轨道 {tid} 连续两集同模式"


def test_sternberg_same_episode_regenerate_idempotent():
    """同集重复生成（engine LLM 路径会二次调用）不得污染历史：
    共同轨道模式一致，且下一集仍只与首集结果错峰。
    注：第二次调用时轨道集合可能不同 —— _schedule 的 last_touched
    漂移是既有行为，不在本任务范围。"""
    sr = Showrunner(make_bundle())
    card1a = sr.generate_decision_card(1, make_state())
    card1b = sr.generate_decision_card(1, make_state())
    common1 = set(card1a.sternberg_distribution) & set(card1b.sternberg_distribution)
    assert common1, "测试前提：主线轨道应稳定参与调度"
    for tid in common1:
        assert card1a.sternberg_distribution[tid] == card1b.sternberg_distribution[tid]
    card2 = sr.generate_decision_card(2, make_state())
    for tid in set(card1a.sternberg_distribution) & set(card2.sternberg_distribution):
        assert card1a.sternberg_distribution[tid] != card2.sternberg_distribution[tid]


def test_sternberg_top3_when_more_than_3_tracks():
    """>3 轨道时按调度优先级取前 3（_schedule 当前最多 3 条，直接测硬约束函数）"""
    sr = Showrunner(make_bundle())
    dist = sr._sternberg_assign(1, ["A", "B", "C", "E"])
    assert set(dist) == {"A", "B", "C"}
    assert len(set(dist.values())) == 3


# ---------- Step 5：Yorke 分形 beat ----------

def test_fractal_beats_dual_scale():
    sr = Showrunner(make_bundle())
    card1 = sr.generate_decision_card(1, make_state())
    assert card1.beats, "测试前提：应有 beat"
    for b in card1.beats:
        assert b["macro_phase"] == "equilibrium"           # ep1/12 → 幕级 equilibrium
        assert b["micro_phase"] in TODOROV_PHASES          # 章级沿用现有逻辑
        assert b["phase"] == b["micro_phase"]              # 旧键保留兼容前端
    card_mid = sr.generate_decision_card(5, make_state())
    assert all(b["macro_phase"] == "recognition" for b in card_mid.beats)  # 5/12
    card_end = sr.generate_decision_card(12, make_state())
    assert all(b["macro_phase"] == "new_equilibrium" for b in card_end.beats)


# ---------- Step 6：CONCOCT concreteness_curve ----------

def test_concreteness_curve_default_rising():
    card = Showrunner(make_bundle()).generate_decision_card(1, make_state())
    curve = card.concreteness_curve
    assert len(curve) == len(card.beats)                   # 每 beat 一个目标
    assert all(0.0 <= v <= 1.0 for v in curve)
    assert curve == sorted(curve) and curve[0] < curve[-1], "默认 rising"


def test_concreteness_curve_shapes():
    peak = Showrunner(make_bundle({"concreteness_shape": "peak"})) \
        .generate_decision_card(1, make_state()).concreteness_curve
    assert max(peak) > peak[0] and max(peak) > peak[-1], "peak：中段高于两端"
    valley = Showrunner(make_bundle({"concreteness_shape": "valley"})) \
        .generate_decision_card(1, make_state()).concreteness_curve
    assert min(valley) < valley[0] and min(valley) < valley[-1], "valley：中段低于两端"


# ---------- Step 7：McKee gap 规则模板 ----------

def test_mckee_gap_archetype_templates():
    state = make_state()
    state.narrative.current_scene = "开封府夜审"
    card = Showrunner(make_bundle()).generate_decision_card(1, state)
    assert len(card.gaps) == len(card.advance)
    joined = "；".join(card.gaps)
    # advance = [A(Quest), B(Tragedy)]：按原型选模板，非旧占位串
    assert "接近目标时代价显现" in joined                  # Quest 模板
    assert any("主线" in g and "接近目标时代价显现" in g for g in card.gaps)
    assert all("读者预期 vs 实际发生的落差设计" not in g or "副线" not in g
               for g in card.gaps), "有原型的轨道不得退回占位串"
    assert "开封府夜审" in joined                          # 结合上一章场景


def test_mckee_gap_unknown_archetype_fallback():
    tracks = [{"id": "A", "name": "主线", "arc_type": "Serialized",
               "archetype": "Voyage"}]
    card = Showrunner(make_bundle({"tracks": tracks, "theme_track": "A"})) \
        .generate_decision_card(1, make_state())
    assert card.gaps and "主线" in card.gaps[0]


# ---------- Step 8：Snyder 读 target_length ----------

def test_snyder_uses_target_length():
    sr12 = Showrunner(make_bundle(target_length=12))
    sr6 = Showrunner(make_bundle(target_length=6))
    cov12 = sr12.generate_decision_card(6, make_state()).snyder_coverage
    cov6 = sr6.generate_decision_card(6, make_state()).snyder_coverage
    assert sum(cov12.values()) < sum(cov6.values()), "同集数下短篇覆盖更多锚点"
    # 末集必须全覆盖
    assert all(sr12.generate_decision_card(12, make_state()).snyder_coverage.values())
    assert all(sr6.generate_decision_card(6, make_state()).snyder_coverage.values())
    # 第 1 集只覆盖开头少数锚点
    first = sr12.generate_decision_card(1, make_state()).snyder_coverage
    assert first["开场画面"] and not first["终场画面"]


# ---------- Step 9：CFPG 池更新（上限/排队/pool_stats） ----------

def test_foreshadow_pool_max_default_8():
    sr = Showrunner(make_bundle())
    assert sr.pool.pool_max == 8


def test_pool_full_queues_new_foreshadows():
    """满池（默认上限 8）时新伏笔排队，不进入 new_foreshadows"""
    pool = [make_fs(i, planted=1) for i in range(8)]     # 8 条未回收 = 满池
    card = Showrunner(make_bundle()).generate_decision_card(1, make_state(pool))
    # ep1 对 ep1 所种年龄为 0，未到期，无回收 → 0 空位
    assert card.new_foreshadows == []
    assert len(card.queued_foreshadows) == len(card.seed) == 1
    assert card.pool_stats == {"active": 8, "overdue": 0, "queued": 1}


def test_pool_partial_capacity_admits_until_full():
    pool = [make_fs(i, planted=3) for i in range(7)]     # 7 活跃（未到期）+ 空位 1
    pool.append(make_fs(99, planted=1, payed_off=True))  # 已回收不占位
    card = Showrunner(make_bundle()).generate_decision_card(3, make_state(pool))
    assert len(card.new_foreshadows) == 1
    assert card.queued_foreshadows == []
    assert card.pool_stats["active"] == 7
    assert card.pool_stats["queued"] == 0


def test_pool_stats_overdue_count():
    pool = [make_fs(1, planted=1), make_fs(2, planted=5)]
    card = Showrunner(make_bundle()).generate_decision_card(6, make_state(pool))
    assert card.pool_stats["active"] == 2
    assert card.pool_stats["overdue"] == 1               # F1 年龄 5 > 4
    assert card.pool_stats["queued"] == 0


def test_pool_max_configurable_via_genre_params():
    sr = Showrunner(make_bundle({"foreshadow_pool_max": 3}))
    assert sr.pool.pool_max == 3
    pool = [make_fs(i, planted=3) for i in range(3)]
    card = sr.generate_decision_card(3, make_state(pool))
    assert card.new_foreshadows == [] and len(card.queued_foreshadows) == 1
