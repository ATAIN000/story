"""Module 5.1 分层IR — L0-L5 全输出 IR 不输出自然语言（蓝图 5.1 字段逐字）

只有 L5 末端 realizer 绑定语言（中文/英文/日文）。

IR 承载两层数据：
  - 事件语义层（5W）：语言无关
  - 质感参数层（texture）：语言相关，由 realizer 解读

【Phase 5 计划决策1 简化声明】
`did`/subtext 的「概念 ID」不引入 WordNet/HowNet 库——用本地概念映射表：
- CONCEPT_IDS：event_type/action 关键词 → 概念 ID 字符串（如 accuse → act:accuse、
  fear → emo:fear），覆盖 types.py EventType 全部取值 + 常见 action 词
- 未知词回退 act:unknown / emo:unknown（不崩），见 to_concept_id()
- SubtextInterlingua.map_to(language)：本地映射表 INTERLINGUA_ZH / INTERLINGUA_EN
  （概念 ID → 本语言表达）；无命中返回概念 ID 本身，调用方可比对
  返回值 == 概念 ID 判断漂移（见 map_to docstring）

（ir_builder / fabula_sjuzhet / realizer / humanize 是后续任务，本文件不建。）
"""
from __future__ import annotations

from dataclasses import dataclass

from ..types import Goal


@dataclass
class IntentIR:
    """L_intent: PDDL风格意图层"""
    characters: list[str]
    goals: list[Goal]           # types.py 已有 Goal（P3.5）
    world_state: dict
    primitives: list            # StoryPrimitive 引用（creativity/primitives.py）


@dataclass
class BeatIR:
    """L_plot: beat序列 — Todorov 5态 × Genre beats"""
    beat_id: str
    phase: str              # equilibrium/disruption/...
    primitives: list
    emotion_target: str     # Reagan弧坐标
    tension: float


@dataclass
class EventIR:
    """L_event: AMR风格事件层 — 事件语义层真正语言无关"""
    who: str
    did: str               # predicate (语言无关概念ID)
    to_whom: str | None
    where: str
    when: str              # 相对时间
    how: str | None        # manner
    why: str | None        # motivation
    subtext: "SubtextInterlingua | None"


@dataclass
class SubtextInterlingua:
    """跨语言可对齐的潜台词表达"""
    emotion_concept: str       # 概念ID, 如 emo:fear
    social_concept: str | None
    intensity: float           # 强度0-1

    def map_to(self, language: str) -> str:
        """由 realizer 映射到目标语言的最接近表达（本地映射表版）。

        漂移标注约定：emotion_concept 在目标语言表中无命中（或 language 本身
        无表）时，返回概念 ID 本身——返回纯字符串无法内嵌漂移度，调用方比对
        返回值 == self.emotion_concept 即可判断发生漂移。social_concept 命中时
        以「情感+社会」组合返回；未命中则忽略（不致崩，漂移判断仍以主概念为准）。
        """
        table = _INTERLINGUA_TABLES.get(language)
        if table is None:
            return self.emotion_concept
        expr = table.get(self.emotion_concept)
        if expr is None:
            return self.emotion_concept
        if self.social_concept is not None:
            social_expr = table.get(self.social_concept)
            if social_expr is not None:
                return f"{expr}+{social_expr}"
        return expr


@dataclass
class DialogueIR:
    """对话IR — 含叙述/对话语域差"""
    speaker: str
    illocution: str            # Speech Act言外之力
    content_concept: str       # 内容概念ID(语言无关)
    emotion_concept: str       # 情感概念ID
    politeness: str            # bald/positive/negative/off_record
    register: str              # narrative_register / dialogue_register


@dataclass
class TextureParams:
    """叙事质感参数 — 语言相关,由culture+language填充"""
    honorific_register: float       # 敬语密度 0-1
    emotion_explicitness: float     # 情感显隐度 0-1
    register_switching: float       # 叙述/对话语域差 0-1
    idiom_density: float            # 成语/习语密度 0-1
    sentence_length_distribution: tuple[float, float]  # 句长(均值,方差)
    implicit_vs_explicit: float     # 含蓄度 0-1
    perspective_distance: str       # 全知/限制/戏剧式
    temporal_ordering: str          # 顺叙/插叙/倒叙


