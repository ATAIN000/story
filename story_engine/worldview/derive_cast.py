"""人物原型推导（P15.2）：worldview + language profile → 建议阵容

规则映射（无 LLM）：从世界观关键参数推导每个角色的 CHAR1-CHAR5 值，
从语言文化 profile 推导中文人设标签，从冲突架构推导弧光类型。

返回 2-4 个角色（1 主角 + 1-3 配角），每个含 persona 字典。
素材来源：docs/角色原型与性格分类_完整调研v2.md + docs/世界观架构_参数全表.md。

P19.1：接受可选 genre_params，从中提取真实人物名（复用 meta.cast.parse_cast
三级兜底：cast 段 → prompt.characters → 题材原型推导名）。无 genre_params
时退回原行为（泛称「主角」「重要配角」），向后兼容。
"""
from __future__ import annotations

from .layers import option_label


def derive_cast(worldview_layers: dict | None = None,
                language_layers: dict | None = None,
                genre_params: dict | None = None) -> list[dict]:
    """从世界观 + 语言 profile 推导建议阵容。

    参数：
      worldview_layers: {L0: {param: value}, ...}（WorldviewProfile.layers 同构）
      language_layers: {LANG1: {param: value}, ...}（可选，补充人设标签推导）
      genre_params: 题材插件 params dict（可选，P19.1 提取真实人物名）

    返回：[{name, role, persona: {pearson_primary, pearson_secondary,
      schmidt_goddess, schmidt_polarity, enneagram_type, enneagram_wing,
      narrative_function, arc_type, arc_lie, arc_want, arc_need, arc_truth,
      tropes, mckee_contradiction_text}}]
    P23.1：名字落到泛称兜底（主角/重要配角/对手/引路人）时附带
    ``placeholder: True`` —— 泛称是角色身份不是人名（曾有项目把「死者」
    当真人名落盘），前端据标记提示用户命名。

    P19.1：name 优先从 genre_params 的 cast 段 / prompt.characters 提取（复用
    meta.cast.parse_cast），取不到时用题材 archetype 推导合理名，最后退回泛称。
    """
    wv = _flat(worldview_layers)
    lang = _flat(language_layers)

    # P19.1：从题材提取真实人物名（parse_cast 三级兜底：cast 段 →
    # prompt.characters → mock 种子；mock 种子是包青天，不适合，所以只用前两级）
    real_names = _extract_genre_names(genre_params)

    # 主角原型：从物理偏离度 + 形而上学推导
    pearson_main = _pearson_from_worldview(wv)
    schmidt_main = _schmidt_from_worldview(wv)
    enneagram_main = _enneagram_from_worldview(wv)
    arc_main = _arc_from_conflict(wv)
    tropes_main = _tropes_from_language(lang)
    func_main = "hero"

    has_name = bool(real_names)
    protagonist = _make_char(
        name=real_names[0] if has_name else "主角", role="主角",
        placeholder=not has_name,
        narrative_function=func_main,
        pearson_primary=pearson_main,
        schmidt_goddess=schmidt_main,
        enneagram_type=enneagram_main,
        arc_type=arc_main,
        tropes=tropes_main,
    )
    cast = [protagonist]

    # 配角 1：互补原型（探索者/智者/照顾者，视主角而定）
    support1_pearson = _complementary_pearson(pearson_main)
    support1 = _make_char(
        name=real_names[1] if len(real_names) > 1 else "重要配角", role="配角",
        placeholder=len(real_names) <= 1,
        narrative_function="ally",
        pearson_primary=support1_pearson,
        schmidt_goddess="none",
        enneagram_type=_complementary_enneagram(enneagram_main),
        arc_type="flat_positive" if arc_main != "flat_positive" else "positive_change",
        tropes="none",
    )
    cast.append(support1)

    # 配角 2（可选）：反派/阴影——当冲突类型为 cosmic/ideological 时
    conflict = wv.get("conflict_types", "")
    if conflict in ("cosmic", "ideological", "civilizational"):
        villain = _make_char(
            name=real_names[2] if len(real_names) > 2 else "对手", role="反派",
            placeholder=len(real_names) <= 2,
            narrative_function="threshold_guardian",
            pearson_primary=_shadow_pearson(pearson_main),
            schmidt_goddess="none",
            schmidt_polarity="villain",
            enneagram_type="8" if enneagram_main != "8" else "3",
            arc_type="fall",
            tropes="none",
        )
        cast.append(villain)

    # 配角 3（可选）：导师——当力量体系为修炼/学习型时
    acquisition = wv.get("acquisition_method", "")
    if acquisition in ("cultivation", "study", "bestowal"):
        mentor = _make_char(
            name=real_names[3] if len(real_names) > 3 else "引路人", role="导师",
            placeholder=len(real_names) <= 3,
            narrative_function="mentor",
            pearson_primary="sage",
            schmidt_goddess="none",
            enneagram_type="5" if enneagram_main != "5" else "9",
            arc_type="flat_positive",
            tropes="hidden_master" if "hidden_master" not in tropes_main else "none",
        )
        cast.append(mentor)

    # 配角 4（可选）：竞争者/同伴——当世界有阶层/势力冲突时
    stratification = wv.get("stratification_basis", "")
    if stratification in ("birth", "power", "wealth") or conflict in ("cosmic", "ideological", "civilizational"):
        rival = _make_char(
            name=real_names[4] if len(real_names) > 4 else "竞争者", role="同伴",
            placeholder=len(real_names) <= 4,
            narrative_function="rival_turned_ally",
            pearson_primary=_complementary_pearson(pearson_main) if support1_pearson != "seeker" else "orphan",
            schmidt_goddess="none",
            enneagram_type="3" if enneagram_main != "3" else "7",
            arc_type="corruption",
            tropes="none",
        )
        cast.append(rival)

    return cast[:5]   # 最多 5 人


