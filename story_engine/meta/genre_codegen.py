"""从 taxonomy 批量生成 genre yaml（不覆盖已有插件文件）。"""
from __future__ import annotations

from pathlib import Path

import yaml

from .genre_taxonomy import GenreTaxon, all_taxa, taxonomy_stats
from .genre_validator import validate_genre_pack

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "plugins" / "genres"
PACKS_DIR = ROOT.parents[1] / "docs" / "packs" / "story.genre"

_TRACK_PROFILES: dict[str, list[dict]] = {
    "cultivation": [
        {"id": "A", "name": "主线·修炼与大势", "arc_type": "Serialized", "archetype": "Quest", "progress": 0.0, "last_touched": 0},
        {"id": "B", "name": "副线·宗门/势力阴影", "arc_type": "Serialized", "archetype": "Monster", "progress": 0.0, "last_touched": 0},
        {"id": "C", "name": "副线·心魔与执念", "arc_type": "Serialized", "archetype": "Tragedy", "progress": 0.0, "last_touched": 0},
        {"id": "D", "name": "单元·秘境见闻", "arc_type": "Anthology", "archetype": "Quest", "progress": 0.0, "last_touched": 0, "min_main_progress": 0.3},
        {"id": "E", "name": "主题·何以为道", "arc_type": "Serialized", "archetype": "Rebirth", "progress": 0.0, "last_touched": 0},
    ],
    "martial": [
        {"id": "A", "name": "主线·江湖大案", "arc_type": "Serialized", "archetype": "Quest", "progress": 0.0, "last_touched": 0},
        {"id": "B", "name": "副线·门派恩怨", "arc_type": "Serialized", "archetype": "Tragedy", "progress": 0.0, "last_touched": 0},
        {"id": "C", "name": "副线·侠义抉择", "arc_type": "Serialized", "archetype": "Rebirth", "progress": 0.0, "last_touched": 0},
        {"id": "D", "name": "单元·客栈奇遇", "arc_type": "Anthology", "archetype": "Monster", "progress": 0.0, "last_touched": 0, "min_main_progress": 0.3},
    ],
    "fantasy": [
        {"id": "A", "name": "主线·远征与预言", "arc_type": "Serialized", "archetype": "Quest", "progress": 0.0, "last_touched": 0},
        {"id": "B", "name": "副线·宫廷/公会阴谋", "arc_type": "Serialized", "archetype": "Monster", "progress": 0.0, "last_touched": 0},
        {"id": "C", "name": "副线·同伴羁绊", "arc_type": "Serialized", "archetype": "Rebirth", "progress": 0.0, "last_touched": 0},
        {"id": "D", "name": "单元·旅途遭遇", "arc_type": "Anthology", "archetype": "Quest", "progress": 0.0, "last_touched": 0, "min_main_progress": 0.3},
        {"id": "E", "name": "主题·力量与代价", "arc_type": "Serialized", "archetype": "Tragedy", "progress": 0.0, "last_touched": 0},
    ],
    "system": [
        {"id": "A", "name": "主线·任务与升级", "arc_type": "Serialized", "archetype": "Quest", "progress": 0.0, "last_touched": 0},
        {"id": "B", "name": "副线·系统真相", "arc_type": "Serialized", "archetype": "Monster", "progress": 0.0, "last_touched": 0},
        {"id": "C", "name": "副线·势力拉拢", "arc_type": "Serialized", "archetype": "Tragedy", "progress": 0.0, "last_touched": 0},
        {"id": "D", "name": "单元·委托副本", "arc_type": "Anthology", "archetype": "Quest", "progress": 0.0, "last_touched": 0, "min_main_progress": 0.3},
        {"id": "E", "name": "主题·外挂与自主", "arc_type": "Serialized", "archetype": "Rebirth", "progress": 0.0, "last_touched": 0},
    ],
    "infinite": [
        {"id": "A", "name": "主线·副本生死", "arc_type": "Serialized", "archetype": "Quest", "progress": 0.0, "last_touched": 0},
        {"id": "B", "name": "副线·资深者博弈", "arc_type": "Serialized", "archetype": "Monster", "progress": 0.0, "last_touched": 0},
        {"id": "C", "name": "副线·信任与背叛", "arc_type": "Serialized", "archetype": "Tragedy", "progress": 0.0, "last_touched": 0},
        {"id": "D", "name": "单元·世界纪", "arc_type": "Anthology", "archetype": "Quest", "progress": 0.0, "last_touched": 0, "min_main_progress": 0.3},
        {"id": "E", "name": "主题·守住人味", "arc_type": "Serialized", "archetype": "Rebirth", "progress": 0.0, "last_touched": 0},
    ],
    "horror": [
        {"id": "A", "name": "主线·揭开禁忌", "arc_type": "Serialized", "archetype": "Quest", "progress": 0.0, "last_touched": 0},
        {"id": "B", "name": "副线·侵蚀与失控", "arc_type": "Serialized", "archetype": "Monster", "progress": 0.0, "last_touched": 0},
        {"id": "C", "name": "副线·同伴崩坏", "arc_type": "Serialized", "archetype": "Tragedy", "progress": 0.0, "last_touched": 0},
        {"id": "D", "name": "单元·怪谈事件", "arc_type": "Anthology", "archetype": "Quest", "progress": 0.0, "last_touched": 0, "min_main_progress": 0.3},
        {"id": "E", "name": "主题·认知代价", "arc_type": "Serialized", "archetype": "Rebirth", "progress": 0.0, "last_touched": 0},
    ],
    "apocalypse": [
        {"id": "A", "name": "主线·求生与据点", "arc_type": "Serialized", "archetype": "Quest", "progress": 0.0, "last_touched": 0},
        {"id": "B", "name": "副线·资源争夺", "arc_type": "Serialized", "archetype": "Monster", "progress": 0.0, "last_touched": 0},
        {"id": "C", "name": "副线·人性底线", "arc_type": "Serialized", "archetype": "Tragedy", "progress": 0.0, "last_touched": 0},
        {"id": "D", "name": "单元·废土遭遇", "arc_type": "Anthology", "archetype": "Quest", "progress": 0.0, "last_touched": 0, "min_main_progress": 0.3},
        {"id": "E", "name": "主题·希望何在", "arc_type": "Serialized", "archetype": "Rebirth", "progress": 0.0, "last_touched": 0},
    ],
    "cyber": [
        {"id": "A", "name": "主线·数据与肉身", "arc_type": "Serialized", "archetype": "Quest", "progress": 0.0, "last_touched": 0},
        {"id": "B", "name": "副线·公司黑幕", "arc_type": "Serialized", "archetype": "Monster", "progress": 0.0, "last_touched": 0},
        {"id": "C", "name": "副线·身份裂隙", "arc_type": "Serialized", "archetype": "Tragedy", "progress": 0.0, "last_touched": 0},
        {"id": "D", "name": "单元·街道委托", "arc_type": "Anthology", "archetype": "Quest", "progress": 0.0, "last_touched": 0, "min_main_progress": 0.3},
        {"id": "E", "name": "主题·何为人类", "arc_type": "Serialized", "archetype": "Rebirth", "progress": 0.0, "last_touched": 0},
    ],
    "steampunk": [
        {"id": "A", "name": "主线·齿轮与帝国", "arc_type": "Serialized", "archetype": "Quest", "progress": 0.0, "last_touched": 0},
        {"id": "B", "name": "副线·发明与禁忌", "arc_type": "Serialized", "archetype": "Monster", "progress": 0.0, "last_touched": 0},
        {"id": "C", "name": "副线·阶级裂痕", "arc_type": "Serialized", "archetype": "Tragedy", "progress": 0.0, "last_touched": 0},
        {"id": "D", "name": "单元·飞艇见闻", "arc_type": "Anthology", "archetype": "Quest", "progress": 0.0, "last_touched": 0, "min_main_progress": 0.3},
    ],
    "space": [
        {"id": "A", "name": "主线·航线与战争", "arc_type": "Serialized", "archetype": "Quest", "progress": 0.0, "last_touched": 0},
        {"id": "B", "name": "副线·外星政治", "arc_type": "Serialized", "archetype": "Monster", "progress": 0.0, "last_touched": 0},
        {"id": "C", "name": "副线·船员羁绊", "arc_type": "Serialized", "archetype": "Rebirth", "progress": 0.0, "last_touched": 0},
        {"id": "D", "name": "单元·星球停靠", "arc_type": "Anthology", "archetype": "Quest", "progress": 0.0, "last_touched": 0, "min_main_progress": 0.3},
        {"id": "E", "name": "主题·家园定义", "arc_type": "Serialized", "archetype": "Tragedy", "progress": 0.0, "last_touched": 0},
    ],
    "mecha": [
        {"id": "A", "name": "主线·出击与升级", "arc_type": "Serialized", "archetype": "Quest", "progress": 0.0, "last_touched": 0},
        {"id": "B", "name": "副线·军部阴谋", "arc_type": "Serialized", "archetype": "Monster", "progress": 0.0, "last_touched": 0},
        {"id": "C", "name": "副线·机体共鸣", "arc_type": "Serialized", "archetype": "Rebirth", "progress": 0.0, "last_touched": 0},
        {"id": "D", "name": "单元·模拟/战场", "arc_type": "Anthology", "archetype": "Quest", "progress": 0.0, "last_touched": 0, "min_main_progress": 0.3},
    ],
    "urban": [
        {"id": "A", "name": "主线·崛起与对抗", "arc_type": "Serialized", "archetype": "Quest", "progress": 0.0, "last_touched": 0},
        {"id": "B", "name": "副线·隐秘势力", "arc_type": "Serialized", "archetype": "Monster", "progress": 0.0, "last_touched": 0},
        {"id": "C", "name": "副线·旧怨新债", "arc_type": "Serialized", "archetype": "Tragedy", "progress": 0.0, "last_touched": 0},
        {"id": "D", "name": "单元·都市奇案", "arc_type": "Anthology", "archetype": "Quest", "progress": 0.0, "last_touched": 0, "min_main_progress": 0.3},
        {"id": "E", "name": "主题·身份与归宿", "arc_type": "Serialized", "archetype": "Rebirth", "progress": 0.0, "last_touched": 0},
    ],
    "workplace": [
        {"id": "A", "name": "主线·职场目标", "arc_type": "Serialized", "archetype": "Quest", "progress": 0.0, "last_touched": 0},
        {"id": "B", "name": "副线·办公室政治", "arc_type": "Serialized", "archetype": "Monster", "progress": 0.0, "last_touched": 0},
        {"id": "C", "name": "副线·私人生活", "arc_type": "Serialized", "archetype": "Rebirth", "progress": 0.0, "last_touched": 0},
        {"id": "D", "name": "单元·项目危机", "arc_type": "Anthology", "archetype": "Quest", "progress": 0.0, "last_touched": 0, "min_main_progress": 0.3},
    ],
    "romance": [
        {"id": "A", "name": "主线·情感推进", "arc_type": "Serialized", "archetype": "Quest", "progress": 0.0, "last_touched": 0},
        {"id": "B", "name": "副线·外部阻力", "arc_type": "Serialized", "archetype": "Monster", "progress": 0.0, "last_touched": 0},
        {"id": "C", "name": "副线·内心创伤", "arc_type": "Serialized", "archetype": "Tragedy", "progress": 0.0, "last_touched": 0},
        {"id": "D", "name": "单元·约会/误会", "arc_type": "Anthology", "archetype": "Quest", "progress": 0.0, "last_touched": 0, "min_main_progress": 0.2},
        {"id": "E", "name": "主题·爱与自由", "arc_type": "Serialized", "archetype": "Rebirth", "progress": 0.0, "last_touched": 0},
    ],
    "historical": [
        {"id": "A", "name": "主线·改命/立身", "arc_type": "Serialized", "archetype": "Quest", "progress": 0.0, "last_touched": 0},
        {"id": "B", "name": "副线·朝堂/时代浪潮", "arc_type": "Serialized", "archetype": "Monster", "progress": 0.0, "last_touched": 0},
        {"id": "C", "name": "副线·人情伦理", "arc_type": "Serialized", "archetype": "Tragedy", "progress": 0.0, "last_touched": 0},
        {"id": "D", "name": "单元·地方风物", "arc_type": "Anthology", "archetype": "Quest", "progress": 0.0, "last_touched": 0, "min_main_progress": 0.3},
        {"id": "E", "name": "主题·个人与时代", "arc_type": "Serialized", "archetype": "Rebirth", "progress": 0.0, "last_touched": 0},
    ],
    "palace": [
        {"id": "A", "name": "主线·争宠/夺嫡", "arc_type": "Serialized", "archetype": "Quest", "progress": 0.0, "last_touched": 0},
        {"id": "B", "name": "副线·后宅联盟", "arc_type": "Serialized", "archetype": "Monster", "progress": 0.0, "last_touched": 0},
        {"id": "C", "name": "副线·真心难辨", "arc_type": "Serialized", "archetype": "Tragedy", "progress": 0.0, "last_touched": 0},
        {"id": "D", "name": "单元·宫宴风波", "arc_type": "Anthology", "archetype": "Quest", "progress": 0.0, "last_touched": 0, "min_main_progress": 0.3},
        {"id": "E", "name": "主题·权与情", "arc_type": "Serialized", "archetype": "Rebirth", "progress": 0.0, "last_touched": 0},
    ],
    "mystery": [
        {"id": "A", "name": "主线·破案", "arc_type": "Serialized", "archetype": "Quest", "progress": 0.0, "last_touched": 0},
        {"id": "B", "name": "副线·真凶阴影", "arc_type": "Serialized", "archetype": "Monster", "progress": 0.0, "last_touched": 0},
        {"id": "C", "name": "副线·正义代价", "arc_type": "Serialized", "archetype": "Tragedy", "progress": 0.0, "last_touched": 0},
        {"id": "D", "name": "单元·关联小案", "arc_type": "Anthology", "archetype": "Quest", "progress": 0.0, "last_touched": 0, "min_main_progress": 0.3},
        {"id": "E", "name": "主题·真相与秩序", "arc_type": "Serialized", "archetype": "Rebirth", "progress": 0.0, "last_touched": 0},
    ],
    "isekai": [
        {"id": "A", "name": "主线·异界立足", "arc_type": "Serialized", "archetype": "Quest", "progress": 0.0, "last_touched": 0},
        {"id": "B", "name": "副线·原世界/书中剧本", "arc_type": "Serialized", "archetype": "Monster", "progress": 0.0, "last_touched": 0},
        {"id": "C", "name": "副线·身份暴露风险", "arc_type": "Serialized", "archetype": "Tragedy", "progress": 0.0, "last_touched": 0},
        {"id": "D", "name": "单元·旅途委托", "arc_type": "Anthology", "archetype": "Quest", "progress": 0.0, "last_touched": 0, "min_main_progress": 0.3},
        {"id": "E", "name": "主题·改变或适应", "arc_type": "Serialized", "archetype": "Rebirth", "progress": 0.0, "last_touched": 0},
    ],
    "military": [
        {"id": "A", "name": "主线·战役目标", "arc_type": "Serialized", "archetype": "Quest", "progress": 0.0, "last_touched": 0},
        {"id": "B", "name": "副线·指挥部博弈", "arc_type": "Serialized", "archetype": "Monster", "progress": 0.0, "last_touched": 0},
        {"id": "C", "name": "副线·战友命运", "arc_type": "Serialized", "archetype": "Tragedy", "progress": 0.0, "last_touched": 0},
        {"id": "D", "name": "单元·战术行动", "arc_type": "Anthology", "archetype": "Quest", "progress": 0.0, "last_touched": 0, "min_main_progress": 0.3},
        {"id": "E", "name": "主题·战争伦理", "arc_type": "Serialized", "archetype": "Rebirth", "progress": 0.0, "last_touched": 0},
    ],
    "slice": [
        {"id": "A", "name": "主线·生活目标", "arc_type": "Serialized", "archetype": "Quest", "progress": 0.0, "last_touched": 0},
        {"id": "B", "name": "副线·社区关系", "arc_type": "Serialized", "archetype": "Rebirth", "progress": 0.0, "last_touched": 0},
        {"id": "C", "name": "副线·旧伤愈合", "arc_type": "Serialized", "archetype": "Tragedy", "progress": 0.0, "last_touched": 0},
        {"id": "D", "name": "单元·日常事件", "arc_type": "Anthology", "archetype": "Quest", "progress": 0.0, "last_touched": 0, "min_main_progress": 0.2},
    ],
    "myth": [
        {"id": "A", "name": "主线·量劫/神战", "arc_type": "Serialized", "archetype": "Quest", "progress": 0.0, "last_touched": 0},
        {"id": "B", "name": "副线·神系政治", "arc_type": "Serialized", "archetype": "Monster", "progress": 0.0, "last_touched": 0},
        {"id": "C", "name": "副线·人性余温", "arc_type": "Serialized", "archetype": "Rebirth", "progress": 0.0, "last_touched": 0},
        {"id": "D", "name": "单元·神话典故变奏", "arc_type": "Anthology", "archetype": "Quest", "progress": 0.0, "last_touched": 0, "min_main_progress": 0.3},
        {"id": "E", "name": "主题·神与人", "arc_type": "Serialized", "archetype": "Tragedy", "progress": 0.0, "last_touched": 0},
    ],
    "sports": [
        {"id": "A", "name": "主线·赛事晋级", "arc_type": "Serialized", "archetype": "Quest", "progress": 0.0, "last_touched": 0},
        {"id": "B", "name": "副线·对手与联盟", "arc_type": "Serialized", "archetype": "Monster", "progress": 0.0, "last_touched": 0},
        {"id": "C", "name": "副线·身体与代价", "arc_type": "Serialized", "archetype": "Tragedy", "progress": 0.0, "last_touched": 0},
        {"id": "D", "name": "单元·训练/热身赛", "arc_type": "Anthology", "archetype": "Quest", "progress": 0.0, "last_touched": 0, "min_main_progress": 0.3},
        {"id": "E", "name": "主题·天赋与努力", "arc_type": "Serialized", "archetype": "Rebirth", "progress": 0.0, "last_touched": 0},
    ],
    "comedy": [
        {"id": "A", "name": "主线·荒唐目标", "arc_type": "Serialized", "archetype": "Quest", "progress": 0.0, "last_touched": 0},
        {"id": "B", "name": "副线·对立吐槽役", "arc_type": "Serialized", "archetype": "Monster", "progress": 0.0, "last_touched": 0},
        {"id": "C", "name": "副线·认真之心", "arc_type": "Serialized", "archetype": "Rebirth", "progress": 0.0, "last_touched": 0},
        {"id": "D", "name": "单元·笑料事件", "arc_type": "Anthology", "archetype": "Quest", "progress": 0.0, "last_touched": 0, "min_main_progress": 0.2},
    ],
}


