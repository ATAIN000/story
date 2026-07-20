"""P7.2 测试：L3 story.language pack 合并进 Realizer 资源池

核心用例（用户指令：只保留核心）：
1. zh realizer 合并 zh-gongan-texture：合并池含 pack 词条且代码常量仍在、
   重复词条去重、敬语体系按子键并集、类常量不被污染
2. 采样进 prompt：fake LLM 下 realize 的 prompt 含 pack 敬语词条（确定性）
3. 兜底：无 registry → 资源=纯代码常量；en pack 对 zh realizer 不合并；
   未知资源键 → warning + 忽略；en realizer 同样合并（zh/en 均生效）
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from story_engine.kernel.registry import ExtensionRegistry
from story_engine.narrative import (
    BeatIR, ChineseRealizer, EnglishRealizer, EventIR, NarrativeIR,
    SceneBreakdown, TextureParams,
)
from story_engine.narrative.ir_builder import TEXTURE_DEFAULTS
from story_engine.types import GenreBundle

PACKS_DIR = (Path(__file__).resolve().parent.parent
             / "story_engine" / "plugins" / "packs")


class FakeLLM:
    """记录调用的伪 LLM（签名对齐 LLMPool.call，同 test_realizer）"""

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
        texture=TextureParams(**TEXTURE_DEFAULTS["zh"]),  # honorific=0.6 → 敬语进 prompt
    )


def _bundle() -> GenreBundle:
    return GenreBundle(genre="mystery", culture="confucian_officialdom",
                       language="zh")


def _real_pack_registry() -> ExtensionRegistry:
    reg = ExtensionRegistry()
    reg.load_packs(PACKS_DIR)   # 含 active 的 zh-gongan-texture
    return reg


# ---------- 用例1：zh realizer 合并 pack 资源（键并集 + 去重 + 子键并集） ----------

def test_zh_realizer_merges_language_pack():
    r = ChineseRealizer(registry=_real_pack_registry())
    res = r.LANGUAGE_RESOURCES
    base = ChineseRealizer.LANGUAGE_RESOURCES
    assert res is not base                          # 实例副本，类常量不被污染
    # 代码常量仍在 + pack 词条并入 + 常量/pack 重复词条去重
    assert "步履沉稳" in res["四字格"]               # 代码常量
    assert "铁面无私" in res["四字格"]               # pack 新词条
    assert res["四字格"].count("明察秋毫") == 1      # 常量与 pack 重复 → 去重
    assert len(base["四字格"]) == 16                # 类常量原样
    # 敬语体系（dict）按子键并集：pack 新敬称进上位，常量仍在
    assert "府尊" in res["敬语体系"]["上位"]
    assert "大人" in res["敬语体系"]["上位"]
    assert "民妇" in res["敬语体系"]["下位"]


# ---------- 用例2：pack 词条经确定性采样进 prompt ----------

def test_pack_entries_reach_prompt():
    llm = FakeLLM({"realize_chapter": "包拯升堂，堂下霎时寂静。"})
    r = ChineseRealizer(llm_call=llm.call, registry=_real_pack_registry())
    text = run(r.realize(_ir(), None, _bundle()))
    assert text == "包拯升堂，堂下霎时寂静。"
    assert len(llm.calls) == 1
    prompt = llm.calls[0][1]
    # zh 默认 honorific_register=0.6 ≥ 0.3 → 敬语体系全量进 prompt（确定性）
    assert "府尊" in prompt and "民妇" in prompt    # pack 敬语词条
    assert "步履沉稳" in prompt                     # 常量采样仍在


# ---------- 用例3：无 registry / 语言不匹配 / 未知键 兜底 ----------

def test_no_registry_mismatch_and_unknown_key(tmp_path):
    # 无 registry：资源 = 纯代码常量（行为与基线逐字一致）
    assert (ChineseRealizer().LANGUAGE_RESOURCES
            is ChineseRealizer.LANGUAGE_RESOURCES)
    assert (EnglishRealizer().LANGUAGE_RESOURCES
            is EnglishRealizer.LANGUAGE_RESOURCES)

    pack_dir = tmp_path / "packs" / "story.language"
    pack_dir.mkdir(parents=True)
    (pack_dir / "en-court-texture.yaml").write_text(
        "manifest_version: 1\nname: en-court-texture\n"
        "extension_point: story.language\n"
        "params:\n  language: en\n  resources:\n"
        "    legal_terms: [grievance, writ, tribunal]\n"
        "    honorifics: [Your Honor, my lady]\n",
        encoding="utf-8")
    (pack_dir / "zh-bogus-key.yaml").write_text(
        "manifest_version: 1\nname: zh-bogus-key\n"
        "extension_point: story.language\n"
        "params:\n  language: zh\n  resources:\n"
        "    生造键: [甲, 乙]\n",
        encoding="utf-8")
    reg = ExtensionRegistry()
    reg.load_packs(tmp_path / "packs")

    # 未知资源键 → warning + 忽略；en pack 对 zh realizer 不合并（内容=常量）
    with pytest.warns(UserWarning, match="未知资源键"):
        zh = ChineseRealizer(registry=reg)
    assert "生造键" not in zh.LANGUAGE_RESOURCES
    assert (zh.LANGUAGE_RESOURCES["四字格"]
            == ChineseRealizer.LANGUAGE_RESOURCES["四字格"])

    # en realizer 合并 en pack（合并逻辑 zh/en 均生效）
    en = EnglishRealizer(registry=reg)
    assert "writ" in en.LANGUAGE_RESOURCES["legal_terms"]       # pack 词条
    assert "grievance" in en.LANGUAGE_RESOURCES["legal_terms"]  # 常量仍在
    assert en.LANGUAGE_RESOURCES["legal_terms"].count("grievance") == 1
    assert "my lady" in en.LANGUAGE_RESOURCES["honorifics"]
