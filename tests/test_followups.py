"""P5.12 follow-up 批次核心测试（用户指令：只保留 3 个核心用例，不穷举边界）

1. intent 消费接线（①）：route(intent) 后 generate_decision_card 产出携带
   作者意图（DecisionCard.author_intent，最新一条生效）；无 intent 时与现状
   一致（author_intent 为 None）
2. Realizer recap（②）：narrate(recap=...) 时 prompt 含 recap 文本；
   recap=None 时与现状逐字一致
3. reactions accessor（⑤）：公开 property 与内部平行表内容一致且为副本；
   engine 不再访问 `_reactions`（源码断言）

全部离线：tmp kernel + fake LLM + stub reader，不触网。
"""
from __future__ import annotations

import asyncio
import inspect
import tempfile
from types import SimpleNamespace

from story_engine import engine as engine_module
from story_engine.evaluator import (
    ChapterSpec, Gate, IterationController, LeaderArbiter,
)
from story_engine.evaluator.types_eval import ReaderReaction
from story_engine.hitl import HumanInput, InterventionRouter
from story_engine.kernel import Kernel
from story_engine.kernel.embedding import Embedder
from story_engine.narrative import NarrativeIR, Narrativizer, TextureParams
from story_engine.narrative.ir_builder import TEXTURE_DEFAULTS
from story_engine.showrunner import Showrunner
from story_engine.types import GenreBundle


def run(coro):
    return asyncio.run(coro)


def _bundle() -> GenreBundle:
    return GenreBundle(
        genre="mystery", culture="confucian_officialdom", target_length=12,
        genre_params={
            "main_track": "A", "theme_track": "E",
            "payoff_window": 2, "beats_per_chapter": 4,
            "emotion_arcs": ["man_in_hole"],
            "tracks": [
                {"id": "A", "name": "主线", "arc_type": "Serialized",
                 "archetype": "Quest"},
                {"id": "E", "name": "主题", "arc_type": "Serialized",
                 "archetype": "Quest"},
            ],
            "foreshadow_templates": [],
        },
        culture_params={"cliffhanger_cycle": ["明扣", "暗扣"]},
    )


# ---------- 用例1：intent 介入 → 决策卡 author_intent（①） ----------

def test_intent_flows_into_decision_card():
    tmp = tempfile.mkdtemp()
    kernel = Kernel(tmp, plugin_dir=None, embedder=Embedder(mode="dummy"))
    try:
        router = InterventionRouter(kernel)
        sr = Showrunner(
            _bundle(), event_source=lambda: kernel.query_world("all_events"))
        state = kernel.query_world("current_state")

        # 无 intent 事件：与现状一致（author_intent 为 None）
        assert sr.generate_decision_card(1, state).author_intent is None

        r = router.route(HumanInput(
            type="intent", reason="改方向",
            payload={"goal_update": "主线转向复仇", "constraint": "不可写死主角"}))
        assert r.ok
        card = sr.generate_decision_card(1, state)
        assert card.author_intent is not None
        assert "主线转向复仇" in card.author_intent
        assert "不可写死主角" in card.author_intent

        # 最新一条 intent 覆盖旧意图（介入即事件的「新意图取代旧意图」语义）
        router.route(HumanInput(
            type="intent", payload={"constraint": "本章必须回收证词伏笔"}))
        card2 = sr.generate_decision_card(1, state)
        assert "本章必须回收证词伏笔" in card2.author_intent
        assert "主线转向复仇" not in card2.author_intent
    finally:
        kernel.close()


# ---------- 用例2：Narrativizer.narrate 可选 recap（②） ----------

class _FakeLLM:
    def __init__(self):
        self.prompts: list[str] = []

    async def call(self, prompt: str, *, purpose: str = "generate", **kwargs):
        self.prompts.append(prompt)
        return SimpleNamespace(text="正文。")


def _ir() -> NarrativeIR:
    return NarrativeIR(
        beats=[], events=[], dialogue_lines=[], scene_breakdown=[],
        texture=TextureParams(**TEXTURE_DEFAULTS["zh"]),
    )


def test_narrate_recap_optional():
    llm = _FakeLLM()
    nav = Narrativizer(bundle=_bundle(), llm_call=llm.call)

    run(nav.narrate(_ir(), recap="第1章《雨夜》结尾：包拯闭门沉思。"))
    assert "第1章《雨夜》结尾：包拯闭门沉思。" in llm.prompts[0]
    assert "前情提要" in llm.prompts[0]

    # recap=None / 缺省：prompt 与现状逐字一致（整段缺席，两种调用等价）
    run(nav.narrate(_ir()))
    run(nav.narrate(_ir(), recap=None))
    assert "前情提要" not in llm.prompts[1]
    assert llm.prompts[1] == llm.prompts[2]


# ---------- 用例3：IterationController.reactions 公开 accessor（⑤） ----------

class _StubParliament:
    async def assess(self, chapter, state=None):
        return []  # 全 PASS → 第 1 轮即收敛


class _StubGates:
    async def check_l5(self, text):
        return Gate(layer="L5", passed=True, failures={})


class _StubReader:
    async def react(self, chapter):
        return ReaderReaction(engagement=4)


def test_reactions_accessor_and_engine_uses_public():
    ctrl = IterationController(
        _StubParliament(), LeaderArbiter(), _StubGates(), reader=_StubReader())
    result = run(ctrl.run(lambda spec, feedback=None: "标题：章\n\n正文。",
                          ChapterSpec()))

    # 公开 property 与内部平行表内容一致（与 versions 同序对齐）
    assert ctrl.reactions == ctrl._reactions
    assert len(ctrl.reactions) == len(result.all_versions) == 1
    assert ctrl.reactions[0].engagement == 4
    # 返回副本：外部改动不影响内部表
    ctrl.reactions.append(ReaderReaction())
    assert len(ctrl._reactions) == 1

    # engine 不再访问 controller._reactions（源码断言，brief 允许的 grep 口径）
    src = inspect.getsource(engine_module)
    assert "._reactions" not in src