def _tracks(profile: str) -> list[dict]:
    tracks = _TRACK_PROFILES.get(profile) or _TRACK_PROFILES["fantasy"]
    # archetype 必须合法
    fixed = []
    for t in tracks:
        tt = dict(t)
        if tt.get("archetype") not in {"Quest", "Monster", "Tragedy", "Rebirth"}:
            tt["archetype"] = "Quest"
        fixed.append(tt)
    return fixed


# 第二波⑤：family → (题材笔法, 特色禁忌)。替代 build_pack 原硬编码的空洞
# style（"1000-1500字，节奏清晰，冲突可见，章末留钩子"——所有 286 包一字不差）。
# 让 realizer 拿到的创作指令有题材笔法特色，而非通用套话。未命中的 family 走
# default（仅长度节奏），不崩。
_STYLE_PROFILES: dict[str, tuple[str, str]] = {
    "martial": (
        "武侠笔法：招式有名目、见源流；打斗写性格（金庸式起承转合）或写意境"
        "（古龙式一招定胜负）；江湖气在称谓规矩恩怨，忌堆砌武功名词",
        "武功招式须有来由，不得凭空发明门派或流派"),
    "xianxia": (
        "仙侠笔法：境界体系清晰、修行有代价；修行即修心，奇景奇遇要有画面感；"
        "法宝神通忌说明书式罗列，神通施展要见人物心性",
        "境界突破须有契机与代价，不得无理由直升"),
    "xuanhuan": (
        "玄幻笔法：血脉天赋体系自洽，奇观服务于人物抉择；世界观靠细节自然展开"
        "（忌设定说明文），热血与谋略并重",
        "天赋外挂须有上限或代价，不得无脑碾压"),
    "wuxia": (
        "武侠笔法：侠在抉择不在武力；江湖人情世故是底色；武打为人物服务，"
        "一招一式见性情",
        "行侠须付代价，不得靠武力解决一切"),
    "romance": (
        "言情笔法：情感靠细节与潜台词推进（一个眼神胜过百字表白）；甜虐节奏"
        "交替；对话俏皮或带刺，忌直白宣告情绪或内心独白堆砌",
        "情感转折须有铺垫，不得靠误会硬撑或突然爱上"),
    "mystery": (
        "推理笔法：线索公平铺陈（读者可参与推理）；真相靠逻辑闭合不靠巧合；"
        "悬念靠信息差，不靠藏；侦破过程见侦探性格",
        "关键线索须前置铺垫，不得结局才抛新证据"),
    "infinite": (
        "无限流笔法：副本规则清晰可推导，智斗博弈见真章；生死压力下见人性；"
        "团队配合与背叛都有逻辑，忌主角无脑开挂",
        "副本通关须靠智谋或规则利用，不得靠数值碾压"),
    "horror": (
        "恐怖笔法：恐惧来自未知与日常的扭曲（非血浆堆砌）；氛围用感官细节层层"
        "堆压；会收会留白，未知的比写出的更可怖",
        "恐怖源须有规则可循，不得纯随机吓人"),
    "apocalypse": (
        "末世笔法：资源即道德试炼；废土细节要脏要真；人性底线在取舍中显形，"
        "忌圣母或纯爽文式无脑收割",
        "生存优势须有代价或限制，不得资源无限"),
    "cyber": (
        "赛博笔法：科技与肉身的张力，霓虹与锈迹的视觉；信息即权力的冷感；"
        "术语克制有质感，忌堆砌；人性在义体与代码夹缝中",
        "科技手段须符合设定体系，不得临时开新科技"),
    "system": (
        "系统笔法：面板任务有游戏化爽感但服务人物成长；忌数值流水账；系统提示"
        "可带性格，任务设计要见巧思",
        "系统奖励须匹配付出，不得无限白嫖"),
    "space": (
        "太空笔法：浩瀚与渺小的反差；科技细节有据可循；星际政治与船员羁绊"
        "交织，宇宙尺度的孤独感与使命感并存",
        "星际航行须符合物理设定，不得随意跃迁"),
    "mecha": (
        "机甲笔法：机体是战士的延伸（共鸣/代价）；战场有战术纵深，忌无双割草；"
        "少年热血与战争残酷并存",
        "机甲战损须真实，机体不得无损通关"),
    "steampunk": (
        "蒸汽朋克笔法：齿轮黄铜的机械美学；发明与禁忌的张力；阶级裂痕藏在"
        "细节里，复古与革新碰撞",
        "机械发明须符合蒸汽时代逻辑，不得电子化"),
    "urban": (
        "都市笔法：现代生活质感（职场/校园/市井的真实细节）；异能或商战要落地，"
        "忌悬浮；烟火气与冲突并存",
        "都市设定须贴近现实逻辑，不得脱离常识"),
    "palace": (
        "宫斗笔法：权谋在言语机锋与日常细节；段位差要显（聪明人遇更聪明的人）；"
        "情感与算计交织，每句话都有弦外之音",
        "宫斗胜负须靠谋略与信息，不得靠主角光环"),
    "short-drama": (
        "短剧笔法：节奏快、钩子密、反转狠；情绪拉满；每集一个小高潮，三五集"
        "一个大反转，爽点密集",
        "反转须有伏笔，不得为反转而反转"),
    "myth": (
        "神话笔法：神性与人性的张力；典故化用要有新意，忌照搬原文；宏大叙事里"
        "见个体命运，志怪图鉴体例（《山海经》式「有兽焉，其状如…」）可作钩子",
        "神话力量须有规则边界，不得全知全能"),
    "isekai": (
        "异世界笔法：穿越者的信息差与适应过程是看点；金手指要有代价或限制；"
        "两个世界的碰撞产生戏剧性，忌无脑碾压",
        "异世界规则须自洽，穿越优势须有上限"),
    "slice": (
        "日常笔法：生活流质感，细节即魅力；治愈感来自真实的烟火与人情；冲突"
        "温和但有温度，忌狗血",
        "日常冲突须温和合理，不得强行狗血"),
    "legal": (
        "律政医疗笔法：专业细节扎实可信；程序正义与人性困境交织；对白有职业"
        "质感，案件见社会切面",
        "专业程序须符合行业真实，不得随意编造"),
    "supernatural": (
        "都市志怪笔法：日常与诡异的交界；民俗志怪元素现代化；恐惧与幽默可并存，"
        "灵异规则要自洽",
        "灵异事件须有民俗或规则依据，不得纯随机"),
    "litrpg": (
        "数值流笔法：成长曲线清晰有爽感；数值面板服务叙事不喧宾夺主；玩家思维"
        "与异世界逻辑碰撞产生趣味",
        "数值成长须合理，不得断崖式跳变"),
    "sports": (
        "竞技笔法：比赛过程有技术细节与战术博弈；热血在逆境反击；胜负见人物"
        "成长，忌主角必胜套路",
        "竞技胜负须有实力基础，不得纯靠主角光环"),
    "fantasy": (
        "奇幻笔法：魔法体系自洽有代价；世界观靠细节与传说自然展开（忌设定说明"
        "文）；奇观服务情节，种族文化有质感",
        "魔法力量须有规则边界，不得全能无耗"),
    "cosmic": (
        "克苏鲁笔法：恐惧来自不可名状与认知崩溃（非怪物战斗）；氛围用衰败细节"
        "与禁忌知识层层堆压；留白与暗示比直白描写更可怖",
        "不可名状之物须保持未知，不得被轻易击败"),
    "comedy": (
        "喜剧笔法：笑点靠反差、误会、错位与机智对白，忌低俗硬挠；人物各有"
        "「认真的荒诞」，喜剧内核可含温情或讽刺",
        "笑点须服务情节或人物，不得为搞笑而搞笑"),
    "food": (
        "美食笔法：菜品描写有色香味形的通感细节；厨艺对决有技术与创意博弈；"
        "烟火气与人情味交织，美食承载记忆与情感",
        "美食描写须有真实饮食逻辑，不得凭空编造"),
    "game-reality": (
        "游戏现实笔法：游戏机制与现实交织的荒诞感；NPC/玩家身份错位产生戏剧性；"
        "规则漏洞是看点，系统与人的边界模糊",
        "游戏规则须自洽，破局须靠规则理解而非乱来"),
    "military": (
        "军事笔法：战场有战略纵深与后勤真实；军人群像有纪律与人性张力；"
        "家国叙事与个体命运交织，忌个人英雄主义泛滥",
        "军事行动须符合战术逻辑，不得靠一人翻盘"),
    "historical": (
        "历史笔法：时代质感在器物、礼制、称谓的考据细节；历史大势与个体命运"
        "交织；古风语言有分寸（雅而不晦），忌现代腔",
        "历史设定须尊重时代背景，不得明显穿帮"),
    "adventure": (
        "冒险笔法：旅程即叙事，未知与奇遇驱动节奏；团队分工与羁绊在危机中显形；"
        "探索的快感在于发现与克服，忌平推",
        "冒险关卡须有挑战梯度，不得一路顺遂"),
}


