"""Mock 剧本 — 《包青天·玉佩案》3 章演示数据

设计意图（对应深度验证报告的三类实测违规）：
- 第1章：认知违规（Epistemic EC）— 复刻 worldstate_paradox 的 D 组情形：
  生成 LLM "看到"赌债设定就让包拯直接点破 → 检查出「包拯此时不知道」→ 修正为合法审问
- 第2章：物理违规（Event Calculus）— 展昭人在赌坊却出现在公堂呈证
  → 修正为补一个"赶回开封府"的状态转移事件
- 第3章：世界规则违规（Z3 / Sanderson 第一律）— 冤魂托梦直接定罪
  → 修正为"梦只做氛围，突破来自证据链汇合"

文本标记：⟪v⟫…⟪/v⟫ = 违规片段（前端标红）；⟪f⟫…⟪/f⟫ = 修正片段（前端标绿）。
事件是对齐文本的"候选世界事件"，由验证器逐步硬约束检查。
"""
from __future__ import annotations

import json
import re

# ============ 初始世界（seed） ============

SEED_CHARACTERS = {
    "包拯":   {"role": "开封府尹", "archetype": "判官", "voice": "沉毅克制，少言而中"},
    "展昭":   {"role": "御前护卫", "archetype": "侠客", "voice": "利落干脆"},
    "公孙策": {"role": "师爷",     "archetype": "谋士", "voice": "缜密斯文"},
    "刘伯":   {"role": "王府管家", "archetype": "嫌疑人", "voice": "恭谨藏怯"},
    "王员外": {"role": "苦主",     "archetype": "受害者", "voice": "焦灼哀恳"},
}

SEED_PHYSICAL = {
    "at(包拯,开封府)": True, "at(展昭,开封府)": True, "at(公孙策,开封府)": True,
    "at(刘伯,王府)": True, "at(王员外,王府)": True,
    "alive(包拯)": True, "alive(展昭)": True, "alive(公孙策)": True,
    "alive(刘伯)": True, "alive(王员外)": True, "alive(张三)": True,
}

SEED_MINDS = {
    "包拯":   {"beliefs": {}, "secrets": [], "goals": ["查明玉佩案真相", "维护律法公正"],
               "affect": {"沉静": 0.9, "悲悯": 0.5}},
    "展昭":   {"beliefs": {}, "secrets": [], "goals": ["护卫包拯", "查访线索"],
               "affect": {"忠诚": 0.9}},
    "公孙策": {"beliefs": {}, "secrets": [], "goals": ["辅佐断案"],
               "affect": {"谨慎": 0.8}},
    "刘伯":   {"beliefs": {}, "secrets": ["赌债累累", "案发夜不在房中"],
               "goals": ["保住管家之位", "掩盖赌债"], "affect": {"惶恐": 0.7}},
    "王员外": {"beliefs": {"玉佩失窃": True}, "secrets": [],
               "goals": ["寻回玉佩"], "affect": {"焦灼": 0.8}},
}

SEED_RELATIONS = {
    "包拯|展昭":   {"type": "信任", "intensity": 0.9, "history": ["御前指派"]},
    "包拯|公孙策": {"type": "信任", "intensity": 0.85, "history": ["多年辅佐"]},
    "王员外|刘伯": {"type": "主仆", "intensity": 0.6, "history": []},
}

SEED_CAUSAL_LINKS = ["玉佩失窃→王员外报案"]

# ============ 第1章：报案与初审（认知违规） ============

CH1_DRAFT = """第一日·辰时，开封府衙。

王员外跪呈状纸，称家传玉佩于昨夜失窃，府中上下无人能解其踪。包拯览状，目光沉静，令其具述始末。

午时，包拯提审管家刘伯。刘伯跪伏堂下，叩首不止，口称尽忠职守。

包拯突然冷声道：⟪v⟫"哦？尽忠职守？那你近来在聚宝赌坊欠下的三千两银子，又作何解释？"⟪/v⟫

刘伯浑身一震，脸色煞白："大人……大人如何得知……"

包拯冷笑：⟪v⟫"本府自有耳目。你且说来，案发之夜，你当真在前厅守夜？"⟪/v⟫"""

