"""Evaluator 子包 — Self-Evaluator（蓝图 Module 6，横切关注点）

Phase 4 实现（独立层，P4.5 才接线 engine）：
  types_eval    — Gate / Critique / RevisionPlan / ReaderReaction /
                  Version / IterationResult / ScoreReport（蓝图 6.1-6.6）
  process_gates — ProcessGate 过程检查点 L1/L2/L3/L5（规则化，不调 LLM）
  leader        — LeaderArbiter 宪法化优先级仲裁（蓝图 6.3，纯规则）
  reader_proxy  — ReaderProxy 读者代理（蓝图 6.4，行为预测非评分）
  iteration     — IterationController 3 轮 best-of-K 迭代控制器（蓝图 6.5）
  critic_parliament — CriticParliament Critic 议会（蓝图 6.2，串联两阶段）
  presentation_scorer — PresentationScorer 展示层打分（蓝图 6.6，
                  唯一出数字分的地方，分数不影响内部判断）
"""
from .types_eval import (
    Gate, Critique, RevisionPlan, ReaderReaction,
    Version, IterationResult, ScoreReport,
)
from .process_gates import (
    ProcessGate, parse_word_range,
    DEFAULT_WORD_RANGE, PRIMITIVE_MIN_PHASE,
)
from .leader import (
    LeaderArbiter, CONSTITUTIONAL_PRIORITY,
    BLOCKING_DIMENSIONS, ARBITRATION_ORDER,
)
from .reader_proxy import ReaderProxy
from .iteration import IterationController, ChapterSpec
from .critic_parliament import CriticParliament
from .presentation_scorer import (
    PresentationScorer, DIMENSION_WEIGHT_KEYS, NEUTRAL_ENGAGEMENT,
)

__all__ = [
    "Gate", "Critique", "RevisionPlan", "ReaderReaction",
    "Version", "IterationResult", "ScoreReport",
    "ProcessGate", "parse_word_range",
    "DEFAULT_WORD_RANGE", "PRIMITIVE_MIN_PHASE",
    "LeaderArbiter", "CONSTITUTIONAL_PRIORITY",
    "BLOCKING_DIMENSIONS", "ARBITRATION_ORDER",
    "ReaderProxy",
    "IterationController", "ChapterSpec",
    "CriticParliament",
    "PresentationScorer", "DIMENSION_WEIGHT_KEYS", "NEUTRAL_ENGAGEMENT",
]
