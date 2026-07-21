"""抽卡开局（Gacha）：库内随机组合 / LLM 合成题材（P8.4 接入）

P8.3 范围：library 模式——从 registry 现有题材/文化/角色原型/世界规则包中
随机组合一张开局卡，支持 lock 锁定栏位（前端「单换一栏」依赖）。
synth 模式（LLM 现场合成 genre 包 + 校验 + 重试 + 降级）在 P8.4 实现；
本模块已留好挂载点与 mock 短路（见 draw_card docstring）。
"""
from __future__ import annotations

import random

from ..types import StoryEngineError


def draw_card(kernel, llm_call=None, mode: str = "library",
              lock: dict | None = None) -> dict:
    """抽一张开局卡（同步；P8.4 将加 async 包装接 synth 分支，本函数保持纯同步）。

    - mode="library"：全部栏位从 registry 库内随机；lock 可锁定任意栏——
      {"genre"/"culture"/"archetype": 名称str, "rule_packs": 名称str或名称list}，
      键缺省或值为 None 视为未锁定；锁定名不在库内时回退随机（宽容：
      前端可能带着上一轮卡面名单重抽，库内已被 reload 改变）。
    - mode="synth"：P8.4 接入 LLM 合成 genre 包。mock 短路在注入点之前——
      llm_call 为 None 或 kernel.llm.is_mock 时恒降级 library 卡（硬约束：
      mock 模式零 LLM 调用），两处判据冗余并存，任一生效即短路。
    """
    card = _draw_library(kernel, lock or {})
    if mode == "library":
        return card
    if mode == "synth":
        if llm_call is None or kernel.llm.is_mock:
            card["note"] = "当前为 mock 模式，AI 自由发挥不可用，已换成库内组合"
            return card
        # P8.4 挂载点：synth 分支（LLM 合成 + validate_genre_pack 校验 +
        # 重试 1 次 + 降级）；本版本 synth 未上线，非 mock 也先降级 library 卡
        card["note"] = "synth 模式尚未上线，已换成库内组合"
        return card
    raise StoryEngineError(f"未知抽卡模式：{mode}")


def _draw_library(kernel, lock: dict) -> dict:
    reg = kernel.registry
    genres = reg.list_plugins("story.genre")["story.genre"]
    cultures = reg.list_plugins("story.culture")["story.culture"]
    if not genres or not cultures:
        raise StoryEngineError("registry 无可用题材/文化包（plugins 未加载）")
    archs = reg.packs("story.character.archetype")
    rules = reg.packs("story.world.rule")

    genre_name = _pick(genres, lock.get("genre"))
    culture_name = _pick(cultures, lock.get("culture"))
    arch = _pick_pack(archs, lock.get("archetype"))
    picked_rules = _pick_rules(rules, lock.get("rule_packs"))
    return {
        "mode": "library",
        "genre": {"name": genre_name, "source": "library",
                  "desc": _genre_desc(reg, genre_name)},
        "culture": {"name": culture_name, "desc": f"文化包 {culture_name}"},
        "archetype": {"name": arch.name if arch else "",
                      "desc": arch.params.get("desc", "") if arch else "",
                      "voice_hint": arch.params.get("voice_hint", "") if arch else ""},
        "rule_packs": [{"name": p.name, "desc": _rule_desc(p)}
                       for p in picked_rules],
        "note": None,
    }


def _pick(names: list, locked) -> str:
    """单选栏位：锁定名在库内则锁定，否则随机（locked=None 自然走随机）"""
    return locked if locked in names else random.choice(names)


def _pick_pack(packs: list, locked):
    if not packs:
        return None
    if locked:
        for p in packs:
            if p.name == locked:
                return p
    return random.choice(packs)


def _pick_rules(rules: list, locked) -> list:
    """规则包栏位：缺省随机抽 ≤2 个；锁定（str 或 list）则取库内匹配项，
    全不匹配回退随机。返回顺序按 registry 扫描序（稳定，便于测试与前端比对）。"""
    if not rules:
        return []
    locked_names = {locked} if isinstance(locked, str) else set(locked or [])
    if locked_names:
        picked = [p for p in rules if p.name in locked_names]
        if picked:
            return picked
    return random.sample(rules, k=min(2, len(rules)))


def _genre_desc(reg, name: str) -> str:
    try:
        m = reg.get_manifest("story.genre", name)
        return m.params.get("resolution_pattern") \
            or str(m.params.get("pacing_curve", ""))[:40]
    except Exception:
        return name


def _rule_desc(pack) -> str:
    """规则包卡面 desc：取首条规则描述（世界规则包的 params 无顶层 desc）"""
    rules = pack.params.get("rules") or []
    if rules and rules[0].get("desc"):
        return rules[0]["desc"]
    return f"世界规则包 {pack.name}"
