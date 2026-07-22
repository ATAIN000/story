"""人物原型推导（P15.2）：worldview + language profile → 建议阵容

规则映射（无 LLM）：从世界观关键参数推导每个角色的 CHAR1-CHAR5 值，
从语言文化 profile 推导中文人设标签，从冲突架构推导弧光类型。

返回 2-4 个角色（1 主角 + 1-3 配角），每个含 persona 字典。
素材来源：docs/角色原型与性格分类_完整调研v2.md + docs/世界观架构_参数全表.md。
"""
from __future__ import annotations

from .layers import option_label


def derive_cast(worldview_layers: dict | None = None,
                language_layers: dict | None = None) -> list[dict]:
    """从世界观 + 语言 profile 推导建议阵容。

    参数：
      worldview_layers: {L0: {param: value}, ...}（WorldviewProfile.layers 同构）
      language_layers: {LANG1: {param: value}, ...}（可选，补充人设标签推导）

    返回：[{name, role, persona: {pearson_primary, pearson_secondary,
      schmidt_goddess, schmidt_polarity, enneagram_type, enneagram_wing,
      narrative_function, arc_type, arc_lie, arc_want, arc_need, arc_truth,
      tropes, mckee_contradiction_text}}]
    """
    wv = _flat(worldview_layers)
    lang = _flat(language_layers)

    # 主角原型：从物理偏离度 + 形而上学推导
    pearson_main = _pearson_from_worldview(wv)
    schmidt_main = _schmidt_from_worldview(wv)
    enneagram_main = _enneagram_from_worldview(wv)
    arc_main = _arc_from_conflict(wv)
    tropes_main = _tropes_from_language(lang)
    func_main = "hero"

    protagonist = _make_char(
        name="主角", role="主角",
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
        name="重要配角", role="配角",
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
            name="对手", role="反派",
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
            name="引路人", role="导师",
            narrative_function="mentor",
            pearson_primary="sage",
            schmidt_goddess="none",
            enneagram_type="5" if enneagram_main != "5" else "9",
            arc_type="flat_positive",
            tropes="hidden_master" if "hidden_master" not in tropes_main else "none",
        )
        cast.append(mentor)

    return cast[:4]   # 最多 4 人


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
               schmidt_polarity="positive") -> dict:
    """构建单角色建议（persona 含 CHAR1-CHAR5 全字段）"""
    arc_lie, arc_want, arc_need, arc_truth = _arc_texts(arc_type, pearson_primary)
    return {
        "name": name,
        "role": role,
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
    """McKee 矛盾维度一句话"""
    pairs = {
        ("warrior", "8"): "渴望保护他人却恐惧暴露自身脆弱",
        ("magician", "5"): "追求终极真理却恐惧知识带来的后果",
        ("seeker", "7"): "渴望自由冒险却恐惧真正停下脚步",
        ("sage", "9"): "追求内心平静却被迫面对外界冲突",
    }
    return pairs.get((pearson, enneagram), "外表坚强内心渴望被理解")


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
