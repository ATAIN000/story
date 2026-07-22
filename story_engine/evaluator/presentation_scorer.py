"""PresentationScorer — 展示层打分（蓝图 6.6）

蓝图 1699-1729 的最小可运行实现（独立层，P4.5 才接线 engine）：

铁律（蓝图 6.6 卷首）：这是唯一出数字分的地方——ScoreReport 只是给用户看的
展示层聚合，分数绝不影响内部判断（内部 critic/Leader 链路只看 verdict，
从不消费数字分）。

与蓝图原文的差异（均已确认，注释在对应代码处）：
- 蓝图 critic_pass_rate 硬写 f"{passed}/7"；此处 total 用实际评估的维度数
  （emotion_arc 扩展时可能是 /8），无 critiques 时回退蓝图默认 7
- 权重读 genre params 的 evaluation_weights（**中文键**：情节连贯/角色动机/
  设定一致性/对话真实度/感官细节/套路检测/主题深度），en↔zh 映射表写在本文件
- emotion_arc 不在权重表 → 展示分只算蓝图 7 维（emotion_arc 的 critique
  计入 critic_pass_rate 的实际评估数，但不进 dimensions/overall）
"""
from __future__ import annotations

from .critic_parliament import ALL_DIMENSIONS
from .types_eval import Critique, ScoreReport

# 空 reader 曲线的中性 engagement 兜底（1-5 量表取中位）
NEUTRAL_ENGAGEMENT = 3.0

# 蓝图 7 英文维度 → evaluation_weights 中文键（mystery.yaml params 逐字）
DIMENSION_WEIGHT_KEYS = {
    "plot_coherence": "情节连贯",
    "character_motivation": "角色动机",
    "setting_consistency": "设定一致性",
    "dialogue_authenticity": "对话真实度",
    "sensory_detail": "感官细节",
    "cliche_detection": "套路检测",
    "theme_depth": "主题深度",
}


class PresentationScorer:
    """展示层打分器——从内部 critic verdict 聚合数字分（给用户看）

    genre_params: 题材插件 params dict（读其中 evaluation_weights 中文键权重；
        权重和不为 1 时归一化；整表缺失时 7 维等权兜底）
    """

    def __init__(self, genre_params: dict | None = None):
        self._weights = self._load_weights(genre_params or {})

    def score(self, critiques: list[Critique],
              reader_curves: dict | None) -> ScoreReport:
        # 聚合：X/N critic 通过（蓝图写 /7；N=实际评估的维度数，
        # emotion_arc 扩展时可能 /8——与蓝图「X/7」的差异在此）
        passed = sum(1 for c in critiques if c.verdict == "PASS")
        evaluated = {c.dimension for c in critiques}
        total = len(evaluated) if evaluated else len(ALL_DIMENSIONS)

        # 7 维展示分：verdict 映射（PASS→1.0 / FAIL→0.0）；
        # 无 critique 的维度 → 0.5 记「未评估」（展示层简化，
        # 串联模式下 judge 未标记的维度本就没有 critic 精审）
        # 修复 2026-07-22：原 1.0 导致空 critiques 时 overall 虚假满分；
        # 改为 0.5（中性）使 overall 反映真实评估状态
        dimensions: dict[str, float] = {d: 0.5 for d in ALL_DIMENSIONS}
        for c in critiques:
            if c.dimension in dimensions:
                dimensions[c.dimension] = 1.0 if c.verdict == "PASS" else 0.0
            # emotion_arc 等扩展维不在蓝图 7 维展示分内（权重表无对应中文键）

        # 类型相关权重（genre 插件中文键 → en 维度，已在构造期归一化）
        overall = sum(self._weights[d] * dimensions[d] for d in dimensions)

        # 读者反应曲线健康度（空曲线 → 中性 3.0）
        curve = (reader_curves or {}).get("engagement") or []
        engagement = (sum(curve) / len(curve)) if curve else NEUTRAL_ENGAGEMENT

        return ScoreReport(
            overall=overall,
            dimensions=dimensions,
            critic_pass_rate=f"{passed}/{total}",
            reader_engagement=engagement,
        )

    @staticmethod
    def _load_weights(genre_params: dict) -> dict[str, float]:
        """中文键 evaluation_weights → en 维度权重；权重和不为 1 时归一化。

        权重表缺失/全空 → 7 维等权兜底（展示分无类型偏好时的中性默认）；
        表中缺某个中文键 → 该维权重 0（不参与 overall）。
        """
        raw = genre_params.get("evaluation_weights") or {}
        weights = {en: float(raw.get(zh, 0.0) or 0.0)
                   for en, zh in DIMENSION_WEIGHT_KEYS.items()}
        total = sum(weights.values())
        if total <= 0:
            equal = 1.0 / len(DIMENSION_WEIGHT_KEYS)
            return {d: equal for d in DIMENSION_WEIGHT_KEYS}
        return {d: w / total for d, w in weights.items()}