def _lookup_style(family: str) -> tuple[str | None, str | None]:
    """family → (笔法, 禁忌)。匹配优先级：精确 → 前缀(system-cn→system) →
    包含(high-fantasy→fantasy)。仍无命中 → (None, None)（走 default，不崩）。"""
    if family in _STYLE_PROFILES:
        return _STYLE_PROFILES[family]
    prefix = family.split("-")[0]
    if prefix in _STYLE_PROFILES:
        return _STYLE_PROFILES[prefix]
    for key, val in _STYLE_PROFILES.items():
        if key in family:
            return val
    return (None, None)


def _style_for(t: GenreTaxon) -> str:
    """family 题材笔法 + 通用长度节奏要求（替代原空洞模板套话）"""
    pen = _lookup_style(t.family)[0]
    parts = [pen] if pen else []
    parts.append("1000-1500字，长短句交错有呼吸感，场景转换用空行分隔，章末留钩子")
    return "；".join(parts)


def _hard_reqs_for(t: GenreTaxon) -> list[str]:
    """题材标签 + 通用结构纪律 + family 特色禁忌"""
    reqs = [
        f"紧扣题材标签：{', '.join(t.tags)}",
        "每章推进至少一个轨道（主线或主题）",
        "禁止无代价的万能解决方案",
        "人物动机必须可被读者理解",
    ]
    taboo = _lookup_style(t.family)[1]
    if taboo:
        reqs.append(taboo)
    return reqs


