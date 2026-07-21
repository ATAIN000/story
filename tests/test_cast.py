"""P11.1 测试：Cast 解析层 + genesis/spawn 插件化 + mystery cast 段

核心用例（任务卡口径，≤3）：
1. mystery：新 genesis 工厂产出阵容 == 包拯五虎（id 集）+ goals/关系与
   mock_script SEED_* 现状一致（走 L1 cast 段，无回退 warning）；
   spawn 改走 state.characters/minds 且幂等
2. romance（无 cast: 走 L2 prompt.characters 解析）：state.characters 含
   沈砚清/顾明璋/柳含烟、不含包拯；goals 默认映射到轨道名
3. 坏格式 characters 字符串（无 cast 段且 prompt.characters 不可解析）
   → 回退 mock 种子阵容 + warning，不崩
"""
import asyncio
import os
import warnings
from unittest import mock

import pytest

from story_engine import mock_script
from story_engine.engine import StoryEngine, _make_genesis_factory
from story_engine.meta.cast import parse_cast


def test_mystery_factory_matches_mock_seeds_and_spawn_idempotent(tmp_path):
    eng = StoryEngine(str(tmp_path))  # 默认题材 mystery
    try:
        # 新 genesis 工厂（bundle 感知）：mystery.yaml cast: 段为 L1 来源。
        # 录制 warning：命中 L1 时不应出现「回退 mock」warning（证明没走 fallback）
        with warnings.catch_warnings(record=True) as rec:
            warnings.simplefilter("always")
            state = _make_genesis_factory(eng.bundle)()
        assert not any("回退" in str(w.message) for w in rec)

        # 阵容 id 集 == 包拯五虎
        assert set(state.characters) == set(mock_script.SEED_CHARACTERS)
        # goals 与 SEED_MINDS 现状逐字一致
        for cid, m in mock_script.SEED_MINDS.items():
            assert state.minds[cid].goals == m["goals"]
        # 关系（type/intensity）与 SEED_RELATIONS 现状一致
        rels = {k: (r.type, r.intensity) for k, r in state.relationships.items()}
        assert rels == {k: (r["type"], r["intensity"])
                        for k, r in mock_script.SEED_RELATIONS.items()}

        # spawn：读 state.characters/minds（mystery 活体 genesis 仍是全量 SEED），
        # 阵容与旧行为一致；两次调用幂等（不重复 spawn）
        asyncio.run(eng._ensure_character_actors())
        actors = eng.kernel.scheduler._character_actors
        assert set(actors) == set(mock_script.SEED_CHARACTERS)
        assert actors["包拯"].config.initial_goals == \
            mock_script.SEED_MINDS["包拯"]["goals"]
        count = len(actors)
        asyncio.run(eng._ensure_character_actors())
        assert len(eng.kernel.scheduler._character_actors) == count
    finally:
        eng.kernel.close()


def test_romance_genesis_cast_from_prompt_characters(tmp_path):
    # romance.yaml 无 cast: 段 → L2 解析 prompt.characters（实读题材插件）
    with mock.patch.dict(os.environ, {"STORY_ENGINE_GENRE": "romance"}):
        eng = StoryEngine(str(tmp_path))
    try:
        state = eng.kernel.query_world("current_state")
        assert {"沈砚清", "顾明璋", "柳含烟"} <= set(state.characters)
        assert "包拯" not in state.characters
        # goals 默认映射：第 1 人 → main_track 轨道名，第 2/3 人 → tracks 按序
        assert state.minds["沈砚清"].goals == ["主线·追求"]
        assert state.minds["顾明璋"].goals == ["副线·障碍"]
        assert state.minds["柳含烟"].goals == ["副线·情敌"]
    finally:
        eng.kernel.close()


def test_bad_characters_string_falls_back_to_mock_seeds():
    # 无 cast 段 + characters 串无有效名字（纯括号/分隔符）→ 回退 + warning 不崩
    params = {"prompt": {"characters": "  （）、，；,, "}}
    with pytest.warns(UserWarning, match="回退"):
        members = parse_cast(params)
    assert [m.id for m in members] == list(mock_script.SEED_CHARACTERS)
    assert members[0].goals == mock_script.SEED_MINDS["包拯"]["goals"]
    assert {r["target"] for r in members[0].relations} == {"展昭", "公孙策"}
