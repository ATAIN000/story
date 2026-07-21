"""抽卡开局（Gacha）：库内随机组合 / LLM 合成题材

library 模式（P8.3）：从 registry 现有题材/文化/角色原型/世界规则包中
随机组合一张开局卡，支持 lock 锁定栏位（前端「单换一栏」依赖），纯同步零 LLM。
synth 模式（P8.4）：draw_card_async 在非 mock 时调 _synth_genre——LLM 现场
合成 genre 包（mystery.yaml 全文作模板锚），validate_genre_pack 校验，
失败带错误反馈重试 1 次，仍失败/调用异常则降级保留 library 卡并写 note。
mock 短路在注入点之前：llm_call 为 None 或 kernel.llm.is_mock 时恒降级
library 卡（硬约束：mock 模式零 LLM 调用），两处判据冗余并存，任一生效即短路。
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
    """抽一张开局卡（纯同步，零 LLM；synth 合成走 draw_card_async）。

    - mode="library"：全部栏位从 registry 库内随机；lock 可锁定任意栏——
      {"genre"/"culture"/"archetype": 名称str, "rule_packs": 名称str或名称list}，
      键缺省或值为 None 视为未锁定；锁定名不在库内时回退随机（宽容：
      前端可能带着上一轮卡面名单重抽，库内已被 reload 改变）。
    - mode="synth"：本同步路径只负责 mock 短路降级——llm_call 为 None 或
      kernel.llm.is_mock 时恒返回 library 卡 + note（硬约束：mock 零 LLM 调用）；
      非 mock 的合成流程必须用 async 入口 draw_card_async。
    """
    card = _draw_library(kernel, lock or {})
    if mode == "library":
        return card
    if mode == "synth":
        # mock 短路（llm_call None / is_mock 冗余双判据，任一生效即降级）；
        # 非 mock 走这里说明调用方绕过了 draw_card_async，同样按降级处理
        card["note"] = "当前为 mock 模式，AI 自由发挥不可用，已换成库内组合"
        return card
    raise StoryEngineError(f"未知抽卡模式：{mode}")


async def draw_card_async(kernel, llm_call=None, mode: str = "library",
                          lock: dict | None = None) -> dict:
    """draw_card 的 async 入口：synth 模式在非 mock 时走 LLM 合成（P8.4）。

    mock 短路在 LLM 调用之前：llm_call 为 None 或 kernel.llm.is_mock 时
    落回同步 draw_card 的降级分支（零 LLM 调用）；library 模式直接同步返回。
    """
    if mode == "synth" and llm_call is not None and not kernel.llm.is_mock:
        card = _draw_library(kernel, lock or {})
        return await _synth_genre(card, llm_call)
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
