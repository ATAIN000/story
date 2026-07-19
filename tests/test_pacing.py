"""P3.4：PacingEngine 五信息论指标 + 决策卡接入的聚焦测试

只覆盖 3 个核心用例（用户指令：不穷举边界）：
  1. 五指标在手算小样本上数值正确（entropy/JSD/MI/CE/twist JSD 对拍）
  2. tension 修正方向正确（reversal_density 低于区间 → beat tension 方差提高）
  3. 退化输入兜底（空事件流/首集/无事件源不崩，pacing 为 None）
"""
from __future__ import annotations

import numpy as np
import pytest

from story_engine.showrunner import Showrunner, PacingEngine, PacingScore
from story_engine.showrunner.pacing import (
    chapter_events, suggest_tension_adjustment, apply_tension_adjustment,
)
from story_engine.types import GenreBundle, WorldState

TRACKS = [
    {"id": "A", "name": "主线", "arc_type": "Serialized", "archetype": "Quest"},
    {"id": "E", "name": "主题", "arc_type": "Serialized", "archetype": "Rebirth"},
]


def make_bundle(genre_overrides: dict | None = None) -> GenreBundle:
    genre_params = {
        "main_track": "A", "theme_track": "E", "beats_per_chapter": 4,
        "tracks": [dict(t) for t in TRACKS],
    }
    if genre_overrides:
        genre_params.update(genre_overrides)
    return GenreBundle(
        genre="mystery", culture="confucian_officialdom",
        genre_params=genre_params,
        culture_params={"cliffhanger_cycle": ["明扣", "暗扣"]},
    )


def make_state() -> WorldState:
    return WorldState()


def ev(event_type: str, **payload) -> dict:
    return {"event_type": event_type, "payload": payload}


# 手算样本：3 个场景（同型连段）
#   场景A = 2×character_action：类型2 / fluents3 / 角色2 → v=[2,...,3,2]/7
#   场景B = 1×world_change：    类型1 / fluents1 / 角色0 → v=[0,1,...,1,0]/2
#   场景C = 1×dialogue：        类型1 / fluents0 / 角色2 → v=[0,0,0,1,...,0,2]/3
SAMPLE_EVENTS = [
    ev("character_action", agent="包拯", effects={"set_fluents": ["a", "b"]}),
    ev("character_action", agent="展昭", effects={"set_fluents": ["c"]}),
    ev("world_change", field="weather", new_value="rain"),
    ev("dialogue", participants=["包拯", "展昭"]),
]


def test_five_metrics_match_hand_computed():
    """五指标数值对拍（手算：entropy=[1.5567,1,0.9183]，pivots=[0.5377,1]，
    MI=1（符号序列 ca→wc→d 完全确定），CE=0，twist=[0.5377,0.7279]）"""
    report = PacingEngine().analyze(SAMPLE_EVENTS)
    m = report["metrics"]
    assert m["entropy"] == pytest.approx([1.5567, 1.0, 0.9183], abs=1e-3)
    assert m["jsd_pivots"] == pytest.approx([0.5377, 1.0], abs=1e-3)
    assert m["mutual_info"] == pytest.approx(1.0, abs=1e-9)
    assert m["conditional_entropy"] == pytest.approx(0.0, abs=1e-9)
    assert m["twist_jsd"] == pytest.approx([0.5377, 0.7279], abs=1e-3)

    score = report["score"]
    # 两个 pivot 都 > 阈值 0.2 → 密度 1.0；幅度 = mean(pivots)
    assert score.reversal_density == pytest.approx(1.0)
    assert score.avg_reversal_magnitude == pytest.approx(0.7688, abs=1e-3)
    # 1 - var(entropy) = 1 - 0.0804；钩子强度 = 末场景 twist JSD
    assert score.pacing_consistency == pytest.approx(0.9196, abs=1e-3)
    assert score.cliffhanger_strength == pytest.approx(0.7279, abs=1e-3)


def test_tension_correction_low_reversal_raises_variance():
    """闭环方向：reversal_density 低于区间 → 下一章 beat tension 方差提高"""
    # 单元层：仅 reversal_density 出区间 → variance_scale 恰为 1.5
    score = PacingScore(reversal_density=0.1, avg_reversal_magnitude=0.4,
                        pacing_consistency=0.7, cliffhanger_strength=0.5)
    adj = suggest_tension_adjustment(score, {"reversal_density": [0.2, 0.4]})
    assert adj["deviations"]["reversal_density"] < 0
    assert adj["variance_scale"] == 1.5
    assert adj["ending_boost"] == 0.0
    beats = [{"tension": t} for t in (0.4, 0.6, 0.8)]
    adjusted = apply_tension_adjustment(beats, adj)
    assert np.var([b["tension"] for b in adjusted]) > np.var([b["tension"] for b in beats])

    # 闭环层：mystery 风格 bundle（无 pacing_targets → 默认区间）；
    # 上一章仅一个章界 marker 事件 → 无 pivot → reversal_density=0（全平）
    events = [ev("narrative_beat", chapter=1)]
    sr = Showrunner(make_bundle(), event_source=lambda: events)
    card = sr.generate_decision_card(2, make_state())
    assert card.pacing is not None
    assert set(card.pacing["score"]) == {
        "reversal_density", "avg_reversal_magnitude",
        "pacing_consistency", "cliffhanger_strength"}
    assert card.pacing["measured_episode"] == 1
    assert card.pacing["score"]["reversal_density"] == 0.0
    assert card.pacing["tension_adjustment"]["variance_scale"] > 1.0
    # 基线（无事件源）对比：本章 beat tension 方差确实提高
    baseline = Showrunner(make_bundle()).generate_decision_card(2, make_state())
    assert baseline.pacing is None
    assert (np.var([b["tension"] for b in card.beats])
            > np.var([b["tension"] for b in baseline.beats]))


def test_degenerate_inputs_no_crash():
    """退化输入兜底：空事件流 / 单事件 / 首集 / 无事件源都不崩"""
    eng = PacingEngine()
    assert eng.calc_pacing([]) is None
    # 单事件单场景：无 pivot，score 仍完整
    s = eng.calc_pacing([ev("character_action", agent="包拯")])
    assert s is not None and s.reversal_density == 0.0
    # 无 chapter 标记的事件流：退化为全部事件，不崩
    assert chapter_events([ev("character_action")], 3) == [ev("character_action")]
    # 首集（无上一章）与空事件源：DecisionCard.pacing 保持 None
    sr = Showrunner(make_bundle(), event_source=lambda: [])
    assert sr.generate_decision_card(1, make_state()).pacing is None
    assert sr.generate_decision_card(2, make_state()).pacing is None
    assert Showrunner(make_bundle()).generate_decision_card(2, make_state()).pacing is None
