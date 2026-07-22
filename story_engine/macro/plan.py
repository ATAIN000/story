"""宏观叙事规划层 — 六大组件数据类（Macro Story Planner 数据层）

设计文档：docs/宏观叙事规划层_设计方案.md 第 3.3 节。
全部组件是纯数据（dataclass + dict 序列化），不依赖 LLM / kernel。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ============================================================
# 组件 1：Story Blueprint（故事蓝图）
# ============================================================

@dataclass
class ThematicArgument:
    """主题论证：主角从 Lie 到 Truth 的弧线"""
    lie: str = ""
    truth: str = ""
    url: str = ""                       # 反方论点（对手/世界的信念）


@dataclass
class CentralConflict:
    """核心冲突定义"""
    protagonist_want: str = ""          # 表面想要
    protagonist_need: str = ""          # 真实需要
    antagonist_want: str = ""           # 对手想要
    stakes: str = ""                    # 赌注


@dataclass
class StoryBlueprint:
    """故事蓝图：logline + 主题论证 + 核心冲突"""
    logline: str = ""
    thematic_argument: ThematicArgument = field(default_factory=ThematicArgument)
    central_conflict: CentralConflict = field(default_factory=CentralConflict)
    story_type: str = ""                # redemption / revenge / growth / forbidden_love / ...
    total_episodes: int = 12
    target_pace: str = "fast_escalation"   # fast_escalation / slow_burn / wave / ...


# ============================================================
# 组件 2：Act Structure（幕结构映射）
# ============================================================

@dataclass
class ActBeat:
    """单个节拍点"""
    name: str                           # opening_image / midpoint / ...
    ep: str = ""                        # "1" 或 "1-3"（映射后的章节位置）
    desc: str = ""                      # 描述


@dataclass
class Act:
    """一幕/段"""
    id: str                             # act_1_setup / act_2a_rising / ...
    name: str = ""                      # "建置"
    episode_range: list[int] = field(default_factory=list)   # [1, 8]
    function: str = ""                  # 宏观功能
    beats: list[ActBeat] = field(default_factory=list)


@dataclass
class ActStructure:
    """幕结构：模板名 + acts 列表"""
    template: str = "three_act_classic"
    acts: list[Act] = field(default_factory=list)


# ============================================================
# 组件 3：Episode Outlines（分集梗概）
# ============================================================

@dataclass
class EpisodeOutline:
    """单集梗概"""
    episode: int = 1
    synopsis: str = ""
    purpose: str = ""                   # beat 功能标签
    key_events: list[str] = field(default_factory=list)
    ends_with_hook: str = ""
    character_arc_focus: str = ""
    flexibility: str = "medium"         # low / medium / high


# ============================================================
# 组件 4：Arc Schedule（角色弧光里程碑表）
# ============================================================

@dataclass
class ArcMilestone:
    """弧光里程碑"""
    episode_range: str = ""             # "1-3"
    phase: str = ""                     # setup / crack / midpoint_shift / ...
    state: str = ""                     # 当前状态描述
    event: str = ""                     # 触发事件
    behavior: str = ""                  # 预期行为


@dataclass
class ArcCharacter:
    """角色弧光定义 + 里程碑"""
    name: str = ""
    archetype_arc: str = ""             # positive_change / steadfast_positive / ...
    lie: str = ""
    truth: str = ""
    milestones: list[ArcMilestone] = field(default_factory=list)


@dataclass
class ArcSchedule:
    """全角色弧光里程碑表"""
    characters: list[ArcCharacter] = field(default_factory=list)


# ============================================================
# 组件 5：Foreshadow Blueprint（伏笔全局布局图）
# ============================================================

@dataclass
class SaliencePoint:
    """显著度阶梯单点"""
    ep: int = 0
    level: float = 0.0
    form: str = ""


@dataclass
class ForeshadowThread:
    """一条伏笔线"""
    id: str = ""                        # FS_001
    name: str = ""
    type: str = ""                      # main_mystery / subplot / character_secret / ...
    plant_episodes: list[int] = field(default_factory=list)
    harvest_episode: int = 0
    salience_ladder: list[SaliencePoint] = field(default_factory=list)
    spacing_rule: str = ""              # max_5_eps
    status: str = "planned"             # planned / planted / harvested


@dataclass
class ForeshadowBlueprint:
    """伏笔全局布局"""
    threads: list[ForeshadowThread] = field(default_factory=list)


# ============================================================
# 组件 6：Pacing Curve（全书情感强度曲线）
# ============================================================

@dataclass
class TensionPoint:
    """张力锚点"""
    episode: int = 0
    tension: float = 0.0
    reason: str = ""


@dataclass
class PacingCurve:
    """节奏曲线"""
    curve_type: str = "wave_escalation"    # linear / wave / wave_escalation / dtg_staircase / custom
    key_tension_points: list[TensionPoint] = field(default_factory=list)
    genre_pace_profile: dict[str, Any] = field(default_factory=dict)


# ============================================================
# 顶层：MacroPlan
# ============================================================

@dataclass
class MacroPlan:
    """宏观计划（六大组件聚合体）"""
    blueprint: StoryBlueprint = field(default_factory=StoryBlueprint)
    act_structure: ActStructure = field(default_factory=ActStructure)
    episode_outlines: list[EpisodeOutline] = field(default_factory=list)
    arc_schedule: ArcSchedule = field(default_factory=ArcSchedule)
    foreshadow_blueprint: ForeshadowBlueprint = field(default_factory=ForeshadowBlueprint)
    pacing_curve: PacingCurve = field(default_factory=PacingCurve)
    revision_log: list[dict[str, Any]] = field(default_factory=list)


# ============================================================
# 注入用：MacroContext（每章注入 DecisionCard 的宏观上下文）
# ============================================================

@dataclass
class MacroContext:
    """每章注入决策卡的宏观上下文（设计文档 4.3 节）"""
    act: str = ""
    beat: str = ""
    beat_description: str = ""
    beat_position: str = ""
    episode_synopsis: str = ""
    arc_directives: list[dict[str, Any]] = field(default_factory=list)
    foreshadow_directives: list[dict[str, Any]] = field(default_factory=list)
    pacing_directive: dict[str, Any] = field(default_factory=dict)
    key_events_required: list[str] = field(default_factory=list)


# ============================================================
# 序列化辅助：dataclass → dict / dict → dataclass
# ============================================================

def _to_dict(obj: Any) -> Any:
    """递归将 dataclass 转为 dict（兼容普通 dict/list/标量）"""
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _to_dict(v) for k, v in obj.__dict__.items()}
    if isinstance(obj, list):
        return [_to_dict(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    return obj


def macro_plan_to_dict(plan: MacroPlan) -> dict:
    """MacroPlan → 可序列化 dict（落盘 macro_plan.json）"""
    return _to_dict(plan)