# ---------- 映射规则 ----------

_PEARSON_MAP = {
    # physics_deviation
    "major": "magician", "total": "magician",
    "minor": "warrior", "none": "warrior",
    # metaphysics（覆盖物理偏离度取值）
    "materialist": "warrior", "idealist": "magician",
    "animist": "seeker", "dualist": "seeker",
}

_SCHMIDT_MAP = {
    "materialist": "athena", "dualist": "hera",
    "idealist": "isis", "animist": "artemis",
}

_ENNEAGRAM_MAP = {
    "major": "5", "total": "5",
    "minor": "8", "none": "8",
    "materialist": "8", "idealist": "4",
    "animist": "9", "dualist": "6",
}

_ARC_MAP = {
    "cosmic": "positive_change", "ideological": "positive_change",
    "personal_vendetta": "fall", "civilizational": "disillusionment",
    "survival": "positive_change", "inheritance": "flat_positive",
}


def _pearson_from_worldview(wv: dict) -> str:
    pd = wv.get("physics_deviation", "")
    if pd in _PEARSON_MAP:
        return _PEARSON_MAP[pd]
    meta = wv.get("metaphysics", "")
    return _PEARSON_MAP.get(meta, "seeker")


def _schmidt_from_worldview(wv: dict) -> str:
    meta = wv.get("metaphysics", "")
    return _SCHMIDT_MAP.get(meta, "none")


def _enneagram_from_worldview(wv: dict) -> str:
    pd = wv.get("physics_deviation", "")
    if pd in _ENNEAGRAM_MAP:
        return _ENNEAGRAM_MAP[pd]
    meta = wv.get("metaphysics", "")
    return _ENNEAGRAM_MAP.get(meta, "7")


def _arc_from_conflict(wv: dict) -> str:
    ct = wv.get("conflict_types", "")
    return _ARC_MAP.get(ct, "positive_change")


def _tropes_from_language(lang: dict) -> str:
    """从语言文化推导人设标签——叙事可靠性不可靠 → hidden_master / chongsheng_chuanyue"""
    reliability = lang.get("narrative_reliability", "")
    if reliability == "unreliable_by_design":
        return "hidden_master"
    classifier = lang.get("classifier_system", "")
    if classifier == "power_marked":
        return "bazong"
    return "none"


def _complementary_pearson(main: str) -> str:
    """主角原型的互补配角原型"""
    pairs = {
        "warrior": "caregiver", "magician": "sage",
        "seeker": "orphan", "creator": "ruler",
    }
    return pairs.get(main, "caregiver")


def _complementary_enneagram(main: str) -> str:
    pairs = {
        "5": "7", "8": "2", "4": "7", "6": "9",
        "7": "5", "9": "3",
    }
    return pairs.get(main, "9")


