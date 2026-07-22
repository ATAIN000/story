"""抽卡开局（Gacha）：题材列表 / LLM 合成题材

【P13 简化】library 模式返回**题材列表**（全量 registry 题材 + 气质/文化/阵容摘要），
前端单栏点选；synth 模式不变（LLM 合成 genre 包）。CARD 结构简化为
{mode, genre:{name,source,desc,yaml?}, note}——删除 culture/archetype/rule_packs 三栏
（世界观向导已取代世界规则栏，文化从题材 allowed_cultures 自带，阵容从 cast 自带）。

synth 模式（P8.4）：draw_card_async 在非 mock 时调 _synth_genre——LLM 现场
合成 genre 包（mystery.yaml 全文作模板锚），validate_genre_pack 校验，
失败带错误反馈重试 1 次，仍失败/调用异常则降级保留 library 卡并写 note。
mock 短路在注入点之前：llm_call 为 None 或 kernel.llm.is_mock 时恒降级
library 卡（硬约束：mock 模式零 LLM 调用），两处判据冗余并存，任一生效即短路。

synth 内部仍用 _draw_library_card 构建四栏上下文（供 _synth_prompt 使用），
但返回前经 _simplify_card 精简为 {mode, genre, note}。
"""
from __future__ import annotations

import random
import re
from pathlib import Path

import yaml

from ..types import StoryEngineError
from .genre_validator import (
    ARCHETYPES, FACTS, KNOWN_CRITICS, PRIMITIVES, validate_genre_pack)


def draw_card(kernel, llm_call=None, mode: str = "library",
              lock: dict | None = None) -> dict:
    """抽卡入口（纯同步，零 LLM；synth 合成走 draw_card_async）。

    - mode="library"（P13）：返回题材列表（全量 registry 题材，含 title/desc/
      culture_title/cast_summary），前端单栏点选。lock 不再需要（单栏无锁）。
    - mode="synth"：mock 短路降级——llm_call 为 None 或 kernel.llm.is_mock 时
      恒返回精简卡 + note（硬约束：mock 零 LLM 调用）；非 mock 走 async 入口。
    """
    if mode == "library":
        return _genre_list(kernel)
    if mode == "synth":
        card = _draw_library_card(kernel, lock or {})
        result = _simplify_card(card)
        result["note"] = "当前为 mock 模式，AI 自由发挥不可用，已换成库内组合"
        return result
    raise StoryEngineError(f"未知抽卡模式：{mode}")


async def draw_card_async(kernel, llm_call=None, mode: str = "library",
                          lock: dict | None = None) -> dict:
    """draw_card 的 async 入口：synth 模式在非 mock 时走 LLM 合成（P8.4）。

    mock 短路在 LLM 调用之前：llm_call 为 None 或 kernel.llm.is_mock 时
    落回同步 draw_card 的降级分支（零 LLM 调用）；library 模式直接同步返回。
    """
    if mode == "library":
        return _genre_list(kernel)
    if mode == "synth" and llm_call is not None and not kernel.llm.is_mock:
        card = _draw_library_card(kernel, lock or {})
        synthed = await _synth_genre(card, llm_call)
        return _simplify_card(synthed)
    return draw_card(kernel, llm_call, mode, lock)


async def _synth_genre(card: dict, llm_call) -> dict:
    """synth 核心：1 次 LLM 合成 → 校验 → 失败带错误反馈重试 1 次 →
    仍失败（或调用异常）降级保留 library 卡并写 note。降级路径恒产出合法卡。"""
    prompt = _synth_prompt(card)
    err = "未知错误"
    for _ in range(2):  # 首次 + 重试 1 次
        try:
            resp = await llm_call(prompt, purpose="gacha_synth",
                                  temperature=0.8, max_tokens=3000)
        except Exception as exc:  # 传输/协议异常：重试提示词无意义，直接降级
            err = f"LLM 调用异常：{exc}"
            break
        text = getattr(resp, "text", None)
        if not isinstance(text, str):
            text = str(resp)
        pack, err = synth_genre_pack(text)
        if pack:
            card["mode"] = "synth"
            card["genre"] = {
                "name": pack["name"], "source": "synth",
                "desc": str(pack["params"].get("resolution_pattern", "")),
                "yaml": pack,
            }
            return card
        prompt += f"\n\n上次产出未过校验：{err}。请修正后重发完整 yaml。"
    card["note"] = f"AI 合成失败（{err}），已换成库内组合"
    return card


