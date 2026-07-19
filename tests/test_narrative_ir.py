"""P5.1 核心测试：NarrativeIR 装配 / SubtextInterlingua.map_to / 概念映射表

用户指令：只保留 3 个核心用例，不穷举边界。
"""
from __future__ import annotations

import typing
from dataclasses import fields

from story_engine.types import EventType, Goal
from story_engine.narrative import (
    IntentIR, BeatIR, EventIR, SubtextInterlingua, DialogueIR,
    TextureParams, SceneBreakdown, NarrativeIR,
    CONCEPT_IDS, to_concept_id,
)


# ---------- 用例1：类型构造（NarrativeIR 全字段装配 + TextureParams 8 字段齐）----------

def test_narrative_ir_full_assembly():
    texture = TextureParams(
        honorific_register=0.8, emotion_explicitness=0.3,
        register_switching=0.6, idiom_density=0.7,
        sentence_length_distribution=(15.0, 4.0),
        implicit_vs_explicit=0.7,
        perspective_distance="限制", temporal_ordering="顺叙",
    )
    assert len(fields(TextureParams)) == 8

    intent = IntentIR(
        characters=["包拯", "公孙策"],
        goals=[Goal(id="g1", holder="包拯", desc="查明真相")],
        world_state={"at(包拯,开封府)": True},
        primitives=[],
    )
    beat = BeatIR(beat_id="b1", phase="disruption", primitives=[intent.primitives],
                  emotion_target="low", tension=0.7)
    subtext = SubtextInterlingua(emotion_concept="emo:fear",
                                 social_concept="soc:entitlement", intensity=0.6)
    event = EventIR(who="包拯", did="act:accuse", to_whom="公孙策",
                    where="开封府", when="当夜", how=None, why="查案",
                    subtext=subtext)
    line = DialogueIR(speaker="包拯", illocution="accuse",
                      content_concept="act:accuse", emotion_concept="emo:anger",
                      politeness="bald", register="dialogue_register")
    scene = SceneBreakdown(scene_id="s1", event_span=(0, 1), location="开封府")

    ir = NarrativeIR(beats=[beat], events=[event], dialogue_lines=[line],
                     scene_breakdown=[scene], texture=texture)
    assert ir.beats[0].phase == "disruption"
    assert ir.events[0].subtext is subtext
    assert ir.dialogue_lines[0].register == "dialogue_register"
    assert ir.scene_breakdown[0].event_span == (0, 1)
    assert ir.texture.sentence_length_distribution == (15.0, 4.0)


# ---------- 用例2：map_to（zh/en 表达不同；未知概念返回 ID 本身，漂移可判）----------

def test_subtext_map_to_language_and_drift():
    s = SubtextInterlingua(emotion_concept="emo:fear", social_concept=None,
                           intensity=0.8)
    zh, en = s.map_to("zh"), s.map_to("en")
    assert zh == "恐惧" and en == "fear" and zh != en

    unknown = SubtextInterlingua(emotion_concept="emo:nostalgia",
                                 social_concept=None, intensity=0.5)
    # 无命中返回概念 ID 本身：调用方比对 返回值 == 概念ID 即判漂移
    assert unknown.map_to("zh") == "emo:nostalgia"
    assert unknown.map_to("en") == "emo:nostalgia"


# ---------- 用例3：概念映射表（EventType 全覆盖 + 关键词命中 + unknown 兜底）----------

def test_concept_ids_cover_event_types_and_keywords():
    for et in typing.get_args(EventType):
        assert et in CONCEPT_IDS, f"EventType {et} 无概念映射"
    assert to_concept_id("accuse") == "act:accuse"
    assert to_concept_id("fear") == "emo:fear"
    assert to_concept_id("不存在的词") == "act:unknown"
    assert to_concept_id("不存在的词", kind="emo") == "emo:unknown"
