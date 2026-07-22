"""宏观叙事规划层子包（Macro Story Planner）

六大组件 dataclass（plan.py）+ 幕结构模板库（templates.py）+ AI 生成器（generator.py）。
设计文档：docs/宏观叙事规划层_设计方案.md
"""
from .plan import (
    Act, ActBeat, ActStructure, ArcCharacter, ArcMilestone, ArcSchedule,
    CentralConflict, EpisodeOutline, ForeshadowBlueprint, ForeshadowThread,
    MacroContext, MacroPlan, PacingCurve, SaliencePoint, StoryBlueprint,
    TensionPoint, ThematicArgument, macro_plan_to_dict,
)
from .templates import TEMPLATES, compute_acts
from .generator import generate_macro_plan

__all__ = [
    # plan.py
    "ThematicArgument", "CentralConflict", "StoryBlueprint",
    "ActBeat", "Act", "ActStructure",
    "EpisodeOutline",
    "ArcMilestone", "ArcCharacter", "ArcSchedule",
    "SaliencePoint", "ForeshadowThread", "ForeshadowBlueprint",
    "TensionPoint", "PacingCurve",
    "MacroPlan", "MacroContext", "macro_plan_to_dict",
    # templates.py
    "TEMPLATES", "compute_acts",
    # generator.py
    "generate_macro_plan",
]
