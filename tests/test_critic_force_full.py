"""第一波② critic 议会兜底精审测试 — assess_full + IterationController.force_full_on_empty

覆盖：
1. assess_full 跳过 judge，直接全维度精审（FAIL/PASS 解析）
2. assess_full 兜底条件（空章节 / 无 LLM / evidence 防幻觉过滤）
3. IterationController force_full_on_empty：judge 放过 → 兜底精审 → 驱动迭代
4. force_full_on_empty=False（默认）→ 不兜底，行为与基线一致
"""
from __future__ import annotations

import pytest

from story_engine.evaluator.critic_parliament import CriticParliament
from story_engine.evaluator.iteration import IterationController, ChapterSpec
from story_engine.evaluator.leader import LeaderArbiter
from story_engine.evaluator.types_eval import Critique


class _Resp:
    def __init__(self, text):
        self.text = text


class FakeLLM:
    """按 purpose 分发响应的 fake LLM。responses: {purpose: text}；未命中 → ''"""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls: list[str] = []

    async def __call__(self, prompt, *, purpose, temperature, max_tokens):
        self.calls.append(purpose)
        return _Resp(self.responses.get(purpose, ""))


def _critic_yaml(verdict, evidence_quote, fix="具体修改指令"):
    return (f"```yaml\nverdict: {verdict}\n"
            f"evidence:\n- \"{evidence_quote}\"\n"
            f"fix_directive: {fix}\nexecutable: yes\n```")


CHAPTER = (
    "他拔出长刀，刀光一闪。对手尚未反应，刃已抵喉。"
    "「你输了。」他淡淡说。鲜血顺着刀槽滴落。"
)


# ---------- assess_full 精审 ----------

@pytest.mark.asyncio
async def test_assess_full_runs_all_dimensions_skipping_judge():
    """assess_full 不调 judge（无 critic_judge purpose），直接跑各维 critic_full_*"""
    llm = FakeLLM({
        # 故意不设 critic_judge，验证 assess_full 不依赖它
        "critic_full_plot_coherence": _critic_yaml("FAIL",
            "他拔出长刀，刀光一闪。", "冲突转折太突兀"),
        "critic_full_setting_consistency": _critic_yaml("PASS", "鲜血顺着刀槽滴落。"),
        "critic_full_character_motivation": _critic_yaml("PASS", "鲜血顺着刀槽滴落。"),
        "critic_full_dialogue_authenticity": _critic_yaml("PASS", "鲜血顺着刀槽滴落。"),
        "critic_full_sensory_detail": _critic_yaml("PASS", "鲜血顺着刀槽滴落。"),
        "critic_full_cliche_detection": _critic_yaml("PASS", "鲜血顺着刀槽滴落。"),
        "critic_full_theme_depth": _critic_yaml("PASS", "鲜血顺着刀槽滴落。"),
    })
    cp = CriticParliament(llm_call=llm)
    critiques = await cp.assess_full(CHAPTER)
    assert "critic_judge" not in llm.calls
    dims = {c.dimension for c in critiques}
    assert "plot_coherence" in dims
    fail = next(c for c in critiques if c.dimension == "plot_coherence")
    assert fail.verdict == "FAIL"


@pytest.mark.asyncio
async def test_assess_full_empty_chapter_returns_empty():
    cp = CriticParliament(llm_call=FakeLLM())
    assert await cp.assess_full("") == []
    assert await cp.assess_full("   ") == []


@pytest.mark.asyncio
async def test_assess_full_no_llm_returns_empty():
    cp = CriticParliament(llm_call=None)
    assert await cp.assess_full(CHAPTER) == []