def _shadow_pearson(main: str) -> str:
    """主角的阴影/反派原型"""
    shadows = {
        "warrior": "revolutionary", "magician": "ruler",
        "seeker": "ruler", "creator": "destroyer",
    }
    return shadows.get(main, "revolutionary")


def _make_char(*, name, role, narrative_function, pearson_primary,
               schmidt_goddess, enneagram_type, arc_type, tropes,
               schmidt_polarity="positive", placeholder=False) -> dict:
    """构建单角色建议（persona 含 CHAR1-CHAR5 全字段）"""
    arc_lie, arc_want, arc_need, arc_truth = _arc_texts(arc_type, pearson_primary)
    return {
        "name": name,
        "role": role,
        "placeholder": placeholder,   # P23.1：泛称名标记（前端提示命名）
        "persona": {
            "narrative_function": narrative_function,
            "pearson_primary": pearson_primary,
            "pearson_secondary": "none",
            "schmidt_goddess": schmidt_goddess,
            "schmidt_polarity": schmidt_polarity,
            "enneagram_type": enneagram_type,
            "enneagram_wing": "none",
            "mckee_contradiction_text": _contradiction_text(pearson_primary, enneagram_type),
            "arc_type": arc_type,
            "arc_lie": arc_lie,
            "arc_want": arc_want,
            "arc_need": arc_need,
            "arc_truth": arc_truth,
            # 兼容：保留 _text 后缀字段供旧代码读
            "arc_lie_text": arc_lie,
            "arc_want_text": arc_want,
            "arc_need_text": arc_need,
            "arc_truth_text": arc_truth,
            "tropes": tropes,
        },
    }


def _arc_texts(arc_type: str, pearson: str) -> tuple[str, str, str, str]:
    """根据弧光类型生成 Lie/Want/Need/Truth 文本"""
    templates = {
        "positive_change": (
            "力量决定一切，弱者不配拥有自由",
            "变得更强，掌控自己的命运",
            "真正的力量来自与他人的联结",
            "强大不是孤独，而是守护所爱之人",
        ),
        "fall": (
            "我能掌控一切而不付出代价",
            "获得绝对的力量与权力",
            "力量的代价是失去人性",
            "凡人不应僭越神之领域",
        ),
        "flat_positive": (
            "正义总会胜利",
            "守护身边重要的人",
            "坚持信念本身就是意义",
            "真正的英雄改变世界而非改变自己",
        ),
        "corruption": (
            "只要目的正确，手段无所谓",
            "实现伟大的目标",
            "目的不能证明手段的正当",
            "堕落从不始于大恶，始于小妥协",
        ),
        "disillusionment": (
            "世界是公平的，努力就有回报",
            "获得应得的认可与地位",
            "世界本不公平，但仍值得为之奋斗",
            "真相虽痛，但幻觉更危险",
        ),
    }
    return templates.get(arc_type, templates["positive_change"])


