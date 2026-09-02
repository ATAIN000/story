"""章节事件总线测试（借鉴 DSH 事件驱动扩展点）。

验证 ChapterEventBus 的注册/触发/返回值收集/异常隔离，以及 engine 的
validation/text_layer 事件驱动校验（行为与直接调用一致）。
"""
from __future__ import annotations

import asyncio

from story_engine.kernel.chapter_events import (
    CHAPTER_EVENTS, ChapterEventBus, VALIDATION_TEXT)


def run(coro):
    return asyncio.run(coro)


def test_event_names_defined():
    assert VALIDATION_TEXT == "validation/text_layer"
    assert "chapter/begin" in CHAPTER_EVENTS
    assert "chapter/committed" in CHAPTER_EVENTS


def test_on_and_emit_collects_results():
    bus = ChapterEventBus()
    bus.on("validation/text_layer", lambda chapter_no, text: ["v1"])
    bus.on("validation/text_layer", lambda chapter_no, text: ["v2", "v3"])
    out = run(bus.emit("validation/text_layer", chapter_no=1, text="x"))
    assert out == [["v1"], ["v2", "v3"]]


def test_emit_no_listeners_returns_empty():
    bus = ChapterEventBus()
    assert run(bus.emit("chapter/begin", chapter_no=1)) == []


def test_emit_none_results_filtered():
    bus = ChapterEventBus()
    bus.on("chapter/begin", lambda chapter_no: None)
    bus.on("chapter/begin", lambda chapter_no: "got")
    assert run(bus.emit("chapter/begin", chapter_no=1)) == ["got"]


def test_listener_exception_does_not_break_others():
    bus = ChapterEventBus()

    def bad(**kw):
        raise ValueError("boom")

    bus.on("chapter/begin", bad)
    bus.on("chapter/begin", lambda **kw: "ok")
    out = run(bus.emit("chapter/begin", chapter_no=1))
    assert out == ["ok"]  # bad 炸了不影响后面的监听器


def test_async_listener_supported():
    bus = ChapterEventBus()

    async def ahandler(**kw):
        return "async-result"

    bus.on("draft/generated", ahandler)
    assert run(bus.emit("draft/generated", chapter_no=2, text="t")) == ["async-result"]


def test_off_and_clear():
    bus = ChapterEventBus()
    h = lambda **kw: 1
    bus.on("chapter/begin", h)
    bus.off("chapter/begin", h)
    assert run(bus.emit("chapter/begin", chapter_no=1)) == []
    bus.on("chapter/begin", lambda **kw: 2)
    bus.clear("chapter/begin")
    assert run(bus.emit("chapter/begin", chapter_no=1)) == []


# ---------- engine 事件驱动校验（行为一致性） ----------
def test_engine_validation_via_event_listener(monkeypatch):
    """engine 的 validation/text_layer 走事件监听：默认监听器产出 violations
    （与直接调用 _check_text_consistency 行为一致）。mock 下校验关闭。"""
    import tempfile
    from pathlib import Path
    # monkeypatch 自动还原，不污染后续测试（os.environ 直改会泄漏）
    monkeypatch.setenv("STORY_ENGINE_EMBED_MODE", "dummy")
    monkeypatch.setenv("STORY_ENGINE_SCRIPTED_DEMO", "0")
    monkeypatch.setenv("STORY_ENGINE_ENTITY_CHECK", "1")

    from story_engine.engine import StoryEngine

    tmp = Path(tempfile.mkdtemp())
    eng = StoryEngine(str(tmp))
    # mock 模式下 entity check 关闭（_on_text_validation → []）；
    # 字数门对「正文」（2字）报 word_count 违规（远低于题材区间下限）
    out = run(eng._chapter_bus.emit(VALIDATION_TEXT, chapter_no=1, text="正文"))
    assert len(out) == 2                       # 两个默认监听器
    assert out[0] == []                        # 一致性校验：mock 关
    assert out[1] and out[1][0]["check"] == "word_count"  # 字数门：过短被抓
    eng.kernel.close()