@pytest.mark.asyncio
async def test_assess_full_filters_hallucinated_evidence():
    """evidence 不能逐字命中章节原文 → 该 critique 丢弃（防幻觉）"""
    llm = FakeLLM({
        "critic_full_plot_coherence": _critic_yaml("FAIL",
            "这段原文里根本不存在的句子", "幻觉修改"),
        "critic_full_setting_consistency": _critic_yaml("PASS",
            "鲜血顺着刀槽滴落。"),
        "critic_full_character_motivation": _critic_yaml("PASS",
            "鲜血顺着刀槽滴落。"),
        "critic_full_dialogue_authenticity": _critic_yaml("PASS",
            "鲜血顺着刀槽滴落。"),
        "critic_full_sensory_detail": _critic_yaml("PASS",
            "鲜血顺着刀槽滴落。"),
        "critic_full_cliche_detection": _critic_yaml("PASS",
            "鲜血顺着刀槽滴落。"),
        "critic_full_theme_depth": _critic_yaml("PASS",
            "鲜血顺着刀槽滴落。"),
    })
    cp = CriticParliament(llm_call=llm)
    critiques = await cp.assess_full(CHAPTER)
    # plot_coherence 的 evidence 是幻觉 → 过滤掉
    dims = {c.dimension for c in critiques}
    assert "plot_coherence" not in dims


# ---------- IterationController force_full_on_empty ----------

@pytest.mark.asyncio
async def test_controller_force_full_rescues_empty_judge(monkeypatch):
    """judge 放过（assess 空）+ force_full → assess_full 兜底发现 FAIL → 迭代"""
    # judge 返回空 → assess 空；assess_full 的 plot_coherence 返回 FAIL
    llm = FakeLLM({
        "critic_judge": "[]",   # judge 放过
        "critic_full_plot_coherence": _critic_yaml("FAIL",
            "他拔出长刀，刀光一闪。", "转折需铺垫"),
        "critic_full_setting_consistency": _critic_yaml("PASS",
            "鲜血顺着刀槽滴落。"),
        "critic_full_character_motivation": _critic_yaml("PASS",
            "鲜血顺着刀槽滴落。"),
        "critic_full_dialogue_authenticity": _critic_yaml("PASS",
            "鲜血顺着刀槽滴落。"),
        "critic_full_sensory_detail": _critic_yaml("PASS",
            "鲜血顺着刀槽滴落。"),
        "critic_full_cliche_detection": _critic_yaml("PASS",
            "鲜血顺着刀槽滴落。"),
        "critic_full_theme_depth": _critic_yaml("PASS",
            "鲜血顺着刀槽滴落。"),
    })
    cp = CriticParliament(llm_call=llm)
    leader = LeaderArbiter()
    controller = IterationController(
        cp, leader, gates=None, max_rounds=2, force_full_on_empty=True)

    async def gen(spec, feedback=None):
        return CHAPTER

    result = await controller.run(gen, ChapterSpec())
    # best 版本应携带 assess_full 发现的 FAIL critique（plot_coherence blocking）
    assert result.best is not None
    dims = {c.dimension for c in result.best.critiques}
    assert "plot_coherence" in dims
    assert result.best.revision.blocking is True
    # 触发过 assess_full（critic_full_* purpose 被调用）
    assert any(p.startswith("critic_full_") for p in llm.calls)


@pytest.mark.asyncio
async def test_controller_force_full_off_does_not_call_assess_full():
    """force_full_on_empty=False（默认）→ judge 放过也不兜底，行为与基线一致"""
    llm = FakeLLM({"critic_judge": "[]"})   # judge 放过
    cp = CriticParliament(llm_call=llm)
    leader = LeaderArbiter()
    controller = IterationController(
        cp, leader, gates=None, max_rounds=2, force_full_on_empty=False)

    async def gen(spec, feedback=None):
        return CHAPTER

    result = await controller.run(gen, ChapterSpec())
    assert result.best is not None
    # 未兜底：best.critiques 为空（judge 放过 + 无 assess_full）
    assert result.best.critiques == []
    assert result.best.revision.blocking is False
    # 没调过 critic_full_*
    assert not any(p.startswith("critic_full_") for p in llm.calls)


