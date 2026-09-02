"""第一波③ 标题 fallback 测试 — _fallback_title

覆盖：mock 跳过 / 合理标题 / 包装清理 / 退化标题拒绝 / 长度闸 / 异常兜底。
用未绑定方法 + 轻量 self（只暴露 .llm）避免实例化 StoryEngine。
"""
from __future__ import annotations

import pytest

from story_engine.engine import StoryEngine


class _Resp:
    def __init__(self, text):
        self.text = text


class _FakeLLM:
    def __init__(self, text="", is_mock=False, exc=False):
        self.text = text
        self.is_mock = is_mock
        self.exc = exc
        self.last_prompt = ""

    async def call(self, prompt, *, purpose, temperature, max_tokens):
        if self.exc:
            raise RuntimeError("llm boom")
        self.last_prompt = prompt
        return _Resp(self.text)


class _Engine:
    """轻量 self：只暴露 _fallback_title 依赖的 .llm"""

    def __init__(self, llm):
        self.llm = llm


BODY = ("破庙之中，烛火摇曳。百晓生展开残页，墨迹自行游动。"
        "门外风声骤起，一道黑影掠入，刀光破空而下。")


@pytest.mark.asyncio
async def test_mock_llm_skips_fallback():
    """mock 模式不调 LLM，直接返回 None（保留默认「第N章」）"""
    e = _Engine(_FakeLLM(is_mock=True))
    assert await StoryEngine._fallback_title(e, BODY) is None


@pytest.mark.asyncio
async def test_clean_title_returned():
    e = _Engine(_FakeLLM(text="残页惊变"))
    assert await StoryEngine._fallback_title(e, BODY) == "残页惊变"


@pytest.mark.asyncio
async def test_strips_quote_and_prefix_wrappers():
    """LLM 常给标题加引号/书名号/「标题：」前缀/#，应清理"""
    cases = [
        '「残页惊变」', '《残页惊变》', '"残页惊变"',
        '标题：残页惊变', '# 残页惊变', 'Title: 残页惊变',
        ' 残页惊变 ', '“残页惊变”',
    ]
    for raw in cases:
        e = _Engine(_FakeLLM(text=raw))
        assert await StoryEngine._fallback_title(e, BODY) == "残页惊变", raw


@pytest.mark.asyncio
async def test_degenerate_chapterN_title_rejected():
    """LLM 仍退化为「第N章」→ 不合格，返回 None"""
    for raw in ["第四章", "第4章", "第一百章"]:
        e = _Engine(_FakeLLM(text=raw))
        assert await StoryEngine._fallback_title(e, BODY) is None, raw


@pytest.mark.asyncio
async def test_too_long_title_rejected():
    e = _Engine(_FakeLLM(text="这是一个特别特别长的章节标题超过十六个字"))
    assert await StoryEngine._fallback_title(e, BODY) is None


@pytest.mark.asyncio
async def test_too_short_title_rejected():
    e = _Engine(_FakeLLM(text="啊"))
    assert await StoryEngine._fallback_title(e, BODY) is None


@pytest.mark.asyncio
async def test_llm_exception_returns_none():
    """LLM 调用异常 → None（不阻塞，调用方保留默认标题）"""
    e = _Engine(_FakeLLM(exc=True))
    assert await StoryEngine._fallback_title(e, BODY) is None


@pytest.mark.asyncio
async def test_multiline_takes_first_line():
    """LLM 返回多行（标题+多余解释），只取首行"""
    e = _Engine(_FakeLLM(text="残页惊变\n（这是本章标题）"))
    assert await StoryEngine._fallback_title(e, BODY) == "残页惊变"
