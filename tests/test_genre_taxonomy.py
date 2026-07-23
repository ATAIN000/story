"""P22 测试：genre taxonomy 315 题材 + 三轴亲和 + 浏览 API

核心用例（用户指令：只保留核心）：
1. 数量与唯一性：≥300 taxa、id/title 全局唯一、315 个 genre yaml 全过
   validate_genre_pack（H7 门禁）
2. 无幽灵文化：taxonomy default_culture 与全部 genre allowed_cultures
   都落在已注册 culture ∪ {*}
3. 抽样产决策卡：每 family 抽 1 题材，GenreBundle+Showrunner 直接产卡不崩
4. 浏览 API：分页 / q 搜索 / tags AND / tier 筛选
5. C6 亲和：错配骨架 → MEDIUM 警告；亲和骨架 → 无 C6
6. begin 响应带三轴推荐字段
"""
from __future__ import annotations

from pathlib import Path

import yaml

from story_engine.kernel.registry import ExtensionRegistry
from story_engine.meta.genre_taxonomy import (
    all_taxa, is_preset_compatible, list_taxa, macro_templates_for_genre,
    presets_for_genre, taxon_by_id, taxonomy_stats)
from story_engine.meta.genre_validator import validate_genre_pack
from story_engine.macro.conflict_check import check_cross_layer
from story_engine.showrunner.decision import Showrunner
from story_engine.types import GenreBundle, WorldState

GENRES_DIR = (Path(__file__).resolve().parent.parent
              / "story_engine" / "plugins" / "genres")
PLUGINS_DIR = GENRES_DIR.parent


# ---------- 用例1：数量、唯一性、全量 yaml 过门禁 ----------

def test_taxonomy_count_and_unique():
    taxa = all_taxa()
    assert len(taxa) >= 300
    stats = taxonomy_stats()
    assert stats["legacy"] == 29
    ids = [t.id for t in taxa]
    titles = [t.title for t in taxa]
    assert len(ids) == len(set(ids)), "taxon id 重复"
    assert len(titles) == len(set(titles)), "taxon title 重复"


def test_all_genre_yamls_pass_validate():
    files = sorted(GENRES_DIR.glob("*.yaml"))
    assert len(files) >= 300
    bad = []
    for p in files:
        errs = validate_genre_pack(
            yaml.safe_load(p.read_text(encoding="utf-8")))
        if errs:
            bad.append(f"{p.stem}: {';'.join(errs)}")
    assert not bad, f"{len(bad)} 个包未过门禁：{bad[:3]}"


# ---------- 用例2：无幽灵文化 ----------

def test_no_ghost_cultures():
    reg = ExtensionRegistry()
    reg.scan_plugins(PLUGINS_DIR)
    cultures = set(reg.list_plugins("story.culture")["story.culture"])
    # taxonomy 推荐文化全部已注册
    for t in all_taxa():
        assert t.default_culture in cultures, \
            f"{t.id} default_culture 幽灵：{t.default_culture}"
    # 全部 genre 包（含 legacy）allowed_cultures 无幽灵
    for g in reg.list_plugins("story.genre")["story.genre"]:
        m = reg.get_manifest("story.genre", g)
        for c in (m.allowed_cultures or ["*"]):
            assert c == "*" or c in cultures, f"{g} allowed_cultures 幽灵：{c}"


# ---------- 用例3：每 family 抽样产决策卡 ----------

def test_sample_decision_cards_per_family():
    reg = ExtensionRegistry()
    reg.scan_plugins(PLUGINS_DIR)
    seen_families: dict[str, str] = {}
    for t in all_taxa():
        seen_families.setdefault(t.family, t.id)
    assert len(seen_families) >= 30  # 35 族
    for fam, gid in sorted(seen_families.items()):
        m = reg.get_manifest("story.genre", gid)
        bundle = GenreBundle(genre=gid, culture="confucian_officialdom",
                             genre_params=m.params, culture_params={})
        card = Showrunner(bundle).generate_decision_card(1, WorldState())
        assert card is not None, f"{fam}/{gid} 产卡失败"