def build_pack(t: GenreTaxon) -> dict:
    tracks = _tracks(t.track_profile)
    ids = [x["id"] for x in tracks]
    main = "A" if "A" in ids else ids[0]
    theme = "E" if "E" in ids else ids[-1]
    pack = {
        "manifest_version": 1,
        "name": t.id,
        "extension_point": "story.genre",
        "activation_events": [f"on_genre:{t.id}"],
        "fusion": {
            "type": "base" if t.tier == "base" else t.tier,
            "parent_genres": [t.family],
            "core_conflict": t.vibe,
            "fusion_formula": f"{t.family_title} × {t.subtrope}",
        },
        "culture_bound": False,
        "allowed_cultures": ["*"],
        "params": {
            "title": t.title,
            "pacing_curve": f"{t.title}节奏：建置→冲突升级→反转→收束",
            "power_system": "narrative_driven",
            "emotion_arcs": ["man_in_hole", "cinderella"],
            "conflict_types": [
                {"type": "cognitive", "weight": 0.3},
                {"type": "relational", "weight": 0.3},
                {"type": "physical", "weight": 0.2},
                {"type": "political", "weight": 0.2},
            ],
            "information_distribution": "partial",
            "max_red_herrings": 2,
            "resolution_pattern": f"在「{t.title}」核心冲突中完成主题兑现",
            "main_track": main,
            "theme_track": theme,
            "payoff_window": 2,
            "beats_per_chapter": 4,
            "tracks": tracks,
            "world_rules": [
                {
                    "id": "no_deus_ex",
                    "kind": "bool",
                    "desc": "结局不得凭空引入未铺垫关键",
                    "expr": "not(is_resolution and introduces_new_key_clue)",
                },
            ],
            "foreshadow_templates": [
                {"content": "早早出现的异常细节", "trigger": "中段复现", "payoff": "指向核心真相"},
                {"content": "配角随口一句话", "trigger": "危机时被记起", "payoff": "成为破局钥匙"},
            ],
            "taboo_list": [
                f"必须兑现「{t.title}」的核心承诺，不得换皮跑题",
                "关键胜利须来自角色抉择，而非突然开挂",
                "设定前后一致，禁止无铺垫的规则变更",
            ],
            "evaluation_weights": {
                "情节连贯": 0.25,
                "设定一致性": 0.20,
                "角色动机": 0.15,
                "套路检测": 0.15,
                "对话真实度": 0.10,
                "感官细节": 0.10,
                "主题深度": 0.05,
            },
            "active_critics": [
                "plot_coherence", "setting_consistency",
                "character_motivation", "cliche_detection",
            ],
            "prompt": {
                "role": f"{t.title}小说作者",
                "setting": (
                    f"以「{t.vibe}」为世界基底的故事舞台；"
                    f"默认文化气质贴近 {t.default_culture}，"
                    f"推荐世界观骨架 {t.primary_preset}。"
                ),
                "characters": (
                    f"主角（被抛入{t.title}核心冲突的人）、"
                    f"对手/阻力（体现该品类规则压力）、"
                    f"同伴（提供情感与信息差）"
                ),
                "style": _style_for(t),
                "hard_requirements": _hard_reqs_for(t),
            },
            "phase_beats": {
                "equilibrium": [
                    {"id": "setup", "desc": "日常与承诺建立", "primitive": "GoalFormation"},
                ],
                "disruption": [
                    {"id": "break", "desc": "打破平衡的事件", "primitive": "TurningPoint"},
                    {"id": "pressure", "desc": "压力升级", "primitive": "Suspense"},
                ],
                "recognition": [
                    {"id": "reveal", "desc": "关键认知更新", "primitive": "Revelation"},
                    {"id": "clash", "desc": "对立表面化", "primitive": "Conflict"},
                ],
                "repair": [
                    {"id": "cost", "desc": "付出代价推进", "primitive": "Sacrifice"},
                    {"id": "betray", "desc": "信任或规则被撕裂", "primitive": "Betrayal"},
                ],
                "new_equilibrium": [
                    {"id": "settle", "desc": "新平衡与主题兑现", "primitive": "Recognition"},
                    {"id": "hook", "desc": "下一阶段钩子", "primitive": "Suspense"},
                ],
            },
            "blend_domains": [t.family_title, t.subtrope, "人物抉择"],
            "pacing_targets": {
                "reversal_density": [0.3, 0.7],
                "avg_reversal_magnitude": [0.3, 0.7],
                "pacing_consistency": [0.5, 0.8],
                "cliffhanger_strength": [0.5, 0.9],
            },
            "taxonomy_tags": list(t.tags),
            "recommended_preset": t.primary_preset,
            "recommended_culture": t.default_culture,
        },
    }
    return pack


def generate_all(*, write_packs: bool = True) -> dict:
    PLUGIN_DIR.mkdir(parents=True, exist_ok=True)
    if write_packs:
        PACKS_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    skipped = 0
    errors: list[str] = []
    for t in all_taxa():
        if t.legacy:
            skipped += 1
            continue
        path = PLUGIN_DIR / f"{t.id}.yaml"
        if path.exists():
            skipped += 1
            continue
        pack = build_pack(t)
        errs = validate_genre_pack(pack)
        if errs:
            errors.append(f"{t.id}: {';'.join(errs)}")
            continue
        text = yaml.safe_dump(pack, allow_unicode=True, sort_keys=False)
        path.write_text(text, encoding="utf-8")
        if write_packs:
            (PACKS_DIR / f"{t.id}.yaml").write_text(text, encoding="utf-8")
        written += 1
    stats = taxonomy_stats()
    return {"written": written, "skipped": skipped, "errors": errors, **stats}


if __name__ == "__main__":
    result = generate_all()
    print(result)
    if result["errors"]:
        raise SystemExit(1)
    if result["total"] < 300:
        raise SystemExit(f"taxonomy total {result['total']} < 300")
