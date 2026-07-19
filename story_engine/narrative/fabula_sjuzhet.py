"""Module 5.2 Fabula/Sjuzhet 分离 — 蓝图 5.2 决策3（规则化零 LLM）

- FabulaBuilder.build(events)：真值层——全事件按 world_tick 排序 + characters 集合
- SjuzhetSelector.select(fabula, bundle)：呈现层——按 genre_params 可选键
  `pov_strategy`（缺省 omniscient）与 `narrative_order`（缺省 linear）
  产出呈现顺序 + 可见子集；不重排 fabula 本身

输入事件形态：dict（kernel.query_world("all_events") 返回
WorldEvent.to_dict()+active，键含 event_id/event_type/timestamp/world_tick/
payload/...）。EventIR 层对接由 P5.6 engine 侧编排，本模块不管。

时间键：本系统事件 dict 有 world_tick（int，event_store 落库字段）——
蓝图伪码的 e.world_tick 与此一致；无 world_tick 时回退事件在列表中的序号。
（注：payload 里的 story_time 是展示用字符串如 "第1日·午时"，不可作排序键。）

fair_play 启发式（pov_strategy=="fair_play"，供 mystery 类题材）：事件
payload 文本含 culprit/murderer/真凶 关键词即视为「真凶身份相关事件」，
移到末尾（recognition 相位），其余保持原序。纯文本关键词启发式，
不接 effects/fluent 解析（本期简化，注释见 _is_culprit_event）。
"""
from __future__ import annotations

import json
import warnings
from dataclasses import dataclass, field
from typing import Any

from ..types import GenreBundle

# fair_play 真凶关键词（启发式，大小写不敏感；中英关键词见模块 docstring）
_CULPRIT_KEYWORDS = ("culprit", "murderer", "真凶")


@dataclass
class Fabula:
    """真值层：故事世界发生的所有事件（按 world_tick 排序）+ 涉及角色集合"""
    all_events: list[dict] = field(default_factory=list)
    characters: set[str] = field(default_factory=set)


@dataclass
class Sjuzhet:
    """呈现层：讲给读者的事件子集 + 呈现顺序 + POV 策略

    order 字段为蓝图伪码之外的增量字段：记录实际生效的叙事顺序
    （linear/reverse），便于下游 realizer/调试核查。
    """
    events: list[dict] = field(default_factory=list)
    pov: str = "omniscient"
    order: str = "linear"


class FabulaBuilder:
    """构建 fabula：故事世界发生的所有事件（真值层）"""

    def build(self, events: list[dict]) -> Fabula:
        # world_tick 缺省时回退列表序号（保持输入相对序）
        indexed = list(enumerate(events))
        ordered = sorted(
            indexed, key=lambda p: (p[1].get("world_tick", p[0]), p[0]))
        all_events = [e for _, e in ordered]
        characters = {
            e.get("payload", {}).get("agent")
            for e in all_events
            if e.get("payload", {}).get("agent")
        }
        return Fabula(all_events=all_events, characters=characters)


class SjuzhetSelector:
    """选择 sjuzhet：讲给读者的子集 + 重排（呈现层）"""

    def select(self, fabula: Fabula, genre: GenreBundle) -> Sjuzhet:
        params = genre.genre_params or {}
        pov = params.get("pov_strategy", "omniscient")
        order = params.get("narrative_order", "linear")

        # POV 决定可见子集
        if pov == "omniscient":
            visible = list(fabula.all_events)
        elif pov == "fair_play":
            visible = self._fair_play(fabula.all_events)
        else:
            # 其他 pov（如 limited）本期简化为全知 + warning（Phase 5 不做限知投影）
            warnings.warn(
                f"未实现的 pov_strategy={pov!r}，回退 omniscient", stacklevel=2)
            pov = "omniscient"
            visible = list(fabula.all_events)

        # narrative_order 决定呈现顺序
        if order == "linear":
            events = visible
        elif order == "reverse":
            events = list(reversed(visible))
        else:
            warnings.warn(
                f"未知 narrative_order={order!r}，回退 linear", stacklevel=2)
            order = "linear"
            events = visible

        return Sjuzhet(events=events, pov=pov, order=order)

    def _fair_play(self, events: list[dict]) -> list[dict]:
        """真凶身份相关事件延后到 recognition 相位（=末尾），其余保持原序"""
        normal = [e for e in events if not self._is_culprit_event(e)]
        culprit = [e for e in events if self._is_culprit_event(e)]
        return normal + culprit

    @staticmethod
    def _is_culprit_event(event: dict) -> bool:
        """启发式：payload 序列化文本含真凶关键词（不解析 effects/fluent）"""
        text = json.dumps(event.get("payload") or {}, ensure_ascii=False).lower()
        return any(k in text for k in _CULPRIT_KEYWORDS)
