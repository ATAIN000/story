"""skill_router + realizer._skill_block 测试 — P-skill 技能包触发匹配接线。

覆盖：
1. select_skills 题材轴 + 原语轴双匹配（武侠/言情/悬疑/通用/无命中）
2. genre_signature / beat_primitive_names 稳健性
3. _skill_block 注入条件（有 registry / 无 registry / 非中文 / 无命中）
4. 端到端：真实插件 registry 加载 → realizer 注入 skill prompt_template
"""
from __future__ import annotations

from pathlib import Path

import pytest

from story_engine.narrative.skill_router import (
    SKILL_TRIGGER_MAP, SkillRule, beat_primitive_names, genre_signature,
    select_skills,
)
from story_engine.narrative.realizer import ChineseRealizer, EnglishRealizer


# ---------- 测试用 mock ----------

class _Bundle:
    """轻量 GenreBundle 替身：只暴露 genre / genre_params / language"""

    def __init__(self, genre="myth-shanhai", tags=None, fusion_formula="",
                 language="zh"):
        self.genre = genre
        self.language = language
        self.genre_params = {
            "taxonomy_tags": tags or [],
            "fusion": {"fusion_formula": fusion_formula} if fusion_formula else {},
        }


class _Beat:
    def __init__(self, primitives):
        self.primitives = primitives


class _IR:
    def __init__(self, beats):
        self.beats = beats
        self.texture = None


# ---------- genre_signature ----------

def test_genre_signature_combines_genre_prefix_tags_and_fusion():
    b = _Bundle("myth-shanhai", tags=["myth", "sinosphere"],
                fusion_formula="神话 × shanhai")
    sig = genre_signature(b)
    assert "myth" in sig and "shanhai" in sig and "sinosphere" in sig


def test_genre_signature_none_bundle_is_empty():
    assert genre_signature(None) == ""


def test_genre_signature_underscore_genre_normalized():
    # genre 用下划线也应拆出前缀（romance_cn_ceo → romance/cn/ceo）
    b = _Bundle("romance_cn_ceo", tags=["romance"])
    assert "romance" in genre_signature(b)


# ---------- beat_primitive_names ----------

def test_beat_primitive_names_from_string_list():
    ir = _IR([_Beat(["Conflict", "Suspense"])])
    assert beat_primitive_names(ir) == {"Conflict", "Suspense"}


def test_beat_primitive_names_handles_none_ir():
    assert beat_primitive_names(None) == set()


def test_beat_primitive_names_empty_beats():
    assert beat_primitive_names(_IR([])) == set()


# ---------- select_skills 题材 + 原语双轴 ----------

def test_select_combat_genre_with_conflict_includes_martial_pacing():
    """百鬼当道式：myth 题材 + Conflict 原语 → 武打四拍法"""
    skills = select_skills(_Bundle("myth-shanhai", tags=["myth"]),
                           _IR([_Beat(["Conflict"])]))
    assert "martial-combat-pacing" in skills


def test_select_romance_sacrifice_includes_reveal():
    skills = select_skills(_Bundle("romance-cn-ceo", tags=["romance"]),
                           _IR([_Beat(["Sacrifice", "Betrayal"])]))
    assert "concealed-sacrifice-reveal" in skills
    assert "escalating-misunderstanding" in skills


def test_select_mystery_revelation_includes_evidence_chain():
    skills = select_skills(_Bundle("mystery-family-locked", tags=["mystery"]),
                           _IR([_Beat(["Revelation", "Recognition"])]))
    assert "evidence-chain-buildup" in skills
    assert "deliberate-slip" in skills


def test_select_generic_suspense_includes_cliffhanger_for_any_genre():
    """通用结构技法（无题材约束）：任意题材 + Suspense → 评书扣子"""
    skills = select_skills(_Bundle("slice-food", tags=["slice"]),
                           _IR([_Beat(["Suspense"])]))
    assert "cliffhanger-split" in skills


def test_select_no_match_for_genre_without_relevant_primitive():
    """题材命中但有原语约束 + 本章无该原语 → 不注入（场景未到）"""
    skills = select_skills(_Bundle("myth-shanhai", tags=["myth"]),
                           _IR([_Beat(["GoalFormation"])]))
    # GoalFormation 无任何技法绑定 → 空列表
    assert skills == []


def test_select_combat_primitive_without_combat_genre_excluded():
    """原语命中但题材不符 → 不注入（武侠技法不进言情章）"""
    skills = select_skills(_Bundle("romance-cn-ceo", tags=["romance"]),
                           _IR([_Beat(["Conflict"])]))
    # push-pull-tension 是言情+Conflict，应命中；martial-combat-pacing 不应命中
    assert "push-pull-tension" in skills
    assert "martial-combat-pacing" not in skills