def _contradiction_text(pearson: str, enneagram: str) -> str:
    """McKee 矛盾维度一句话——根据原型×九型组合生成角色内心矛盾。

    旧版只有4个组合，其余全走兜底"外表坚强内心渴望被理解"，
    导致配角/反派/导师矛盾维度千篇一律。扩展到覆盖全部原型。
    """
    pairs = {
        # warrior 原型
        ("warrior", "8"): "渴望保护他人却恐惧暴露自身脆弱",
        ("warrior", "3"): "追求荣耀却恐惧被遗忘",
        ("warrior", "6"): "渴望守护秩序却恐惧权威的压迫",
        ("warrior", "1"): "追求正义却恐惧自己成为暴君",
        # caregiver 原型
        ("caregiver", "2"): "渴望被需要却恐惧失去自我",
        ("caregiver", "9"): "渴望和谐却恐惧直面冲突",
        ("caregiver", "6"): "渴望守护他人却恐惧自己不够强大",
        ("caregiver", "4"): "渴望理解他人痛苦却恐惧被他人的黑暗吞噬",
        # revolutionary 原型
        ("revolutionary", "8"): "渴望推翻压迫却恐惧自己成为新的暴君",
        ("revolutionary", "3"): "渴望改变世界却恐惧失去自我认同",
        ("revolutionary", "7"): "渴望自由却恐惧责任的束缚",
        ("revolutionary", "1"): "渴望理想社会却恐惧人性的不可改变",
        # sage 原型
        ("sage", "5"): "追求终极真理却恐惧知识带来的后果",
        ("sage", "9"): "追求内心平静却被迫面对外界冲突",
        ("sage", "1"): "追求正确答案却恐惧真相的破坏性",
        ("sage", "4"): "追求深层理解却恐惧被误解和孤立",
        # seeker 原型
        ("seeker", "7"): "渴望自由冒险却恐惧真正停下脚步",
        ("seeker", "4"): "渴望找到归属却恐惧失去独特性",
        ("seeker", "5"): "渴望探索未知却恐惧发现自己的无知",
        # magician 原型
        ("magician", "5"): "追求终极真理却恐惧知识带来的后果",
        ("magician", "8"): "渴望变革却恐惧力量的失控",
        ("magician", "4"): "渴望创造奇迹却恐惧平庸的现实",
        # creator 原型
        ("creator", "4"): "渴望创造完美却恐惧作品暴露真实的自己",
        ("creator", "7"): "渴望无限可能却恐惧做出选择",
        # ruler 原型
        ("ruler", "8"): "渴望掌控秩序却恐惧失控的混乱",
        ("ruler", "3"): "渴望建立帝国却恐惧被权力腐蚀",
        # jester 原型
        ("jester", "7"): "渴望用幽默解构一切却恐惧面对真实的痛苦",
        ("jester", "2"): "渴望逗乐他人却恐惧自己不被认真对待",
        # lover 原型
        ("lover", "2"): "渴望深度联结却恐惧被抛弃",
        ("lover", "4"): "渴望灵魂伴侣却恐惧亲密关系中的失去",
        # orphan 原型
        ("orphan", "6"): "渴望归属却恐惧被背叛",
        ("orphan", "9"): "渴望平凡安稳却恐惧被世界遗忘",
    }
    return pairs.get((pearson, enneagram), f"追求{pearson}的核心价值却恐惧其反面")


# 泛称（角色类型描述，不是人名）——_extract_genre_names 过滤掉这些
_GENERIC_ROLE_LABELS = frozenset({
    "主角", "重要配角", "配角", "对手", "对手/阻力", "反派", "同伴",
    "引路人", "导师", "死者", "情人", "爱人", "旁观者", "叙述者",
})


def _extract_genre_names(genre_params: dict | None) -> list[str]:
    """P19.1：从题材 params 提取真实人物名。

    复用 meta.cast.parse_cast 的前两级（cast 段 → prompt.characters）；
    第三级 mock 种子（包青天）不适用于新题材，故不使用。
    过滤泛称（主角/配角/对手等角色类型描述）——taxonomy 生成的题材其
    prompt.characters 只有角色类型无具体人名，_parse_l2 会把「主角」当
    名字提取，这里剔掉。无可用名 → 空列表（调用方退回泛称 + placeholder）。
    """
    if not genre_params or not isinstance(genre_params, dict):
        return []
    try:
        from ..meta.cast import _parse_l1, _parse_l2
    except ImportError:
        return []
    members = _parse_l1(genre_params.get("cast"), genre_params)
    if not members:
        prompt = genre_params.get("prompt") or {}
        members = _parse_l2(prompt.get("characters"), genre_params)
    return [m.id for m in members
            if m.id and m.id not in _GENERIC_ROLE_LABELS]


def _flat(layers: dict | None) -> dict[str, str]:
    """分层 {L0: {k: v}} → 扁平 {k: v}"""
    out: dict[str, str] = {}
    if not layers or not isinstance(layers, dict):
        return out
    for params in layers.values():
        if isinstance(params, dict):
            for k, v in params.items():
                if isinstance(v, str):
                    out[k] = v
    return out


