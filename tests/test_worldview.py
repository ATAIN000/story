"""tests for story_engine.worldview（Phase 12：全 10 层）

覆盖 brief 要求的 3 个核心场景：
  1. 级联收窄：metaphysics=materialist → consciousness_nature 不含 soul_based
  2. 违例检出：上述 profile 显式设 consciousness_nature=soul_based → violations 命中
  3. 容忍：空 profile / 未知键不崩；to_prompt_text 跳过空层
"""
from __future__ import annotations

from story_engine.worldview import (
    ALL_PARAMS, LAYERS, LANGUAGE_LAYERS, CHARACTER_LAYERS, PREDICATES, WorldviewProfile, evaluate,
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
    # 10 层齐全（L0-L9）
    assert [l["id"] for l in LAYERS] == [
        "L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L9"]
    # 语言 5 层齐全（LANG1-LANG5）
    assert [l["id"] for l in LANGUAGE_LAYERS] == [
        "LANG1", "LANG2", "LANG3", "LANG4", "LANG5"]
    # 人物原型 5 层齐全（CHAR1-CHAR5）
    assert [l["id"] for l in CHARACTER_LAYERS] == [
        "CHAR1", "CHAR2", "CHAR3", "CHAR4", "CHAR5"]
    # 每参数至少 4 个枚举值，每值含 value/label
    # （text_input 类型除外——它只有一个占位项 __text__）
    for layer in LAYERS + LANGUAGE_LAYERS + CHARACTER_LAYERS:
        for p in layer["params"]:
            if p.get("type") == "text_input":
                assert len(p["options"]) >= 1, f"{p['key']} text_input 选项过少"
                continue
            assert len(p["options"]) >= 4, f"{p['key']} 选项过少"
            for o in p["options"]:
                assert "value" in o and "label" in o, f"{p['key']} 选项缺字段"
    # 关键枚举值（素材原文）存在
    assert "soul_based" in [o["value"] for o in ALL_PARAMS["consciousness_nature"]["options"]]
    assert "materialist" in [o["value"] for o in ALL_PARAMS["metaphysics"]["options"]]
    # L4-L7 关键枚举值抽检（素材原文）
    assert "conditional_immortal" in [o["value"] for o in ALL_PARAMS["mortality_model"]["options"]]
    assert "theocracy" in [o["value"] for o in ALL_PARAMS["political_system"]["options"]]
    assert "language_is_magic" in [o["value"] for o in ALL_PARAMS["language_paradigm"]["options"]]
    assert "precursor" in [o["value"] for o in ALL_PARAMS["lost_civilizations"]["options"]]
    # L8-L9 关键枚举值抽检（素材原文）
    assert "manufactured" in [o["value"] for o in ALL_PARAMS["truth_structure"]["options"]]
    assert "collective" in [o["value"] for o in ALL_PARAMS["memory_system"]["options"]]
    assert "nature_hidden" in [o["value"] for o in ALL_PARAMS["hidden_truths"]["options"]]
    assert "transcendent" in [o["value"] for o in ALL_PARAMS["conflict_resolution"]["options"]]
    assert "cosmic" in [o["value"] for o in ALL_PARAMS["conflict_types"]["options"]]
    # LANG1-LANG5 关键枚举值抽检（素材原文）
    assert "performative" in [o["value"] for o in ALL_PARAMS["language_power"]["options"]]
    assert "power_marked" in [o["value"] for o in ALL_PARAMS["classifier_system"]["options"]]
    assert "unreliable_by_design" in [o["value"] for o in ALL_PARAMS["narrative_reliability"]["options"]]
    assert "prophecy_first" in [o["value"] for o in ALL_PARAMS["temporal_narrative"]["options"]]
    assert "ineffable_negation" in [o["value"] for o in ALL_PARAMS["preferred_rhetoric"]["options"]]
    # CHAR1-CHAR5 关键枚举值抽检（素材原文）
    assert "hero" in [o["value"] for o in ALL_PARAMS["narrative_function"]["options"]]
    assert "magician" in [o["value"] for o in ALL_PARAMS["pearson_primary"]["options"]]
    assert "athena" in [o["value"] for o in ALL_PARAMS["schmidt_goddess"]["options"]]
    assert "villain" in [o["value"] for o in ALL_PARAMS["schmidt_polarity"]["options"]]
    assert "5" in [o["value"] for o in ALL_PARAMS["enneagram_type"]["options"]]
    assert "positive_change" in [o["value"] for o in ALL_PARAMS["arc_type"]["options"]]
    assert "bazong" in [o["value"] for o in ALL_PARAMS["tropes"]["options"]]
    # 参数总数：71（L0-L9 世界观）+ 15（LANG1-LANG5 语言）+ 14（CHAR1-CHAR5 人物原型）= 100
    assert len(ALL_PARAMS) == 100
    # 谓词条数符合预期（批1-3 ≥55，批4 语言交叉追加 >70，批5 人物原型追加 >80）
    assert len(PREDICATES) > 80


# ---------- P12.2 端点测试（3 核心） ----------
def test_schema_endpoint_layers_and_param_count():
    """GET /api/worldview/schema：layers 含 L0-L9 + LANG1-LANG5、param_count 与
    ALL_PARAMS 一致（86）、layers_covered 为当前已数据化层。"""
    from fastapi.testclient import TestClient
    from conftest import import_backend_main
    backend = import_backend_main()
    r = TestClient(backend.app).get("/api/worldview/schema")
    assert r.status_code == 200, r.text
    body = r.json()
    expected = ["L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L9",
                "LANG1", "LANG2", "LANG3", "LANG4", "LANG5",
                "CHAR1", "CHAR2", "CHAR3", "CHAR4", "CHAR5"]
    assert [l["id"] for l in body["layers"]] == expected
    assert body["param_count"] == len(ALL_PARAMS)  # 100（71 世界观 + 15 语言 + 14 人物原型）
    assert body["layers_covered"] == expected


def test_evaluate_endpoint_materialist_narrows_consciousness_nature():
    """POST /api/worldview/evaluate：materialist profile 经端点扁平化 + evaluate
    → allowed[consciousness_nature] 不含 soul_based（跨层收窄，端点直通纯函数）。"""
    from fastapi.testclient import TestClient
    from conftest import import_backend_main
    backend = import_backend_main()
    r = TestClient(backend.app).post(
        "/api/worldview/evaluate",
        json={"profile": {"L0": {"metaphysics": "materialist"}}})
    assert r.status_code == 200, r.text
    body = r.json()
    allowed_cn = body["allowed"]["consciousness_nature"]
    assert "soul_based" not in allowed_cn   # 唯物基底不允许灵魂独立存在
    assert "emergent" in allowed_cn
    assert body["violations"] == []         # profile 未显式设违例值


def test_confirm_with_worldview_persists_and_rejects_violations():
    """POST /api/gacha/confirm 携带 worldview：合法 profile → 落盘 worldview.json
    （含 layers/preset/created_at）+ project.json 含 worldview 摘要；
    违例 profile → 422 不落盘。走无 project_name 的原地 init 路径，避免新建
    项目目录带来的 SQLite 句柄锁（finally 只删 JSON 文件，不动项目目录）。"""
    import json as _json
    from fastapi.testclient import TestClient
    from conftest import import_backend_main
    backend = import_backend_main()
    orig = (backend.engine.genre.name, backend.engine.culture.name)
    proj_dir = backend.engine.project_dir   # conftest 临时项目目录
    c = TestClient(backend.app)
    try:
        # 合法 profile：library 卡 + worldview（无违例）→ 原地 init + 落盘
        valid_wv = {
            "layers": {"L0": {"metaphysics": "materialist",
                              "consciousness_nature": "emergent"}},
            "preset": "sci-fi-hard",
        }
        card = {"mode": "library", "genre": {"name": "mystery", "source": "library",
                                             "desc": "d"},
                "culture": {"name": "confucian_officialdom"},
                "archetype": {"name": ""}, "rule_packs": [], "note": None,
                "worldview": valid_wv}
        r = c.post("/api/gacha/confirm", json=card)
        assert r.status_code == 200, r.text
        wv_file = proj_dir / "worldview.json"
        assert wv_file.exists()
        wv_data = _json.loads(wv_file.read_text(encoding="utf-8"))
        assert wv_data["layers"] == valid_wv["layers"]
        assert wv_data["preset"] == "sci-fi-hard"
        assert wv_data["created_at"]
        meta = _json.loads(
            (proj_dir / "project.json").read_text(encoding="utf-8"))
        assert meta["worldview"]["preset"] == "sci-fi-hard"
        assert meta["worldview"]["param_count"] == 2  # 两个参数已设

        # 违例 profile：materialist + soul_based → 422 不落盘不切换
        bad_card = {"mode": "library",
                    "genre": {"name": "mystery", "source": "library", "desc": "d"},
                    "culture": {"name": "confucian_officialdom"},
                    "archetype": {"name": ""}, "rule_packs": [], "note": None,
                    "worldview": {"layers": {"L0": {
                        "metaphysics": "materialist",
                        "consciousness_nature": "soul_based"}}}}
        r2 = c.post("/api/gacha/confirm", json=bad_card)
        assert r2.status_code == 422, r2.text
        # 失败前不应改写已落盘的 worldview.json（内容仍是合法那份）
        assert _json.loads(wv_file.read_text(encoding="utf-8"))["preset"] == "sci-fi-hard"
    finally:
        # 恢复 engine 题材/文化 + 删掉测试写的 JSON 文件（不删项目目录本身）
        for f in (proj_dir / "worldview.json",):
            if f.exists():
                f.unlink(missing_ok=True)
        c.post("/api/project/init",
               json={"genre": orig[0], "culture": orig[1]})


# ---------- P12.3 双通道融合（3 核心） ----------

def test_realizer_prompt_includes_worldview_section_when_provided():
    """有 worldview profile 时 Realizer prompt 含「=== 世界观设定 ===」段，
    段体为 WorldviewProfile.to_prompt_text() 输出。fake LLM 记录 prompt 断言。"""
    import asyncio
    from types import SimpleNamespace
    from story_engine.narrative import (BeatIR, ChineseRealizer, EventIR,
                                        NarrativeIR, SceneBreakdown, TextureParams)
    from story_engine.narrative.ir_builder import TEXTURE_DEFAULTS

    class _FakeLLM:
        def __init__(self):
            self.captured = None

        async def call(self, prompt, *, purpose="realize_chapter", **kw):
            self.captured = prompt
            return SimpleNamespace(text="正文。")

    profile = WorldviewProfile(layers={"L0": {"metaphysics": "dualist"}})
    wv_text = profile.to_prompt_text()
    assert wv_text  # 非空（L0 形而上学已设）

    ir = NarrativeIR(
        beats=[BeatIR("b1", "disruption", ["Suspense"], "man_in_hole", 0.7)],
        events=[EventIR("甲", "act:x", None, "地", "第1日·午", None, None, None)],
        dialogue_lines=[], scene_breakdown=[SceneBreakdown("s1", (0, 1), "地")],
        texture=TextureParams(**TEXTURE_DEFAULTS["zh"]))
    llm = _FakeLLM()
    realizer = ChineseRealizer(llm_call=llm.call)
    asyncio.run(realizer.realize(ir, None, None, worldview_text=wv_text))
    prompt = llm.captured
    assert "=== 世界观设定 ===" in prompt
    assert wv_text in prompt          # 段体含 to_prompt_text 输出


def test_realizer_prompt_unchanged_when_no_worldview():
    """无 worldview profile（worldview_text=None）时 prompt 不含世界观段，
    与现状逐字一致。"""
    import asyncio
    from types import SimpleNamespace
    from story_engine.narrative import (BeatIR, ChineseRealizer, EventIR,
                                        NarrativeIR, SceneBreakdown, TextureParams)
    from story_engine.narrative.ir_builder import TEXTURE_DEFAULTS

    class _FakeLLM:
        async def call(self, prompt, *, purpose="realize_chapter", **kw):
            self.captured = prompt
            return SimpleNamespace(text="正文。")

    ir = NarrativeIR(
        beats=[BeatIR("b1", "disruption", ["Suspense"], "man_in_hole", 0.7)],
        events=[EventIR("甲", "act:x", None, "地", "第1日·午", None, None, None)],
        dialogue_lines=[], scene_breakdown=[SceneBreakdown("s1", (0, 1), "地")],
        texture=TextureParams(**TEXTURE_DEFAULTS["zh"]))
    llm = _FakeLLM()
    realizer = ChineseRealizer(llm_call=llm.call)
    asyncio.run(realizer.realize(ir, None, None))   # worldview_text 缺省 None
    assert "=== 世界观设定 ===" not in llm.captured


def test_worldview_to_world_rules_passes_validator_check():
    """to_world_rules() 产出的 kind=bool 规则 expr 能过 ConsistencyValidator
    .check_rule_expr（限 5 事实词汇表内）。"""
    from story_engine.validator import ConsistencyValidator

    # power_existence=nonexistent → has_supernatural=False
    p1 = WorldviewProfile(layers={"L3": {"power_existence": "nonexistent"}})
    bool_rules = [r for r in p1.to_world_rules() if r.get("kind") == "bool"]
    assert bool_rules, "应至少产出 1 条布尔规则"
    for r in bool_rules:
        assert ConsistencyValidator.check_rule_expr(r["expr"]), \
            f"expr 非法：{r['expr']}"

    # power_existence=common → has_supernatural=True
    p2 = WorldviewProfile(layers={"L3": {"power_existence": "common"}})
    exprs = [r["expr"] for r in p2.to_world_rules() if r.get("kind") == "bool"]
    assert "has_supernatural" in exprs
    assert ConsistencyValidator.check_rule_expr("has_supernatural")


# ---------- P12.4 十骨架预设（2 核心） ----------
def test_all_ten_presets_pass_evaluate_no_violations():
    """十骨架每个 preset：参数键是 ALL_PARAMS 的子集（当前覆盖 L0-L3，
    L4-L7 预设值待 P12.6 后半补全）、值在合法枚举内、evaluate 无违例。"""
    from story_engine.worldview import PRESETS, evaluate

    all_keys = set(ALL_PARAMS)
    assert len(PRESETS) == 10, f"应有 10 个骨架，实际 {len(PRESETS)}"
    for p in PRESETS:
        params = p["params"]
        # 字段合法：键集合是 ALL_PARAMS 的子集（L4-L7 尚未补全预设值）
        assert set(params) <= all_keys, f"{p['key']} 含未知参数键"
        # 值合法：每个值都在 ALL_PARAMS 对应枚举内
        for k, v in params.items():
            valid = [o["value"] for o in ALL_PARAMS[k]["options"]]
            assert v in valid, f"{p['key']}.{k}={v} 不在合法枚举 {valid}"
        # evaluate 无违例
        res = evaluate(params)
        assert res["violations"] == [], \
            f"{p['key']} 有违例：{res['violations']}"


def test_schema_endpoint_presets_have_name_vibe_and_summary():
    """GET /api/worldview/schema：presets 列表 10 项，每项含 key/name/vibe/summary。"""
    from fastapi.testclient import TestClient
    from conftest import import_backend_main
    backend = import_backend_main()
    r = TestClient(backend.app).get("/api/worldview/schema")
    assert r.status_code == 200, r.text
    presets = r.json()["presets"]
    assert len(presets) == 10
    for p in presets:
        assert p["key"] and p["name"] and p["vibe"] and p["summary"], \
            f"preset 字段不完整：{p}"
        assert "metaphysics=" in p["summary"]   # 摘要含关键参数
