"""worldview profile — 世界观档案（L0-L9 全 10 层选择 + 提示文本 + world_rules 翻译）

职责：
  - 持有用户在各层选定的枚举值（``layers``：层 id → {param_key: value}）
  - :meth:`WorldviewProfile.to_prompt_text`：生成给 LLM 的设定指令文本
  - :meth:`WorldviewProfile.to_world_rules`：把可表达为布尔事实的设定翻译成
    validator 可消费的 world_rules（限 ``WORLD_FACT_TYPES`` 5 事实词汇表），
    不可表达的设定以 ``narrative`` 形式返回（kind="narrative"，无 expr）。

设计约束：
  - 不依赖 z3 / 任何新第三方库
  - 容忍部分填写（无值的层/参数跳过）
  - 未知键忽略（不崩）
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .layers import ALL_PARAMS, LAYERS, LANGUAGE_LAYERS, LAYER_BY_ID, option_label


# 5 事实词汇表（与 story_engine.validator.WORLD_FACT_TYPES 对齐）
_WORLD_FACT_VOCAB = {"has_supernatural", "is_resolution", "narrator_is_killer",
                     "case_age_days", "introduces_new_key_clue"}


@dataclass
class WorldviewProfile:
    """世界观档案：各层选定参数值的集合。

    ``layers`` 结构::

        {
          "L0": {"physics_deviation": "major", "metaphysics": "dualist", ...},
          "L1": {...},
          ...
        }
    """

    layers: dict[str, dict[str, str]] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # 构造 / 扁平化
    # ------------------------------------------------------------------
    def __post_init__(self) -> None:
        # 防御：未知层 id / 未知参数键静默剔除（容忍原则）
        cleaned: dict[str, dict[str, str]] = {}
        for layer_id, params in self.layers.items():
            if layer_id not in LAYER_BY_ID or not isinstance(params, dict):
                continue
            cleaned[layer_id] = {
                k: v for k, v in params.items() if k in ALL_PARAMS and isinstance(v, str)
            }
        self.layers = cleaned

    def as_flat(self) -> dict[str, str]:
        """扁平化为 ``{param_key: value}``（跨层合并，后写覆盖——同键不应跨层）。"""
        flat: dict[str, str] = {}
        for layer_id in sorted(self.layers):
            for k, v in self.layers.get(layer_id, {}).items():
                flat[k] = v
        return flat

    # ------------------------------------------------------------------
    # 提示文本
    # ------------------------------------------------------------------
    def to_prompt_text(self) -> str:
        """生成给 LLM 的世界观设定指令。

        每层一行（如「物理偏离=major：灵气是第五基本力」）；整层无值的跳过。
        每层格式：``[L0 存在论基础] 物理偏离度=核心物理定律被修改；形而上学=二元``。
        同时输出语言层（LANG1-LANG5），格式同上。
        """
        lines: list[str] = []
        for layer in LAYERS + LANGUAGE_LAYERS:
            params = self.layers.get(layer["id"], {})
            if not params:
                continue
            parts: list[str] = []
            for p in layer["params"]:
                val = params.get(p["key"])
                if not val:
                    continue
                parts.append(f"{p['label']}={option_label(p['key'], val)}")
            if parts:
                lines.append(f"[{layer['id']} {layer['name']}] " + "；".join(parts))
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # world_rules 翻译
    # ------------------------------------------------------------------
    def to_world_rules(self) -> list[dict]:
        """把可表达的设定翻译成 validator 可消费的 world_rules。

        限 ``WORLD_FACT_TYPES`` 5 事实词汇表：只有能映射到这 5 个布尔/算术事实的
        设定才生成可执行规则（``kind="bool"``，带 ``expr``）；其余以
        ``kind="narrative"`` 返回（无 ``expr``，仅作 LLM 提示用）。

        返回的每条形如::

            {"id": "wv_has_supernatural",
             "kind": "bool" | "narrative",
             "desc": "...",
             "expr": "has_supernatural == False"}   # 仅 kind=bool 时
        """
        flat = self.as_flat()
        rules: list[dict] = []

        # 1. has_supernatural（L3 power_existence 决定）
        pe = flat.get("power_existence")
        if pe == "nonexistent":
            rules.append({"id": "wv_has_supernatural", "kind": "bool",
                          "desc": "世界观无超自然力量",
                          "expr": "not(has_supernatural)"})
        elif pe in {"universal", "common", "rare", "unique", "dormant"}:
            rules.append({"id": "wv_has_supernatural", "kind": "bool",
                          "desc": f"世界观存在超自然力量（{option_label('power_existence', pe)}）",
                          "expr": "has_supernatural"})

        # 2. narrator_is_killer 等 3 个事实词汇仍无参数映射（5 事实词汇表覆盖留白）
        # 3. case_age_days / introduces_new_key_clue（悬疑专用，本批不覆盖）

        # 其余设定均无法落入 5 事实词汇表 → narrative
        narrative_keys = [k for k in flat if k != "power_existence"]
        if narrative_keys:
            desc_parts = [f"{k}={flat[k]}" for k in narrative_keys]
            rules.append({
                "id": "wv_narrative_context",
                "kind": "narrative",
                "desc": "世界观上下文（超出 5 事实词汇表，仅作 LLM 提示）：" +
                        "；".join(desc_parts),
            })

        return rules
