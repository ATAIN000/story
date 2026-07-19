"""P5.5 双语验收：同一 IR 经 zh/en realizer 叙事等价（蓝图 1420，Module 5 验证核心）

用户指令：只写核心用例，不穷举边界（≤3）：
  1. 双语验收主用例：同一 NarrativeIR（beats/events/dialogue/texture，event 带
     subtext、dialogue 带 emotion 概念）分别经 ChineseRealizer / EnglishRealizer
     （各配 fake LLM）——zh prompt 含四字格/敬语素材 + 中文 texture 指令，
     en prompt 含法律词汇/长句嵌套素材 + 英文 texture 指令；两 prompt 的 IR
     摘要段结构对齐（同 beats/events 数、同 phase 序列——「叙事等价」的
     可执行定义：同一故事骨架驱动）
  2. subtext 双语映射：同一 SubtextInterlingua → map_to("zh")/map_to("en")
     返回不同语言表达；经两 realizer 的 IR 摘要时 subtext 各按本语言呈现
  3. 返回结构对齐：Narrativizer(language=zh/en) 链路均走通（realize→humanize
     不崩），各返回字符串；en ai-ism 进 fake 输出则被 en 表过滤
"""
from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace

from story_engine.narrative import (
    BeatIR, ChineseRealizer, DialogueIR, EnglishRealizer, EventIR,
    NarrativeIR, Narrativizer, SceneBreakdown, SubtextInterlingua,
    TextureParams,
)
from story_engine.types import GenreBundle


class FakeLLM:
    """记录调用的伪 LLM（签名对齐 LLMPool.call，与 test_realizer.py 同款）"""

    def __init__(self, scripts: dict[str, str]):
        self.calls: list[tuple[str, str]] = []  # (purpose, prompt)
        self._scripts = scripts

    async def call(self, prompt: str, *, purpose: str = "generate", **kwargs):
        self.calls.append((purpose, prompt))
        return SimpleNamespace(text=self._scripts.get(purpose, ""))


def run(coro):
    return asyncio.run(coro)


def _ir() -> NarrativeIR:
    """同一故事骨架：2 beats / 2 events（其一带 subtext）/ 1 dialogue。"""
    return NarrativeIR(
        beats=[
            BeatIR("b1", "equilibrium", ["Atmosphere"], "man_in_hole", 0.2),
            BeatIR("b2", "disruption", ["Suspense", "Conflict"],
                   "man_in_hole", 0.7),
        ],
        events=[
            EventIR("包拯", "act:accuse", "刘伯", "开封府", "第1日·午时",
                    None, "玉佩失窃",
                    SubtextInterlingua("emo:fear", "soc:loyalty", 0.8)),
            EventIR("刘伯", "act:confess", "包拯", "开封府", "第1日·未时",
                    "低声", None, None),
        ],
        dialogue_lines=[
            DialogueIR("包拯", "accuse", "act:accuse", "emo:anger",
                       "negative", "dialogue_register"),
        ],
        scene_breakdown=[SceneBreakdown("s1", (0, 2), "开封府")],
        # 取值使双语资源采样均触发：idiom 0.5→zh 四字格5条/en 头韵5条；
        # honorific 0.6→zh 敬语体系(≥0.3)/en Honorifics(≥0.2)；句长均值18→en 句式4条
        texture=TextureParams(
            honorific_register=0.6, emotion_explicitness=0.3,
            register_switching=0.6, idiom_density=0.5,
            sentence_length_distribution=(18.0, 8.0), implicit_vs_explicit=0.7,
            perspective_distance="全知", temporal_ordering="顺叙"),
    )


def _bundle(language: str) -> GenreBundle:
    prompt = {
        "zh": {"role": "公案小说作者", "setting": "北宋，包拯开封府断案",
               "characters": "包拯（府尹）、刘伯（嫌疑人）",
               "style": "800-1200字，文白相间", "hard_requirements": []},
        "en": {"role": "a courtroom novelist", "setting": "a Victorian assize court",
               "characters": "the magistrate, the petitioner",
               "style": "900-1300 words, measured prose", "hard_requirements": []},
    }[language]
    return GenreBundle(genre="mystery", culture="courtroom", language=language,
                       genre_params={"prompt": prompt})


def _summary_lines(prompt: str) -> list[str]:
    """取 prompt 首个 === 段（IR 摘要段）的非空行——zh/en 段标题不同，结构相同。"""
    lines = prompt.splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("=== "))
    end = next(i for i in range(start + 1, len(lines))
               if lines[i].startswith("=== "))
    return [l for l in lines[start + 1:end] if l.strip()]


