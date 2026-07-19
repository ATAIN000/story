"""Evaluator 子包 — Self-Evaluator（蓝图 Module 6，横切关注点）

Phase 4 实现（独立层，P4.5 才接线 engine）：
  types_eval    — Gate / Critique / RevisionPlan / ReaderReaction /
                  Version / IterationResult / ScoreReport（蓝图 6.1-6.6）
  process_gates — ProcessGate 过程检查点 L1/L2/L3/L5（规则化，不调 LLM）
  leader        — LeaderArbiter 宪法化优先级仲裁（蓝图 6.3，纯规则）
  reader_proxy  — ReaderProxy 读者代理（蓝图 6.4，行为预测非评分）

（iteration / presentation_scorer 为后续任务，本子包暂不包含。）
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

__all__ = [
    "Gate", "Critique", "RevisionPlan", "ReaderReaction",
    "Version", "IterationResult", "ScoreReport",
    "ProcessGate", "parse_word_range",
    "DEFAULT_WORD_RANGE", "PRIMITIVE_MIN_PHASE",
    "LeaderArbiter", "CONSTITUTIONAL_PRIORITY",
    "BLOCKING_DIMENSIONS", "ARBITRATION_ORDER",
    "ReaderProxy",
]