@dataclass
class SceneBreakdown:
    """场景切分（蓝图引用未定义，最小定义）：event 索引区间 + 地点"""
    scene_id: str
    event_span: tuple[int, int]
    location: str


@dataclass
class NarrativeIR:
    """完整叙事IR — 传给语言realizer"""
    beats: list[BeatIR]
    events: list[EventIR]
    dialogue_lines: list[DialogueIR]
    scene_breakdown: list[SceneBreakdown]
    texture: TextureParams


# ============ 本地概念映射表（决策1 简化：不引入 WordNet/HowNet）============

CONCEPT_IDS: dict[str, str] = {
    # ---- EventType 全覆盖（types.py Literal 7 值）----
    "character_action": "act:character_action",
    "world_change": "act:world_change",
    "narrative_beat": "act:narrative_beat",
    "dialogue": "act:dialogue",
    "scene_transition": "act:scene_transition",
    "author_intervention": "act:author_intervention",
    "branch_fork": "act:branch_fork",
    # ---- 常见 action 关键词 ----
    "accuse": "act:accuse",
    "confess": "act:confess",
    "deceive": "act:deceive",
    "betray": "act:betray",
    "attack": "act:attack",
    "defend": "act:defend",
    "flee": "act:flee",
    "pursue": "act:pursue",
    "hide": "act:hide",
    "reveal": "act:reveal",
    "discover": "act:discover",
    "investigate": "act:investigate",
    "negotiate": "act:negotiate",
    "threaten": "act:threaten",
    "promise": "act:promise",
    "refuse": "act:refuse",
    "obey": "act:obey",
    "command": "act:command",
    "plead": "act:plead",
    "forgive": "act:forgive",
    "sacrifice": "act:sacrifice",
    "rescue": "act:rescue",
    "kill": "act:kill",
    "steal": "act:steal",
    "lie": "act:lie",
    "witness": "act:witness",
    "conspire": "act:conspire",
    "arrest": "act:arrest",
    "judge": "act:judge",
    "reward": "act:reward",
    "punish": "act:punish",
    "mourn": "act:mourn",
    "celebrate": "act:celebrate",
    "persuade": "act:persuade",
    "bribe": "act:bribe",
    # ---- 情感关键词（subtext 用）----
    "fear": "emo:fear",
    "anger": "emo:anger",
    "joy": "emo:joy",
    "sadness": "emo:sadness",
    "shame": "emo:shame",
    "guilt": "emo:guilt",
    "pride": "emo:pride",
    "love": "emo:love",
    "hatred": "emo:hatred",
    "envy": "emo:envy",
    "hope": "emo:hope",
    "despair": "emo:despair",
}


def to_concept_id(keyword: str, kind: str = "act") -> str:
    """关键词 → 概念 ID；未知词回退 f"{kind}:unknown"（不崩）。"""
    return CONCEPT_IDS.get(keyword, f"{kind}:unknown")


# ---- interlingua → 本语言表达（zh/en 各一套）----

INTERLINGUA_ZH: dict[str, str] = {
    "emo:fear": "恐惧",
    "emo:anger": "愤怒",
    "emo:joy": "喜悦",
    "emo:sadness": "悲伤",
    "emo:shame": "羞愧",
    "emo:guilt": "内疚",
    "emo:pride": "骄傲",
    "emo:love": "爱",
    "emo:hatred": "恨",
    "emo:envy": "嫉妒",
    "emo:hope": "希望",
    "emo:despair": "绝望",
    "soc:entitlement": "优越感",
    "soc:loyalty": "忠诚",
}

INTERLINGUA_EN: dict[str, str] = {
    "emo:fear": "fear",
    "emo:anger": "anger",
    "emo:joy": "joy",
    "emo:sadness": "sadness",
    "emo:shame": "shame",
    "emo:guilt": "guilt",
    "emo:pride": "pride",
    "emo:love": "love",
    "emo:hatred": "hatred",
    "emo:envy": "envy",
    "emo:hope": "hope",
    "emo:despair": "despair",
    "soc:entitlement": "entitlement",
    "soc:loyalty": "loyalty",
}

_INTERLINGUA_TABLES: dict[str, dict[str, str]] = {
    "zh": INTERLINGUA_ZH,
    "en": INTERLINGUA_EN,
}
