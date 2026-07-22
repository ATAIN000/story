"""worldview 子包 — 世界观 10 层架构（批1：L0-L3）

Phase 12.1 实现：
  layers     — L0-L3 全量参数（31 个，枚举值+中文标签+连锁影响）
  predicates — L0-L3 跨层一致性谓词（44 条）+ evaluate 纯函数
  profile    — WorldviewProfile + to_prompt_text + to_world_rules

素材唯一来源：docs/世界观架构_参数全表.md（逐条录入，不臆造）。
"""
from .layers import (LAYERS, LANGUAGE_LAYERS, ALL_PARAMS, LAYER_BY_ID,
                     param_values, option_label)
from .predicates import PREDICATES, evaluate
from .profile import WorldviewProfile
from .presets import PRESETS, PRESET_BY_KEY, preset_summaries

__all__ = [
    "LAYERS", "LANGUAGE_LAYERS", "ALL_PARAMS", "LAYER_BY_ID",
    "param_values", "option_label",
    "PREDICATES", "evaluate",
    "WorldviewProfile",
    "PRESETS", "PRESET_BY_KEY", "preset_summaries",
]
