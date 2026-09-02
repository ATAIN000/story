"""叙事技能包路由器 — story.skill 包按触发条件匹配本章（P-skill 接线）

背景：14 个 story.skill 包（武打四拍法、悬念扣子、爽句、对白技巧等）写好了
极精彩的 prompt_template，但长期"注册可见未接线"——没有任何生成环节消费。
本模块把"该不该在本章注入这个技法"从 realizer 里独立出来，按两个轴匹配：

1. 题材轴：从 bundle.genre（如 "myth-shanhai"）取前缀 + taxonomy_tags +
   fusion_formula 组成题材签名，匹配 skill 包的适用题材。
2. 原语轴：从本章 IR 的 beat.primitives（8 原语：Conflict/Suspense/
   TurningPoint/Revelation/Sacrifice/Betrayal/Recognition/GoalFormation）
   匹配 skill 包适用的叙事场景。

匹配规则（任一 skill）：
- 双命中（题材+原语都中）→ 高优先级，必注入
- 仅题材命中且该包无原语约束（题材常驻技法）→ 注入
- 仅原语命中且该包无题材约束（通用结构技法）→ 注入
- 仅题材命中但该包有原语约束而本章无该原语 → 不注入（场景还没到）
- 仅原语命中但该包题材不匹配 → 不注入（题材不符，如武侠技法注入言情）

为避免 prompt 过长，默认上限 4 个，按优先级（双命中 > 单命中）排序后截断。
全模块纯函数、零 LLM、零副作用，可独立测试。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SkillRule:
    """一个 skill 包的触发规则。

    name:        skill 包 manifest name（与 registry.packs("story.skill")
                 的 PluginInstance.name 对齐）
    genre_kw:    适用题材关键词（任一命中题材签名即题材匹配）；空 tuple =
                 无题材约束（通用技法）
    primitives:  适用原语名（任一命中本章 beat primitives 即场景匹配）；空
                 tuple = 无场景约束（题材常驻）
    priority:    手工优先级权重（同分时排序用，默认 0）
    """
    name: str
    genre_kw: tuple[str, ...] = ()
    primitives: tuple[str, ...] = ()
    priority: int = 0


# 14 个 story.skill 包的触发规则。genre_kw 用题材前缀/标签词（小写），
# primitives 用 creativity.primitives 的 8 原语类名。
#
# 题材前缀规律（见 meta/genre_taxonomy.py + plugins/genres/*.yaml）：
#   wuxia-/xianxia-/xuanhuan-  武侠·仙侠·玄幻（战斗、江湖、宗门）
#   romance-/palace-/short-drama-  言情·宫斗·短剧（情感、虐恋、反转）
#   mystery-/infinite-/cosmic-/horror-/legal-  悬疑·无限·克苏鲁·恐怖·律政
#   myth-  神话（混合：战斗+伏笔+反转都常见）
#   urban-power-/system-  都市异能·系统（混合）
SKILL_TRIGGER_MAP: tuple[SkillRule, ...] = (
    # ===== 武侠 / 江湖 / 仙玄（战斗系）=====
    SkillRule("martial-combat-pacing",
              genre_kw=("wuxia", "xianxia", "xuanhuan", "jianghu", "martial",
                        "sword", "mecha", "military", "myth", "urban-power"),
              primitives=("Conflict",),
              priority=10),
    SkillRule("martial-as-metaphor",
              genre_kw=("wuxia", "xianxia", "xuanhuan", "jianghu", "martial",
                        "sword", "myth"),
              primitives=("Conflict", "TurningPoint"),
              priority=8),
    SkillRule("jianghu-debt-escalation",
              genre_kw=("wuxia", "jianghu", "xianxia", "xuanhuan"),
              primitives=("Conflict", "TurningPoint"),
              priority=7),
    # ===== 言情 / 虐恋 / 宫斗 / 短剧（情感系）=====
    SkillRule("concealed-sacrifice-reveal",
              genre_kw=("romance", "palace", "short-drama", "otome", "sweet",
                        "ceo", "chase", "rebirth", "stand-in", "harem"),
              primitives=("Sacrifice",),
              priority=9),
    SkillRule("escalating-misunderstanding",
              genre_kw=("romance", "palace", "short-drama", "otome", "sweet",
                        "ceo", "chase", "dark", "rebirth"),
              primitives=("Betrayal", "TurningPoint"),
              priority=7),
    SkillRule("push-pull-tension",
              genre_kw=("romance", "palace", "short-drama", "otome", "sweet",
                        "ceo", "chase", "rebirth", "vampire", "werewolf",
                        "romantasy"),
              primitives=("Conflict",),
              priority=8),
    # ===== 悬疑 / 推理 / 惊悚（智斗系）=====
    SkillRule("courtroom-interrogation",
              genre_kw=("mystery", "infinite", "cosmic", "horror", "legal",
                        "spy", "prosecutor", "gongan", "court", "psych",
                        "detective", "forensic"),
              primitives=("Recognition", "Conflict"),
              priority=9),
    SkillRule("deliberate-slip",
              genre_kw=("mystery", "infinite", "cosmic", "horror", "legal",
                        "spy", "prosecutor", "gongan", "detective", "forensic"),
              primitives=("Revelation", "Recognition"),
              priority=8),
    SkillRule("evidence-chain-buildup",
              genre_kw=("mystery", "infinite", "cosmic", "horror", "legal",
                        "spy", "prosecutor", "gongan", "detective", "forensic"),
              primitives=("Revelation", "TurningPoint"),
              priority=8),
    SkillRule("false-lead-redirection",
              genre_kw=("mystery", "infinite", "cosmic", "horror", "spy",
                        "thriller", "detective"),
              primitives=("Revelation", "TurningPoint", "Suspense"),
              priority=7),
    # ===== 通用结构技法（题材不限，按原语/章位匹配）=====
    SkillRule("cliffhanger-split",
              genre_kw=(),            # 全题材适用
              primitives=("Suspense",),
              priority=6),
    SkillRule("hidden-thread-foreshadow",
              genre_kw=(),            # 全题材适用
              primitives=("Suspense", "Revelation"),
              priority=6),
    SkillRule("foreshadow-echo",
              genre_kw=(),            # 全题材适用
              primitives=("Revelation", "Recognition"),
              priority=6),
    SkillRule("identity-reversal-impact",
              genre_kw=(),            # 全题材适用
              primitives=("TurningPoint", "Revelation", "Betrayal"),
              priority=7),
)


def _prim_name(p) -> str:
    """从 beat.primitives 元素稳健提取原语类名。

    元素可能是：字符串名（"Conflict"）/ 类对象（Conflict）/ 实例。
    """
    if isinstance(p, str):
        return p.strip()
    name = getattr(p, "__name__", None)   # 类对象
    if isinstance(name, str):
        return name
    return type(p).__name__                # 实例


def beat_primitive_names(ir) -> set[str]:
    """本章所有 beat 出现过的原语类名集合（去重）。ir 为 None/无 beats → 空 set。"""
    names: set[str] = set()
    if ir is None:
        return names
    beats = getattr(ir, "beats", None) or []
    for b in beats:
        for p in (getattr(b, "primitives", None) or []):
            names.add(_prim_name(p))
    return names


def genre_signature(bundle) -> str:
    """题材签名：bundle.genre 前缀 + taxonomy_tags + fusion_formula 词，小写拼接。

    用于子串匹配 genre_kw。例如 myth-shanhai（taxonomy_tags=[myth,sinosphere]）
    → "myth shanhai myth sinosphere"。
    """
    if bundle is None:
        return ""
    tokens: list[str] = []
    genre = (getattr(bundle, "genre", "") or "").lower()
    if genre:
        tokens.extend(part for part in genre.replace("_", "-").split("-") if part)
    params = getattr(bundle, "genre_params", None) or {}
    tags = params.get("taxonomy_tags") or []
    if isinstance(tags, list):
        tokens.extend(str(t).lower() for t in tags)
    fusion = (params.get("fusion") or {})
    if isinstance(fusion, dict):
        formula = fusion.get("fusion_formula") or fusion.get("core_conflict") or ""
        if isinstance(formula, str):
            tokens.extend(
                w for w in formula.lower().replace("×", " ").replace("/", " ").split()
                if w)
    return " ".join(dict.fromkeys(tokens))   # 去重保序


def select_skills(bundle, ir, *, max_skills: int = 4) -> list[str]:
    """按题材+原语双轴匹配，返回命中的 skill 包 name 列表（已排序截断）。

    规则见模块 docstring。返回空 list 表示本章无适用技法（prompt 与现状一致）。
    """
    sig = genre_signature(bundle)
    prims = beat_primitive_names(ir)
    scored: list[tuple[int, int, str]] = []   # (match_score, priority, name)
    for rule in SKILL_TRIGGER_MAP:
        genre_hit = (not rule.genre_kw) or any(
            kw in sig for kw in rule.genre_kw)
        prim_hit = (not rule.primitives) or any(
            pn in prims for pn in rule.primitives)
        # 无任何触发条件的包（不应出现）跳过
        if not rule.genre_kw and not rule.primitives:
            continue
        if genre_hit and prim_hit:
            # 双命中（含"无约束轴自动为真"的情形）：
            #   - 通用包(genre_kw 空) + 原语命中 → prim_hit 真，genre_hit 真(空kw)
            #   - 题材常驻(primitives 空) + 题材命中 → 同理
            #   - 双轴都有且都命中
            scored.append((2, rule.priority, rule.name))
        elif genre_hit and not rule.primitives:
            # 题材命中 + 无原语约束 = 题材常驻技法
            scored.append((2, rule.priority, rule.name))
        elif prim_hit and not rule.genre_kw:
            # 原语命中 + 无题材约束 = 通用结构技法
            scored.append((2, rule.priority, rule.name))
        # 其余（仅题材命中但有原语约束 / 仅原语命中但有题材约束）→ 不注入
    # 排序：match_score 降序 → priority 降序 → name 稳定
    scored.sort(key=lambda t: (-t[0], -t[1], t[2]))
    out: list[str] = []
    for _score, _pri, name in scored:
        if name not in out:
            out.append(name)
        if len(out) >= max_skills:
            break
    return out
