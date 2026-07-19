"""Creativity 子包 — Module 4 叙事原语层 + HTN 意图规划器（Phase 3）"""
from .primitives import (
    StateView,
    Conflict, Suspense, TurningPoint, Revelation,
    Sacrifice, Betrayal, Recognition, GoalFormation,
    ALL_PRIMITIVES, PrimitiveComposite,
)
from .planner import (
    AuthorIntent, NarrativePlanner,
    state_view_from_world, apply_delta_to_view,
    TODOROV_PHASES, DEFAULT_PHASE_BEATS, PRIMITIVE_TABLE,
)
from .blending import ConceptualBlending, CreativeSeed

__all__ = [
    "ConceptualBlending", "CreativeSeed",
    "StateView",
    "Conflict", "Suspense", "TurningPoint", "Revelation",
    "Sacrifice", "Betrayal", "Recognition", "GoalFormation",
    "ALL_PRIMITIVES", "PrimitiveComposite",
    "AuthorIntent", "NarrativePlanner",
    "state_view_from_world", "apply_delta_to_view",
    "TODOROV_PHASES", "DEFAULT_PHASE_BEATS", "PRIMITIVE_TABLE",
]
