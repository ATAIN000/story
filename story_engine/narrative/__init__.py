"""Narrative 子包 — Module 5 叙事化层（Phase 5）

P5.1 第一批：分层 IR 类型 + 本地概念映射表。
P5.2 第二批：IRBuilder（决策卡 + 事件流 → NarrativeIR，规则化零 LLM）。
（fabula_sjuzhet / realizer / humanize 为后续任务。）
"""
from .ir import (
    IntentIR, BeatIR, EventIR, SubtextInterlingua, DialogueIR,
    TextureParams, SceneBreakdown, NarrativeIR,
    CONCEPT_IDS, INTERLINGUA_ZH, INTERLINGUA_EN, to_concept_id,
)
from .ir_builder import IRBuilder, TEXTURE_DEFAULTS, resolve_texture

__all__ = [
    "IntentIR", "BeatIR", "EventIR", "SubtextInterlingua", "DialogueIR",
    "TextureParams", "SceneBreakdown", "NarrativeIR",
    "CONCEPT_IDS", "INTERLINGUA_ZH", "INTERLINGUA_EN", "to_concept_id",
    "IRBuilder", "TEXTURE_DEFAULTS", "resolve_texture",
]
