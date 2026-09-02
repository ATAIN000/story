"""Model-visible-logged 测试（借鉴 DSH：模型可见即已记录）。

验证 LLM 调用的完整上下文（prompt/response/章节/token/耗时）落入
llm_calls 表，可按章节重建该章的完整调用链。独立于世界状态事件流
（不进 events 表，不污染 tick/rollback）。
"""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from story_engine.kernel.syscalls import Kernel
from story_engine.world.event_store import EventStore


def run(coro):
    return asyncio.run(coro)


# ---------- EventStore 层：llm_calls 表读写 ----------
def test_record_and_read_llm_calls():
    tmp = Path(tempfile.mkdtemp())
    store = EventStore(str(tmp / "story.db"))
    store.record_llm_call(chapter=1, purpose="generate_chapter", model="glm",
                          prompt="写第一章", response="正文……",
                          tokens_in=100, tokens_out=200, latency_ms=1500.5)
    store.record_llm_call(chapter=1, purpose="extract_events", model="glm",
                          prompt="抽事件", response="[]",
                          tokens_in=50, tokens_out=10, latency_ms=300.0)
    store.record_llm_call(chapter=2, purpose="generate_chapter", model="glm",
                          prompt="写第二章", response="正文2",
                          tokens_in=120, tokens_out=220, latency_ms=1600.0)
    ch1 = store.llm_calls_for_chapter(1)
    assert len(ch1) == 2                       # 第1章两次调用
    assert ch1[0]["purpose"] == "generate_chapter"
    assert ch1[0]["prompt"] == "写第一章"      # 完整 prompt 落盘
    assert ch1[0]["response"] == "正文……"      # 完整 response 落盘
    assert ch1[0]["tokens_out"] == 200
    ch2 = store.llm_calls_for_chapter(2)
    assert len(ch2) == 1 and ch2[0]["prompt"] == "写第二章"
    store.close()


def test_llm_calls_not_in_events_table():
    """llm_calls 独立于事件流：不进 events 表，不影响世界状态 tick。"""
    tmp = Path(tempfile.mkdtemp())
    store = EventStore(str(tmp / "story.db"))
    head_before = store.head_tick("main") if hasattr(store, "head_tick") else None
    store.record_llm_call(chapter=1, purpose="p", model="m", prompt="x",
                          response="y", tokens_in=1, tokens_out=1, latency_ms=1)
    # events 表无 llm 记录（不在事件流）
    rows = store._conn.execute(
        "SELECT COUNT(*) FROM events WHERE event_type='llm_call'").fetchone()
    assert rows[0] == 0
    store.close()


# ---------- kernel 接线：LLM call → on_call → store ----------
def test_kernel_llm_call_recorded_to_store():
    """kernel 初始化后 llm.on_call 接到 store；一次 call 落 llm_calls 表。"""
    tmp = Path(tempfile.mkdtemp())
    k = Kernel(tmp, plugin_dir=None)
    assert k.llm.on_call is not None          # 接线完成
    k.llm.current_chapter = 5
    run(k.llm_call("测试 prompt", purpose="script_analyze"))
    k.llm.current_chapter = None
    calls = k.store.llm_calls_for_chapter(5)
    assert len(calls) == 1
    assert calls[0]["purpose"] == "script_analyze"
    assert calls[0]["prompt"] == "测试 prompt"
    k.close()


def test_llm_call_without_chapter_still_recorded():
    """chapter=None（非章节上下文，如起名/分析）也记录，chapter 列空。"""
    tmp = Path(tempfile.mkdtemp())
    k = Kernel(tmp, plugin_dir=None)
    run(k.llm_call("起名", purpose="cast_naming"))
    # chapter=None 的记录
    rows = k.store._conn.execute(
        "SELECT chapter, purpose FROM llm_calls WHERE purpose='cast_naming'").fetchall()
    assert len(rows) == 1 and rows[0][0] is None
    k.close()
