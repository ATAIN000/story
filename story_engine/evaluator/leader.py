"""LeaderArbiter — Leader 仲裁器（蓝图 6.3，宪法化优先级）

蓝图 1563-1603 的最小可运行实现（纯规则，不调 LLM）：

- CONSTITUTIONAL_PRIORITY 蓝图 7 维逐字（顺序即优先级，高优先级 FAIL →
  必须修订）。按优先级遍历：verdict==FAIL 且 executable != "no" →
  must_fix 收 fix_directive；executable == "no" → noted 记
  `[无法修复] {dim}: {fix_directive}`（记录但不触发修订）
- blocking 一票否决：前 3 维（setting_consistency/plot_coherence/
  character_motivation）任一 FAIL → True，即使低维度全 PASS 也必须修订。
  P4 决策：executable == "no" 的 FAIL 不 blocking——无法修复的修订
  只记录、不触发回滚（否则永远卡死在该层）
- emotion_arc 插入位置（计划决策2）：插在 character_motivation 之后
  （同属严重级），但不进前 3 blocking 集合——blocking 只取蓝图原文前 3 维
- 不在优先级表中的维度不参与仲裁（蓝图语义：只按表裁决）
"""
from __future__ import annotations

from .types_eval import Critique, RevisionPlan

# 蓝图 CONSTITUTIONAL_PRIORITY 逐字（顺序=优先级；blocking 只取前 3 维）
CONSTITUTIONAL_PRIORITY = [
    "setting_consistency",   # 最高: 设定不一致=致命
    "plot_coherence",        # 情节不连贯=严重
    "character_motivation",  # 动机不合理=严重
    "dialogue_authenticity", # 对话不真实=中等
    "sensory_detail",        # 感官不足=轻微
    "cliche_detection",      # 套路=轻微
    "theme_depth",           # 主题浅=最低
]

# blocking 集合：蓝图原文前 3 维（一票否决）
BLOCKING_DIMENSIONS = frozenset(CONSTITUTIONAL_PRIORITY[:3])

# 仲裁遍历序（计划决策2）：repo 扩展维 emotion_arc 插在 character_motivation
# 之后（同属严重级），但不进 blocking 集合
ARBITRATION_ORDER = list(CONSTITUTIONAL_PRIORITY)
ARBITRATION_ORDER.insert(
    ARBITRATION_ORDER.index("character_motivation") + 1, "emotion_arc")


class LeaderArbiter:
    """宪法化优先级仲裁——纯规则，无状态，不调 LLM"""

    def arbitrate(self, critiques: list[Critique]) -> RevisionPlan:
        must_fix: list[str] = []
        noted: list[str] = []
        for dim in ARBITRATION_ORDER:
            critique = self._find(dim, critiques)
            if critique and critique.verdict == "FAIL":
                if critique.executable != "no":
                    must_fix.append(critique.fix_directive)
                else:
                    noted.append(f"[无法修复] {dim}: {critique.fix_directive}")
        # 高优先级可执行 FAIL 一票否决：即使低维度全 PASS 也必须修订
        blocking = any(
            c.verdict == "FAIL" and c.executable != "no"
            and c.dimension in BLOCKING_DIMENSIONS
            for c in critiques)
        return RevisionPlan(must_fix=must_fix, noted=noted, blocking=blocking)

    @staticmethod
    def _find(dim: str, critiques: list[Critique]) -> Critique | None:
        for c in critiques:
            if c.dimension == dim:
                return c
        return None