CH1_EVENTS = [
    {"event_type": "world_change", "summary": "时间推进：第1日·辰时",
     "payload": {"field": "story_time", "new_value": "第1日·辰时"}},
    {"event_type": "character_action", "summary": "王员外报案",
     "payload": {"agent": "王员外", "action": "报案", "story_time": "第1日·辰时",
                 "serves_goal": "寻回玉佩", "motivation": "玉佩失窃",
                 "establishes_cause": ["王员外报案→包拯受理"]}},
    {"event_type": "character_action", "summary": "包拯受理案件",
     "payload": {"agent": "包拯", "action": "受理案件", "story_time": "第1日·辰时",
                 "serves_goal": "查明玉佩案真相", "motivation": "玉佩失窃",
                 "effects": {"learn": {"包拯": ["玉佩失窃", "王员外称府中三嫌疑人"]}}}},
    {"event_type": "character_action", "summary": "包拯点破刘伯赌债（违规）",
     "payload": {"agent": "包拯", "action": "点破赌债", "story_time": "第1日·午时",
                 "serves_goal": "查明玉佩案真相", "motivation": "玉佩失窃",
                 "requires_knowing": ["刘伯赌债"]}},
    {"event_type": "narrative_beat", "summary": "第1章节拍：公堂初审",
     "payload": {"chapter": 1, "scene": "开封府公堂", "tension": 0.45,
                 "track_progress": {"A": 0.15, "B": 0.2, "C": 0.05, "D": 0.0, "E": 0.1}}},
]

CH1_CORRECTED = """第一日·辰时，开封府衙。

王员外跪呈状纸，称家传玉佩于昨夜失窃，府中上下无人能解其踪。包拯览状，目光沉静，令其具述始末。

午时，包拯提审管家刘伯。刘伯跪伏堂下，叩首不止。

⟪f⟫"刘伯，你是王府管家，王府上下可有你不知之事？"
刘伯叩首："大人，小人尽忠职守，府中事务无不亲力亲为。"
包拯微微点头："好。本府问你，三更时分，你在何处？"
"小人……小人在前厅守夜。"
刘伯答话时，袖口微颤，露出半角当票。包拯目光一凝，按下不表，挥手道："先退下吧。"⟪/f⟫"""

CH1_CORRECTED_EVENTS = [
    CH1_EVENTS[0], CH1_EVENTS[1], CH1_EVENTS[2],
    {"event_type": "character_action", "summary": "包拯询问刘伯行踪（合法审问）",
     "payload": {"agent": "包拯", "action": "询问行踪", "story_time": "第1日·午时",
                 "serves_goal": "查明玉佩案真相", "motivation": "玉佩失窃",
                 "effects": {"learn": {"包拯": ["刘伯自称案发夜在前厅守夜"]}}}},
    {"event_type": "character_action", "summary": "刘伯掩饰（袖口当票）",
     "payload": {"agent": "刘伯", "action": "掩饰", "story_time": "第1日·午时",
                 "serves_goal": "掩盖赌债", "motivation": "玉佩失窃"}},
    CH1_EVENTS[4],
]

# ============ 第2章：暗访赌坊（物理违规） ============

CH2_DRAFT = """第二日·清晨，包拯唤展昭至书房，低声吩咐数语。展昭领命，换作客商打扮，径往城南聚宝赌坊。

赌坊内烟雾缭绕。展昭坐定半日，与账房攀谈。账房起先支吾，展昭亮出腰牌，账房方吐露实情：王府管家刘伯是此地常客，欠下三千两赌债；案发那夜，他三更才从赌坊后门离开。

展昭抄录账册条目，收入怀中。

⟪v⟫午时三刻，展昭在开封府公堂呈上抄录的账册。⟪/v⟫包拯逐条看过，指节轻叩案面："刘伯……" """

CH2_EVENTS = [
    {"event_type": "world_change", "summary": "时间推进：第2日·清晨",
     "payload": {"field": "story_time", "new_value": "第2日·清晨"}},
    {"event_type": "character_action", "summary": "包拯遣展昭暗访",
     "payload": {"agent": "包拯", "action": "遣展昭暗访", "story_time": "第2日·清晨",
                 "serves_goal": "查明玉佩案真相", "motivation": "玉佩失窃",
                 "effects": {"set_fluents": ["at(展昭,聚宝赌坊)"],
                             "unset_fluents": ["at(展昭,开封府)"]}}},
    {"event_type": "character_action", "summary": "展昭查得刘伯赌债与行踪",
     "payload": {"agent": "展昭", "action": "查访赌坊", "story_time": "第2日·上午",
                 "serves_goal": "查访线索", "motivation": "玉佩失窃",
                 "effects": {"learn": {"展昭": ["刘伯赌债", "刘伯案发夜现身赌坊"]}}}},
    {"event_type": "character_action", "summary": "展昭公堂呈账册（违规：人未回府）",
     "payload": {"agent": "展昭", "action": "呈上账册", "story_time": "第2日·午时",
                 "serves_goal": "查访线索", "motivation": "玉佩失窃",
                 "physical_preconditions": ["at(展昭,开封府)"],
                 "effects": {"learn": {"包拯": ["刘伯赌债", "刘伯案发夜不在房中"]}}}},
    {"event_type": "narrative_beat", "summary": "第2章节拍：暗访得证",
     "payload": {"chapter": 2, "scene": "聚宝赌坊→开封府", "tension": 0.62,
                 "track_progress": {"A": 0.4, "B": 0.6, "C": 0.3, "D": 0.0, "E": 0.2}}},
]

