"""VoiceProfile — 角色声音档案（Module 2.5）+ 反思机制（Module 2.4）

蓝图 docs/Story_Engine_工程蓝图.md:846-877。
声音档案由 Culture+Language 插件参数化，不在内核硬编码。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class VoiceProfile:
    """角色声音档案 — 由 Culture + Language 插件参数化"""
    speaker_id: str
    sentence_length: tuple[float, float] = (12.0, 4.0)   # (均值, 方差)
    formality_ratio: dict[str, float] = field(
        default_factory=lambda: {"文言": 0.3, "白话": 0.7})
    catchphrases: list[str] = field(default_factory=list)
    rhetoric_preferences: list[str] = field(default_factory=list)
    forbidden_words: list[str] = field(default_factory=lambda: [
        "啊这", "确实", "拉满", "拿捏", "破防", "emo",
    ])
    emotional_baseline: str = "沉静"
    voice_hint: str = ""   # 自然语言描述，注入 propose prompt

    def to_dict(self) -> dict:
        return asdict(self)

    def prompt_snippet(self) -> str:
        """注入 SOAR propose 的简短声音约束"""
        parts = [f"说话风格：{self.voice_hint or self.emotional_baseline}"]
        if self.catchphrases:
            parts.append(f"口头禅：{'、'.join(self.catchphrases[:3])}")
        if self.forbidden_words:
            parts.append(f"禁用词：{'、'.join(self.forbidden_words[:5])}")
        return "；".join(parts)

    @classmethod
    def from_seed(cls, character_id: str, seed: dict[str, Any] | None = None) -> "VoiceProfile":
        """从 mock_script.SEED_CHARACTERS 风格的 dict 生成"""
        seed = seed or {}
        voice = seed.get("voice", "")
        archetype = seed.get("archetype", "")
        return cls(
            speaker_id=character_id,
            voice_hint=voice or f"{archetype}口吻",
            emotional_baseline=voice.split("，")[0] if voice else "沉静",
            catchphrases=list(seed.get("catchphrases", [])),
        )

    @classmethod
    def from_plugins(
        cls,
        archetype: str,
        culture_params: dict | None = None,
        language: str = "zh",
        character_id: str = "",
    ) -> "VoiceProfile":
        """从文化+语言插件生成声音档案（蓝图 2.5 工厂）"""
        culture_params = culture_params or {}
        mapping = culture_params.get("archetype_mapping", {})
        mapped = mapping.get(archetype, archetype)
        catchphrases = []
        if hasattr(culture_params.get("catchphrases"), "__iter__"):
            catchphrases = list(culture_params.get("catchphrases") or [])
        # 评书文化偏好：文言比例偏高
        formality = {"文言": 0.4, "白话": 0.6} if language == "zh" else {"formal": 0.5, "casual": 0.5}
        return cls(
            speaker_id=character_id or archetype,
            formality_ratio=formality,
            catchphrases=catchphrases[:5],
            emotional_baseline=str(mapped),
            voice_hint=f"{mapped}风格",
        )


# 反思触发阈值（generative_agents 朴素阈值）
REFLECTION_IMPORTANCE_THRESHOLD = 150  # 累积 importance 达此值触发反思
REFLECTION_COUNT_THRESHOLD = 8         # 或 episodic 条数达此值


@dataclass
class ReflectionTrigger:
    """反思触发器状态"""
    accumulated_importance: int = 0
    event_count: int = 0

    def observe(self, importance: int) -> bool:
        """记录一次事件；返回是否应触发反思"""
        self.accumulated_importance += max(1, importance)
        self.event_count += 1
        return (
            self.accumulated_importance >= REFLECTION_IMPORTANCE_THRESHOLD
            or self.event_count >= REFLECTION_COUNT_THRESHOLD
        )

    def reset(self) -> None:
        self.accumulated_importance = 0
        self.event_count = 0