# ---------- 用例4：浏览 API 分页/搜索/筛选 ----------

def test_genres_api_pagination_filter():
    from conftest import import_backend_main
    from fastapi.testclient import TestClient
    backend = import_backend_main()
    with TestClient(backend.app) as c:
        r = c.get("/api/gacha/genres", params={"limit": 5})
        d = r.json()
        assert r.status_code == 200
        assert d["total"] >= 300 and len(d["items"]) == 5
        assert d["facets"]["families"] and d["facets"]["tags"]
        # q 搜索
        d = c.get("/api/gacha/genres", params={"q": "无限"}).json()
        assert d["total"] > 0
        assert all("无限" in (i["title"] + i["family_title"] + i["vibe"])
                   or "dungeon_loop" in i["tags"] or "myriad" in i["tags"]
                   for i in d["items"])
        # tags AND：交集应小于等于单 tag
        only_rom = c.get("/api/gacha/genres",
                         params={"tags": "romance", "limit": 1}).json()["total"]
        both = c.get("/api/gacha/genres",
                     params={"tags": "romance,cultivation", "limit": 100}
                     ).json()
        assert 0 < both["total"] <= only_rom
        assert all({"romance", "cultivation"} <= set(i["tags"])
                   for i in both["items"])
        # tier 筛选
        d = c.get("/api/gacha/genres", params={"tier": "hot", "limit": 100}).json()
        assert d["total"] > 0
        assert all(i["tier"] == "hot" for i in d["items"])


# ---------- 用例5：C6 题材×骨架亲和 ----------

def test_c6_affinity_warning_on_mismatch():
    # xianxia-ascension 亲和 xianxia_cultivation；选 cthulhu_mythos → MEDIUM
    ws = check_cross_layer({}, None, [], "xianxia-ascension",
                           wv_preset="cthulhu_mythos")
    c6 = [w for w in ws if w.type == "C6"]
    assert len(c6) == 1 and c6[0].severity == "MEDIUM"
    assert "xianxia_cultivation" in c6[0].suggestion
    # 亲和骨架 → 无 C6
    ws = check_cross_layer({}, None, [], "xianxia-ascension",
                           wv_preset="xianxia_cultivation")
    assert not [w for w in ws if w.type == "C6"]
    # 空 preset / 未知题材 → 无 C6
    assert not [w for w in check_cross_layer({}, None, [], "xianxia-ascension")
                if w.type == "C6"]
    assert not [w for w in check_cross_layer(
        {}, None, [], "no-such-genre", wv_preset="cthulhu_mythos")
        if w.type == "C6"]
    # taxonomy 函数本身
    assert is_preset_compatible("xianxia-ascension", "xianxia_cultivation")
    assert not is_preset_compatible("xianxia-ascension", "cthulhu_mythos")
    assert "xianxia_cultivation" in presets_for_genre("xianxia-ascension")
    assert "save_the_cat_15" in macro_templates_for_genre("infinite-rule-game")


# ---------- 用例6：begin 响应带三轴推荐 ----------

def test_begin_response_has_taxonomy_fields():
    from conftest import import_backend_main
    from fastapi.testclient import TestClient
    backend = import_backend_main()
    with TestClient(backend.app) as c:
        r = c.post("/api/gacha/begin", json={"genre_name": "xianxia-ascension"})
        d = r.json()
        assert r.status_code == 200
        assert d["recommended_presets"][0] == "xianxia_cultivation"
        assert d["recommended_macro_templates"]
        assert "cultivation" in d["tags"]
        assert d["family_title"] == "修仙"
        assert d["culture_title"]
        c.post(f"/api/gacha/{d['session_id']}/cancel")
        # macro/templates?genre= 推荐标记
        tpls = c.get("/api/macro/templates",
                     params={"genre": "infinite-rule-game"}).json()["templates"]
        recommended = [t["name"] for t in tpls if t["recommended"]]
        assert set(recommended) == set(
            macro_templates_for_genre("infinite-rule-game"))
