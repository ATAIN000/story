"""tests/test_p19_system_fix.py — P19 系统性问题修复核心测试（3 用例）

P19.1: derive_cast 从题材取真实名字 / macro prompt 含名字约束
P19.3: key_events 覆盖检查产出 feedback
"""
from __future__ import annotations

from story_engine.worldview.derive_cast import derive_cast
from story_engine.macro.generator import _build_prompt
from story_engine.types import GenreBundle


# ============================================================
# P19.1: derive_cast 从题材 prompt.characters 提取真实名字
# ============================================================

def test_derive_cast_extracts_real_names():
    """derive_cast 传入 genre_params（含 prompt.characters）→
    返回的角色 name 是真实人名而非泛称「主角」「重要配角」"""
    genre_params = {
        "prompt": {
            "characters": "沈昭（诊所大夫，通晓药理）、陆锋（武馆拳师，刚直重义）",
        },
        "tracks": [{"id": "A", "name": "主线"}],
        "main_track": "A",
    }
    cast = derive_cast(
        worldview_layers={"L0": {"physics_deviation": "minor"}},
        genre_params=genre_params,
    )
    names = [c["name"] for c in cast]
    assert "沈昭" in names, f"主角名应为沈昭，实际 {names}"
    assert "陆锋" in names, f"配角名应为陆锋，实际 {names}"
    # 确保不再是泛称
    assert "主角" not in names
    assert "重要配角" not in names


# ============================================================
# P19.1: macro generator prompt 含名字硬约束
# ============================================================

def test_macro_prompt_contains_name_constraint():
    """_build_prompt 注入 cast_profile 后，prompt 含「人物名硬约束」段"""
    bundle = GenreBundle(
        genre="test", culture="test",
        genre_params={"title": "测试", "prompt": {"characters": "沈昭、陆锋"}},
        culture_params={},
    )
    cast_profile = derive_cast(
        genre_params=bundle.genre_params)
    prompt = _build_prompt(bundle, None, cast_profile,
                           "save_the_cat_15", 12, None)
    assert "人物名硬约束" in prompt
    # 约束段包含从 cast_profile 提取的名字
    cast_names = [c["name"] for c in cast_profile if c.get("name")]
    for name in cast_names:
        assert name in prompt


# ============================================================
# P19.3: key_events 覆盖检查产出 feedback
# ============================================================

def test_key_events_coverage_produces_feedback():
    """macro_context 有 key_events_required 但决策卡 beats 不覆盖 →
    _check_macro_coverage 往 macro_context['feedback'] 追加提示"""
    from story_engine.showrunner.decision import DecisionCard

    card = DecisionCard(
        episode=1, advance=["A"], seed=[], mid_touch=["E"], dormant=[],
        sternberg_distribution={}, active_payoffs=[],
        beats=[{"beat_id": "ep1_b1", "phase": "equilibrium",
                "track_name": "主线", "primitives": []}],
        snyder_coverage={}, target_arc="", gaps=[], ending_hook={},
        theme_touch=False, new_foreshadows=[],
    )
    card.macro_context = {
        "key_events_required": ["发现古剑中封印的剑灵", "与追杀者首次交锋"],
        "foreshadow_directives": [],
        "feedback_exists": False,
    }
    # 直接调用引擎的检查方法（不依赖完整引擎实例）
    from story_engine.engine import StoryEngine
    StoryEngine._check_macro_coverage(None, card)
    feedback = card.macro_context.get("feedback")
    assert feedback is not None and len(feedback) > 0, (
        "未覆盖的 key_events 应产出 feedback")
    assert "发现古剑" in " ".join(feedback) or "古剑" in " ".join(feedback)
