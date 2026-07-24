"""P23.1 测试：人物条目灌水修复（展示过滤 + 阵容质量）

核心用例（用户指令：只保留核心）：
1. cast.json 覆盖 prompt.characters：项目阵容进生成 prompt（祁望/死者式名单），
   无 cast.json 时保持题材默认文案
2. characters_view 白名单过滤：事件流噪音 mind（不在阵容册且无目标/秘密）
   不展示；阵容 mind 与有实质内容 mind 保留
3. derive_cast 占位名标记：无题材人名时泛称带 placeholder=True，
   题材有真实人名时 False
"""
from __future__ import annotations

import json

from story_engine.engine import StoryEngine
from story_engine.types import CharacterMind, WorldState
from story_engine.worldview.derive_cast import derive_cast


# ---------- 用例1：cast.json 覆盖 prompt.characters ----------

def test_cast_json_overrides_prompt_characters(tmp_path, monkeypatch):
    monkeypatch.setenv("STORY_ENGINE_GENRE", "romance")
    (tmp_path / "cast.json").write_text(json.dumps([
        {"id": "祁望", "role": "主角"},
        {"id": "死者", "role": "配角"},
    ], ensure_ascii=False), encoding="utf-8")
    eng = StoryEngine(str(tmp_path))
    try:
        chars = eng.bundle.genre_params["prompt"]["characters"]
        assert chars == "祁望（主角）、死者（配角）"
        # registry 缓存不被污染（romance 原始 characters 文案还在）
        assert "沈砚清" in eng.genre.params["prompt"]["characters"]
    finally:
        eng.kernel.close()


def test_no_cast_json_keeps_genre_characters(tmp_path, monkeypatch):
    monkeypatch.setenv("STORY_ENGINE_GENRE", "romance")
    eng = StoryEngine(str(tmp_path))
    try:
        chars = eng.bundle.genre_params["prompt"]["characters"]
        assert "沈砚清" in chars  # 题材默认文案原样
    finally:
        eng.kernel.close()


# ---------- 用例2：characters_view 白名单过滤 ----------

def test_characters_view_filters_noise_minds():
    state = WorldState(tick=0)
    # 阵容册：祁望（主角）
    state.characters["祁望"] = {"role": "主角"}
    state.minds["祁望"] = CharacterMind("祁望", goals=["查明真相"])
    # 噪音 mind：事件流带入的占位/群体名（仅零散信念，无目标/秘密）
    for junk in ("嫌疑人甲", "评议会", "三名登记在册的嫌疑人", "角色"):
        m = CharacterMind(junk)
        m.beliefs["案发现场在城东"] = True
        state.minds[junk] = m
    # 有实质内容的非阵容 mind（后期登场的真嫌疑人，有秘密）→ 保留
    real = CharacterMind("真凶李四")
    real.secrets.append("其实他在场")
    state.minds["真凶李四"] = real

    cards = StoryEngine._characters_view(state)
    ids = [c["id"] for c in cards]
    assert "祁望" in ids
    assert "真凶李四" in ids
    for junk in ("嫌疑人甲", "评议会", "三名登记在册的嫌疑人", "角色"):
        assert junk not in ids


# ---------- 用例3：derive_cast 占位名标记 ----------

def test_derive_cast_placeholder_flags():
    # 无 genre_params → 泛称名 + placeholder=True
    cast = derive_cast(None, None, None)
    assert cast[0]["name"] == "主角" and cast[0]["placeholder"] is True
    assert cast[1]["name"] == "重要配角" and cast[1]["placeholder"] is True
    # 题材有真实人名（prompt.characters 可解析）→ placeholder=False
    genre_params = {"prompt": {
        "characters": "沈砚清（医药世家独女）、顾明璋（书香门第公子）、柳含烟（名伶）"}}
    cast = derive_cast(None, None, genre_params)
    assert cast[0]["name"] == "沈砚清" and cast[0]["placeholder"] is False
    assert cast[1]["name"] == "顾明璋" and cast[1]["placeholder"] is False
