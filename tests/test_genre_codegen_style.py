"""第二波⑤ codegen 题材笔法测试 — _STYLE_PROFILES / _lookup_style / build_pack

验证：codegen 生成的 prompt.style 不再是空洞模板套话，而是 family 题材笔法；
hard_requirements 含 family 特色禁忌；所有 codegen 包过门禁。
"""
from story_engine.meta.genre_codegen import (
    _STYLE_PROFILES, _lookup_style, _style_for, _hard_reqs_for, build_pack,
)
from story_engine.meta.genre_taxonomy import GenreTaxon, all_taxa
from story_engine.meta.genre_validator import validate_genre_pack


def _taxon(family, tags=("x", "y")):
    return GenreTaxon(
        id=f"test-{family}", title=f"测试·{family}", family=family,
        family_title=family, subtrope="test", tier="base", tags=tuple(tags),
        default_culture="modern-chinese-urban", primary_preset="shanhai_zhiguai",
        secondary_presets=(), track_profile="fantasy", vibe=f"{family}测试",
    )


def test_style_no_longer_generic_template():
    """style 不再是原空洞的「1000-1500字，节奏清晰，冲突可见，章末留钩子」"""
    style = _style_for(_taxon("martial"))
    assert "武侠笔法" in style
    assert style != "1000-1500字，节奏清晰，冲突可见，章末留钩子"


def test_lookup_style_exact_match():
    pen, taboo = _lookup_style("martial")
    assert pen and "武侠" in pen
    assert taboo


def test_lookup_style_prefix_match():
    """system-cn → system（前缀匹配）"""
    pen, _ = _lookup_style("system-cn")
    assert pen and "系统" in pen


def test_lookup_style_contains_match():
    """high-fantasy → fantasy（包含匹配）"""
    pen, _ = _lookup_style("high-fantasy")
    assert pen and "奇幻" in pen


def test_lookup_style_unknown_returns_none():
    assert _lookup_style("nonexistent-genre") == (None, None)


def test_hard_reqs_include_family_taboo():
    """命中 family 的包，hard_requirements 含 family 特色禁忌（5 条而非 4）"""
    reqs = _hard_reqs_for(_taxon("mystery"))
    assert len(reqs) == 5
    assert any("线索" in r or "证据" in r for r in reqs)


def test_hard_reqs_unknown_family_still_has_four_base():
    """未命中 family → 仅 4 条通用纪律（不崩）"""
    reqs = _hard_reqs_for(_taxon("nonexistent"))
    assert len(reqs) == 4


def test_all_codegen_packs_have_stylistic_style_and_pass_validation():
    """全量：所有 codegen 包 build_pack 过门禁 + style 命中题材笔法"""
    codegen = [t for t in all_taxa() if not t.legacy]
    assert len(codegen) > 200   # 回归保护：codegen 包数量级
    for t in codegen:
        pack = build_pack(t)
        errs = validate_genre_pack(pack)
        assert not errs, f"{t.id} 门禁失败: {errs}"
        style = pack["params"]["prompt"]["style"]
        assert "笔法" in style, f"{t.id}({t.family}) style 未命中笔法"
        # 5 键齐全（test_genre_plugins 契约）
        prompt = pack["params"]["prompt"]
        for key in ("role", "setting", "characters", "style", "hard_requirements"):
            assert key in prompt


def test_style_profiles_all_have_pen_and_taboo():
    """数据完整性：每个 _STYLE_PROFILES 项都有 (笔法, 禁忌) 两元素"""
    for fam, (pen, taboo) in _STYLE_PROFILES.items():
        assert isinstance(pen, str) and pen.strip(), fam
        assert isinstance(taboo, str) and taboo.strip(), fam
        assert "笔法" in pen, f"{fam} 笔法缺「笔法」标记"