# ---------- 用例1：双语验收主用例——同一 IR 两语言 prompt 各带本语言素材且骨架对齐 ----------

def test_bilingual_same_ir_narrative_equivalence():
    zh_llm = FakeLLM({"realize_chapter": "包拯升堂，堂下霎时寂静。"})
    en_llm = FakeLLM({"realize_chapter": "The court fell silent."})
    zh_text = run(ChineseRealizer(llm_call=zh_llm.call).realize(
        _ir(), None, _bundle("zh")))
    en_text = run(EnglishRealizer(llm_call=en_llm.call).realize(
        _ir(), None, _bundle("en")))
    assert zh_text == "包拯升堂，堂下霎时寂静。"
    assert en_text == "The court fell silent."
    assert len(zh_llm.calls) == 1 and len(en_llm.calls) == 1  # 各恰好 1 次 LLM 调用

    zh_prompt, en_prompt = zh_llm.calls[0][1], en_llm.calls[0][1]
    # 各带本语言资源库素材：zh 四字格 + 三级敬语；en 法律词汇 + 头韵 + 长句嵌套
    assert "步履沉稳" in zh_prompt and "大人" in zh_prompt and "草民" in zh_prompt
    assert "grievance" in en_prompt and "safe and sound" in en_prompt
    assert "It was not until the ink had dried" in en_prompt
    # 各带本语言 texture 解读指令
    assert "敬语密度" in zh_prompt and "四字格密度" in zh_prompt
    assert "Honorific density" in en_prompt and "Idiom density" in en_prompt

    # 「叙事等价」可执行定义：两 prompt 的 IR 摘要段结构对齐（同一故事骨架驱动）
    zh_sum, en_sum = _summary_lines(zh_prompt), _summary_lines(en_prompt)
    zh_beats = [l for l in zh_sum if l.startswith("[beat")]
    en_beats = [l for l in en_sum if l.startswith("[beat")]
    assert zh_beats == en_beats                       # beat 行语言无关，逐字相同
    assert re.findall(r"phase=(\w+)", zh_prompt) == \
        re.findall(r"phase=(\w+)", en_prompt) == ["equilibrium", "disruption"]
    # 同 events 数 / 同 dialogue 数（摘要行计数；概念 ID 语言无关两侧均现）
    assert sum(l.startswith("- ") and " illocution=" not in l for l in zh_sum) == \
        sum(l.startswith("- ") and " illocution=" not in l for l in en_sum) == 2
    assert sum(" illocution=" in l for l in zh_sum) == \
        sum(" illocution=" in l for l in en_sum) == 1
    for concept in ("act:accuse", "act:confess"):
        assert concept in zh_prompt and concept in en_prompt


# ---------- 用例2：subtext 双语映射——map_to zh/en 不同且经摘要各按本语言呈现 ----------

def test_subtext_map_to_bilingual():
    sub = SubtextInterlingua("emo:fear", "soc:loyalty", 0.8)
    assert sub.map_to("zh") == "恐惧+忠诚"
    assert sub.map_to("en") == "fear+loyalty"
    # 经两 realizer 的 IR 摘要：subtext 与 dialogue 情感各按本语言呈现（零 LLM）
    zh_sum = ChineseRealizer()._ir_summary(_ir())
    en_sum = EnglishRealizer()._ir_summary(_ir())
    assert "subtext=恐惧+忠诚" in zh_sum
    assert "subtext=fear+loyalty" in en_sum
    assert "emotion=愤怒" in zh_sum and "emotion=anger" in en_sum


# ---------- 用例3：返回结构对齐——Narrativizer zh/en 链路走通，ai-ism 各按本语言过滤 ----------

def test_narrativizer_bilingual_chain_structure_aligned():
    zh_llm = FakeLLM({"realize_chapter": "值得注意的是，包拯升堂。"})
    en_llm = FakeLLM({"realize_chapter": "In conclusion, the verdict was read."})
    zh_nav = Narrativizer(bundle=_bundle("zh"), llm_call=zh_llm.call)
    en_nav = Narrativizer(bundle=_bundle("en"), llm_call=en_llm.call)
    zh_out = run(zh_nav.narrate(_ir()))
    en_out = run(en_nav.narrate(_ir()))
    # 返回结构对齐：两语言链路（realize→humanize）各返回非空字符串
    assert isinstance(zh_out, str) and zh_out
    assert isinstance(en_out, str) and en_out
    # humanize 各按本语言表过滤 fake 输出里的 ai-ism
    assert "值得注意的是" not in zh_out
    assert "In conclusion" not in en_out and "In the end" in en_out
