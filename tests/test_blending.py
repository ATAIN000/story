"""P3.7：ConceptualBlending 简化版（决策7）核心测试（用户指令：限 3 用例）

1. mock LLM + dummy embed 下 generate_creative_seed 返回 seed，novelty/surprise ∈ [0,1]
2. 门控默认关闭（BLEND_EVERY=0）：决策卡 creative_seeds 为空且零 LLM 调用
3. 门控开启（BLEND_EVERY=1）：决策卡带 1 个 seed（mock LLM）
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from story_engine.creativity import ConceptualBlending, CreativeSeed
from story_engine.kernel.embedding import Embedder
from story_engine.showrunner import Showrunner
from story_engine.types import GenreBundle, WorldState

DOMAINS = ["科举", "玉器行当", "漕运"]

TRACKS = [
    {"id": "A", "name": "主线", "arc_type": "Serialized", "archetype": "Quest"},
    {"id": "E", "name": "主题", "arc_type": "Serialized", "archetype": "Quest"},
]


class MockLLM:
    """记录调用次数的伪 LLM（签名对齐 LLMPool.call）"""

    def __init__(self, text: str = ""):
        self.calls: list[str] = []
        self._text = text

    async def call(self, prompt: str, **kwargs):
        self.calls.append(prompt)
        return SimpleNamespace(text=self._text)


def run(coro):
    return asyncio.run(coro)


def make_showrunner(llm: MockLLM) -> Showrunner:
    bundle = GenreBundle(
        genre="romance", culture="confucian_officialdom", target_length=12,
        genre_params={
            "main_track": "A", "theme_track": "E",
            "tracks": [dict(t) for t in TRACKS],
            "foreshadow_templates": [
                {"content": "证词矛盾", "trigger": "质询", "payoff": "破绽"},
            ],
            "blend_domains": list(DOMAINS),
        },
        culture_params={},
    )
    blender = ConceptualBlending(
        llm.call, embedder=Embedder(mode="dummy"), blend_domains=list(DOMAINS))
    return Showrunner(bundle, blender=blender,
                      recent_texts_source=lambda: ["包拯升堂问案，展昭呈上玉佩。"])


def test_generate_creative_seed_scores_in_range():
    """mock LLM + dummy embed：返回 seed，恰好 1 次 LLM 调用，novelty/surprise ∈ [0,1]"""
    llm = MockLLM("科举考场化作玉器行：考生入场先验「玉牌」身家，考官按行规断卷。")
    blender = ConceptualBlending(
        llm.call, embedder=Embedder(mode="dummy"), blend_domains=list(DOMAINS))
    seed = run(blender.generate_creative_seed(
        recent_texts=["包拯升堂，公孙策呈上玉佩拓片，刘伯跪堂下称冤。"],
        reference_texts=["证词矛盾", "异常物件"]))
    assert isinstance(seed, CreativeSeed)
    assert len(llm.calls) == 1
    assert len(seed.domains) == 2 and seed.domains[0] != seed.domains[1]
    assert seed.domains[0] in DOMAINS and seed.domains[1] in DOMAINS
    assert seed.emergent
    assert 0.0 <= seed.novelty <= 1.0
    assert 0.0 <= seed.surprise <= 1.0


def test_gate_off_by_default_no_llm_call(monkeypatch):
    """BLEND_EVERY=0（默认关闭）：creative_seeds 为空且零 LLM 调用"""
    monkeypatch.setenv("STORY_ENGINE_BLEND_EVERY", "0")
    llm = MockLLM("融合创意")
    sr = make_showrunner(llm)
    card = sr.generate_decision_card(1, WorldState())
    card = run(sr.attach_creative_seed(card, 1))
    assert card.creative_seeds == []
    assert llm.calls == []


def test_gate_on_attaches_one_seed(monkeypatch):
    """BLEND_EVERY=1：决策卡带 1 个 seed（mock LLM，恰好 1 次调用）"""
    monkeypatch.setenv("STORY_ENGINE_BLEND_EVERY", "1")
    llm = MockLLM("漕运船帮的「水牌」化作梨园点戏簿，名角登台须对牌应卯。")
    sr = make_showrunner(llm)
    card = sr.generate_decision_card(1, WorldState())
    card = run(sr.attach_creative_seed(card, 1))
    assert len(llm.calls) == 1
    assert len(card.creative_seeds) == 1
    seed = card.creative_seeds[0]
    assert set(seed) == {"domains", "emergent", "novelty", "surprise"}
    assert len(seed["domains"]) == 2
    assert 0.0 <= seed["novelty"] <= 1.0
    assert 0.0 <= seed["surprise"] <= 1.0
