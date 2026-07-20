"""P7.3 测试：L4 story.evaluator pack 扩充 critic 维度库 + Leader 优先级插入

核心用例（用户指令：只保留核心）：
1. 覆盖语义：真实 emotion-arc pack（与硬编码 emotion_arc 重名）的
   guide/examples 覆盖硬编码三元组，模块级 DIMENSION_GUIDE 不被污染；
   pack 同位 priority 声明对 Leader 幂等（仲裁序与基线一致）
2. 新维度 + Leader 插入：tmp pack（test_dimension, after:plot_coherence,
   blocking: true）→ critic 识别新维度 + Leader 仲裁序位置正确（must_fix
   顺序行为断言）+ blocking 一票否决生效 + 全局常量不被污染
3. 容错：缺 dimension 的 pack 跳过+warning；priority 锚点不存在 →
   warning + 追加末尾不崩；无 registry 时 dimension_guide 即模块常量
   （identity，与基线逐字一致）
"""
from __future__ import annotations

import logging
from pathlib import Path

from story_engine.evaluator.critic_parliament import (
    CriticParliament, DIMENSION_GUIDE,
)
from story_engine.evaluator.leader import (
    ARBITRATION_ORDER, BLOCKING_DIMENSIONS, LeaderArbiter,
)
from story_engine.kernel.registry import ExtensionRegistry
from story_engine.types import GenreBundle
from story_engine.evaluator.types_eval import Critique

PACKS_DIR = (Path(__file__).resolve().parent.parent
             / "story_engine" / "plugins" / "packs")


def _critique(dim: str, fix: str, verdict: str = "FAIL") -> Critique:
    return Critique(dimension=dim, verdict=verdict, evidence=[],
                    fix_directive=fix, executable="yes")


# ---------- 用例1：pack 覆盖硬编码维度（emotion_arc 重名场景） ----------

def test_pack_guide_overrides_hardcoded_dimension():
    reg = ExtensionRegistry()
    reg.load_packs(PACKS_DIR)   # 含 active 的 emotion-arc（dimension: emotion_arc）
    p = CriticParliament(registry=reg)

    # pack 的 guide/examples 覆盖硬编码三元组
    assert p.dimension_guide is not DIMENSION_GUIDE
    desc, good, bad = p.dimension_guide["emotion_arc"]
    assert desc.startswith("评估情感弧是否按决策卡目标弧")
    assert good.startswith("正例：她攥紧那封信")
    assert bad.startswith("反例：上一段还悲痛欲绝")
    # 其余维度原样；模块级硬编码不被污染
    assert p.dimension_guide["plot_coherence"] == DIMENSION_GUIDE["plot_coherence"]
    assert DIMENSION_GUIDE["emotion_arc"][0].startswith("情感弧线：")

    # 样例 pack 声明 after:character_motivation / blocking: false
    assert p.leader_insertions == [("emotion_arc", "after", "character_motivation")]
    assert p.leader_blocking == set()
    # emotion_arc 已在硬编码位（同位声明）→ 幂等：仲裁序行为与基线一致
    leader = LeaderArbiter(insertions=p.leader_insertions,
                           blocking_extra=p.leader_blocking)
    plan = leader.arbitrate([
        _critique("theme_depth", "改主题"),
        _critique("emotion_arc", "改情感弧"),
    ])
    assert plan.must_fix == ["改情感弧", "改主题"]   # emotion_arc 在 theme_depth 前
    assert plan.blocking is False                    # 未进 blocking 集合
    assert list(ARBITRATION_ORDER).count("emotion_arc") == 1


# ---------- 用例2：新维度入库 + Leader 按声明插入 + blocking ----------

