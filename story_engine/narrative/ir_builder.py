"""Module 5.1 IRBuilder — 决策卡 + 事件流 → NarrativeIR（Phase 5 计划决策2，规则化零 LLM）

从现有体系投影 NarrativeIR（不接线 engine，P5.6 才接）：
- beats：决策卡 beats（beat_id / phase=micro_phase / primitives /
  emotion_target=target_arc / tension，键名见 showrunner/decision.py _plan_beats）
- events：kernel.query_world("all_events") 本章事件 → EventIR 5W 规则映射
- dialogue_lines：事件 payload 的对话字段 → DialogueIR（现状无对话字段 → 空表，
  见 _dialogue_ir 注释；Speech Act/politeness 用默认推断规则）
- scene_breakdown：按相邻事件 where 变化切分
- texture：TEXTURE_DEFAULTS 按 language 取默认值表，culture_params
  `texture_overrides` 可选覆盖；未知 language 回退 zh + warning

全部规则化，零 LLM 调用。
"""
from __future__ import annotations

import re
import warnings
from typing import Any

from ..types import GenreBundle
from .ir import (
    BeatIR, DialogueIR, EventIR, NarrativeIR, SceneBreakdown, TextureParams,
    to_concept_id,
)

# physical fluent "at(who,place)" 解析（types.py physical 键格式，见 mock_script.SEED_PHYSICAL）
_AT_RE = re.compile(r"^at\(([^,]+),([^)]+)\)$")

# TextureParams 默认值表（决策2 逐字：zh+confucian 一套 + en 一套合理对应值）
TEXTURE_DEFAULTS: dict[str, dict[str, Any]] = {
    "zh": {
        "honorific_register": 0.6,
        "emotion_explicitness": 0.3,
        "idiom_density": 0.5,
        "implicit_vs_explicit": 0.7,
        "register_switching": 0.6,
        "sentence_length_distribution": (18.0, 8.0),
        "perspective_distance": "全知",
        "temporal_ordering": "顺叙",
    },
    "en": {
        "honorific_register": 0.2,
        "emotion_explicitness": 0.6,
        "idiom_density": 0.3,
        "implicit_vs_explicit": 0.3,
        "register_switching": 0.3,
        "sentence_length_distribution": (15.0, 6.0),
        "perspective_distance": "全知",
        "temporal_ordering": "顺叙",
    },
}


def resolve_texture(bundle: GenreBundle) -> TextureParams:
    """language 默认值表 + culture_params.texture_overrides 覆盖（可选）。

    未知 language 回退 zh 表 + warning；culture 维度的微调本期不做
    （计划只给 zh+confucian 一套，texture_overrides 优先于 language 表）。
    """
    lang = bundle.language or "zh"
    table = TEXTURE_DEFAULTS.get(lang)
    if table is None:
        warnings.warn(f"未知 language {lang!r}，texture 回退 zh 默认值表",
                      stacklevel=2)
        table = TEXTURE_DEFAULTS["zh"]
    params = dict(table)
    overrides = (bundle.culture_params or {}).get("texture_overrides") or {}
    for k, v in overrides.items():
        if k in params:  # 只认 TextureParams 已有字段，未知键忽略
            params[k] = v
    return TextureParams(**params)


def _chapter_slice(events: list[dict], chapter: int) -> tuple[int, int]:
    """第 chapter 章的事件区间 [start, end)。

    章界规则对齐 showrunner/pacing.py 的 chapter_events（narrative_beat 载荷的
    chapter 标记沿日志单调不减；第 k 章 = 最后一个 chapter<k 标记之后，到最后
    一个 chapter==k 标记含）。两处差异：pacing 取「上一章」（episode-1）且返回
    子列表，这里取第 chapter 章本身并返回索引（事件时刻 fold 要用到位置）。
    完全无 chapter 标记退化为全部事件；无对应章 → 空区间。
    """
    if chapter < 1 or not events:
        return (0, 0)
    marks = [(i, e["payload"]["chapter"]) for i, e in enumerate(events)
             if e.get("event_type") == "narrative_beat"
             and isinstance(e.get("payload"), dict)
             and isinstance(e["payload"].get("chapter"), int)]
    if not marks:
        return (0, len(events))
    start = max((i for i, ch in marks if ch < chapter), default=-1) + 1
    end = max((i for i, ch in marks if ch == chapter), default=-1) + 1
    if end <= start:
        return (0, 0)
    return (start, end)


def _scene_breakdown(wheres: list[str]) -> list[SceneBreakdown]:
    """按相邻事件 where 变化切分；scene_id=s{i+1}，event_span 为半开区间 [start, end)"""
    scenes: list[SceneBreakdown] = []
    for i, w in enumerate(wheres):
        if scenes and scenes[-1].location == w:
            prev = scenes[-1]
            scenes[-1] = SceneBreakdown(prev.scene_id, (prev.event_span[0], i + 1), w)
        else:
            scenes.append(SceneBreakdown(f"s{len(scenes) + 1}", (i, i + 1), w))
    return scenes


