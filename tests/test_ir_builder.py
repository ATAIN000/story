"""P5.2 核心测试：IRBuilder（决策卡 + 事件流 → NarrativeIR，规则化零 LLM）

用户指令：只保留 3 个核心用例，不穷举边界：
  1. 真实 kernel 事件流 → EventIR 5W 投影（who/did/where/why/when；where 来自 at fluent）
  2. 决策卡 beats → BeatIR 映射；scene_breakdown 按 where 变化切分
  3. texture 默认值表（zh 对拍 / texture_overrides 覆盖 / en 表值域 [0,1]）
"""
from __future__ import annotations

import pytest

from story_engine.kernel import Kernel
from story_engine.narrative import IRBuilder, NarrativeIR, resolve_texture
from story_engine.types import GenreBundle, WorldEvent, WorldState

# 与 mock_script.SEED_PHYSICAL 同格式：初始 at() fluent 直接进初始状态（不经事件）
SEED_PHYSICAL = {"at(包拯,开封府)": True, "at(展昭,聚宝赌坊)": True}


def _seed_state() -> WorldState:
    s = WorldState()
    s.physical.update(SEED_PHYSICAL)
    return s


@pytest.fixture
def kernel(tmp_path):
    k = Kernel(str(tmp_path), plugin_dir=None, initial_state_factory=_seed_state)
    yield k
    k.close()


def _commit(kernel: Kernel, tick: int, event_type: str, **payload) -> None:
    kernel.commit_event(WorldEvent(
        event_id=f"e{tick}", event_type=event_type,
        timestamp="2026-07-19T00:00:00", world_tick=tick, branch_id="main",
        payload=payload))


def _bundle(**kw) -> GenreBundle:
    return GenreBundle(genre="mystery", culture="confucian_officialdom", **kw)


CARD = {"beats": [], "target_arc": "man_in_hole"}


# ---------- 用例1：真实 kernel 事件流 → EventIR 5W 投影 ----------

def test_event_ir_5w_projection(kernel):
    # 本章 3 个 character_action + 章界 beat；章界之后的事件（tick5）不属于本章
    _commit(kernel, 1, "character_action", agent="包拯", action="accuse",
            motivation="玉佩失窃", story_time="第1日·午时")
    _commit(kernel, 2, "character_action", agent="展昭", action="investigate",
            motivation="查访线索",
            effects={"set_fluents": ["at(展昭,聚宝赌坊)"],
                     "unset_fluents": ["at(展昭,开封府)"]})
    _commit(kernel, 3, "character_action", agent="展昭", action="呈上账册",
            motivation="查访线索")
    _commit(kernel, 4, "narrative_beat", chapter=1, scene="公堂", tension=0.5)
    _commit(kernel, 5, "character_action", agent="包拯", action="签票缉拿")

    ir = IRBuilder(kernel, _bundle()).build(CARD, 1)
    assert isinstance(ir, NarrativeIR)
    # 章界切片 = 3 行动 + 章界 beat（含）；tick5 被排除
    assert [e.who for e in ir.events] == ["包拯", "展昭", "展昭", "world"]

    # who=payload.agent；did=action 关键词命中映射表；why=motivation；when=story_time；
    # where：包拯全程无 at() effect → 退回 physical projection（seed 的 at(包拯,开封府)）
    e1 = ir.events[0]
    assert (e1.who, e1.did, e1.where, e1.why, e1.when) == \
        ("包拯", "act:accuse", "开封府", "玉佩失窃", "第1日·午时")
    # 事件自身 effects 在其时刻之后才生效 → e2 时刻取不到 at(展昭) → unknown
    assert ir.events[1].where == "unknown"
    # e3：前向 fold 得 at(展昭,聚宝赌坊)；action 未收录 → did 退回 event_type 概念；
    # 无 story_time → when 回退 chapter 标记
    e3 = ir.events[2]
    assert (e3.where, e3.did, e3.why, e3.when) == \
        ("聚宝赌坊", "act:character_action", "查访线索", "chapter_1")
    assert e3.how is None and e3.subtext is None
    # actor 事件无 dialogue/says 字段 → 空表（现状简化）
    assert ir.dialogue_lines == []


# ---------- 用例2：决策卡 beats → BeatIR；scene_breakdown 按 where 切分 ----------

def test_beats_and_scene_breakdown(kernel):
    _commit(kernel, 1, "character_action", agent="包拯", action="受理案件",
            motivation="玉佩失窃")
    _commit(kernel, 2, "character_action", agent="包拯", action="询问行踪")
    _commit(kernel, 3, "character_action", agent="展昭", action="查访赌坊")
    _commit(kernel, 4, "narrative_beat", chapter=1, scene="公堂", tension=0.5)

    card = {
        "beats": [
            {"beat_id": "ep1_b1", "micro_phase": "equilibrium",
             "primitives": ["EstablishShot"], "tension": 0.4},
            {"beat_id": "ep1_b2", "micro_phase": "disruption",
             "primitives": ["Accuse", "Conceal"], "tension": 0.72},
        ],
        "target_arc": "man_in_hole",
    }
    ir = IRBuilder(kernel, _bundle()).build(card, 1)

    # beats → BeatIR：phase 取 micro_phase，emotion_target=target_arc，primitives/tension 透传
    assert [(b.beat_id, b.phase, b.primitives, b.emotion_target, b.tension)
            for b in ir.beats] == [
        ("ep1_b1", "equilibrium", ["EstablishShot"], "man_in_hole", 0.4),
        ("ep1_b2", "disruption", ["Accuse", "Conceal"], "man_in_hole", 0.72),
    ]

    # 无 at() effect → 全静态：where 序列 [开封府, 开封府, 聚宝赌坊, unknown]
    # → 按相邻变化切 3 场景，event_span 为半开区间
    assert [(s.scene_id, s.event_span, s.location) for s in ir.scene_breakdown] == [
        ("s1", (0, 2), "开封府"),
        ("s2", (2, 3), "聚宝赌坊"),
        ("s3", (3, 4), "unknown"),
    ]


# ---------- 用例3：texture 默认值表 + texture_overrides 覆盖 + en 表 ----------

def test_texture_defaults_and_overrides():
    # zh 默认值表数值对拍（决策2：zh+confucian 一套）
    t = resolve_texture(_bundle(language="zh"))
    assert t.honorific_register == 0.6
    assert t.emotion_explicitness == 0.3
    assert t.idiom_density == 0.5
    assert t.implicit_vs_explicit == 0.7
    assert t.register_switching == 0.6
    assert t.sentence_length_distribution == (18.0, 8.0)
    assert t.perspective_distance == "全知"
    assert t.temporal_ordering == "顺叙"

    # culture_params.texture_overrides 覆盖生效；未覆盖项保持默认；未知键忽略
    t2 = resolve_texture(_bundle(language="zh", culture_params={
        "texture_overrides": {"honorific_register": 0.9, "unknown_key": 1.0}}))
    assert t2.honorific_register == 0.9
    assert t2.idiom_density == 0.5

    # en 表存在且密度类字段值域 [0,1]
    te = resolve_texture(_bundle(language="en", culture_params={}))
    for v in (te.honorific_register, te.emotion_explicitness, te.idiom_density,
              te.implicit_vs_explicit, te.register_switching):
        assert 0.0 <= v <= 1.0
    assert te.sentence_length_distribution == (15.0, 6.0)
    assert te.perspective_distance and te.temporal_ordering
