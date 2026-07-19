"""P4.3：Leader 仲裁 + 读者代理核心测试（用户指令：限 3 用例）

1. 高优先级 FAIL 一票否决：setting_consistency FAIL（executable=yes）
   → blocking=True 且 fix_directive 进 must_fix；同批低优先级 FAIL 正确归位
2. executable=no → 进 noted 不进 must_fix，且不 blocking（即便高优先级）；
   emotion_arc FAIL → 进 must_fix 但不 blocking（验证扩展维位置语义）
3. reader：fake LLM 返回蓝图格式文本 → 字段解析正确（含 1-5 钳制）；
   react 两次 → curve 累积两条
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from story_engine.evaluator import (
    CONSTITUTIONAL_PRIORITY, Critique, LeaderArbiter, ReaderProxy,
)

CHAPTER = (
    "标题：玉佩案·初审\n\n"
    "包拯升堂，惊堂木一拍，堂下霎时寂静。\n"
    "刘伯跪于堂下，汗出如浆，坚称案发夜未曾离开王府半步。\n"
)


def critique(dim: str, verdict: str, fix: str, executable: str) -> Critique:
    return Critique(dimension=dim, verdict=verdict, evidence=["某引文"],
                    fix_directive=fix, executable=executable)


class FakeLLM:
    """按序返回剧本响应的伪 LLM（签名对齐 LLMPool.call，记录调用）"""

    def __init__(self, responses: list[str]):
        self.calls: list[tuple[str, dict]] = []  # (purpose, kwargs)
        self._responses = list(responses)

    async def call(self, prompt: str, *, purpose: str = "generate", **kwargs):
        self.calls.append((purpose, kwargs))
        return SimpleNamespace(
            text=self._responses.pop(0) if self._responses else "")


def run(coro):
    return asyncio.run(coro)


def test_high_priority_fail_vetoes_and_low_priority_sorted():
    """setting_consistency FAIL → blocking=True、fix_directive 进 must_fix；
    同批 theme_depth FAIL 也进 must_fix，且 must_fix 按宪法优先级排序"""
    plan = LeaderArbiter().arbitrate([
        # 故意乱序传入：仲裁顺序应由 CONSTITUTIONAL_PRIORITY 决定
        critique("theme_depth", "FAIL", "补一处律法与人情的张力", "yes"),
        critique("plot_coherence", "PASS", "", "yes"),
        critique("setting_consistency", "FAIL", "改掉明清称谓", "yes"),
    ])
    assert plan.blocking is True
    assert plan.must_fix == ["改掉明清称谓", "补一处律法与人情的张力"]
    assert plan.noted == []
    # 宪法表逐字校验（蓝图 7 维，blocking 只取前 3）
    assert CONSTITUTIONAL_PRIORITY[:3] == [
        "setting_consistency", "plot_coherence", "character_motivation"]


def test_non_executable_noted_and_emotion_arc_not_blocking():
    """executable=no（即便最高优先级）→ noted 记 [无法修复]、不进 must_fix、
    不 blocking；emotion_arc FAIL → 进 must_fix 但不 blocking"""
    plan = LeaderArbiter().arbitrate([
        critique("setting_consistency", "FAIL", "大改世界观才能修复", "no"),
        critique("emotion_arc", "FAIL", "中段补一次情感转折", "yes"),
    ])
    assert plan.must_fix == ["中段补一次情感转折"]
    assert plan.noted == ["[无法修复] setting_consistency: 大改世界观才能修复"]
    assert plan.blocking is False


def test_reader_proxy_parses_and_accumulates_curve():
    """fake LLM 返回蓝图格式文本 → 字段解析正确（9/0 钳制到 5/1）；
    react 两次 → reaction_curve 累积两条、predictions 全收"""
    llm = FakeLLM([
        "1. yes\n"
        "2. 展昭\n"
        "3. 刘伯的赌债会被包拯揭穿\n"
        "4. 9/4/0\n"
        "5. 公孙策誊写口供的过渡段\n",
        "1. no\n"
        "2. 包拯\n"
        "3. 展昭夜探王府取证\n"
        "4. 2/3/4\n"
        "5. \n",
    ])
    proxy = ReaderProxy("30岁喜欢悬疑的读者", llm_call=llm.call)
    r1 = run(proxy.react(CHAPTER))
    assert r1.continue_reading is True
    assert r1.favorite_character == "展昭"
    assert r1.prediction == "刘伯的赌债会被包拯揭穿"
    assert (r1.tension, r1.curiosity, r1.engagement) == (5, 4, 1)  # 钳制 9→5, 0→1
    assert r1.skip_point == "公孙策誊写口供的过渡段"
    r2 = run(proxy.react(CHAPTER))
    assert r2.continue_reading is False
    assert (r2.tension, r2.curiosity, r2.engagement) == (2, 3, 4)
    assert r2.skip_point == ""
    # 曲线累积两条；predictions 全收；调用参数 temperature=0.5
    assert proxy.get_reaction_curve() == {
        "tension": [5, 2], "curiosity": [4, 3], "engagement": [1, 4]}
    assert proxy.get_predictions() == ["刘伯的赌债会被包拯揭穿", "展昭夜探王府取证"]
    assert len(proxy.reaction_history) == 2
    assert [p for p, _ in llm.calls] == ["reader_proxy", "reader_proxy"]
    assert all(kw["temperature"] == 0.5 for _, kw in llm.calls)