def test_new_dimension_and_leader_insertion(tmp_path):
    pack_dir = tmp_path / "packs" / "story.evaluator"
    pack_dir.mkdir(parents=True)
    (pack_dir / "test-dim.yaml").write_text(
        "manifest_version: 1\n"
        "name: test-dim\n"
        "extension_point: story.evaluator\n"
        "params:\n"
        "  dimension: test_dimension\n"
        "  guide: 测试维度说明\n"
        "  examples:\n"
        "    pass: 好的样子\n"
        "    fail: 坏的样子\n"
        "  priority: after:plot_coherence\n"
        "  blocking: true\n",
        encoding="utf-8")
    reg = ExtensionRegistry()
    reg.load_packs(tmp_path / "packs")

    # critic 识别新维度：genre active_critics 引用即启用（不被当未知维度跳过）
    bundle = GenreBundle(genre="mystery", culture="confucian_officialdom",
                         genre_params={"active_critics": ["test_dimension"]})
    p = CriticParliament(registry=reg, genre=bundle)
    assert p.dimensions == ["test_dimension"]
    assert p.dimension_guide["test_dimension"] == (
        "测试维度说明", "正例：好的样子", "反例：坏的样子")

    # Leader：插在 plot_coherence 之后（theme_depth 之前）；blocking 生效
    leader = LeaderArbiter(insertions=p.leader_insertions,
                           blocking_extra=p.leader_blocking)
    plan = leader.arbitrate([
        _critique("theme_depth", "改主题"),
        _critique("test_dimension", "改测试维"),
        _critique("setting_consistency", "", verdict="PASS"),
    ])
    assert plan.must_fix == ["改测试维", "改主题"]
    # blocking 只可能来自 test_dimension（setting_consistency 为 PASS）
    assert plan.blocking is True
    # 实例隔离：全局常量不被污染
    assert "test_dimension" not in ARBITRATION_ORDER
    assert "test_dimension" not in BLOCKING_DIMENSIONS


# ---------- 用例3：容错 + 无 registry 基线一致 ----------

def test_fault_tolerance_and_no_registry_baseline(tmp_path, caplog):
    pack_dir = tmp_path / "packs" / "story.evaluator"
    pack_dir.mkdir(parents=True)
    # 缺 dimension → 跳过 + warning
    (pack_dir / "no-dimension.yaml").write_text(
        "manifest_version: 1\n"
        "name: no-dimension\n"
        "extension_point: story.evaluator\n"
        "params:\n"
        "  guide: 没有维度名\n"
        "  examples:\n"
        "    pass: 甲\n"
        "    fail: 乙\n",
        encoding="utf-8")
    # priority 锚点不存在 → warning + 追加末尾（不崩）
    (pack_dir / "bad-anchor.yaml").write_text(
        "manifest_version: 1\n"
        "name: bad-anchor\n"
        "extension_point: story.evaluator\n"
        "params:\n"
        "  dimension: orphan_dimension\n"
        "  guide: 孤儿维度说明\n"
        "  examples:\n"
        "    pass: 甲\n"
        "    fail: 乙\n"
        "  priority: after:nonexistent_dim\n",
        encoding="utf-8")
    reg = ExtensionRegistry()
    reg.load_packs(tmp_path / "packs")

    with caplog.at_level(logging.WARNING):
        p = CriticParliament(registry=reg)
    # 缺 dimension 的 pack 被跳过（guide 文本未进维度库）+ warning
    assert "orphan_dimension" in p.dimension_guide          # 合法 pack 仍入库
    assert all("没有维度名" not in t for t in p.dimension_guide.values())
    assert any("缺 dimension/guide/examples" in r.getMessage()
               for r in caplog.records)
    assert p.leader_insertions == [("orphan_dimension", "after", "nonexistent_dim")]

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        leader = LeaderArbiter(insertions=p.leader_insertions,
                               blocking_extra=p.leader_blocking)
    assert any("追加到仲裁序末尾" in r.getMessage() for r in caplog.records)
    # 追加末尾不崩：orphan 排在最末（theme_depth 之后）
    plan = leader.arbitrate([
        _critique("orphan_dimension", "改孤儿"),
        _critique("theme_depth", "改主题"),
    ])
    assert plan.must_fix == ["改主题", "改孤儿"]

    # 无 registry：dimension_guide 即模块常量（identity），规则为空——
    # 行为与基线逐字一致
    base = CriticParliament()
    assert base.dimension_guide is DIMENSION_GUIDE
    assert base.leader_insertions == [] and base.leader_blocking == set()
    base_leader = LeaderArbiter()
    assert base_leader._order is ARBITRATION_ORDER
    assert base_leader._blocking is BLOCKING_DIMENSIONS