@pytest.mark.asyncio
async def test_controller_force_full_bounded_per_round():
    """每轮 judge 放过都兜底（保证 best 选择基于一致评估），但有上限：
    不超过 max_rounds × 维度数，且 gen 不改进时 _has_improvement 会提前停"""
    call_count = {"full": 0}

    class CountingLLM(FakeLLM):
        async def __call__(self, prompt, *, purpose, temperature, max_tokens):
            if purpose.startswith("critic_full_"):
                call_count["full"] += 1
            return await super().__call__(prompt, purpose=purpose,
                                          temperature=temperature,
                                          max_tokens=max_tokens)

    llm = CountingLLM({
        "critic_judge": "[]",
        # 所有 critic_full：plot_coherence FAIL（blocking → 持续迭代），其余 PASS
        "critic_full_plot_coherence": _critic_yaml("FAIL",
            "他拔出长刀，刀光一闪。", "转折需铺垫"),
        "critic_full_setting_consistency": _critic_yaml("PASS",
            "鲜血顺着刀槽滴落。"),
        "critic_full_character_motivation": _critic_yaml("PASS",
            "鲜血顺着刀槽滴落。"),
        "critic_full_dialogue_authenticity": _critic_yaml("PASS",
            "鲜血顺着刀槽滴落。"),
        "critic_full_sensory_detail": _critic_yaml("PASS",
            "鲜血顺着刀槽滴落。"),
        "critic_full_cliche_detection": _critic_yaml("PASS",
            "鲜血顺着刀槽滴落。"),
        "critic_full_theme_depth": _critic_yaml("PASS",
            "鲜血顺着刀槽滴落。"),
    })
    cp = CriticParliament(llm_call=llm)
    leader = LeaderArbiter()
    controller = IterationController(
        cp, leader, gates=None, max_rounds=3, force_full_on_empty=True)

    async def gen(spec, feedback=None):
        return CHAPTER   # 不改进 → 第2轮 _has_improvement=False 提前停

    await controller.run(gen, ChapterSpec())
    # 兜底确实触发；上限 = max_rounds × 维度数（7 维 × 3 轮 = 21）
    assert call_count["full"] > 0
    assert call_count["full"] <= 3 * 7


# ---------- 第三波⑥：critic 模型覆盖 ----------

@pytest.mark.asyncio
async def test_critic_model_passed_when_env_set(monkeypatch):
    """STORY_ENGINE_CRITIC_MODEL 设定时，_call_llm 带 model 覆盖"""
    monkeypatch.setenv("STORY_ENGINE_CRITIC_MODEL", "stronger-critic-model")
    captured = {}

    async def fake_call(prompt, **kw):
        captured.update(kw)
        return _Resp("```yaml\nverdict: PASS\n```")

    cp = CriticParliament(llm_call=fake_call)
    assert cp._critic_model == "stronger-critic-model"
    await cp._call_llm("prompt", purpose="critic_test", max_tokens=100)
    assert captured.get("model") == "stronger-critic-model"


@pytest.mark.asyncio
async def test_critic_model_not_passed_when_env_unset(monkeypatch):
    """未设 STORY_ENGINE_CRITIC_MODEL → 不传 model（test fake 签名兼容）"""
    monkeypatch.delenv("STORY_ENGINE_CRITIC_MODEL", raising=False)
    captured = {}

    async def fake_call(prompt, **kw):
        captured.update(kw)
        return _Resp("```yaml\nverdict: PASS\n```")

    cp = CriticParliament(llm_call=fake_call)
    assert cp._critic_model is None
    await cp._call_llm("prompt", purpose="critic_test", max_tokens=100)
    assert "model" not in captured


@pytest.mark.asyncio
async def test_assess_uses_critic_model(monkeypatch):
    """端到端：assess 的 judge 调用携带 critic 模型覆盖"""
    monkeypatch.setenv("STORY_ENGINE_CRITIC_MODEL", "gpt-strong")
    seen_models = []

    class _ModelLLM(FakeLLM):
        async def __call__(self, prompt, *, purpose, temperature, max_tokens,
                           **kw):
            seen_models.append(kw.get("model"))
            return _Resp("[]")   # judge 放过 → assess 返回空

    cp = CriticParliament(llm_call=_ModelLLM())
    await cp.assess(CHAPTER)
    assert "gpt-strong" in seen_models
