"""MetaGenerator — Module 8 三路并行配置（蓝图 Module 8.1）

不是生成故事，是生成「故事生成器配置」：
UserIntent → StoryConfig(Genre×Culture×Language) → pipeline

三路：
  A. RuleConfigurator — 规则决策树（兜底）
  B. RAGCombinator    — 检索最相似插件模板（常见需求）
  C. DomainLearner    — 从语料 learn（Phase 3+，本次跳过）

合并策略（_merge）：
  - 路径 B 命中（score>0）优先；B 失败或非法组合时 fallback 到 A
"""
from __future__ import annotations

from ..types_meta import StoryConfig, UserIntent
from .rule_configurator import RuleConfigurator
from .rag_combinator import RAGCombinator


class MetaGenerator:
    def __init__(self, kernel):
        self.kernel = kernel
        self.rule_configurator = RuleConfigurator(kernel)
        self.rag_combinator = RAGCombinator(kernel)
        # 路径 C（DomainLearner）是 Phase 3+ 任务，本次跳过

    async def generate_config(self, intent: UserIntent) -> StoryConfig:
        # 路径 A：规则兜底（必返回）
        config_a = self.rule_configurator.configure(intent)

        # 路径 B：RAG 检索最相似模板
        config_b = None
        try:
            config_b = self.rag_combinator.retrieve(intent)
        except Exception:
            config_b = None

        return self._merge(config_a, config_b)

    @staticmethod
    def _merge(config_a: StoryConfig, config_b: StoryConfig | None) -> StoryConfig:
        """合并：RAG 命中优先；否则回退规则"""
        if config_b is None:
            return config_a
        # 标记来源是 merged（两路都跑了）
        merged = StoryConfig(
            genre=config_b.genre,
            culture=config_b.culture,
            language=config_b.language,
            target_length=config_b.target_length,
            platform=config_b.platform,
            evaluation_weights=config_b.evaluation_weights or config_a.evaluation_weights,
            active_critics=config_b.active_critics or config_a.active_critics,
            source="merged",
            matched_template=config_b.matched_template,
        )
        return merged
