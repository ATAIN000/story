"""RuleConfigurator — 路径 A：决策树配置（蓝图 Module 8 路径 A 兜底）

把 UserIntent 通过硬编码规则映射到 StoryConfig。
适用于：常见需求（已知题材关键词）、RAG 失败时的兜底。
"""
from __future__ import annotations

from ..types_meta import StoryConfig, UserIntent


# 题材关键词 → genre 插件名（蓝图硬编码 3 config 的最小版）
GENRE_KEYWORDS = {
    "mystery":  ["悬疑", "破案", "侦探", "推理", "凶杀", "案件", "公案"],
    "wuxia":    ["江湖", "武林", "武侠", "侠客", "门派", "恩怨"],
    "romance":  ["言情", "爱情", "恋爱", "romance", "才子佳人"],
}

# 文化提示词 → culture 插件名
CULTURE_HINTS = {
    "confucian_officialdom": ["中国古风", "古代中国", "儒家", "公案", "北宋", "唐朝"],
    # "scandinavian_protestant": ["北欧", "维京", "斯堪的纳维亚"],  # 该插件未实现，注释掉
}


def _match_genre(theme: str) -> str:
    theme_lower = theme.lower()
    for genre, kws in GENRE_KEYWORDS.items():
        if any(kw.lower() in theme_lower for kw in kws):
            return genre
    return "mystery"  # 默认


def _match_culture(hint: str) -> str:
    for culture, kws in CULTURE_HINTS.items():
        if any(kw in hint for kw in kws):
            return culture
    return "confucian_officialdom"  # 默认（当前唯一可用插件）


class RuleConfigurator:
    """路径 A：规则决策树配置"""

    def __init__(self, kernel):
        self.kernel = kernel

    def configure(self, intent: UserIntent) -> StoryConfig:
        genre = _match_genre(intent.theme)
        culture = _match_culture(intent.culture_hint)
        language = intent.language or "zh"

        # 组合校验（蓝图 v3.0 赌注2：culture_bound 题材拒绝非法组合）
        self.kernel.registry.validate_combo(genre, culture)

        # 从插件拉取评估权重与 critic 维度（蓝图 v3.0 赌注5）
        genre_manifest = self.kernel.registry.get_manifest("story.genre", genre)
        weights = dict(genre_manifest.params.get("evaluation_weights", {}))
        critics = list(genre_manifest.params.get("active_critics", []))

        return StoryConfig(
            genre=genre, culture=culture, language=language,
            target_length=intent.target_length,
            platform=intent.platform,
            evaluation_weights=weights,
            active_critics=critics,
            source="rule",
        )