def test_select_respects_max_skills_cap():
    skills = select_skills(_Bundle("mystery-family-locked", tags=["mystery"]),
                           _IR([_Beat(["Revelation", "Recognition",
                                       "Conflict", "TurningPoint"])]),
                           max_skills=2)
    assert len(skills) == 2


def test_select_returns_known_skill_names_only():
    """所有返回名必须在 SKILL_TRIGGER_MAP 里（防止拼写漂移）"""
    valid = {r.name for r in SKILL_TRIGGER_MAP}
    skills = select_skills(_Bundle("myth-shanhai", tags=["myth"]),
                           _IR([_Beat(["Conflict", "Suspense",
                                       "TurningPoint"])]))
    for s in skills:
        assert s in valid


def test_select_priority_orders_double_hit_before_single():
    """双命中应排在单命中之前：myth+Conflict（双命中 martial-combat-pacing）
    排在仅原语命中的通用包之前"""
    skills = select_skills(_Bundle("myth-shanhai", tags=["myth"]),
                           _IR([_Beat(["Conflict", "Suspense"])]))
    # martial-combat-pacing（双命中，priority 10）应在 cliffhanger-split（通用，6）前
    assert skills.index("martial-combat-pacing") < skills.index("cliffhanger-split")


# ---------- _skill_block 注入条件 ----------

@pytest.fixture(scope="module")
def real_registry():
    """真实插件 registry（加载 story_engine/plugins，含 14 个 skill 包）"""
    from story_engine.kernel.registry import ExtensionRegistry
    r = ExtensionRegistry()
    r.scan_plugins(Path("story_engine/plugins"))
    return r


def test_skill_block_injects_templates_with_registry(real_registry):
    """有 registry + myth+Conflict → 非空，含武打四拍法 prompt_template"""
    rz = ChineseRealizer(registry=real_registry)
    block = rz._skill_block(_Bundle("myth-shanhai", tags=["myth"]),
                            _IR([_Beat(["Conflict"])]))
    assert block != ""
    assert "叙事技法" in block
    assert "四拍" in block or "架" in block   # martial-combat-pacing 四拍法标志


def test_skill_block_empty_without_registry():
    """无 registry → 返回 ''（零行为漂移）"""
    rz = ChineseRealizer(registry=None)
    block = rz._skill_block(_Bundle("myth-shanhai", tags=["myth"]),
                            _IR([_Beat(["Conflict"])]))
    assert block == ""


def test_skill_block_empty_for_english():
    """英文 realizer → 返回 ''（暂不注入中文技法，避免跨语言污染）"""
    rz = EnglishRealizer(registry=None)
    block = rz._skill_block(_Bundle("myth-shanhai", tags=["myth"]),
                            _IR([_Beat(["Conflict"])]))
    assert block == ""


def test_skill_block_empty_when_no_match(real_registry):
    """有 registry 但无命中（田园 + GoalFormation）→ 返回 ''"""
    rz = ChineseRealizer(registry=real_registry)
    block = rz._skill_block(_Bundle("slice-food", tags=["slice"]),
                            _IR([_Beat(["GoalFormation"])]))
    assert block == ""


def test_skill_block_templates_ordered_by_priority(real_registry):
    """注入顺序遵循 select_skills 优先级（高优先级在前）"""
    rz = ChineseRealizer(registry=real_registry)
    names = select_skills(_Bundle("myth-shanhai", tags=["myth"]),
                          _IR([_Beat(["Conflict", "Suspense"])]))
    block = rz._skill_block(_Bundle("myth-shanhai", tags=["myth"]),
                            _IR([_Beat(["Conflict", "Suspense"])]))
    # 第一个命中的高优先级包（martial-combat-pacing）的内容应出现在 block 前部
    pos_first = block.find("四拍") if "四拍" in block else block.find("架")
    pos_last_skill = block.rfind("评书") if "评书" in block else block.rfind("悬念")
    if pos_first != -1 and pos_last_skill != -1:
        assert pos_first < pos_last_skill


# ---------- 防回归：SkillRule 数据完整性 ----------

def test_all_skill_rules_have_at_least_one_trigger():
    """每个 SkillRule 必须有 genre_kw 或 primitives（否则永不命中）"""
    for rule in SKILL_TRIGGER_MAP:
        assert rule.genre_kw or rule.primitives, f"{rule.name} 无任何触发条件"


def test_skill_rule_names_unique():
    names = [r.name for r in SKILL_TRIGGER_MAP]
    assert len(names) == len(set(names))