class IRBuilder:
    """决策卡 + kernel 事件流 → NarrativeIR（决策2，规则化零 LLM）。

    kernel 只需支持 query_world("all_events") / query_world("current_state")
    （Kernel syscall 的鸭子类型，不为类型标注引入 kernel 依赖）。
    """

    def __init__(self, kernel, bundle: GenreBundle):
        self.kernel = kernel
        self.bundle = bundle

    def build(self, decision_card, chapter: int) -> NarrativeIR:
        # all_events 含已回滚时间线，只取 active 事件（同 decision.py _pacing_feedback）
        active = [e for e in self.kernel.query_world("all_events")
                  if e.get("active", True)]
        start, end = _chapter_slice(active, chapter)
        chapter_evs = active[start:end]
        wheres = self._where_per_event(active, start, end)
        return NarrativeIR(
            beats=_beat_irs(decision_card),
            events=[self._event_ir(e, w, chapter)
                    for e, w in zip(chapter_evs, wheres)],
            dialogue_lines=[d for d in (self._dialogue_ir(e) for e in chapter_evs)
                            if d is not None],
            scene_breakdown=_scene_breakdown(wheres),
            texture=resolve_texture(self.bundle),
        )

    # ---------- events → EventIR 5W ----------
    def _where_per_event(self, active: list[dict], start: int, end: int) -> list[str]:
        """本章每个事件「事件时刻」的 at(who) 位置（与本章事件一一对齐）。

        规则：从全量 active 事件流前向 fold effects 里的 at(who,place)
        set/unset_fluents（事件自身 effects 在其时刻之后才生效）；全日志从未被
        at() effect 触碰的 agent 退回当前 physical projection（覆盖 seed 进
        初始状态的静态位置，如 SEED_PHYSICAL）；再取不到 → "unknown"。
        """
        moved: set[str] = set()
        for e in active:
            eff = (e.get("payload") or {}).get("effects") or {}
            for f in (eff.get("set_fluents") or []) + (eff.get("unset_fluents") or []):
                m = _AT_RE.match(str(f))
                if m:
                    moved.add(m.group(1))
        loc: dict[str, str] = {}
        state = self.kernel.query_world("current_state")
        for f, v in (getattr(state, "physical", None) or {}).items():
            m = _AT_RE.match(str(f))
            if v and m and m.group(1) not in moved:
                loc[m.group(1)] = m.group(2)
        out: list[str] = []
        for i, e in enumerate(active):
            if i >= end:
                break
            p = e.get("payload") or {}
            if i >= start:
                out.append(loc.get(p.get("agent", "world"), "unknown"))
            eff = p.get("effects") or {}
            for f in eff.get("unset_fluents") or []:
                m = _AT_RE.match(str(f))
                if m and loc.get(m.group(1)) == m.group(2):
                    del loc[m.group(1)]
            for f in eff.get("set_fluents") or []:
                m = _AT_RE.match(str(f))
                if m:
                    loc[m.group(1)] = m.group(2)
        return out

    def _event_ir(self, e: dict, where: str, chapter: int) -> EventIR:
        p = e.get("payload") or {}
        # did：payload 的 action 关键词优先；缺失/未收录（回退 act:unknown）时
        # 退回 event_type（types.py EventType 7 值在 CONCEPT_IDS 已全覆盖）
        action = p.get("action")
        did = to_concept_id(action) if isinstance(action, str) else "act:unknown"
        if did == "act:unknown":
            did = to_concept_id(e.get("event_type", ""))
        return EventIR(
            who=p.get("agent", "world"),
            did=did,
            to_whom=p.get("target"),
            where=where,
            when=p.get("story_time") or f"chapter_{chapter}",
            how=p.get("manner"),
            why=p.get("motivation"),
            subtext=None,  # 本期不做潜台词推断（决策2 从简；留待后续 realizer 侧任务）
        )

    def _dialogue_ir(self, e: dict) -> DialogueIR | None:
        """对话 payload → DialogueIR；无对话字段 → None（汇总后为空表）。

        现状说明（决策2 认可的简化）：CharacterActor 提交的 character_action
        payload（agent/action/summary/serves_goal/motivation/effects/chapter）
        不带 dialogue/says 字段，全代码库亦无 event_type="dialogue" 的提交，
        故实际产出目前恒为空表。字段存在时的 Speech Act / politeness / register
        走默认推断规则（零 LLM），content/emotion 用 to_concept_id。
        """
        p = e.get("payload") or {}
        text = p.get("dialogue") or p.get("says")
        if not text:
            return None
        return DialogueIR(
            speaker=p.get("speaker") or p.get("agent", "world"),
            illocution="assert",
            content_concept=to_concept_id(str(p.get("action") or text)),
            emotion_concept=to_concept_id(str(p.get("emotion", "")), kind="emo"),
            politeness="positive",
            register="dialogue_register",
        )


def _beat_irs(decision_card) -> list[BeatIR]:
    """决策卡 beats → BeatIR；decision_card 兼容 DecisionCard 对象与 dict"""
    if isinstance(decision_card, dict):
        beats = decision_card.get("beats") or []
        target_arc = decision_card.get("target_arc", "")
    else:
        beats = decision_card.beats
        target_arc = decision_card.target_arc
    return [
        BeatIR(
            beat_id=str(b.get("beat_id", f"b{i + 1}")),
            phase=b.get("micro_phase") or b.get("phase", ""),
            primitives=list(b.get("primitives") or []),
            emotion_target=target_arc,
            tension=float(b.get("tension", 0.5)),
        )
        for i, b in enumerate(beats)
    ]
