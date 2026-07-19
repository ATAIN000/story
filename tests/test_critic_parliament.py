"""P4.2：CriticParliament（赌注5 串联模式）核心测试（用户指令：限 3 用例）

1. judge 无存疑 → 返回 [] 且零 critic 调用（fake LLM 记录调用次数断言）
2. judge 报存疑 → 只精审存疑段；quote 过滤生效（evidence 不在原文中 → 丢弃；
   evidence 在原文中 → 保留）
3. 共振加权：两个 critic 命中同一存疑段 → confidence="high"；单 critic 命中 → "low"
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from story_engine.evaluator.critic_parliament import CriticParliament
from story_engine.types import GenreBundle

CHAPTER = (
    "标题：玉佩案·初审\n\n"
    "包拯升堂，惊堂木一拍，堂下霎时寂静。\n"
    "刘伯跪于堂下，汗出如浆，坚称案发夜未曾离开王府半步。\n"
    "展昭呈上玉佩拓片，公孙策在旁记录口供。\n"
)
# 存疑段：须为章节原文逐字子串（stage 1 quote 过滤要求）
SUSPECT_QUOTE = "刘伯跪于堂下，汗出如浆，坚称案发夜未曾离开王府半步。"

JUDGE_ONE_SUSPECT = (
    f"- quote: {SUSPECT_QUOTE}\n"
    "  reason: 刘伯的否认与前文赌债伏笔可能矛盾\n")


class FakeLLM:
    """按 purpose 分发剧本响应的伪 LLM（签名对齐 LLMPool.call，记录调用）"""

    def __init__(self, scripts: dict[str, str]):
        self.calls: list[tuple[str, str]] = []  # (purpose, prompt)
        self._scripts = scripts

    async def call(self, prompt: str, *, purpose: str = "generate", **kwargs):
        self.calls.append((purpose, prompt))
        return SimpleNamespace(text=self._scripts.get(purpose, ""))


def run(coro):
    return asyncio.run(coro)


def make_parliament(dimensions: list[str], llm: FakeLLM) -> CriticParliament:
    bundle = GenreBundle(genre="mystery", culture="confucian_officialdom",
                         genre_params={"active_critics": list(dimensions)})
    return CriticParliament(genre=bundle, llm_call=llm.call)


def test_judge_no_suspect_zero_critic_calls():
    """judge 返回空存疑列表 → assess 返回 []，只有 1 次 judge 调用、零 critic 调用"""
    llm = FakeLLM({"critic_judge": "[]"})
    parliament = make_parliament(["plot_coherence", "cliche_detection"], llm)
    result = run(parliament.assess(CHAPTER))
    assert result == []
    assert [p for p, _ in llm.calls] == ["critic_judge"]


def test_quote_filter_drops_hallucinated_evidence():
    """judge 报存疑 → 每维 1 次 critic 且 prompt 只含存疑段；
    evidence 不在章节原文中的 critique 被丢弃，在原文中的保留"""
    llm = FakeLLM({
        "critic_judge": JUDGE_ONE_SUSPECT,
        # evidence 不在章节原文中（幻觉 quote）→ 该 critique 丢弃
        "critic_plot_coherence": (
            "verdict: FAIL\n"
            "evidence:\n  - 展昭拔剑指向刘伯，大喝一声。\n"
            "fix_directive: 补一段展昭赶回的过渡\n"
            "executable: yes\n"),
        # evidence 为章节原文子串 → 保留
        "critic_character_motivation": (
            "verdict: FAIL\n"
            "evidence:\n  - 坚称案发夜未曾离开王府半步\n"
            "fix_directive: 补充刘伯坚持否认的动机铺垫（赌债压力）\n"
            "executable: yes\n"),
    })
    dims = ["plot_coherence", "character_motivation"]
    parliament = make_parliament(dims, llm)
    result = run(parliament.assess(CHAPTER))
    # 1 次 judge + 2 次 critic（每维 1 次）
    assert [p for p, _ in llm.calls] == ["critic_judge"] + [f"critic_{d}" for d in dims]
    # 只精审存疑段：critic prompt 含存疑段引文，不含非存疑句
    for purpose, prompt in llm.calls[1:]:
        assert SUSPECT_QUOTE in prompt
        assert "展昭呈上玉佩拓片" not in prompt
    # quote 过滤：幻觉 critique 丢弃，原文 quote 的保留
    assert len(result) == 1
    assert result[0].dimension == "character_motivation"
    assert result[0].verdict == "FAIL"
    assert result[0].evidence == ["坚称案发夜未曾离开王府半步"]
    assert result[0].fix_directive == "补充刘伯坚持否认的动机铺垫（赌债压力）"
    assert result[0].executable == "yes"


def test_resonance_weighting_multi_vs_single_critic():
    """两 critic 命中同一存疑段 → confidence="high"；单 critic 命中 → "low" """
    scripts = {
        "critic_judge": JUDGE_ONE_SUSPECT,
        "critic_plot_coherence": (
            "verdict: FAIL\n"
            "evidence:\n  - 坚称案发夜未曾离开王府半步\n"
            "fix_directive: 让否认与伏笔对齐\n"
            "executable: yes\n"),
        "critic_setting_consistency": (
            "verdict: FAIL\n"
            "evidence:\n  - 刘伯跪于堂下，汗出如浆\n"
            "fix_directive: 管家跪礼用词核对\n"
            "executable: partial\n"),
    }
    # 两个 critic 命中同一存疑段 → 都 high
    llm = FakeLLM(dict(scripts))
    parliament = make_parliament(["plot_coherence", "setting_consistency"], llm)
    result = run(parliament.assess(CHAPTER))
    assert len(result) == 2
    assert {c.dimension for c in result} == {"plot_coherence", "setting_consistency"}
    assert all(c.confidence == "high" for c in result)
    # 单 critic 命中 → low
    llm1 = FakeLLM(dict(scripts))
    parliament1 = make_parliament(["plot_coherence"], llm1)
    result1 = run(parliament1.assess(CHAPTER))
    assert len(result1) == 1
    assert result1[0].confidence == "low"
