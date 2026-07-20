"""P7.4 测试：L5 world.rule pack 引用合并 + Z3 expr 加载校验

核心用例（用户指令：只保留核心）：
1. 引用合并：mystery（rule_packs: [fair-play]）的 world_rules 含 pack 的
   no_late_clue 新规则；同 id 的 fair_play 取 pack 版（desc 为 pack 值）；
   内嵌规则原位保留、插件 params 本体不被污染；合并结果可过 Z3 管线
2. 非法 expr 拒载：tmp pack 含坏 expr / 引用未知事实 / 缺 id 的规则 +
   一条好规则 → 坏规则跳过 + warning，好规则正常合并，未注册包跳过不崩
3. 未配置 rule_packs 的 genre（romance）world_rules 与 yaml 基线逐字一致
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

from story_engine.engine import StoryEngine
from story_engine.types import WorldEvent, WorldState

GENRES_DIR = (Path(__file__).resolve().parent.parent
              / "story_engine" / "plugins" / "genres")


# ---------- 用例1：rule_packs 引用合并（mystery + fair-play） ----------

def test_rule_packs_reference_merge(tmp_path, monkeypatch):
    monkeypatch.setenv("STORY_ENGINE_GENRE", "mystery")
    eng = StoryEngine(str(tmp_path))
    try:
        rules = eng.validator.world_rules
        by_id = {r["id"]: r for r in rules}
        # 内嵌 3 条原位保留 + pack 新规则 no_late_clue 追加在末尾
        assert [r["id"] for r in rules] == [
            "sanderson_1", "fair_play", "case_aging", "no_late_clue"]
        # 同 id 的 fair_play 取 pack 版（desc/expr 为 pack 值）
        assert by_id["fair_play"]["desc"] == \
            "叙述者不可为凶手（读者与侦探信息同步）"
        assert by_id["no_late_clue"]["expr"] == \
            "not(is_resolution and introduces_new_key_clue)"
        # bundle.genre_params 与 validator 消费同一份合并结果
        assert eng.bundle.genre_params["world_rules"] == rules
        # 插件 params 本体不被污染（合并在副本上进行）
        assert [r["id"] for r in eng.genre.params["world_rules"]] == [
            "sanderson_1", "fair_play", "case_aging"]
        # 合并后的规则集可过 Z3 管线：空 payload 事件不崩且无违规
        #（no_late_clue 引用的 introduces_new_key_clue 已入事实词汇表）
        event = WorldEvent(event_id="e1", event_type="test", timestamp="",
                           world_tick=0, branch_id="main", payload={})
        check = eng.validator._check_world_rules_smt(event, WorldState())
        assert check.passed is True
    finally:
        eng.kernel.close()


# ---------- 用例2：非法 expr / 坏结构规则拒载 + warning ----------

def test_invalid_expr_rules_rejected(tmp_path, monkeypatch, caplog):
    pack_dir = tmp_path / "packs" / "story.world.rule"
    pack_dir.mkdir(parents=True)
    (pack_dir / "broken-rules.yaml").write_text(
        "manifest_version: 1\n"
        "name: broken-rules\n"
        "extension_point: world.rule\n"
        "params:\n"
        "  rules:\n"
        "    - id: good_extra\n"
        "      kind: bool\n"
        "      desc: 合法规则\n"
        "      expr: \"not(is_resolution and has_supernatural)\"\n"
        "    - id: bad_syntax\n"
        "      kind: bool\n"
        "      desc: 括号不闭合\n"
        "      expr: \"not((is_resolution\"\n"
        "    - id: unknown_fact\n"
        "      kind: bool\n"
        "      desc: 引用未声明事实\n"
        "      expr: \"not(alien_fact)\"\n"
        "    - kind: bool\n"
        "      desc: 缺 id 的规则\n"
        "      expr: \"not(is_resolution)\"\n",
        encoding="utf-8")
    monkeypatch.setenv("STORY_ENGINE_GENRE", "mystery")
    eng = StoryEngine(str(tmp_path / "proj"))
    try:
        eng.registry.load_packs(tmp_path / "packs")
        params = {
            "rule_packs": ["broken-rules", "missing-pack"],
            "world_rules": [{"id": "base", "kind": "bool", "desc": "内嵌",
                             "expr": "not(narrator_is_killer)"}],
        }
        with caplog.at_level(logging.WARNING):
            merged = eng._merge_world_rule_packs(params)["world_rules"]
        # 好规则合并进来；坏 expr / 未知事实 / 缺 id / 未注册包全部跳过
        assert {r["id"] for r in merged} == {"base", "good_extra"}
        msgs = [r.getMessage() for r in caplog.records]
        assert any("bad_syntax" in m and "非法" in m for m in msgs)
        assert any("unknown_fact" in m and "非法" in m for m in msgs)
        assert any("缺 id/expr" in m for m in msgs)
        assert any("未注册" in m for m in msgs)
    finally:
        eng.kernel.close()


# ---------- 用例3：未配置 rule_packs 的 genre 与基线逐字一致 ----------

def test_genre_without_rule_packs_baseline(tmp_path, monkeypatch):
    monkeypatch.setenv("STORY_ENGINE_GENRE", "romance")
    eng = StoryEngine(str(tmp_path))
    try:
        expected = yaml.safe_load(
            (GENRES_DIR / "romance.yaml").read_text(encoding="utf-8")
        )["params"]["world_rules"]
        assert eng.validator.world_rules == expected
        # 未走合并路径：bundle.genre_params 即插件 params 本体（零拷贝）
        assert eng.bundle.genre_params is eng.genre.params
    finally:
        eng.kernel.close()