CH2_CORRECTED = """第二日·清晨，包拯唤展昭至书房，低声吩咐数语。展昭领命，换作客商打扮，径往城南聚宝赌坊。

赌坊内烟雾缭绕。展昭坐定半日，与账房攀谈。账房起先支吾，展昭亮出腰牌，账房方吐露实情：王府管家刘伯是此地常客，欠下三千两赌债；案发那夜，他三更才从赌坊后门离开。

展昭抄录账册条目，收入怀中。⟪f⟫他不再停留，出得坊门翻身上马，连夜路也不避，赶回开封府。⟪/f⟫

午时三刻，展昭在开封府公堂呈上抄录的账册。包拯逐条看过，指节轻叩案面："刘伯……" """

CH2_CORRECTED_EVENTS = [
    CH2_EVENTS[0], CH2_EVENTS[1], CH2_EVENTS[2],
    {"event_type": "character_action", "summary": "展昭赶回开封府（补状态转移）",
     "payload": {"agent": "展昭", "action": "赶回开封府", "story_time": "第2日·午时",
                 "serves_goal": "查访线索", "motivation": "玉佩失窃",
                 "effects": {"set_fluents": ["at(展昭,开封府)"],
                             "unset_fluents": ["at(展昭,聚宝赌坊)"]}}},
    {"event_type": "character_action", "summary": "展昭公堂呈账册",
     "payload": {"agent": "展昭", "action": "呈上账册", "story_time": "第2日·午时",
                 "serves_goal": "查访线索", "motivation": "玉佩失窃",
                 "physical_preconditions": ["at(展昭,开封府)"],
                 "effects": {"learn": {"包拯": ["刘伯赌债", "刘伯案发夜不在房中"]}}}},
    CH2_EVENTS[4],
]

# ============ 第3章：夜审与收网（Sanderson 违规） ============

CH3_DRAFT = """第三日·子时，包拯独坐书房，烛影摇红。

恍惚间，阴风穿堂，烛火尽绿。一白衣冤魂立于案前，泣诉道："害我者张三，左腕带伤……"言毕而散。

包拯猛然惊醒，冷汗透衣。

⟪v⟫次日升堂，包拯据此梦兆签票拿人，将张三锁拿归案，当堂定罪：谋财害命，窃取玉佩，铁案如山。⟪/v⟫"""

CH3_EVENTS = [
    {"event_type": "world_change", "summary": "时间推进：第3日·子时",
     "payload": {"field": "story_time", "new_value": "第3日·子时"}},
    {"event_type": "character_action", "summary": "包拯夜梦冤魂（氛围）",
     "payload": {"agent": "包拯", "action": "夜梦冤魂", "story_time": "第3日·子时",
                 "has_supernatural": True, "is_resolution": False}},
    {"event_type": "character_action", "summary": "包拯据梦定罪（违规：鬼神解案）",
     "payload": {"agent": "包拯", "action": "据梦定罪", "story_time": "第3日·辰时",
                 "serves_goal": "查明玉佩案真相",
                 "has_supernatural": True, "is_resolution": True}},
    {"event_type": "narrative_beat", "summary": "第3章节拍：夜审收网",
     "payload": {"chapter": 3, "scene": "开封府书房→公堂", "tension": 0.85,
                 "track_progress": {"A": 0.65, "B": 0.8, "C": 0.45, "D": 0.0, "E": 0.35}}},
]

CH3_CORRECTED = """第三日·子时，包拯独坐书房，烛影摇红。

恍惚间，阴风穿堂，烛火尽绿。似有白衣人影立于案前，欲言又止。包拯猛然惊醒，冷汗透衣，⟪f⟫静坐良久，自忖："梦境幽渺，不足为凭。断案须得实证。"⟪/f⟫

次日升堂。⟪f⟫公孙策呈上玉佩拓片——内侧所刻小字，竟是"张记永宝"四字。包拯再传刘伯，刘伯见赌债之事已无可遮掩，只得供认：案发夜里，他曾见一个左腕带伤的客人鬼祟出入王府角门。

赌债是动机，刻字是物证，目击是人证。三链汇合，包拯签票缉拿张三。⟪/f⟫"""

