"""Narrative 子包 — Module 5 叙事化层（Phase 5）

P5.1 第一批：分层 IR 类型 + 本地概念映射表。
P5.2 第二批：IRBuilder（决策卡 + 事件流 → NarrativeIR，规则化零 LLM）。
P5.3 第三批：Fabula/Sjuzhet 分离（真值层/呈现层，规则化零 LLM）。
P5.4 第四批：Realizer 共创者（zh/en）+ Narrativizer + humanize（1 次 LLM）。
"""
from .ir import (
    IntentIR, BeatIR, EventIR, SubtextInterlingua, DialogueIR,
    TextureParams, SceneBreakdown, NarrativeIR,
    CONCEPT_IDS, INTERLINGUA_ZH, INTERLINGUA_EN, to_concept_id,
)
from .ir_builder import IRBuilder, TEXTURE_DEFAULTS, resolve_texture
from .fabula_sjuzhet import Fabula, Sjuzhet, FabulaBuilder, SjuzhetSelector
from .realizer import (
    LanguageRealizer, ChineseRealizer, EnglishRealizer, Narrativizer,
)
from .humanize import (
    AI_ISMS_ZH, AI_ISMS_EN, _filter_ai_isms, _inject_imperfection,
)

__all__ = [
    "IntentIR", "BeatIR", "EventIR", "SubtextInterlingua", "DialogueIR",
    "TextureParams", "SceneBreakdown", "NarrativeIR",
    "CONCEPT_IDS", "INTERLINGUA_ZH", "INTERLINGUA_EN", "to_concept_id",
    "IRBuilder", "TEXTURE_DEFAULTS", "resolve_texture",
    "Fabula", "Sjuzhet", "FabulaBuilder", "SjuzhetSelector",
    "LanguageRealizer", "ChineseRealizer", "EnglishRealizer", "Narrativizer",
    "AI_ISMS_ZH", "AI_ISMS_EN", "_filter_ai_isms", "_inject_imperfection",
]
