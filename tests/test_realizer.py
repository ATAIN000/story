"""P5.4 核心测试：Realizer 共创者 + humanize（蓝图 5.3 决策4/5）

用户指令：只保留 3 个核心用例，不穷举边界：
  1. fake LLM 下 realize：prompt 含 IR 摘要片段（beat phase/event 5W 元素）
     + texture 数值指令 + 中文资源库素材（四字格/敬语）+ 插件 hard_requirements；
     恰好 1 次 LLM 调用，返回 fake 文本
  2. Narrativizer 链路 + 语言选择：zh→ChineseRealizer；未知语言→zh+warning；
     humanize 接入（含 ai-ism 的 fake 输出 → 过滤后不含该 ism）
  3. `_filter_ai_isms`：zh/en 删除/替换各一断言
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from story_engine.narrative import (
    BeatIR, ChineseRealizer, EnglishRealizer, EventIR, NarrativeIR, Narrativizer,
    SceneBreakdown, TextureParams, _filter_ai_isms,
)
from story_engine.narrative.ir_builder import TEXTURE_DEFAULTS
from story_engine.types import GenreBundle


class FakeLLM:
    """记录调用的伪 LLM（签名对齐 LLMPool.call，P4.2 同款）"""

    def __init__(self, scripts: dict[str, str]):
        self.calls: list[tuple[str, str]] = []  # (purpose, prompt)
        self._scripts = scripts

    async def call(self, prompt: str, *, purpose: str = "generate", **kwargs):
        self.calls.append((purpose, prompt))
        return SimpleNamespace(text=self._scripts.get(purpose, ""))


def run(coro):
    return asyncio.run(coro)


def _ir() -> NarrativeIR:
    return NarrativeIR(
        beats=[BeatIR("b1", "disruption", ["Suspense", "Conflict"],
                      "man_in_hole", 0.7)],
        events=[EventIR("包拯", "act:accuse", "刘伯", "开封府",
                        "第1日·午时", None, "玉佩失窃", None)],
        dialogue_lines=[],
        scene_breakdown=[SceneBreakdown("s1", (0, 1), "开封府")],
        texture=TextureParams(**TEXTURE_DEFAULTS["zh"]),  # idiom_density=0.5, honorific=0.6
    )


def _bundle(language: str = "zh") -> GenreBundle:
    return GenreBundle(
        genre="mystery", culture="confucian_officialdom", language=language,
        genre_params={"prompt": {
            "role": "公案小说作者",
            "setting": "北宋，包拯开封府断案",
            "characters": "包拯（府尹）、展昭（护卫）",
            "style": "800-1200字，文白相间",
            "hard_requirements": ["禁用超自然力量直接破案（梦兆/冤魂只能渲染氛围）"],
        }})


# ---------- 用例1：fake LLM realize — prompt 共创者四要素齐备 ----------

def test_realize_prompt_co_creation():
    llm = FakeLLM({"realize_chapter": "包拯升堂，惊堂木一拍，堂下霎时寂静。"})
    realizer = ChineseRealizer(llm_call=llm.call)
    text = run(realizer.realize(_ir(), None, _bundle()))

    assert text == "包拯升堂，惊堂木一拍，堂下霎时寂静。"
    assert len(llm.calls) == 1                       # 恰好 1 次 LLM 调用
    prompt = llm.calls[0][1]
    # IR 摘要：beat（phase+tension+primitives）与 event 5W 元素
    assert "phase=disruption" in prompt and "tension=0.70" in prompt
    assert "Suspense" in prompt
    assert "包拯" in prompt and "act:accuse" in prompt
    assert "开封府" in prompt and "玉佩失窃" in prompt
    # texture 数值翻成的创作指令（zh 表 idiom_density=0.5 / honorific=0.6）
    assert "0.50" in prompt and "0.60" in prompt
    # 中文资源库素材：四字格确定性采样（0.5→前5条含「步履沉稳」）+ 三级敬语
    assert "步履沉稳" in prompt
    assert "大人" in prompt and "草民" in prompt
    # 插件 prompt 段：role/style/hard_requirements
    assert "公案小说作者" in prompt and "文白相间" in prompt
    assert "禁用超自然力量直接破案" in prompt


# ---------- 用例2：Narrativizer 链路 + 语言选择 + humanize 接入 ----------

def test_narrativizer_chain_language_selection_and_humanize():
    # zh：realize → humanize，fake 输出里的 ai-ism 被过滤（删除 + 替换各一）
    llm = FakeLLM({"realize_chapter": "值得注意的是，包拯升堂。总而言之，案有蹊跷。"})
    nav = Narrativizer(bundle=_bundle("zh"), llm_call=llm.call)
    text = run(nav.narrate(_ir()))
    assert "值得注意的是" not in text          # 删除类条目
    assert "总而言之" not in text and "总之" in text  # 替换类条目
    # 语言选择：zh→ChineseRealizer，en→EnglishRealizer
    assert isinstance(nav.select_realizer("zh"), ChineseRealizer)
    assert isinstance(nav.select_realizer("en"), EnglishRealizer)
    # 未知语言 → zh + warning；走 narrate 仍按中文链路产出
    with pytest.warns(UserWarning, match="未知语言"):
        assert isinstance(nav.select_realizer("fr"), ChineseRealizer)
    nav_fr = Narrativizer(bundle=_bundle("fr"), llm_call=llm.call)
    with pytest.warns(UserWarning, match="未知语言"):
        out = run(nav_fr.narrate(_ir()))
    assert out == text


# ---------- 用例3：_filter_ai_isms 删除/替换各一断言（zh+en） ----------

def test_filter_ai_isms_zh_and_en():
    # zh 删除：「映入眼帘」去掉后句子仍成立
    assert _filter_ai_isms("一轮明月映入眼帘。", "zh") == "一轮明月。"
    # zh 替换：「似乎」→ 更朴素的「像是」
    assert _filter_ai_isms("他似乎早已察觉。", "zh") == "他像是早已察觉。"
    # en 替换
    assert _filter_ai_isms("In conclusion, he left.", "en") == "In the end, he left."
    assert _filter_ai_isms("a tapestry of lies", "en") == "a web of lies"
