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


# ---------- P12.2 端点测试（3 核心） ----------
def test_schema_endpoint_layers_and_param_count():
    """GET /api/worldview/schema：layers 含 L0-L3、param_count 与 ALL_PARAMS 一致、
    layers_covered 仅已数据化层。"""
    from fastapi.testclient import TestClient
    from conftest import import_backend_main
    backend = import_backend_main()
    r = TestClient(backend.app).get("/api/worldview/schema")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [l["id"] for l in body["layers"]] == ["L0", "L1", "L2", "L3"]
    assert body["param_count"] == len(ALL_PARAMS)  # 31
    assert body["layers_covered"] == ["L0", "L1", "L2", "L3"]


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
