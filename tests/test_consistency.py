"""设定一致性硬校验测试：实体登记 / 漂移检出 / 别名归并 / 回溯校验。

全部离线（纯逻辑，零 LLM）：EntityLedger 与两个 check 函数都是纯规则。
"""
from __future__ import annotations

from story_engine.narrative.consistency import (
    EntityLedger, check_callback_validity, check_entity_consistency,
    extract_entities_rule)


# ---------- EntityLedger 登记与别名 ----------
def test_register_and_lookup_alias():
    led = EntityLedger()
    led.register("陈世嚣", "character", 3, aliases=["明公", "陈大人"])
    assert led.lookup("陈世嚣") == "陈世嚣"
    assert led.lookup("明公") == "陈世嚣"      # 别名归并到 canonical
    assert led.lookup("林晚娘") is None


def test_register_increments_mentions():
    led = EntityLedger()
    led.register("金箍棒", "artifact", 3)
    led.register("金箍棒", "artifact", 5, aliases=["定海神针"])
    e = led.entities["金箍棒"]
    assert e["mentions"] == 2
    assert e["first_seen"] == 3
    assert "定海神针" in e["aliases"]


def test_ledger_persistence_roundtrip(tmp_path):
    led = EntityLedger()
    led.register("刘浩", "character", 1, aliases=["贤弟"])
    led.register("逆星大阵", "formation", 7)
    p = tmp_path / "entities.json"
    led.save(p)
    loaded = EntityLedger.load(p)
    assert loaded.lookup("贤弟") == "刘浩"
    assert loaded.entities["逆星大阵"]["type"] == "formation"


def test_load_missing_returns_empty(tmp_path):
    led = EntityLedger.load(tmp_path / "nope.json")
    assert led.entities == {}


# ---------- 漂移检出 ----------
def test_drift_detected_for_similar_artifact():
    led = EntityLedger()
    led.register("周天星斗大阵", "formation", 3)
    # LLM 抽取结果（真实路径：engine 传 extracted；此处直接给）
    text = "陈世嚣催动逆星大阵，符文流转，金光森然。"
    extracted = [{"name": "逆星大阵", "type": "formation", "aliases": []}]
    v = check_entity_consistency(text, led, chapter=7, extracted=extracted)
    assert any(x["kind"] == "entity_drift" for x in v)
    drift = [x for x in v if x["kind"] == "entity_drift"][0]
    assert "周天星斗大阵" in drift["candidates"]


def test_no_drift_for_registered_entity():
    led = EntityLedger()
    led.register("金箍棒", "artifact", 3)
    text = "刘浩握紧金箍棒，碎片发烫。"
    assert check_entity_consistency(text, led, chapter=4) == []


def test_new_entity_registered_not_violation():
    led = EntityLedger()
    led.register("金箍棒", "artifact", 3)
    # 新法器（不相似）登场 → 登记放行，不报漂移
    text = "林晚娘祭出「银河梭」，划破夜空。"
    v = check_entity_consistency(text, led, chapter=5)
    assert not any(x["kind"] == "entity_drift" for x in v)
    assert led.lookup("银河梭") == "银河梭"


def test_alias_reuse_not_drift():
    led = EntityLedger()
    led.register("陈世嚣", "character", 3, aliases=["明公"])
    text = "明公负手而立，望着刘浩。"
    assert check_entity_consistency(text, led, chapter=4) == []


# ---------- 回溯校验 ----------
PRIOR = [
    "刘浩在蟠桃园救一株灵芝，调动地脉被千里眼发现",
    "太白金星携玉帝旨意前来暗示刘浩身份",
    "林晚娘塞给刘浩一枚玉简",
]


def test_callback_valid_when_in_prior():
    text = "刘浩忽然想起林晚娘塞给他的那枚玉简，掌心发烫。"
    assert check_callback_validity(text, PRIOR) == []


def test_callback_flagged_when_not_in_prior():
    text = "他忽然想起土地神说过的话——量劫是天庭设计的清洗。"
    v = check_callback_validity(text, PRIOR)
    assert any(x["kind"] == "fabricated_callback" for x in v)


def test_callback_ignores_non_marker_sentences():
    text = "刘浩握紧铁棒，向前冲去。"
    assert check_callback_validity(text, PRIOR) == []


def test_callback_empty_prior_passes():
    assert check_callback_validity("他想起什么。", []) == []


# ---------- 规则抽取 ----------
def test_extract_rule_known_names_and_marked():
    text = "刘浩祭出「金箍棒」，林晚娘在旁。"
    ents = extract_entities_rule(text, known_names=["刘浩", "林晚娘"])
    names = {e["name"] for e in ents}
    assert "刘浩" in names and "林晚娘" in names
    assert "金箍棒" in names
    types = {e["name"]: e["type"] for e in ents}
    assert types["刘浩"] == "character"
    assert types["金箍棒"] == "artifact"
