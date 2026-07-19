"""StoryConfig + UserIntent 数据结构（蓝图 Module 8.1）"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class UserIntent:
    """用户意图 — Meta-Generator 的输入"""
    theme: str = ""                 # "破案/悬疑/武侠/言情/..."
    culture_hint: str = ""          # "中国古风/北欧/..."
    language: str = "zh"
    target_length: int = 12         # 章数
    platform: str = "novel"
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class StoryConfig:
    """三正交轴配置 — 传给 Kernel 初始化整个 pipeline"""
    genre: str
    culture: str
    language: str = "zh"
    target_length: int = 12
    platform: str = "novel"
    evaluation_weights: dict[str, float] = field(default_factory=dict)
    active_critics: list[str] = field(default_factory=list)
    source: str = "rule"            # "rule" / "rag" / "merged"
    matched_template: str = ""      # RAG 命中的模板名（debug 用）

    def to_dict(self) -> dict:
        return {
            "genre": self.genre, "culture": self.culture, "language": self.language,
            "target_length": self.target_length, "platform": self.platform,
            "evaluation_weights": self.evaluation_weights,
            "active_critics": self.active_critics,
            "source": self.source,
            "matched_template": self.matched_template,
        }
