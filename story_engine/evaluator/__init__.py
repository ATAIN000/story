"""Evaluator 子包 — Self-Evaluator（蓝图 Module 6，横切关注点）

Phase 4 P4.1 实现（独立层，P4.5 才接线 engine）：
  types_eval    — Gate / Critique / RevisionPlan / ReaderReaction /
                  Version / IterationResult / ScoreReport（蓝图 6.1-6.6）
  process_gates — ProcessGate 过程检查点 L1/L2/L3/L5（规则化，不调 LLM）

（critic_parliament / leader / reader_proxy / iteration /
  presentation_scorer 为后续任务，本子包暂不包含。）
"""
from .types_eval import (
    Gate, Critique, RevisionPlan, ReaderReaction,
    Version, IterationResult, ScoreReport,
)
from .process_gates import (
    ProcessGate, parse_word_range,
    DEFAULT_WORD_RANGE, PRIMITIVE_MIN_PHASE,
)

__all__ = [
    "Gate", "Critique", "RevisionPlan", "ReaderReaction",
    "Version", "IterationResult", "ScoreReport",
    "ProcessGate", "parse_word_range",
    "DEFAULT_WORD_RANGE", "PRIMITIVE_MIN_PHASE",
]