async def name_cast_with_llm(cast: list[dict], worldview_layers: dict | None,
                             genre_params: dict | None, llm_call,
                             genre_name: str = "") -> list[dict]:
    """对 cast 中 placeholder=True 的角色，用 LLM 根据人物特点+世界观起名。

    原地修改 cast（替换 name 字段，清 placeholder 标记），返回 cast。
    LLM 调用失败/mock 模式/无 placeholder → 原样返回（不阻塞流程）。

    单次 LLM 调用为全部 placeholder 角色起名（一次性批量，省 token）。
    """
    placeholders = [(i, c) for i, c in enumerate(cast)
                    if c.get("placeholder") or c.get("name") in _GENERIC_ROLE_LABELS]
    if not placeholders:
        return cast

    # 构建 prompt（给足世界设定信息，让名字贴合世界观气质）
    wv = _flat(worldview_layers)
    setting_hints = []
    if wv.get("power_source"):
        setting_hints.append(f"力量来源={wv['power_source']}")
    if wv.get("conflict_types"):
        setting_hints.append(f"冲突类型={wv['conflict_types']}")
    if wv.get("political_system"):
        setting_hints.append(f"政治体制={wv['political_system']}")
    if wv.get("cosmo_scope"):
        setting_hints.append(f"宇宙尺度={wv['cosmo_scope']}")
    if wv.get("power_existence"):
        setting_hints.append(f"力量存在={wv['power_existence']}")
    setting = "；".join(setting_hints) if setting_hints else ""

    title = ""
    if genre_params:
        title = genre_params.get("title", "") or genre_name

    char_descs = []
    for _i, c in placeholders:
        persona = c.get("persona", {})
        role = c.get("role", "")
        # 把角色的完整设定发给 LLM（不只是原型+矛盾）
        parts = [f"{role}"]
        p = persona.get("pearson_primary", "")
        if p: parts.append(f"原型={p}")
        e = persona.get("enneagram_type", "")
        if e: parts.append(f"九型={e}")
        ct = persona.get("mckee_contradiction_text", "")
        if ct: parts.append(f"矛盾={ct}")
        at = persona.get("arc_type", "")
        if at: parts.append(f"弧光={at}")
        al = persona.get("arc_lie", "")
        aw = persona.get("arc_want", "")
        if al: parts.append(f"执念={al}")
        if aw: parts.append(f"追求={aw}")
        tr = persona.get("tropes", "")
        if tr and tr != "none": parts.append(f"标签={tr}")
        nf = persona.get("narrative_function", "")
        if nf: parts.append(f"功能={nf}")
        char_descs.append("（".join([parts[0], "，".join(parts[1:])]) + "）" if len(parts) > 1 else parts[0])

    # 世界观全层级摘要（不只是力量+冲突）
    wv_hints = []
    for label, key in [("力量来源", "power_source"), ("冲突类型", "conflict_types"),
                        ("政治体制", "political_system"), ("宇宙尺度", "cosmo_scope"),
                        ("力量存在", "power_existence"), ("获取方式", "acquisition_method"),
                        ("核心价值", "core_values"), ("宗教类型", "religion_type"),
                        ("经济体系", "economic_system"), ("知识分配", "knowledge_distribution")]:
        v = wv.get(key)
        if v: wv_hints.append(f"{label}={v}")
    wv_summary = "；".join(wv_hints)

    prompt = (
        f"你是一位专业的玄幻/网文小说角色设计师。\n"
        f"请为以下《{title or genre_name}》题材小说的角色起中文人名（2-3字，有辨识度，符合世界观的气质）。\n\n"
        f"=== 世界设定 ===\n{wv_summary}\n\n"
        f"=== 需要命名的角色 ===\n"
        + "\n".join(f"- {d}" for d in char_descs) + "\n\n"
        f"要求：名字要贴合角色的原型气质和世界观设定，"
        f"各角色名字风格要统一（同一世界观下），但要有辨识度不能太像。\n"
        f'只输出JSON数组，{len(placeholders)}个名字，不要其他文字：'
        f'["名字","名字"]')

    try:
        import json
        resp = await llm_call(prompt, purpose="cast_naming",
                              temperature=0.8, max_tokens=16384,
                              no_retry=True)
        text = resp.text.strip() if hasattr(resp, "text") else str(resp).strip()
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return cast
        names = json.loads(text[start:end + 1])
        if not isinstance(names, list) or len(names) != len(placeholders):
            return cast
        for (idx, _c), name in zip(placeholders, names):
            if isinstance(name, str) and name.strip():
                cast[idx]["name"] = name.strip()
                cast[idx]["placeholder"] = False
    except Exception:
        pass  # LLM 起名失败不阻塞，保留泛称
    return cast
