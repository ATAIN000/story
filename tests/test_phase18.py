"""tests/test_phase18.py — P18 跨层检测 + 审阅面板 + macro_alignment 核心测试

P18.1: C1 fair_deduction+precognition 检测 / clean profile 无警告 / C2 身份冲突
P18.2: regenerate_component 单组件重摇 / 冲突标记注入 prompt
P18.3: macro_alignment 检测缺失 key_event / clean pass / progress 端点结构
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from story_engine.macro.conflict_check import check_cross_layer
from story_engine.macro.generator import generate_macro_plan, regenerate_component
from story_engine.macro import macro_plan_to_dict
from story_engine.types import GenreBundle
from story_engine.evaluator.leader import ARBITRATION_ORDER

from conftest import import_backend_main


def run(coro):
    return asyncio.run(coro)


# ============================================================
# P18.1: 跨层冲突检测
# ============================================================

def test_c1_fair_deduction_with_precognition_detected():
    """C1: 公案悬疑（fair_play）+ 血脉天赋/觉醒能力 → 检测到 HIGH 冲突"""
    wv = {"layers": {"L3": {
        "power_source": "bloodline",
        "acquisition_method": "awakening",
        "power_existence": "rare",
    }}}
    genre_params = {"information_distribution": "fair_play", "pacing_curve": "slow_burn"}
    warnings = check_cross_layer(genre_params, wv, [], "mystery")
    c1_warnings = [w for w in warnings if w.type == "C1"]
    assert len(c1_warnings) >= 1
    assert all(w.severity == "HIGH" for w in c1_warnings)
    assert any("公平推理" in w.title or "公平" in w.description for w in c1_warnings)


def test_clean_profile_no_warnings():
    """无冲突的 profile → 0 warnings"""
    wv = {"layers": {"L3": {"power_existence": "nonexistent"}}}
    genre_params = {"pacing_curve": "medium"}
    warnings = check_cross_layer(genre_params, wv, [], "romance")
    assert len(warnings) == 0


def test_c2_identity_mismatch_detected():
    """C2: 提刑官 + 神权社会 → HIGH 冲突"""
    wv = {"layers": {"L5": {"political_system": "theocracy"}}}
    cast = [{"name": "沈明", "role": "提刑官"}]
    warnings = check_cross_layer({}, wv, cast, "mystery")
    c2_warnings = [w for w in warnings if w.type == "C2"]
    assert len(c2_warnings) >= 1
    assert c2_warnings[0].severity == "HIGH"
    assert "提刑" in c2_warnings[0].title or "theocracy" in c2_warnings[0].title


# ============================================================
# P18.2: 单组件重摇 + 冲突标记注入
# ============================================================

def _mock_kernel(is_mock: bool = True):
    return SimpleNamespace(llm=SimpleNamespace(is_mock=is_mock))


def _bundle():
    return GenreBundle(
        genre="mystery", culture="confucian_officialdom", target_length=10,
        genre_params={"title": "悬疑", "resolution_pattern": "推理破案",
                      "main_track": "A"},
    )


def _cast():
    return [{"name": "陆明", "role": "主角", "persona": {
        "arc_lie": "信任等于软弱", "arc_truth": "连接才是力量",
        "arc_want": "破案", "arc_need": "学会信任", "arc_type": "positive_change"}}]


def test_regenerate_component_preserves_other_components():
    """单组件重摇：重摇 pacing，其余组件不变"""
    kernel = _mock_kernel(True)
    bundle = _bundle()
    cast = _cast()
    # 先生成完整计划
    plan = run(generate_macro_plan(kernel, bundle, None, cast, "save_the_cat_15"))
    plan_dict = macro_plan_to_dict(plan)
    original_blueprint_logline = plan_dict["blueprint"]["logline"]
    original_episodes_count = len(plan_dict["episode_outlines"])

    # 重摇 pacing 组件
    new_plan = run(regenerate_component(
        kernel, bundle, None, cast, "save_the_cat_15",
        "pacing", plan_dict))
    new_dict = macro_plan_to_dict(new_plan)

    # blueprint 保持不变
    assert new_dict["blueprint"]["logline"] == original_blueprint_logline
    # episodes 保持不变
    assert len(new_dict["episode_outlines"]) == original_episodes_count
    # pacing_curve 存在
    assert "key_tension_points" in new_dict["pacing_curve"]


def test_conflict_warnings_injected_into_prompt():
    """冲突标记注入到宏观生成 prompt"""
    class _RecordingLLM:
        def __init__(self):
            self.prompt = ""

        async def __call__(self, prompt, **kw):
            self.prompt = prompt
            return SimpleNamespace(text="invalid: not yaml")

    llm_call = _RecordingLLM()
    kernel = SimpleNamespace(
        llm=SimpleNamespace(is_mock=False), llm_call=llm_call)
    conflict_warnings = [
        {"severity": "HIGH", "title": "测试冲突",
         "description": "测试描述", "suggestion": "测试建议"}
    ]
    run(generate_macro_plan(kernel, _bundle(), None, _cast(), "save_the_cat_15",
                            conflict_warnings=conflict_warnings))
    assert "跨层冲突约束" in llm_call.prompt
    assert "测试冲突" in llm_call.prompt


# ============================================================
# P18.3: macro_alignment critic + progress 端点
# ============================================================

def test_macro_alignment_in_arbitration_order():
    """macro_alignment 在仲裁序中，位于 setting_consistency 之后、plot_coherence 之前"""
    assert "macro_alignment" in ARBITRATION_ORDER
    idx_macro = ARBITRATION_ORDER.index("macro_alignment")
    idx_setting = ARBITRATION_ORDER.index("setting_consistency")
    idx_plot = ARBITRATION_ORDER.index("plot_coherence")
    assert idx_setting < idx_macro < idx_plot


def test_macro_alignment_dimension_in_guide():
    """macro_alignment 在 critic 维度库中"""
    from story_engine.evaluator.critic_parliament import DIMENSION_GUIDE
    assert "macro_alignment" in DIMENSION_GUIDE
    desc, good, bad = DIMENSION_GUIDE["macro_alignment"]
    assert desc  # 非空
    assert "宏观" in desc or "计划" in desc


def test_macro_progress_endpoint_structure():
    """GET /api/macro/progress → 含 current_episode / foreshadow_status 等字段"""
    import json
    import tempfile
    from pathlib import Path
    # 先生成一个 plan 并写入临时项目目录
    plan = macro_plan_to_dict(run(generate_macro_plan(
        _mock_kernel(True), _bundle(), None, _cast(), "save_the_cat_15")))
    backend = import_backend_main()
    from fastapi.testclient import TestClient
    with TestClient(backend.app) as c:
        # 写入 macro_plan.json 到 engine.project_dir
        plan_path = Path(backend.deps.engine.project_dir) / "macro_plan.json"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        resp = c.get("/api/macro/progress")
    assert resp.status_code == 200
    data = resp.json()
    assert "current_episode" in data
    assert "total_episodes" in data
    assert "foreshadow_status" in data
    assert "arc_phases" in data
    assert isinstance(data["foreshadow_status"], list)