CH3_CORRECTED_EVENTS = [
    CH3_EVENTS[0], CH3_EVENTS[1],
    {"event_type": "character_action", "summary": "包拯自省：梦不足凭",
     "payload": {"agent": "包拯", "action": "自省", "story_time": "第3日·寅时",
                 "serves_goal": "维护律法公正"}},
    {"event_type": "character_action", "summary": "公孙策呈玉佩刻字（物证）",
     "payload": {"agent": "公孙策", "action": "呈玉佩刻字", "story_time": "第3日·辰时",
                 "serves_goal": "辅佐断案", "motivation": "玉佩失窃",
                 "effects": {"learn": {"包拯": ["玉佩内侧刻字「张记永宝」"]}}}},
    {"event_type": "character_action", "summary": "刘伯供认目击者（人证）",
     "payload": {"agent": "刘伯", "action": "供认", "story_time": "第3日·辰时",
                 "serves_goal": "保住管家之位", "motivation": "玉佩失窃",
                 "effects": {"learn": {"包拯": ["案发夜左腕带伤者出入王府角门"]}}}},
    {"event_type": "character_action", "summary": "包拯签票缉拿张三（证据链驱动）",
     "payload": {"agent": "包拯", "action": "签票缉拿", "story_time": "第3日·午时",
                 "serves_goal": "查明玉佩案真相", "motivation": "玉佩失窃",
                 "is_resolution": False,
                 "effects": {"set_fluents": ["at(张三,开封府大牢)"]}}},
    CH3_EVENTS[3],
]

# ============ 章节注册表 ============

DRAFTS = {
    1: {"title": "报案与初审", "text": CH1_DRAFT, "events": CH1_EVENTS},
    2: {"title": "暗访赌坊", "text": CH2_DRAFT, "events": CH2_EVENTS},
    3: {"title": "夜审与收网", "text": CH3_DRAFT, "events": CH3_EVENTS},
}

CORRECTIONS = {
    1: {"text": CH1_CORRECTED, "events": CH1_CORRECTED_EVENTS,
        "note": "删除包拯直接点破赌债的对白，改为合法审问；以「袖口当票」埋下视觉伏笔"},
    2: {"text": CH2_CORRECTED, "events": CH2_CORRECTED_EVENTS,
        "note": "补「展昭赶回开封府」状态转移事件，物理链闭合"},
    3: {"text": CH3_CORRECTED, "events": CH3_CORRECTED_EVENTS,
        "note": "冤魂托梦仅作氛围（Sanderson 第二律：限制>能力）；定罪改为刻字物证+目击人证+赌债动机三链汇合"},
}

# 伏笔（CFPG）生命周期脚本
FORESHADOW_SCRIPT = {
    1: {"planted": [
            {"foreshadow_id": "F1", "content": "玉佩内侧刻有小字",
             "trigger_condition": "验看玉佩", "payoff": "刻字「张记永宝」指向张三",
             "required": True},
            {"foreshadow_id": "F2", "content": "刘伯案发夜不在房中（袖口当票）",
             "trigger_condition": "查访行踪", "payoff": "赌坊账房证实刘伯案发夜现身",
             "required": True}],
        "payed": []},
    2: {"planted": [
            {"foreshadow_id": "F3", "content": "与刘伯同来的左腕带伤客人",
             "trigger_condition": "排查嫌疑人", "payoff": "张三左腕有旧伤",
             "required": True}],
        "payed": ["F2"]},
    3: {"planted": [
            {"foreshadow_id": "F4", "content": "张三自称案发夜在邻县探亲",
             "trigger_condition": "提审张三", "payoff": "待续（下一章验证不在场证明）",
             "required": False}],
        "payed": ["F1", "F3"]},
}

CHAPTER_TITLES = {1: "报案与初审", 2: "暗访赌坊", 3: "夜审与收网"}


# ============ Mock LLM 响应路由 ============

def respond(purpose: str, prompt: str) -> str:
    m = re.search(r"【CHAPTER=(\d+)】", prompt)
    chapter = int(m.group(1)) if m else 1
    if purpose == "generate_chapter":
        return DRAFTS.get(chapter, DRAFTS[3])["text"]
    if purpose == "extract_events":
        return json.dumps(DRAFTS.get(chapter, DRAFTS[3])["events"], ensure_ascii=False)
    if purpose == "correct_chapter":
        return CORRECTIONS[chapter]["text"]
    if purpose == "extract_corrected_events":
        return json.dumps(CORRECTIONS[chapter]["events"], ensure_ascii=False)
    return ""
