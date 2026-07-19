"""P5.3 核心测试：Fabula/Sjuzhet 分离（蓝图 5.2 决策3，规则化零 LLM）

用户指令：只保留 3 个核心用例，不穷举边界：
  1. fabula 真值层：乱序事件输入 → 按 world_tick 排序 + characters 集合正确
  2. sjuzhet 缺省：omniscient + linear → 全事件原序、pov/order 字段正确
  3. fair_play：真凶关键词事件被延后到末尾，其余原序；未知 order/pov 回退 warning 不崩
"""
from __future__ import annotations

import pytest

from story_engine.narrative import FabulaBuilder, SjuzhetSelector
from story_engine.types import GenreBundle


def _event(tick: int, agent: str, **payload) -> dict:
    """与 kernel.query_world("all_events") 返回形态对齐：to_dict()+active"""
    return {"event_id": f"e{tick}", "event_type": "character_action",
            "timestamp": "2026-07-19T00:00:00", "world_tick": tick,
            "branch_id": "main", "payload": {"agent": agent, **payload},
            "schema_version": 1, "timeline": 0, "active": True}


def _bundle(**params) -> GenreBundle:
    return GenreBundle(genre="mystery", culture="confucian_officialdom",
                       genre_params=params)


# ---------- 用例1：fabula 真值层 ----------

def test_fabula_sorts_by_world_tick_and_collects_characters():
    events = [_event(3, "展昭", action="呈上账册"),
              _event(1, "包拯", action="accuse"),
              _event(2, "展昭", action="investigate")]
    fabula = FabulaBuilder().build(events)
    assert [e["world_tick"] for e in fabula.all_events] == [1, 2, 3]
    assert fabula.characters == {"包拯", "展昭"}


# ---------- 用例2：sjuzhet 缺省 omniscient + linear ----------

def test_sjuzhet_default_omniscient_linear():
    events = [_event(1, "包拯"), _event(2, "展昭"), _event(3, "包拯")]
    fabula = FabulaBuilder().build(events)
    sjuzhet = SjuzhetSelector().select(fabula, _bundle())
    assert sjuzhet.events == fabula.all_events   # 全事件原序
    assert sjuzhet.pov == "omniscient"
    assert sjuzhet.order == "linear"


# ---------- 用例3：fair_play 延后真凶事件 + 未知键回退 warning ----------

def test_sjuzhet_fair_play_delays_culprit_events_and_fallbacks():
    events = [_event(1, "包拯", action="accuse"),
              _event(2, "展昭", action="查访", clue="账册指向真凶"),   # 含真凶关键词
              _event(3, "包拯", action="升堂")]
    fabula = FabulaBuilder().build(events)

    # fair_play：真凶身份相关事件移到末尾（recognition 相位），其余保持原序
    sjuzhet = SjuzhetSelector().select(
        fabula, _bundle(pov_strategy="fair_play"))
    assert [e["world_tick"] for e in sjuzhet.events] == [1, 3, 2]
    assert sjuzhet.pov == "fair_play"
    assert sjuzhet.order == "linear"

    # 未知 narrative_order / pov_strategy：回退 linear/omniscient + warning，不崩
    with pytest.warns(UserWarning, match="narrative_order"):
        sj = SjuzhetSelector().select(
            fabula, _bundle(narrative_order="interleaved"))
    assert sj.order == "linear"
    assert sj.events == fabula.all_events
    with pytest.warns(UserWarning, match="pov_strategy"):
        sj = SjuzhetSelector().select(fabula, _bundle(pov_strategy="limited"))
    assert sj.pov == "omniscient"
    assert sj.events == fabula.all_events
