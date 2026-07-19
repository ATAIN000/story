"""Showrunner 子包 — 多轨道调度器（Module 3）

公开 API（沿用 Phase 1 kernel shim 模式，外部 import 零改动）：
  Showrunner            — 调度器，10 步 control loop 生成决策卡
  DecisionCard          — 每集决策卡
  Track                 — 叙事轨道
  ForeshadowPoolManager — CFPG 伏笔池管理（容量/老化/排队）
  STERNBERG_MODES / TODOROV_PHASES — 理论常量
  PacingEngine / PacingScore    — P3.4 节奏量化（Module 3.3 五信息论指标）
"""
from .tracks import Track, ForeshadowPoolManager
from .decision import (
    DecisionCard, Showrunner,
    STERNBERG_MODES, TODOROV_PHASES, GAP_TEMPLATES,
)
from .pacing import PacingEngine, PacingScore

__all__ = [
    "Showrunner", "DecisionCard", "Track", "ForeshadowPoolManager",
    "STERNBERG_MODES", "TODOROV_PHASES", "GAP_TEMPLATES",
    "PacingEngine", "PacingScore",
]
