"""worldview presets — 十骨架经典世界观预设（P12.4）

10 个经典叙事骨架的完整 L0-L3 世界观档案。每个 preset 填满全部 31 个参数，
所有取值均为 :data:`layers.ALL_PARAMS` 中登记的合法枚举值，且通过
:func:`predicates.evaluate` 无违例。

骨架灵感来源：task brief 表格（非逐字，是合理推演），参数组合忠实于
``docs/世界观架构_参数全表.md`` 的连锁约束。

字段说明::

    {
      "key":   骨架 slug（API 引用名），
      "name":  中文名，
      "vibe":  一句话气质（前端展示用），
      "params": {<param_key>: <enum_value>, ...}  # 31 个参数全填
    }
"""
from __future__ import annotations

PRESETS: list[dict] = [
    # ---------------------------------------------------------------- 1
    {
        "key": "hard_reality",
        "name": "现实本格",
        "vibe": "严格遵循现实物理的纯粹现实世界，悬疑/本格推理的底座。",
        "params": {
            # L0
            "physics_deviation": "none",
            "metaphysics": "materialist",
            "time_structure": "linear",
            "space_structure": "3d_standard",
            "causality": "deterministic",
            "consciousness_nature": "emergent",
            "information_laws": "conserved",
            "entropy_law": "standard",
            # L1
            "cosmo_scope": "universal",
            "cosmo_mutability": "immutable",
            "divine_nature": "absent",
            "cosmo_cognition": "known",
            "origin_type": "evolution",
            "eschatology": "heat_death",
            "plane_structure": "single",
            "destiny_mechanism": "none",
            # L2
            "terrain_paradigm": "earthlike",
            "gravity_atmosphere": "standard",
            "resource_paradigm": "energy",
            "magical_geography": "none",
            "environmental_hazards": "natural_only",
            "celestial_bodies": "standard",
            "infrastructure_level": "developed",
            # L3
            "power_existence": "nonexistent",
            "power_source": "internal",
            "acquisition_method": "innate",
            "cost_structure": "physical_fatigue",
            "progression_model": "none",
            "system_transparency": "hard",
            "power_interaction": "single",
            "power_regulation": "integrated",
        },
    },
    # ---------------------------------------------------------------- 2
    {
        "key": "xianxia_cultivation",
        "name": "修真问道",
        "vibe": "灵气为第五基本力，逆天改命、飞升长生的修仙宇宙。",
        "params": {
            # L0
            "physics_deviation": "major",
            "metaphysics": "dualist",
            "time_structure": "linear",
            "space_structure": "foldable",
            "causality": "intentional",
            "consciousness_nature": "soul_based",
            "information_laws": "conserved",
            "entropy_law": "reversed",
            # L1
            "cosmo_scope": "universal",
            "cosmo_mutability": "mutable_force",
            "divine_nature": "ascended",
            "cosmo_cognition": "partially_known",
            "origin_type": "creation",
            "eschatology": "transcendence",
            "plane_structure": "nested",
            "destiny_mechanism": "threads",
            # L2
            "terrain_paradigm": "earthlike",
            "gravity_atmosphere": "supernatural_atmosphere",
            "resource_paradigm": "energy",
            "magical_geography": "ley_lines",
            "environmental_hazards": "magical_storms",
            "celestial_bodies": "standard",
            "infrastructure_level": "magical",
            # L3
            "power_existence": "common",
            "power_source": "external_environmental",
            "acquisition_method": "cultivation",
            "cost_structure": "consumption",
            "progression_model": "realm_breakthrough",
            "system_transparency": "semi_hard",
            "power_interaction": "hierarchical",
            "power_regulation": "self_regulated",
        },
    },
    # ---------------------------------------------------------------- 3
    {
        "key": "wuxia_jianghu",
        "name": "武侠江湖",
        "vibe": "内力为尊、恩怨分明，没有天花板的武学江湖。",
        "params": {
            # L0
            "physics_deviation": "minor",
            "metaphysics": "materialist",
            "time_structure": "linear",
            "space_structure": "3d_standard",
            "causality": "deterministic",
            "consciousness_nature": "emergent",
            "information_laws": "conserved",
            "entropy_law": "standard",
            # L1
            "cosmo_scope": "regional",
            "cosmo_mutability": "immutable",
            "divine_nature": "absent",
            "cosmo_cognition": "known",
            "origin_type": "evolution",
            "eschatology": "unknown",
            "plane_structure": "single",
            "destiny_mechanism": "threads",
            # L2
            "terrain_paradigm": "earthlike",
            "gravity_atmosphere": "standard",
            "resource_paradigm": "land",
            "magical_geography": "none",
            "environmental_hazards": "natural_only",
            "celestial_bodies": "standard",
            "infrastructure_level": "basic",
            # L3
            "power_existence": "common",
            "power_source": "internal",
            "acquisition_method": "cultivation",
            "cost_structure": "physical_fatigue",
            "progression_model": "skill_tree",
            "system_transparency": "hard",
            "power_interaction": "single",
            "power_regulation": "self_regulated",
        },
    },
    # ---------------------------------------------------------------- 4
    {
        "key": "cthulhu_mythos",
        "name": "克苏鲁神话",
        "vibe": "宇宙级冷漠与不可名状的禁忌知识，理性在恐惧前崩溃。",
        "params": {
            # L0
            "physics_deviation": "minor",
            "metaphysics": "custom",
            "time_structure": "linear",
            "space_structure": "non_euclidean",
            "causality": "chaotic",
            "consciousness_nature": "fundamental",
            "information_laws": "supernatural",
            "entropy_law": "standard",
            # L1
            "cosmo_scope": "universal",
            "cosmo_mutability": "immutable",
            "divine_nature": "unknowable",
            "cosmo_cognition": "unknown",
            "origin_type": "mythic",
            "eschatology": "unknown",
            "plane_structure": "dual",
            "destiny_mechanism": "none",
            # L2
            "terrain_paradigm": "earthlike",
            "gravity_atmosphere": "standard",
            "resource_paradigm": "information",
            "magical_geography": "cursed_lands",
            "environmental_hazards": "dimensional_incursions",
            "celestial_bodies": "standard",
            "infrastructure_level": "basic",
            # L3
            "power_existence": "rare",
            "power_source": "knowledge_based",
            "acquisition_method": "study",
            "cost_structure": "backlash",
            "progression_model": "horizontal",
            "system_transparency": "mystery",
            "power_interaction": "single",
            "power_regulation": "unregulated",
        },
    },
    # ---------------------------------------------------------------- 5
    {
        "key": "cyberpunk",
        "name": "赛博朋克",
        "vibe": "高科技低生活，巨头垄断与数据洪流中的霓虹废墟。",
        "params": {
            # L0
            "physics_deviation": "minor",
            "metaphysics": "materialist",
            "time_structure": "linear",
            "space_structure": "networked",
            "causality": "deterministic",
            "consciousness_nature": "substrate_independent",
            "information_laws": "destroyable",
            "entropy_law": "standard",
            # L1
            "cosmo_scope": "regional",
            "cosmo_mutability": "immutable",
            "divine_nature": "absent",
            "cosmo_cognition": "partially_known",
            "origin_type": "evolution",
            "eschatology": "entropy_death",
            "plane_structure": "single",
            "destiny_mechanism": "threads",
            # L2
            "terrain_paradigm": "earthlike",
            "gravity_atmosphere": "toxic",
            "resource_paradigm": "information",
            "magical_geography": "none",
            "environmental_hazards": "environmental_decay",
            "celestial_bodies": "standard",
            "infrastructure_level": "cyberpunk",
            # L3
            "power_existence": "common",
            "power_source": "mixed",
            "acquisition_method": "mutation",
            "cost_structure": "addiction",
            "progression_model": "skill_tree",
            "system_transparency": "hard",
            "power_interaction": "stackable",
            "power_regulation": "government_regulated",
        },
    },
    # ---------------------------------------------------------------- 6
    {
        "key": "western_fantasy",
        "name": "西幻史诗",
        "vibe": "众神创世、魔力涌动，魔法学院与英雄宿命交织的史诗大陆。",
        "params": {
            # L0
            "physics_deviation": "minor",
            "metaphysics": "dualist",
            "time_structure": "linear",
            "space_structure": "multidimensional",
            "causality": "narrative",
            "consciousness_nature": "soul_based",
            "information_laws": "supernatural",
            "entropy_law": "standard",
            # L1
            "cosmo_scope": "planar",
            "cosmo_mutability": "immutable",
            "divine_nature": "actor",
            "cosmo_cognition": "partially_known",
            "origin_type": "creation",
            "eschatology": "apocalypse",
            "plane_structure": "multiple",
            "destiny_mechanism": "prophecy",
            # L2
            "terrain_paradigm": "earthlike",
            "gravity_atmosphere": "supernatural_atmosphere",
            "resource_paradigm": "artifact",
            "magical_geography": "ley_lines",
            "environmental_hazards": "monster_tides",
            "celestial_bodies": "standard",
            "infrastructure_level": "magical",
            # L3
            "power_existence": "common",
            "power_source": "external_environmental",
            "acquisition_method": "study",
            "cost_structure": "consumption",
            "progression_model": "linear_levels",
            "system_transparency": "hard",
            "power_interaction": "stackable",
            "power_regulation": "self_regulated",
        },
    },
    # ---------------------------------------------------------------- 7
    {
        "key": "shanhai_zhiguai",
        "name": "山海志怪",
        "vibe": "万物有灵、山神水府，壶中洞天与飞升得道的华夏志怪世界。",
        "params": {
            # L0
            "physics_deviation": "minor",
            "metaphysics": "animist",
            "time_structure": "linear",
            "space_structure": "nested",
            "causality": "narrative",
            "consciousness_nature": "fundamental",
            "information_laws": "conserved",
            "entropy_law": "reversed",
            # L1
            "cosmo_scope": "regional",
            "cosmo_mutability": "cyclical_mutability",
            "divine_nature": "actor",
            "cosmo_cognition": "partially_known",
            "origin_type": "mythic",
            "eschatology": "transcendence",
            "plane_structure": "nested",
            "destiny_mechanism": "prophecy",
            # L2
            "terrain_paradigm": "earthlike",
            "gravity_atmosphere": "supernatural_atmosphere",
            "resource_paradigm": "land",
            "magical_geography": "ley_lines",
            "environmental_hazards": "monster_tides",
            "celestial_bodies": "astrological",
            "infrastructure_level": "basic",
            # L3
            "power_existence": "rare",
            "power_source": "external_environmental",
            "acquisition_method": "cultivation",
            "cost_structure": "time_cost",
            "progression_model": "realm_breakthrough",
            "system_transparency": "medium",
            "power_interaction": "hierarchical",
            "power_regulation": "self_regulated",
        },
    },
    # ---------------------------------------------------------------- 8
    {
        "key": "infinite_flow",
        "name": "无限流",
        "vibe": "主神空间驱动的副本轮回，系统面板与兑换点数堆叠出无限可能。",
        "params": {
            # L0
            "physics_deviation": "minor",
            "metaphysics": "materialist",
            "time_structure": "branching",
            "space_structure": "nested",
            "causality": "deterministic",
            "consciousness_nature": "substrate_independent",
            "information_laws": "creatable",
            "entropy_law": "standard",
            # L1
            "cosmo_scope": "planar",
            "cosmo_mutability": "mutable_force",
            "divine_nature": "source",
            "cosmo_cognition": "unknown",
            "origin_type": "engineered",
            "eschatology": "engineered_end",
            "plane_structure": "multiple",
            "destiny_mechanism": "threads",
            # L2
            "terrain_paradigm": "dimensional_maze",
            "gravity_atmosphere": "variable",
            "resource_paradigm": "artifact",
            "magical_geography": "dimensional_rifts",
            "environmental_hazards": "dimensional_incursions",
            "celestial_bodies": "standard",
            "infrastructure_level": "cyberpunk",
            # L3
            "power_existence": "universal",
            "power_source": "systemic",
            "acquisition_method": "contract",
            "cost_structure": "consumption",
            "progression_model": "exponential",
            "system_transparency": "hard",
            "power_interaction": "stackable",
            "power_regulation": "weaponized",
        },
    },
    # ---------------------------------------------------------------- 9
    {
        "key": "post_apocalyptic",
        "name": "末日废土",
        "vibe": "大灾变后的辐射荒原，净水即生命、变异即生存的崩溃文明。",
        "params": {
            # L0
            "physics_deviation": "minor",
            "metaphysics": "materialist",
            "time_structure": "linear",
            "space_structure": "3d_standard",
            "causality": "deterministic",
            "consciousness_nature": "emergent",
            "information_laws": "destroyable",
            "entropy_law": "accelerated",
            # L1
            "cosmo_scope": "regional",
            "cosmo_mutability": "degrading",
            "divine_nature": "absent",
            "cosmo_cognition": "partially_known",
            "origin_type": "accident",
            "eschatology": "apocalypse",
            "plane_structure": "single",
            "destiny_mechanism": "none",
            # L2
            "terrain_paradigm": "earthlike",
            "gravity_atmosphere": "toxic",
            "resource_paradigm": "life",
            "magical_geography": "cursed_lands",
            "environmental_hazards": "environmental_decay",
            "celestial_bodies": "standard",
            "infrastructure_level": "post_apocalyptic",
            # L3
            "power_existence": "rare",
            "power_source": "internal",
            "acquisition_method": "mutation",
            "cost_structure": "physical_fatigue",
            "progression_model": "capped",
            "system_transparency": "hard",
            "power_interaction": "single",
            "power_regulation": "unregulated",
        },
    },
    # ---------------------------------------------------------------- 10
    {
        "key": "urban_supernatural",
        "name": "都市灵异",
        "vibe": "霓虹灯下的灵界重叠，阴阳眼与凶宅秘闻的现代怪谈。",
        "params": {
            # L0
            "physics_deviation": "minor",
            "metaphysics": "dualist",
            "time_structure": "linear",
            "space_structure": "3d_standard",
            "causality": "karmic",
            "consciousness_nature": "soul_based",
            "information_laws": "supernatural",
            "entropy_law": "standard",
            # L1
            "cosmo_scope": "conditional",
            "cosmo_mutability": "immutable",
            "divine_nature": "unknowable",
            "cosmo_cognition": "unknown",
            "origin_type": "eternal",
            "eschatology": "unknown",
            "plane_structure": "dual",
            "destiny_mechanism": "karma",
            # L2
            "terrain_paradigm": "earthlike",
            "gravity_atmosphere": "standard",
            "resource_paradigm": "artifact",
            "magical_geography": "cursed_lands",
            "environmental_hazards": "dimensional_incursions",
            "celestial_bodies": "event_significant",
            "infrastructure_level": "developed",
            # L3
            "power_existence": "rare",
            "power_source": "bloodline",
            "acquisition_method": "innate",
            "cost_structure": "backlash",
            "progression_model": "horizontal",
            "system_transparency": "soft",
            "power_interaction": "single",
            "power_regulation": "suppressed",
        },
    },
]

PRESET_BY_KEY: dict[str, dict] = {p["key"]: p for p in PRESETS}


def preset_summaries() -> list[dict]:
    """返回前端友好的 preset 摘要列表（key/name/vibe + 关键参数摘要）。"""
    out: list[dict] = []
    for p in PRESETS:
        params = p["params"]
        # 摘要：挑 4 个最具辨识度的参数（中文标签化由前端或 option_label 处理，
        # 此处返回 key=value 原始串，保持端点轻量）
        highlight_keys = ("physics_deviation", "metaphysics",
                          "power_source", "power_existence")
        summary = "；".join(f"{k}={params[k]}" for k in highlight_keys)
        out.append({
            "key": p["key"],
            "name": p["name"],
            "vibe": p["vibe"],
            "summary": summary,
        })
    return out
