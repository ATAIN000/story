"""evaluator 类型层 — Module 6 Self-Evaluator 核心数据类型（蓝图 6.1-6.6）

核心区分（蓝图 Module 6 卷首）：自评器是内部控制信号（驱动生成-修正闭环），
不是外部打分。内部从不出数字分数，只输出 verdict + quote + fix_directive；
ScoreReport 只是给用户看的展示层聚合。

本文件只定义类型；critic_parliament / leader / reader_proxy / iteration /
presentation_scorer 的行为实现是 Phase 4 后续任务。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Critique:
    """单维度 critic 结论（蓝图 6.2 字段逐字）"""
    dimension: str
    verdict: str               # PASS / FAIL
    evidence: list[str]        # quote-backed！无引用直接丢弃（防 CriticGPT 幻觉）
    fix_directive: str         # 具体修改指令
    executable: str            # yes / no / partial（在 generator 能力内吗？）
    confidence: str = "low"    # 共振加权用（P4 决策1：只增字段，不破坏蓝图字段）


@dataclass
class Gate:
    """过程 Gate 结果（蓝图 6.1：每层 binary pass/fail，FAIL 回滚该层）"""
    layer: str                 # "L1"/"L2"/"L3"/"L5"（蓝图 6.1 原文无 L4，不臆造）
    passed: bool
    failures: dict             # {check_name: reason}


@dataclass
class RevisionPlan:
    """Leader 仲裁输出（蓝图 6.3）"""
    must_fix: list[str] = field(default_factory=list)
    noted: list[str] = field(default_factory=list)
    blocking: bool = False


@dataclass
class ReaderReaction:
    """读者代理反应（蓝图 6.4 prompt 的 4 问 + 跳过点；行为预测非评分）"""
    continue_reading: bool = True
    favorite_character: str = ""
    prediction: str = ""
    tension: int = 3
    curiosity: int = 3
    engagement: int = 3
    skip_point: str = ""


@dataclass
class Version:
    """迭代控制器的一轮版本（蓝图 6.5；P4 决策1 附加 gates 字段，只增）"""
    round: int
    text: str
    critiques: list[Critique] = field(default_factory=list)
    revision: RevisionPlan | None = None
    gates: list[Gate] = field(default_factory=list)


@dataclass
class IterationResult:
    """3 轮 best-of-K 迭代结果（蓝图 6.5：保留所有版本，best 不是最后一版）"""
    best: Version
    all_versions: list[Version] = field(default_factory=list)


@dataclass
class ScoreReport:
    """外部打分（蓝图 6.6 展示层 — 从内部 critic verdict 聚合，内部从不使用）"""
    overall: float = 0.0
    dimensions: dict[str, float] = field(default_factory=dict)
    critic_pass_rate: str = "0/7"
    reader_engagement: float = 0.0
