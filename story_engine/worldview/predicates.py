"""worldview predicates — 跨层一致性谓词（批1：L0-L3 相关）

素材唯一来源：docs/世界观架构_参数全表.md
  - 各参数的「谓词」段（显式标记）
  - 连锁标记 ``→`` / ``↔``（蕴含/互斥）

谓词格式（机器可读）：

    {
      "when": {<param_key>: <value>, ...},      # 全部匹配时触发
      "then": {
        "<param_key>": {"disallow": [<value>, ...]},   # 收窄：禁用值
        "<param_key>": {"require": [<value>, ...]},    # （可选）限定取值
        "require_note": "<text>",                       # 仅提示，不强制取值
      },
      "message": "<中文解释>",
      "source": "<素材定位，如 P0.2 谓词段 / 行 35-37>"
    }

evaluate(profile) 为纯函数，容忍部分 profile 与未知键。
"""
from __future__ import annotations

from .layers import ALL_PARAMS, param_values

# ----------------------------------------------------------------------------
# PREDICATES
# ----------------------------------------------------------------------------
PREDICATES: list[dict] = [
    # ---- L0 内部：metaphysics → consciousness_nature / causality ----
    {
        "when": {"metaphysics": "materialist"},
        "then": {"consciousness_nature": {"disallow": ["soul_based", "collective"]}},
        "message": "唯物基底不允许灵魂独立存在",
        "source": "P0.2 谓词段 / 行 36",
    },
    {
        "when": {"metaphysics": "idealist"},
        "then": {"causality": {"require": ["intentional"]}},
        "message": "唯心基底：意志可直接影响物理现实（因果=意图驱动）",
        "source": "P0.2 谓词段 / 行 37",
    },
    {
        "when": {"metaphysics": "animist"},
        "then": {"consciousness_nature": {"require": ["fundamental", "collective"]}},
        "message": "万物有灵：意识必须是宇宙基本属性或集体形态",
        "source": "P0.2 连锁 / 行 32",
    },
    {
        "when": {"metaphysics": "dualist"},
        "then": {"consciousness_nature": {"require": ["soul_based", "substrate_independent"]}},
        "message": "二元论：意识须可独立于肉体（灵魂载体或载体无关）",
        "source": "P0.2 连锁 / 行 30",
    },

    # ---- L0 内部：physics_deviation ----
    {
        "when": {"physics_deviation": "total"},
        "then": {"require_note": "所有层全部从零重建，需要独立的物理百科"},
        "message": "完全不同的物理体系需独立物理百科",
        "source": "P0.1 谓词段（↔） / 行 23",
    },
    {
        "when": {"physics_deviation": "major"},
        "then": {"gravity_atmosphere": {"disallow": ["standard"]}},
        "message": "核心物理被修改：环境不应是标准现实大气",
        "source": "P0.1 major 连锁 / 行 20",
    },

    # ---- L0 内部：time_structure ----
    {
        "when": {"time_structure": "linear"},
        "then": {
            "eschatology": {"disallow": ["eternal_cycle"]},
            "destiny_mechanism": {"disallow": ["predestination", "self_fulfilling"]},
        },
        "message": "线性时间不允许无终结循环/宿命/自我实现（因果单向）",
        "source": "P0.3 谓词段 / 行 51",
    },
    {
        "when": {"time_structure": "cyclic"},
        "then": {"origin_type": {"require": ["cyclical_renewal", "eternal"]}},
        "message": "循环时间要求起源是周期重生或永恒",
        "source": "P0.3 cyclic 连锁 / 行 44",
    },
    {
        "when": {"time_structure": "branching"},
        "then": {"require_note": "分支时间需 paradox_handling_rule（悖论处理规则）"},
        "message": "分支/多重时间需显式悖论处理规则",
        "source": "P0.3 谓词段 / 行 52",
    },
    {
        "when": {"time_structure": "multiverse"},
        "then": {"require_note": "多重时间轴需 paradox_handling_rule（悖论处理规则）"},
        "message": "分支/多重时间需显式悖论处理规则",
        "source": "P0.3 谓词段 / 行 52",
    },

    # ---- L0 → L1：entropy_law ↔ eschatology ----
    {
        "when": {"entropy_law": "standard"},
        "then": {"eschatology": {"disallow": ["eternal_cycle", "transcendence"]}},
        "message": "标准热力学熵不允许永恒循环或超越终结",
        "source": "P0.8 / P1.6 连锁 / 行 100, 171",
    },
    {
        "when": {"entropy_law": "reversed"},
        "then": {"eschatology": {"disallow": ["heat_death", "entropy_death"]}},
        "message": "局部逆熵的世界不应走向热寂或熵死",
        "source": "P0.8 reversed 连锁 / 行 101",
    },
    {
        "when": {"entropy_law": "accelerated"},
        "then": {"eschatology": {"require": ["apocalypse", "entropy_death"]}},
        "message": "加速衰变导向末日或熵死",
        "source": "P0.8 accelerated 连锁 / 行 103",
    },

    # ---- L0 → L1：information_laws → divine_nature ----
    {
        "when": {"information_laws": "supernatural"},
        "then": {"acquisition_method": {"require": ["study", "innate", "bestowal"]}},
        "message": "超自然信息（真名/誓言有力量）：力量获取须含知识/天赋/赐予",
        "source": "P0.7 supernatural 连锁 / 行 93",
    },
    {
        "when": {"information_laws": "infectious"},
        "then": {"environmental_hazards": {"require": ["dimensional_incursions", "magical_storms"]}},
        "message": "信息可感染：环境威胁须体现超自然侵蚀",
        "source": "P0.7 infectious 连锁 / 行 94",
    },

    # ---- L1 内部：divine_nature ----
    {
        "when": {"divine_nature": "absent"},
        "then": {"origin_type": {"disallow": ["creation"]}},
        "message": "无神的世界不应是有意识的创世行为",
        "source": "P1.3 absent 连锁 / 行 136",
    },
    {
        "when": {"divine_nature": "actor"},
        "then": {"origin_type": {"require": ["creation", "engineered", "mythic"]}},
        "message": "人格神行动者要求起源是创世/设计/神话",
        "source": "P1.3 actor 连锁 / 行 137",
    },
    {
        "when": {"divine_nature": "ascended"},
        "then": {"cosmo_mutability": {"disallow": ["immutable"]}},
        "message": "凡人可封神：宇宙规则不可永恒不变",
        "source": "P1.3 ascended 连锁 / 行 141",
    },
    {
        "when": {"divine_nature": "source"},
        "then": {"cosmo_mutability": {"require": ["mutable_force"]}},
        "message": "神是法则源头：杀神=改规则，故规则可被力量改变",
        "source": "P1.3 source 连锁 / 行 138",
    },
    {
        "when": {"divine_nature": "projection"},
        "then": {"cosmo_mutability": {"require": ["mutable_collective"]}},
        "message": "神是信仰投射：规则由集体意志改变",
        "source": "P1.3 projection 连锁 / 行 139",
    },

    # ---- L1 内部：cosmo_mutability ↔ progression_model ----
    {
        "when": {"cosmo_mutability": "immutable"},
        "then": {"progression_model": {"disallow": ["boundless"]}},
        "message": "宇宙规则永恒不变：力量体系无上限不合理",
        "source": "P1.2 immutable 连锁 / 行 126",
    },
    {
        "when": {"cosmo_mutability": "mutable_force"},
        "then": {"progression_model": {"require": ["boundless", "exponential", "realm_breakthrough"]}},
        "message": "力量可改规则：进阶模型须无天花板或境界碾压",
        "source": "P1.2 mutable_force 连锁 / 行 127",
    },
    {
        "when": {"cosmo_mutability": "degrading"},
        "then": {"resource_paradigm": {"disallow": ["none"]}},
        "message": "规则在退化：必定存在稀缺资源（灵气/魔法在枯竭）",
        "source": "P1.2 degrading 连锁 / 行 130",
    },

    # ---- L1 内部：plane_structure ↔ space_structure ----
    {
        "when": {"plane_structure": "single"},
        "then": {"space_structure": {"disallow": ["multidimensional", "nested"]}},
        "message": "单一物理世界与多维/嵌套空间冲突",
        "source": "P1.7 single / P0.4 连锁",
    },
    {
        "when": {"plane_structure": "multiple"},
        "then": {"space_structure": {"require": ["multidimensional", "nested", "networked"]}},
        "message": "多位面结构要求空间是多维/嵌套/网络化",
        "source": "P1.7 multiple / P0.4 连锁",
    },
    {
        "when": {"plane_structure": "collapsed"},
        "then": {"environmental_hazards": {"disallow": ["none_significant", "natural_only"]}},
        "message": "位面融合/破碎：环境必有超自然威胁",
        "source": "P1.7 collapsed 连锁 / 行 186",
    },

    # ---- L1 → L0：cosmo_cognition ↔ information_laws ----
    {
        "when": {"cosmo_cognition": "unknowable"},
        "then": {"information_laws": {"disallow": ["conserved"]}},
        "message": "宇宙真相不可知与信息守恒矛盾",
        "source": "P1.4 unknowable / P0.7 连锁",
    },
    {
        "when": {"cosmo_cognition": "known"},
        "then": {"information_laws": {"disallow": ["destroyable", "infectious"]}},
        "message": "真相普遍可知与信息可抹除/可感染矛盾",
        "source": "P1.4 known / P0.7 连锁",
    },

    # ---- L0/L1 → L1：causality ↔ destiny_mechanism ----
    {
        "when": {"causality": "deterministic"},
        "then": {"destiny_mechanism": {"require": ["predestination", "threads", "none"]}},
        "message": "严格因果律匹配宿命/命运之线/无命运",
        "source": "P0.5 deterministic 连锁 / 行 69",
    },
    {
        "when": {"causality": "narrative"},
        "then": {"destiny_mechanism": {"require": ["prophecy", "self_fulfilling", "competing_fates"]}},
        "message": "叙事因果匹配预言/自我实现/竞争命运",
        "source": "P0.5 narrative 连锁 / 行 72",
    },
    {
        "when": {"causality": "karmic"},
        "then": {"destiny_mechanism": {"require": ["karma"]}},
        "message": "因果报应模式匹配业力命运机制",
        "source": "P0.5 karmic 连锁 / 行 73",
    },
    {
        "when": {"causality": "chaotic"},
        "then": {"destiny_mechanism": {"require": ["none"]}},
        "message": "无因果的世界不应有命运机制",
        "source": "P0.5 chaotic 连锁 / 行 74",
    },

    # ---- L2 → L0：gravity_atmosphere ↔ physics_deviation ----
    {
        "when": {"gravity_atmosphere": "supernatural_atmosphere"},
        "then": {"physics_deviation": {"disallow": ["none"]}},
        "message": "超自然大气与完全遵循现实物理冲突",
        "source": "P2.2 supernatural_atmosphere 连锁 / 行 226",
    },

    # ---- L2 → L1：magical_geography ↔ plane_structure ----
    {
        "when": {"magical_geography": "dimensional_rifts"},
        "then": {"plane_structure": {"disallow": ["single"]}},
        "message": "维度裂缝/传送门要求非单一物理世界",
        "source": "P2.4 dimensional_rifts 连锁 / 行 257",
    },

    # ---- L3 内部：system_transparency ↔ magic_solves_conflict ----
    {
        "when": {"system_transparency": "soft"},
        "then": {"require_note": "软魔法不可用于解决核心冲突（Sanderson 第一定律）"},
        "message": "软魔法不应被用于解决冲突",
        "source": "P3.6 谓词段 / 行 380",
    },
    {
        "when": {"system_transparency": "mystery"},
        "then": {"require_note": "完全不可知的力量绝不可用于解决冲突（Sanderson 第一定律）"},
        "message": "不可知的力量绝不可用于解决冲突",
        "source": "P3.6 谓词段 / 行 380",
    },

    # ---- L3 ↔ L0：power_source ↔ metaphysics / information_laws ----
    {
        "when": {"power_source": "knowledge_based"},
        "then": {"information_laws": {"require": ["supernatural"]}},
        "message": "知识系魔法要求信息有超自然属性（真名/誓言有力量）",
        "source": "P3.2 knowledge_based / P0.7 连锁",
    },
    {
        "when": {"power_source": "granted"},
        "then": {"divine_nature": {"disallow": ["absent"]}},
        "message": "被赋予的力量要求非无神世界",
        "source": "P3.2 granted 连锁 / 行 318",
    },
    {
        "when": {"power_source": "bloodline"},
        "then": {"acquisition_method": {"require": ["innate", "bestowal"]}},
        "message": "血脉天赋须搭配先天/赐予获取方式",
        "source": "P3.2 bloodline 连锁 / 行 321",
    },

    # ---- L3 ↔ L0：cost_structure ↔ metaphysics ----
    {
        "when": {"cost_structure": "sacrifice"},
        "then": {"consciousness_nature": {"disallow": ["emergent"]}},
        "message": "牺牲代价（献祭记忆/寿命/灵魂）与涌现意识矛盾",
        "source": "P3.4 sacrifice / P0.6 连锁",
    },
    {
        "when": {"cost_structure": "corruption"},
        "then": {"metaphysics": {"disallow": ["materialist"]}},
        "message": "堕落代价（越用越不人）与纯唯物基底矛盾",
        "source": "P3.4 corruption / P0.2 连锁",
    },

    # ---- L3 ↔ L2：power_source ↔ resource_paradigm ----
    {
        "when": {"power_source": "external_material"},
        "then": {"resource_paradigm": {"disallow": ["none"]}},
        "message": "消耗外部物质的力量要求存在稀缺资源",
        "source": "P3.2 external_material 连锁 / 行 316",
    },

    # ---- L3 内部：power_existence ↔ power_regulation ----
    {
        "when": {"power_existence": "nonexistent"},
        "then": {"power_regulation": {"require": ["integrated"]}},
        "message": "无超自然力量：力量管理为社会正常部分（无特殊管理）",
        "source": "P3.1 / P3.8 连锁",
    },
    {
        "when": {"power_existence": "universal"},
        "then": {"power_regulation": {"disallow": ["suppressed"]}},
        "message": "全民皆有力量时压制不可行",
        "source": "P3.1 universal / P3.8 suppressed 连锁",
    },
]


