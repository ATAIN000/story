"""前置约束最大化测试（检测-补救 → 预防-兜底）。

改造 1：实体登记表前置注入 prompt（生成前约束，源头防漂移）。
验证 format_entities_for_prompt 格式化 + realizer 注入链。
"""
from __future__ import annotations

from story_engine.narrative.consistency import (
    EntityLedger, format_entities_for_prompt)


# ---------- format_entities_for_prompt ----------
def test_format_empty_ledger_returns_empty():
    assert format_entities_for_prompt(EntityLedger()) == ""
    assert format_entities_for_prompt(None) == ""


def test_format_groups_by_type_with_aliases():
    led = EntityLedger()
    led.register("刘浩", "character", 1, aliases=["贤弟"])
    led.register("金箍棒碎片", "artifact", 3)
    led.register("周天星斗大阵", "formation", 3)
    led.register("凌霄殿", "location", 2)
    out = format_entities_for_prompt(led)
    assert "沿用勿改" in out
    assert "人物：刘浩（别称：贤弟）" in out
    assert "法器/器物：金箍棒碎片" in out
    assert "阵法/法术：周天星斗大阵" in out
    assert "地点/场所：凌霄殿" in out


def test_format_orders_by_entity_type():
    led = EntityLedger()
    led.register("花果山", "location", 1)
    led.register("刘浩", "character", 1)
    out = format_entities_for_prompt(led)
    # character 在 location 前（ENTITY_TYPES 顺序）
    assert out.index("刘浩") < out.index("花果山")


# ---------- realizer 注入链 ----------
def _ir():
    """最小 NarrativeIR（同 test_language_packs 的构造口径）。"""
    from story_engine.narrative.ir import (
        BeatIR, EventIR, NarrativeIR, SceneBreakdown, TextureParams)
    from story_engine.narrative.ir_builder import TEXTURE_DEFAULTS
    return NarrativeIR(
        beats=[BeatIR("b1", "disruption", ["Suspense"], "man_in_hole", 0.7)],
        events=[EventIR("包拯", "act:accuse", "刘伯", "开封府",
                        "第1日·午时", None, "玉佩失窃", None)],
        dialogue_lines=[],
        scene_breakdown=[SceneBreakdown("s1", (0, 1), "开封府")],
        texture=TextureParams(**TEXTURE_DEFAULTS["zh"]),
    )


def test_realize_prompt_includes_entities():
    """realize 传 entities_text 时 prompt 含实体段；不传时整段缺席。"""
    from story_engine.narrative.realizer import ChineseRealizer
    rz = ChineseRealizer(llm_call=None)
    prompt_with = rz._render_prompt(_ir(), entities_text="【已建立设定】法器：金箍棒")
    prompt_without = rz._render_prompt(_ir())
    assert "金箍棒" in prompt_with
    assert "金箍棒" not in prompt_without
    assert "已建立设定" in prompt_with


def test_realize_entities_absent_when_none():
    """entities_text=None/空串 → prompt 与现状逐字一致（无该段）。"""
    from story_engine.narrative.realizer import ChineseRealizer
    rz = ChineseRealizer(llm_call=None)
    p_none = rz._render_prompt(_ir(), entities_text=None)
    p_empty = rz._render_prompt(_ir(), entities_text="")
    assert p_none == p_empty
    assert "已建立设定" not in p_none