def synth_genre_pack(text: str) -> tuple[dict | None, str | None]:
    """解析+校验 LLM 合成的 genre yaml；返回 (pack, error)，error 为 None 即通过。

    容忍 markdown 代码围栏（```yaml ... ```）；除 H7 检查集（genre_validator）
    外额外要求 name 键——confirm 落盘文件名与卡面展示都依赖它。
    """
    text = text.strip()
    if text.startswith("```"):  # 剥离首行 ```yaml 与结尾 ```
        text = re.sub(r"^```[^\n]*\n", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    try:
        d = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return None, f"YAML 解析失败：{exc}"
    if not isinstance(d, dict):
        return None, "产出不是 mapping"
    errs = validate_genre_pack(d)
    if not d.get("name"):
        errs.append("缺 name 键")
    if errs:
        return None, "；".join(errs)
    return d, None


def _synth_prompt(card: dict) -> str:
    """synth 提示词：mystery.yaml 全文作模板锚 + 卡面 culture/archetype/
    voice_hint/rule_packs 上下文 + 校验词汇表（单一事实源：genre_validator
    常量，校验规则演进时提示词自动跟随）。"""
    culture = card.get("culture") or {}
    arch = card.get("archetype") or {}
    rules = "、".join(f"{p['name']}（{p.get('desc') or '无描述'}）"
                      for p in card.get("rule_packs") or []) or "无"
    return f"""你在为故事引擎现场设计一个新题材包（genre pack）。

【开局上下文】（题材内容必须贴合以下组合）
- 文化包：{culture.get('name', '')} — {culture.get('desc', '')}
- 人物原型：{arch.get('name', '')} — {arch.get('desc', '')}（语气提示：{arch.get('voice_hint', '')}）
- 世界规则包：{rules}

【模板锚点】以下是内置题材包 mystery.yaml 全文，仅作字段结构与格式的模板
（键名、层级、取值范围照此；设定与文案必须原创，不得照抄内容）：
```yaml
{_template_anchor()}
```

【硬性要求】（产出将逐条机器校验，任一不过即被拒）
- 只输出完整 yaml 文本：不要任何解释、前言后语或 markdown 代码围栏
- manifest_version: 1；extension_point: story.genre；name 用英文小写连字符新名
  （不得叫 mystery）；activation_events: ["on_genre:<name>"]；
  culture_bound: false；allowed_cultures: ["*"]
- tracks ≥3 条，每条含 id/name/arc_type/archetype/progress/last_touched；
  archetype 取值限 {sorted(ARCHETYPES)}
- main_track、theme_track 必须指向真实轨道 id；
  beats_per_chapter 为 3-6 的整数；payoff_window 为 ≥1 的整数
- prompt 段含 role/setting/characters/style/hard_requirements 五键
- phase_beats 五相齐全：equilibrium/disruption/recognition/repair/new_equilibrium；
  beat 的 primitive 取值限 {sorted(PRIMITIVES)}
- world_rules 可省略；若写，expr 仅用事实词 {sorted(FACTS)} 与 not/and/or/true/false
- evaluation_weights 各权重之和 = 1.0；active_critics 取值限 {sorted(KNOWN_CRITICS)}
"""


def _template_anchor() -> str:
    """模板锚：内置 mystery.yaml 全文（包内资源，与插件目录配置无关）；
    读取失败退化为无锚（校验仍在，只是少模板参照）。"""
    path = Path(__file__).resolve().parent.parent / "plugins" / "genres" / "mystery.yaml"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return "#（模板文件缺失）"


# ---------- P13：题材列表（library 模式返回前端点选网格） ----------

def _genre_list(kernel) -> dict:
    """library 模式：遍历全量 registry 题材 → 列表（title/desc/culture_title/
    cast_summary），前端单栏点选。不再随机抽文化/原型/规则栏。"""
    reg = kernel.registry
    genres = reg.list_plugins("story.genre")["story.genre"]
    if not genres:
        raise StoryEngineError("registry 无可用题材包（plugins 未加载）")
    dm = reg.display_map()
    items = []
    for name in sorted(genres):
        try:
            m = reg.get_manifest("story.genre", name)
        except Exception:
            continue
        params = m.params
        title = params.get("title") or name
        desc = (params.get("resolution_pattern")
                or str(params.get("pacing_curve", ""))[:40]
                or name)
        culture_title = _culture_title_for(m, dm)
        cast_summary = _cast_summary(params)
        items.append({"name": name, "title": title, "desc": desc,
                      "culture_title": culture_title,
                      "cast_summary": cast_summary})
    return {"mode": "library", "genres": items, "note": None}


def _culture_title_for(manifest, dm: dict) -> str:
    """题材卡文化徽标：语言文化已在世界观向导中选，这里不再显示固定文化——
    P14 后文化不在题材阶段定（向导里选）。题材卡只显示题材气质，不显示文化。"""
    return ""


def _cast_summary(params: dict) -> list[str]:
    """题材卡阵容摘要：L1 cast: 段 id 列表（≤8），或 L2 prompt.characters 原文片段。"""
    cast = params.get("cast")
    if isinstance(cast, list):
        names = [str(c.get("id") or "").strip()
                 for c in cast if isinstance(c, dict)]
        names = [n for n in names if n]
        if names:
            return names[:8]
    prompt = params.get("prompt") or {}
    chars = prompt.get("characters")
    if isinstance(chars, str) and chars.strip():
        return [chars.strip()[:60]]
    return []


# ---------- P13：CARD 精简 ----------

def _simplify_card(card: dict) -> dict:
    """内部四栏卡 → 精简 CARD {mode, genre:{name,source,desc,yaml?}, note}。
    删除 culture/archetype/rule_packs（P13 去重：文化自带、规则由世界观向导产出）。"""
    return {
        "mode": card.get("mode", "library"),
        "genre": card.get("genre") or {},
        "note": card.get("note"),
    }


# ---------- P13：文化推导（confirm 从题材自带取，不再从 card.culture 读） ----------

def derive_culture(allowed_cultures: list | None, genre_name: str | None = None) -> str:
    """从题材 allowed_cultures + genre_name 推导最匹配的文化。

    P18 修复：不再恒回 confucian_officialdom（导致所有题材都是公案风格）。
    策略：非通配取首条；通配时按 genre_name 关键词匹配推荐文化。
    开局不阻塞——用户可后续在设置页改。"""
    # 题材→推荐文化映射（按题材气质对齐）
    GENRE_CULTURE_HINT = {
        # 东方/古风题材 → 儒家官场
        "mystery": "confucian_officialdom", "wuxia": "confucian_officialdom",
        "romance": "confucian_officialdom", "wuxia-steampunk": "confucian_officialdom",
        "political-cultivation": "confucian_officialdom", "tomb-exploration": "confucian_officialdom",
        "historical-isekai": "confucian_officialdom", "historical-system": "confucian_officialdom",
        "folk-cthulhu": "confucian_officialdom", "xianxia-cthulhu": "confucian_officialdom",
        "supernatural-management": "confucian_officialdom", "sequence-pathway": "confucian_officialdom",
        # 其余 → anglo-american（现代/科幻/西幻/穿越类）
    }
    allowed = allowed_cultures or ["*"]
    if "*" not in allowed:
        return allowed[0] if allowed else "confucian_officialdom"
    # 通配：按题材推荐
    if genre_name and genre_name in GENRE_CULTURE_HINT:
        return GENRE_CULTURE_HINT[genre_name]
    non_star = [c for c in allowed if c != "*"]
    return non_star[0] if non_star else "anglo-american"


# ---------- 内部：synth 四栏上下文（仅供 _synth_prompt，不暴露前端） ----------

def _draw_library_card(kernel, lock: dict) -> dict:
    """内部：构建四栏卡供 synth 提示词上下文。P13 前是 library 模式的返回体，
    现仅 synth 内部消费——前端不再看到 culture/archetype/rule_packs 栏。"""
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