# ----------------------------------------------------------------------------
# evaluate
# ----------------------------------------------------------------------------
def _matches_when(when: dict, profile: dict) -> bool:
    """when 中所有键值都必须在 profile 中出现且相等。"""
    for k, v in when.items():
        if profile.get(k) != v:
            return False
    return True


def evaluate(profile: dict | None) -> dict:
    """评估 worldview profile 的跨层一致性。

    返回::

        {
          "allowed": {<param_key>: [<allowed_value>, ...]},  # 收窄后的合法值
          "violations": [{"param", "value", "message"}, ...],
        }

    纯函数：
      - ``profile`` 可为 ``None``/空/部分（缺键视为未设置，不触发依赖该键的谓词）
      - 未知键被忽略，不引发异常
      - ``allowed`` 仅包含被谓词收窄过的参数（其余参数仍取 :data:`ALL_PARAMS` 全集）
    """
    profile = dict(profile or {})

    # 1. 计算 allowed：初始为全集，逐条谓词收窄
    allowed: dict[str, list[str]] = {key: param_values(key) for key in ALL_PARAMS}

    # 2. 检测违例：profile 中已存在的值是否被某触发的谓词 disallow
    violations: list[dict] = []

    for pred in PREDICATES:
        when = pred.get("when", {})
        if not _matches_when(when, profile):
            continue
        then = pred.get("then", {})
        for target_key, constraint in then.items():
            if target_key == "require_note":
                continue
            if not isinstance(constraint, dict):
                continue
            disallow = constraint.get("disallow", [])
            require = constraint.get("require")

            # 收窄 allowed
            if disallow:
                allowed[target_key] = [v for v in allowed[target_key] if v not in disallow]
            if require:
                allowed[target_key] = [v for v in allowed[target_key] if v in require]

            # 违例检测（仅当 profile 显式设置了该参数）
            actual = profile.get(target_key)
            if actual is None:
                continue
            if actual in disallow:
                violations.append({
                    "param": target_key,
                    "value": actual,
                    "message": pred.get("message", ""),
                })
            elif require and actual not in require:
                violations.append({
                    "param": target_key,
                    "value": actual,
                    "message": pred.get("message", ""),
                })

    return {"allowed": allowed, "violations": violations}
