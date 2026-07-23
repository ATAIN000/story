"""跨层冲突检测引擎（Patch A / ③.5）

规则化检测 5 类跨层冲突（C1-C5），不调 LLM。从 genre_params +
worldview_profile + cast_profile 提取关键值做匹配，命中 known_conflicts
模式库则产出 ConflictWarning。

五类检测规则（素材 docs/开局向导升级方案_跨层检测+交互流程.md §2.1-2.5）：
- C1 题材核心承诺 vs 世界观力量体系（fair_deduction + 预知能力 = 破坏推理公平）
- C2 人物身份 vs 世界观社会结构（提刑官 + 神权社会 = 权力来源冲突）
- C3 力量体系多源矛盾（≥2 种力量来源未定义关系）
- C4 世界观基调 vs 题材节奏要求（末日废土 + 快节奏甜宠 = 基调冲突）
- C5 语言质感 vs 题材对白密度（文白相间 + 高密度对话 = 阅读负担）

设计约束：
- 纯规则匹配，零 LLM 调用
- 模式库从素材逐条数据化（~30 条已知冲突模式）
- 容忍部分填写（无值的参数跳过，不报错）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConflictWarning:
    """单条跨层冲突警告"""
    type: str           # "C1"-"C5"
    severity: str       # "HIGH" / "MEDIUM" / "LOW"
    title: str          # 冲突标题
    description: str    # 冲突描述
    suggestion: str     # 修正建议


# ============================================================
# 辅助：从各种格式提取 worldview flat dict
# ============================================================

def _to_flat(worldview_profile) -> dict[str, str]:
    """从 WorldviewProfile / dict / flat dict 提取 {param_key: value}"""
    if worldview_profile is None:
        return {}
    # WorldviewProfile 实例
    if hasattr(worldview_profile, "as_flat"):
        return worldview_profile.as_flat()
    # dict with "layers" key
    if isinstance(worldview_profile, dict):
        if "layers" in worldview_profile and isinstance(worldview_profile["layers"], dict):
            flat: dict[str, str] = {}
            for _layer_id, params in worldview_profile["layers"].items():
                if isinstance(params, dict):
                    for k, v in params.items():
                        if isinstance(v, str):
                            flat[k] = v
            return flat
        # already flat
        return {k: v for k, v in worldview_profile.items() if isinstance(v, str)}
    return {}


# ============================================================
# C1: 题材核心承诺 vs 世界观力量体系
# ============================================================

def _derive_core_promise(genre_params: dict, genre_name: str = "") -> str:
    """从 genre_params 推导 core_promise 概念。
    素材 2.1：fair_deduction / power_fantasy / emotional_resonance
    """
    name = (genre_name or "").lower()
    params = genre_params or {}

    # fair_play / fair_deduction：推理公平承诺
    if params.get("information_distribution") == "fair_play":
        return "fair_deduction"

    # 甜宠/言情 → emotional_resonance
    if any(kw in name for kw in ("romance", "甜宠", "言情", "sweet")):
        return "emotional_resonance"

    # 升级/爽文 → power_fantasy
    if any(kw in name for kw in ("isekai", "升级", "爽", "system", "dungeon", "pathway")):
        return "power_fantasy"

    # 默认：由 pacing/progression 推断
    if params.get("pacing_curve") in ("fast_escalation", "dtg_staircase"):
        return "power_fantasy"

    return ""


def _check_c1(genre_params: dict, genre_name: str, wv: dict[str, str]) -> list[ConflictWarning]:
    """C1: 题材核心承诺 vs 力量体系（素材 §2.1）"""
    warnings: list[ConflictWarning] = []
    promise = _derive_core_promise(genre_params, genre_name)
    if not promise:
        return warnings

    power_source = wv.get("power_source", "")
    acquisition = wv.get("acquisition_method", "")
    cost = wv.get("cost_structure", "")
    progression = wv.get("progression_model", "")
    power_existence = wv.get("power_existence", "")

    if promise == "fair_deduction":
        # 公案悬疑 + 遗传记忆/预知/读心 → HIGH
        # acquisition=awakening（觉醒=超自然能力觉醒）
        if acquisition == "awakening":
            warnings.append(ConflictWarning(
                type="C1", severity="HIGH",
                title="公平推理 × 超自然觉醒能力",
                description="题材承诺公平推理（fair_play），但世界观中角色可觉醒超自然能力，"
                            "主角可能获得读者无法推理的不对称信息。",
                suggestion="给能力加代价（每次用消耗寿命）或限制（只能看过去不能看未来），"
                           "或改为所有角色都能获取。"))
        # bloodline = 血脉天赋（遗传记忆/读心类）
        if power_source == "bloodline":
            warnings.append(ConflictWarning(
                type="C1", severity="HIGH",
                title="公平推理 × 血脉天赋",
                description="题材承诺公平推理，但力量来源为血脉天赋，主角可能拥有遗传记忆或"
                            "读心等不对称信息获取能力，破坏推理公平性。",
                suggestion="限制血脉能力为辅助手段（不能作为破案关键），或给能力加严格代价。"))
        # innate = 先天天赋（不对称信息）
        if acquisition == "innate" and power_existence in ("rare", "unique"):
            warnings.append(ConflictWarning(
                type="C1", severity="MEDIUM",
                title="公平推理 × 先天不对称能力",
                description="题材承诺公平推理，但力量为少数人先天天赋，主角可能获得不对称信息。",
                suggestion="改为全民皆有（universal）力量，或明确限制天赋不涉及信息获取。"))
        # granted = 被赋予（神赐预知类）
        if acquisition == "granted":
            warnings.append(ConflictWarning(
                type="C1", severity="HIGH",
                title="公平推理 × 神赐能力",
                description="题材承诺公平推理，但力量获取方式为「被赋予」（神赐/契约/传承），"
                            "主角可能获得超自然信息获取能力。",
                suggestion="限制神赐能力为战斗/防御类（非信息类），或给能力加代价。"))

    elif promise == "power_fantasy":
        # 力量升级爽文 + 无明确 power_scaling
        if progression == "none":
            warnings.append(ConflictWarning(
                type="C1", severity="MEDIUM",
                title="力量爽感 × 无进阶体系",
                description="题材承诺力量爽感，但世界观力量体系无进阶模型，"
                            "打脸/升级的爽感无法量化。",
                suggestion="设定明确的进阶模型（线性等级/境界突破/技能树等）。"))
        # 力量升级爽文 + 现代写实法律
        if wv.get("political_system") in ("republic", "meritocracy", "technocracy"):
            warnings.append(ConflictWarning(
                type="C1", severity="HIGH",
                title="力量爽文 × 现代法治社会",
                description="现代法律体系下暴力解决问题=犯罪，力量升级的爽感变成不安。",
                suggestion="加入灰色地带（地下世界/系统空间/异世界），或设定力量体系与法律并行。"))
        # cost=none → 无张力
        if cost == "none" and power_existence != "nonexistent":
            warnings.append(ConflictWarning(
                type="C1", severity="MEDIUM",
                title="力量爽感 × 无代价力量",
                description="力量体系无代价结构，容易变成无张力爽文，角色可以无限使用力量。",
                suggestion="设定代价结构（消耗资源/反噬/时间代价等），增加策略性。"))

    elif promise == "emotional_resonance":
        # 甜宠言情 + 末日/恐怖环境
        tone = wv.get("environment_type", "") or wv.get("physics_deviation", "")
        if any(kw in tone for kw in ("apocalyps", "wasteland", "horror", "末日", "废土")):
            warnings.append(ConflictWarning(
                type="C1", severity="MEDIUM",
                title="情感共鸣 × 末日/恐怖环境",
                description="末日环境的基础不安全感与甜宠/言情的情感安全感承诺冲突。",
                suggestion="设立安全区/日常系空间作为缓冲，或调整为末世治愈方向。"))
        # 情感共鸣 + 社会结构过于宽松（缺少阻碍）
        social = wv.get("political_system", "")
        if social in ("anarchy", "post_scarcity"):
            warnings.append(ConflictWarning(
                type="C1", severity="MEDIUM",
                title="情感共鸣 × 缺乏社会张力",
                description="社会结构过于宽松（无政府/后稀缺），缺少制造虐恋/禁忌的社会张力。",
                suggestion="加入阶层分化或制度性阻碍，制造情感冲突的社会来源。"))

    return warnings


# ============================================================
# C2: 人物身份 vs 世界观社会结构
# ============================================================

# 身份 → 社会制度依赖映射（素材 §2.2 detection_logic 第 3 步）
_IDENTITY_DEPENDENCIES: list[dict] = [
    {
        "role_keywords": ["提刑", "府尹", "推官", "知府", "知县", "判官"],
        "needs_political": ["monarchy", "meritocracy"],
        "conflict_political": ["theocracy", "anarchy"],
        "label": "官僚司法官员",
        "reason_fmt": "{role}权威来自皇帝和法律，{conflict}社会权威来源不同→权力来源冲突",
        "fix": "①改身份为对应社会结构的职业 ②在世界观中加入世俗皇权与{conflict}的制衡",
    },
    {
        "role_keywords": ["骑士", "武士", "侍从"],
        "needs_political": ["monarchy", "feudal"],
        "conflict_political": ["republic", "anarchy", "corporatocracy"],
        "label": "封建军事贵族",
        "reason_fmt": "{role}依赖封建领主制+军事贵族体系，{conflict}社会不存在封建结构",
        "fix": "①改为对应的{conflict}社会职业 ②世界观加入封建元素",
    },
    {
        "role_keywords": ["侦探", "警察", "警官", "检察官", "律师", "医生"],
        "needs_political": ["republic", "meritocracy", "technocracy"],
        "conflict_political": ["feudal", "tribal", "sect_based"],
        "label": "现代职业",
        "reason_fmt": "{role}依赖现代制度，{conflict}社会不存在此类职业体系",
        "fix": "①改为对应的古代/异世界职业 ②世界观加入现代制度元素",
    },
    {
        "role_keywords": ["修士", "和尚", "僧", "尼", "神官", "祭司"],
        "needs_political": ["theocracy", "monarchy"],
        "conflict_political": ["corporatocracy", "technocracy"],
        "label": "宗教人士",
        "reason_fmt": "{role}依赖宗教组织+精神权威，{conflict}社会缺乏宗教制度基础",
        "fix": "①在世界观中加入宗教组织设定 ②改身份为世俗职业",
    },
    {
        "role_keywords": ["修真", "修仙", "仙人", "剑修"],
        "needs_political": ["sect_based", "tribal", "monarchy"],
        "conflict_political": ["republic"],
        "label": "修真者",
        "reason_fmt": "修真者的力量等级天然形成不平等，与{conflict}制冲突",
        "fix": "①社会结构改为长老制/宗门制 ②解释力量体系如何与{conflict}共存",
    },
    {
        "role_keywords": ["商人", "商贾", "掌柜"],
        "needs_economic": ["mercantile", "capitalist"],
        "conflict_economic": ["command", "barter"],
        "label": "商人",
        "reason_fmt": "{role}依赖市场经济+财产权保护，{conflict}经济体系不支持自由商业",
        "fix": "①改为对应的{conflict}经济体系下的角色 ②世界观加入商业元素",
    },
]


def _check_c2(cast_profile: list[dict], wv: dict[str, str]) -> list[ConflictWarning]:
    """C2: 人物身份 vs 社会结构（素材 §2.2）"""
    warnings: list[ConflictWarning] = []
    if not cast_profile:
        return warnings

    political = wv.get("political_system", "")
    economic = wv.get("economic_system", "")

    for char in cast_profile:
        if not isinstance(char, dict):
            continue
        role = str(char.get("role", "")) + str(char.get("name", ""))
        name = char.get("name", char.get("role", "角色"))

        for dep in _IDENTITY_DEPENDENCIES:
            if not any(kw in role for kw in dep["role_keywords"]):
                continue

            # 检查政治体制冲突
            if "conflict_political" in dep and political in dep["conflict_political"]:
                conflict_label = political
                warnings.append(ConflictWarning(
                    type="C2", severity="HIGH",
                    title=f"{dep['label']} × {conflict_label}社会",
                    description=dep["reason_fmt"].format(role=name, conflict=conflict_label),
                    suggestion=dep["fix"].format(conflict=conflict_label)))
                break  # 每个角色最多触发一条 C2

            # 检查经济体系冲突
            if "conflict_economic" in dep and economic in dep["conflict_economic"]:
                conflict_label = economic
                warnings.append(ConflictWarning(
                    type="C2", severity="MEDIUM",
                    title=f"{dep['label']} × {conflict_label}经济",
                    description=dep["reason_fmt"].format(role=name, conflict=conflict_label),
                    suggestion=dep["fix"].format(conflict=conflict_label)))
                break

    return warnings


# ============================================================
# C3: 力量体系多源矛盾
# ============================================================

# C3 known_conflicts（素材 §2.3）：多力量来源未定义关系
_C3_CONFLICT_PAIRS: list[dict] = [
    {
        "sources": ["external_environmental", "theft"],
        "title": "环境汲取 + 夺取力量（未定义关系）",
        "description": "读者不知道环境汲取与夺取（吸功/吞噬）是同源的真相/谎言，"
                       "还是完全不同的两套体系。",
        "suggestion": "在世界观L3明确定义：如「帝国宣称力量来自环境汲取，实际是灵魂吞噬的伪装」",
    },
    {
        "sources": ["knowledge_based", "systemic"],
        "title": "魔法/知识 + 系统面板（未定义关系）",
        "description": "魔法符文体系和系统面板数值化是互补还是互斥？读者需要知道规则。",
        "suggestion": "定义：如「魔法可以驱动系统面板」或「系统面板取代了传统魔法」",
    },
    {
        "sources": ["internal", "granted"],
        "title": "身体自生 + 被赋予（未定义关系）",
        "description": "内功/血脉自生力量与神赐/契约力量的关系未定义。",
        "suggestion": "定义：如「神赐力量激活了体内沉睡的血脉之力」",
    },
    {
        "sources": ["bloodline", "systemic"],
        "title": "血脉天赋 + 系统面板（未定义关系）",
        "description": "血脉天赋和系统面板的力量来源关系未定义，读者困惑两套体系如何共存。",
        "suggestion": "定义：如「系统面板量化了血脉天赋的能力」",
    },
]


def _check_c3(wv: dict[str, str]) -> list[ConflictWarning]:
    """C3: 力量体系多源矛盾（素材 §2.3）"""
    warnings: list[ConflictWarning] = []
    power_source = wv.get("power_source", "")
    acquisition = wv.get("acquisition_method", "")

    # power_source=mixed → 直接警告（多种来源混合但关系未定义）
    if power_source == "mixed":
        warnings.append(ConflictWarning(
            type="C3", severity="MEDIUM",
            title="多来源混合力量（关系未定义）",
            description="力量来源为「多来源混合」，但各来源之间的关系（同源/互斥/互补/层级）未明确定义。",
            suggestion="在世界观L3明确定义各力量来源的关系（如同源变体/互斥体系/互补体系/层级体系）。"))
        return warnings

    # 检查已知冲突组合（power_source × acquisition_method）
    all_sources = {power_source, acquisition}
    for pair in _C3_CONFLICT_PAIRS:
        if all(s in all_sources for s in pair["sources"]):
            warnings.append(ConflictWarning(
                type="C3", severity="MEDIUM",
                title=pair["title"],
                description=pair["description"],
                suggestion=pair["suggestion"]))
            break  # 一组 C3 足够

    return warnings


# ============================================================
# C4: 世界观基调 vs 题材节奏要求
# ============================================================

# C4 known_conflicts（素材 §2.4）
_C4_GENRE_PACE: dict[str, str] = {
    # genre_name_keyword → 节奏要求
    "mystery": "high_density",       # 公案悬疑：要求高信息密度
    "detective": "high_density",
    "horror": "slow_burn",           # 恐怖：要求缓慢渗透
    "cthulhu": "slow_burn",
    "romance": "medium",
    "甜宠": "medium",
    "isekai": "fast",               # 异世界：快节奏升级
    "system": "fast",
}


def _check_c4(genre_params: dict, genre_name: str, wv: dict[str, str]) -> list[ConflictWarning]:
    """C4: 世界观基调 vs 题材节奏要求（素材 §2.4）"""
    warnings: list[ConflictWarning] = []
    name = (genre_name or "").lower()
    params = genre_params or {}

    # 推导题材的节奏要求
    pace_req = ""
    for kw, pace in _C4_GENRE_PACE.items():
        if kw in name:
            pace_req = pace
            break
    if not pace_req:
        pacing_curve = params.get("pacing_curve", "")
        if pacing_curve == "slow_burn":
            pace_req = "slow_burn"
        elif pacing_curve in ("fast_escalation", "dtg_staircase"):
            pace_req = "fast"

    if not pace_req:
        return warnings

    # 世界观基调推断
    physics_dev = wv.get("physics_deviation", "")
    environment = wv.get("environment_type", "")
    wv_tone_slow = False  # 世界观是否天然适合慢节奏
    wv_tone_fast = False

    if any(kw in (physics_dev + environment).lower() for kw in
           ("apocalyps", "wasteland", "末日", "废土", "major")):
        wv_tone_slow = True
    if physics_dev in ("none", "minor"):
        wv_tone_fast = True

    # 公案悬疑（要求高信息密度）+ 慢热世界观
    if pace_req == "high_density" and wv_tone_slow:
        warnings.append(ConflictWarning(
            type="C4", severity="MEDIUM",
            title="高信息密度题材 × 慢热世界观",
            description="公案悬疑要求每集有推理推进，慢热世界观前几集全是铺垫会违反节奏要求。",
            suggestion="①pacing_curve 改为紧凑型 ②在铺垫集也插入线索 ③减少集数"))

    # 恐怖/克苏鲁（要求缓慢渗透）+ 快节奏
    if pace_req == "slow_burn" and wv_tone_fast:
        warnings.append(ConflictWarning(
            type="C4", severity="MEDIUM",
            title="恐怖题材 × 快节奏世界观",
            description="恐怖需要压抑感的缓慢积累，快节奏会破坏恐怖氛围。",
            suggestion="①pacing_curve 改为 slow_burn ②在快节奏段用 jump scare 补偿"))

    return warnings


# ============================================================
# C5: 语言质感 vs 题材对白密度
# ============================================================

def _check_c5(genre_params: dict, genre_name: str, wv: dict[str, str]) -> list[ConflictWarning]:
    """C5: 语言质感 vs 题材对白密度（素材 §2.5）"""
    warnings: list[ConflictWarning] = []
    name = (genre_name or "").lower()
    params = genre_params or {}

    # 高对白密度题材：职场/公案/言情的对白比例较高
    high_dialogue_genres = ("mystery", "court", "workplace", "romance", "甜宠", "职场")
    is_high_dialogue = any(kw in name for kw in high_dialogue_genres)
    # 也通过 beats_per_chapter 推断
    if not is_high_dialogue and params.get("beats_per_chapter", 0) >= 5:
        is_high_dialogue = True

    if not is_high_dialogue:
        return warnings

    # LANG3 语域层级深度：deep = 文白相间/等级森严
    register_depth = wv.get("register_hierarchy_depth", "")
    if register_depth == "deep":
        warnings.append(ConflictWarning(
            type="C5", severity="LOW",
            title="高对白密度 × 深层语域等级",
            description="深层语域等级（6+级敬语）在高频对话中显得拖沓，增加阅读负担。",
            suggestion="①对白用口语，旁白用文白 ②缩短句长 ③适当简化语域层级"))

    return warnings


# ============================================================
# C6: 题材 × 世界观骨架三轴亲和（P22：同源 taxonomy）
# ============================================================

def _check_c6_affinity(genre_name: str, wv_preset: str | None) -> list[ConflictWarning]:
    """题材与所选世界观骨架不亲和 → MEDIUM（可继续，不阻塞）。

    亲和表取 genre_taxonomy（primary + secondary presets）；未知题材 /
    未选骨架 → 不出警。
    """
    if not genre_name or not wv_preset:
        return []
    from ..meta.genre_taxonomy import (
        is_preset_compatible, presets_for_genre, taxon_by_id)
    if is_preset_compatible(genre_name, wv_preset):
        return []
    taxon = taxon_by_id(genre_name)
    if taxon is None:
        return []
    recommended = "、".join(presets_for_genre(genre_name))
    return [ConflictWarning(
        type="C6",
        severity="MEDIUM",
        title="题材与骨架亲和度低",
        description=(
            f"题材「{taxon.title}」的推荐世界观骨架是 {recommended}，"
            f"当前选择的「{wv_preset}」不在亲和列表内——生成可继续，"
            "但题材承诺与底层世界规则可能互相稀释。"),
        suggestion=f"改用推荐骨架（{recommended}），或在创作中刻意经营这种错位感。")]


# ============================================================
# 公开入口
# ============================================================

def check_cross_layer(
    genre_params: dict | None = None,
    worldview_profile=None,
    cast_profile: list[dict] | None = None,
    genre_name: str = "",
    wv_preset: str | None = None,
) -> list[ConflictWarning]:
    """跨层冲突检测主入口。

    参数：
      genre_params: 题材参数 dict（genre bundle 的 params）
      worldview_profile: WorldviewProfile 实例 / {"layers": {...}} / flat dict
      cast_profile: 人物阵容 list[{name, role, persona}]
      genre_name: 题材名（用于关键词匹配）
      wv_preset: 世界观骨架 key（P22 C6 亲和检测；None 跳过）

    返回：list[ConflictWarning]，按 severity 排序（HIGH > MEDIUM > LOW）
    """
    genre_params = genre_params or {}
    cast_profile = cast_profile or []
    wv = _to_flat(worldview_profile)

    warnings: list[ConflictWarning] = []
    warnings.extend(_check_c1(genre_params, genre_name, wv))
    warnings.extend(_check_c2(cast_profile, wv))
    warnings.extend(_check_c3(wv))
    warnings.extend(_check_c4(genre_params, genre_name, wv))
    warnings.extend(_check_c5(genre_params, genre_name, wv))
    warnings.extend(_check_c6_affinity(genre_name, wv_preset))

    # 按严重性排序
    severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    warnings.sort(key=lambda w: severity_order.get(w.severity, 9))
    return warnings
