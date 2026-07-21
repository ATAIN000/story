"""tests for story_engine.worldview（Phase 12.1：L0-L3 批1）

覆盖 brief 要求的 3 个核心场景：
  1. 级联收窄：metaphysics=materialist → consciousness_nature 不含 soul_based
  2. 违例检出：上述 profile 显式设 consciousness_nature=soul_based → violations 命中
  3. 容忍：空 profile / 未知键不崩；to_prompt_text 跳过空层
"""
from __future__ import annotations

from story_engine.worldview import (
    ALL_PARAMS, LAYERS, PREDICATES, WorldviewProfile, evaluate,
)


# ---------- 1. 级联收窄 ----------
def test_metaphysics_materialist_narrows_consciousness_nature():
    result = evaluate({"metaphysics": "materialist"})
    allowed = result["allowed"]["consciousness_nature"]
    # 唯物基底不允许灵魂载体 / 集体意识
    assert "soul_based" not in allowed
    assert "collective" not in allowed
    # 但涌现产物等仍然合法
    assert "emergent" in allowed
    # 未被收窄的参数仍取全集
    assert len(result["allowed"]["physics_deviation"]) == len(
        ALL_PARAMS["physics_deviation"]["options"])


# ---------- 2. 违例检出 ----------
def test_violation_detected_when_value_disallowed():
    profile = {"metaphysics": "materialist", "consciousness_nature": "soul_based"}
    result = evaluate(profile)
    hits = [v for v in result["violations"]
            if v["param"] == "consciousness_nature" and v["value"] == "soul_based"]
    assert hits, f"应检出 consciousness_nature=soul_based 违例， got {result['violations']}"
    assert hits[0]["message"], "违例消息不应为空"


# ---------- 3. 容忍 ----------
def test_evaluate_tolerates_empty_and_unknown_keys():
    # 空 profile 不崩，violations 为空，allowed 为全集
    r1 = evaluate({})
    assert r1["violations"] == []
    assert set(r1["allowed"]) == set(ALL_PARAMS)
    # None / 未知键不崩
    r2 = evaluate(None)
    assert r2["violations"] == []
    r3 = evaluate({"__unknown_param__": "x"})
    assert r3["violations"] == []

    # to_prompt_text：空层跳过；未知层/键被剔除不崩
    p = WorldviewProfile(layers={
        "L0": {"metaphysics": "dualist"},
        "L9": {"bogus": "x"},  # 未知层
        "L3": {"__bad__": "y"},  # 未知键
    })
    text = p.to_prompt_text()
    assert "L0" in text and "L3" not in text  # L3 被剔空 → 跳过
    # 空 profile
    assert WorldviewProfile().to_prompt_text() == ""


# ---------- 数据完整性（轻量校验：素材忠实录入） ----------
def test_layers_data_integrity():
    # 4 层齐全
    assert [l["id"] for l in LAYERS] == ["L0", "L1", "L2", "L3"]
    # 每参数至少 4 个枚举值，每值含 value/label
    for layer in LAYERS:
        for p in layer["params"]:
            assert len(p["options"]) >= 4, f"{p['key']} 选项过少"
            for o in p["options"]:
                assert "value" in o and "label" in o, f"{p['key']} 选项缺字段"
    # 关键枚举值（素材原文）存在
    assert "soul_based" in [o["value"] for o in ALL_PARAMS["consciousness_nature"]["options"]]
    assert "materialist" in [o["value"] for o in ALL_PARAMS["metaphysics"]["options"]]
    # 谓词条数符合预期（≥40）
    assert len(PREDICATES) >= 40
