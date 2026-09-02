"""章节生命周期事件总线（借鉴 DSH 结构化轮次事件流）。

核心循环（决策卡→生成→验证→修正→commit）从方法调用链改为事件驱动：
各步骤 emit 类型化事件，一致性校验/skill 注入/critic 等以**监听器**挂载，
而非硬编码进 engine 方法。新增一种校验/注入 = 注册一个监听器，不动核心循环。

事件（按章节生命周期顺序）：
- chapter/begin        章节开始（chapter_no, state）
- card/issued          决策卡产出（chapter_no, card）
- draft/generated      初稿文本产出（chapter_no, text）
- validation/text_layer 正文层校验点（chapter_no, text）→ 监听器返回 violations
- chapter/committed    章节入库（chapter_no, text）

设计约束（KISS）：监听器同步/异步皆可；emit 收集监听器返回值列表
（violations/feedback 汇入）。行为与原方法链完全一致——同一批 violations。
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger(__name__)

# 章节生命周期事件名（类型化）
CHAPTER_BEGIN = "chapter/begin"
CARD_ISSUED = "card/issued"
DRAFT_GENERATED = "draft/generated"
VALIDATION_TEXT = "validation/text_layer"
CHAPTER_COMMITTED = "chapter/committed"

CHAPTER_EVENTS = (CHAPTER_BEGIN, CARD_ISSUED, DRAFT_GENERATED,
                  VALIDATION_TEXT, CHAPTER_COMMITTED)


class ChapterEventBus:
    """章节事件总线：注册监听器（on）→ emit 触发并收集返回值。

    监听器签名：handler(**payload) -> Any（可为 async）。emit 返回所有
    监听器的非 None 返回值列表（供 violations/feedback 汇入）。
    监听器异常记 warning 不影响其他监听器（不阻塞章节生成）。
    """

    def __init__(self):
        self._listeners: dict[str, list[Callable]] = defaultdict(list)

    def on(self, event: str, handler: Callable) -> Callable:
        """注册监听器（可用作装饰器）。返回 handler 便于链式。"""
        self._listeners[event].append(handler)
        return handler

    def off(self, event: str, handler: Callable) -> None:
        if handler in self._listeners.get(event, []):
            self._listeners[event].remove(handler)

    def clear(self, event: str | None = None) -> None:
        if event is None:
            self._listeners.clear()
        else:
            self._listeners.pop(event, None)

    async def emit(self, event: str, **payload) -> list[Any]:
        """触发事件，按注册序执行监听器，收集非 None 返回值。"""
        results = []
        for handler in list(self._listeners.get(event, [])):
            try:
                out = handler(**payload)
                if inspect.isawaitable(out):
                    out = await out
                if out is not None:
                    results.append(out)
            except Exception:
                logger.warning("章节事件监听器异常 | event=%s | handler=%s",
                               event, getattr(handler, "__name__", handler),
                               exc_info=True)
        return results


def emit_sync(bus: ChapterEventBus, event: str, **payload) -> list[Any]:
    """同步上下文中触发（无运行中事件循环时）。有运行中循环 → 用 emit。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(bus.emit(event, **payload))
    raise RuntimeError("emit_sync 不能在有运行中事件循环的上下文调用（用 await emit）")
