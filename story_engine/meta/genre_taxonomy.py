"""题材多轴 taxonomy：族 × 子套路 × 有限调性 → ≥300 正式题材行。

单源供 codegen / affinity / 开局筛选使用。legacy 现有插件 id 映射到同名行，
codegen 跳过覆盖。
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable


# 族 → (中文族名, 默认骨架, 默认文化, track_profile, [(sub_id, sub_title, tags...)])
_FAMILIES: dict[str, tuple] = {
    "xianxia": ("修仙", "xianxia_cultivation", "confucian_officialdom", "cultivation", [
        ("ascension", "问道飞升", ["cultivation", "sinosphere"]),
        ("sect-war", "宗门争霸", ["cultivation", "politics"]),
        ("rogue", "散修求生", ["cultivation"]),
        ("mortal", "凡人流", ["cultivation"]),
        ("body", "体修霸道", ["cultivation"]),
        ("alchemy", "丹道奇缘", ["cultivation"]),
        ("sword", "剑修一路", ["cultivation"]),
        ("demonic", "魔道沉沦", ["cultivation", "dark"]),
        ("reincarnate", "仙帝归来", ["cultivation", "rebirth"]),
        ("academy", "仙门学院", ["cultivation", "academy"]),
    ]),
    "xuanhuan": ("玄幻", "xianxia_cultivation", "confucian_officialdom", "cultivation", [
        ("empire", "王朝玄幻", ["xuanhuan", "politics"]),
        ("beast", "御兽玄幻", ["xuanhuan"]),
        ("talent", "天赋觉醒", ["xuanhuan", "progression"]),
        ("clan", "家族崛起", ["xuanhuan"]),
        ("forbidden", "禁地探险", ["xuanhuan", "adventure"]),
        ("divine", "神祇战场", ["xuanhuan"]),
        ("bloodline", "血脉觉醒", ["xuanhuan"]),
        ("artifact", "神器争锋", ["xuanhuan"]),
        ("array", "阵法宗师", ["xuanhuan"]),
        ("spirit-pet", "灵宠养成", ["xuanhuan", "slice"]),
    ]),
    "wuxia-path": ("武侠支线", "wuxia_jianghu", "jianghu-martial", "martial", [
        ("jianghu", "江湖恩怨", ["martial", "sinosphere"]),
        ("court-xia", "庙堂与江湖", ["martial", "politics"]),
        ("revenge-xia", "仇杀江湖", ["martial", "revenge"]),
        ("hidden-sect", "隐世门派", ["martial"]),
        ("xia-romance", "侠侣情深", ["martial", "romance"]),
        ("xia-mystery", "武林迷案", ["martial", "mystery"]),
    ]),
    "high-fantasy": ("西幻", "western_fantasy", "anglo-american", "fantasy", [
        ("epic", "史诗远征", ["fantasy", "anglosphere"]),
        ("dragon", "龙骑士", ["fantasy", "romance"]),
        ("academy-magic", "魔法学院", ["fantasy", "academy"]),
        ("chosen", "天命选民", ["fantasy"]),
        ("dark-lord", "魔王远征", ["fantasy", "dark"]),
        ("court-magic", "魔法宫廷", ["fantasy", "politics"]),
        ("dungeon-delve", "地下城探索", ["fantasy", "adventure"]),
        ("fae", "妖精契约", ["fantasy"]),
        ("mercenary", "佣兵团纪", ["fantasy", "adventure"]),
        ("prophecy", "预言破灭", ["fantasy", "burn"]),
    ]),
    "low-fantasy": ("低魔", "western_fantasy", "anglo-american", "mystery", [
        ("gritty", "低魔残酷", ["fantasy", "gritty"]),
        ("political", "低魔权谋", ["fantasy", "politics"]),
        ("heist", "魔法窃案", ["fantasy", "mystery"]),
        ("witch", "女巫日常", ["fantasy", "slice"]),
        ("inquisitor", "猎巫审判", ["fantasy", "mystery"]),
    ]),
    "litrpg": ("游戏异界", "infinite_flow", "modern-chinese-urban", "system", [
        ("panel", "面板升级", ["system", "isekai"]),
        ("skill-tree", "技能树", ["system"]),
        ("crafting", "制造流", ["system"]),
        ("guild", "公会战争", ["system"]),
        ("npc", "NPC觉醒", ["system", "meta"]),
        ("hardcore", "硬核数值", ["system"]),
        ("idle", "挂机流", ["system", "comedy"]),
        ("pvp", "竞技场称霸", ["system", "sports"]),
        ("raid", "团本攻坚", ["system"]),
    ]),
    "infinite": ("无限诸天", "infinite_flow", "modern-chinese-urban", "infinite", [
        ("combat", "热血战斗无限", ["dungeon_loop", "combat"]),
        ("puzzle", "智斗解谜无限", ["dungeon_loop", "mystery"]),
        ("rule-game", "规则博弈无限", ["dungeon_loop", "rules"]),
        ("lone-wolf", "杀伐独行无限", ["dungeon_loop", "dark"]),
        ("myriad", "诸天万界", ["dungeon_loop", "myriad"]),
        ("quick-pass", "快穿任务", ["dungeon_loop", "isekai"]),
        ("book-world", "书中世界", ["dungeon_loop", "meta"]),
        ("movie-world", "影视穿梭", ["dungeon_loop"]),
    ]),
    "system-cn": ("系统流", "infinite_flow", "modern-chinese-urban", "system", [
        ("bind", "绑定系统", ["system"]),
        ("villain-system", "反派系统", ["system", "dark"]),
        ("sign-in", "签到流", ["system", "comedy"]),
        ("shop", "商城系统", ["system"]),
        ("emotion", "情绪系统", ["system"]),
        ("apocalypse-sys", "末世系统", ["system", "wasteland"]),
        ("historical-sys", "历史系统", ["system", "historical"]),
    ]),
    "cosmic": ("克苏鲁", "cthulhu_mythos", "anglo-american", "horror", [
        ("investigator", "调查员", ["cosmic_horror"]),
        ("cult", "邪教蔓延", ["cosmic_horror"]),
        ("dreamland", "幻梦境", ["cosmic_horror"]),
        ("deep-one", "深潜者", ["cosmic_horror"]),
        ("academic", "禁忌学术", ["cosmic_horror", "mystery"]),
        ("slow-corruption", "缓慢堕落", ["cosmic_horror", "dark"]),
    ]),
    "horror": ("恐怖", "cthulhu_mythos", "modern-chinese-urban", "horror", [
        ("haunted", "凶宅", ["horror", "urban"]),
        ("folk", "民俗诡谈", ["horror", "sinosphere"]),
        ("rule", "规则怪谈", ["horror", "rules"]),
        ("school", "校园怪谈", ["horror", "urban"]),
        ("hospital", "医院诡事", ["horror", "urban"]),
        ("comedy-horror", "恐宣喜剧", ["horror", "comedy"]),
    ]),
    "apocalypse": ("末日", "post_apocalyptic", "modern-chinese-urban", "apocalypse", [
        ("wasteland", "废土求生", ["wasteland"]),
        ("zombie", "丧尸围城", ["wasteland"]),
        ("ice", "全球冰封", ["wasteland"]),
        ("virus", "病毒末日", ["wasteland"]),
        ("base", "基地建设", ["wasteland", "farming"]),
        ("sweet", "末世甜宠", ["wasteland", "romance"]),
        ("power", "异能末世", ["wasteland", "urban"]),
    ]),
    "cyber": ("赛博", "cyberpunk", "modern-chinese-urban", "cyber", [
        ("street", "街头义体", ["cyber"]),
        ("corp", "巨型企业", ["cyber", "politics"]),
        ("hacker", "精神黑客", ["cyber"]),
        ("ai-god", "天道AI", ["cyber", "cultivation"]),
        ("palace", "赛博宫斗", ["cyber", "politics"]),
        ("noir", "霓虹侦探", ["cyber", "mystery"]),
    ]),
    "steampunk": ("蒸汽", "cyberpunk", "anglo-american", "steampunk", [
        ("empire", "蒸汽帝国", ["steampunk"]),
        ("inventor", "发明家传奇", ["steampunk"]),
        ("xia-steam", "蒸汽武侠", ["steampunk", "martial"]),
        ("airship", "飞艇冒险", ["steampunk", "adventure"]),
        ("clockwork", "发条密谋", ["steampunk", "mystery"]),
    ]),
    "space": ("星际", "cyberpunk", "anglo-american", "space", [
        ("opera", "太空歌剧", ["space"]),
        ("fleet", "舰队战争", ["space", "military"]),
        ("colony", "殖民星球", ["space"]),
        ("alien", "首次接触", ["space", "horror"]),
        ("trader", "星际商路", ["space"]),
        ("mecha-space", "太空机甲", ["space", "mecha"]),
    ]),
    "mecha": ("机甲", "cyberpunk", "japanese-shinto", "mecha", [
        ("pilot", "驾驶员觉醒", ["mecha"]),
        ("war", "机甲战争", ["mecha", "military"]),
        ("school-mecha", "机甲学园", ["mecha", "academy"]),
        ("ai-partner", "机体有灵", ["mecha"]),
        ("guerrilla", "废土机甲", ["mecha", "wasteland"]),
    ]),
    "urban-power": ("都市异能", "urban_supernatural", "modern-chinese-urban", "urban", [
        ("awakening", "异能觉醒", ["urban"]),
        ("war-god", "战神归来", ["urban", "revenge"]),
        ("healer", "神医下山", ["urban"]),
        ("tycoon", "神豪系统", ["urban", "system"]),
        ("appraisal", "鉴宝奇缘", ["urban"]),
        ("guardian", "龙王保镖", ["urban", "romance"]),
        ("exorcist", "都市驱邪", ["urban", "horror"]),
        ("global-wu", "全球高武", ["urban", "martial"]),
    ]),
    "urban-life": ("都市现实", "hard_reality", "modern-chinese-urban", "workplace", [
        ("workplace", "职场逆袭", ["workplace"]),
        ("startup", "创业沉浮", ["workplace"]),
        ("lawyer", "律政风云", ["workplace"]),
        ("medical", "医疗人间", ["workplace"]),
        ("entertainment", "娱乐圈", ["workplace"]),
        ("esports", "电竞热血", ["sports"]),
        ("live", "直播成长", ["workplace"]),
        ("campus", "校园青春", ["slice"]),
    ]),
    "romance-cn": ("言情", "hard_reality", "modern-chinese-urban", "romance", [
        ("ceo", "霸总宠妻", ["romance"]),
        ("chase", "追妻火葬场", ["romance", "revenge"]),
        ("stand-in", "替身文学", ["romance", "dark"]),
        ("rebirth-sweet", "重生甜宠", ["romance", "rebirth"]),
        ("rebirth-revenge", "重生复仇", ["romance", "revenge"]),
        ("flash", "闪婚暖爱", ["romance"]),
        ("age-gap", "年下恋", ["romance"]),
        ("dark", "黑暗罗曼史", ["romance", "dark"]),
    ]),
    "romance-fantasy": ("奇幻言情", "western_fantasy", "anglo-american", "romance", [
        ("romantasy", "龙与恋人", ["romance", "fantasy"]),
        ("fae-bride", "妖精联姻", ["romance", "fantasy"]),
        ("vampire", "吸血鬼恋曲", ["romance", "urban"]),
        ("werewolf", "狼人伴侣", ["romance", "urban"]),
        ("xianxia-love", "仙侠虐恋", ["romance", "cultivation"]),
        ("isekai-love", "穿越情缘", ["romance", "isekai"]),
    ]),
    "historical": ("历史", "hard_reality", "confucian_officialdom", "historical", [
        ("isekai-hist", "历史穿越", ["historical", "isekai"]),
        ("period", "年代文", ["historical"]),
        ("three-kingdoms", "三国权谋", ["historical", "politics"]),
        ("ming", "大明风华", ["historical"]),
        ("qing", "清穿日常", ["historical", "isekai"]),
        ("farming", "古代种田", ["historical", "farming"]),
        ("merchant", "商贾传奇", ["historical"]),
        ("grandma", "太奶奶穿越", ["historical", "isekai", "comedy"]),
    ]),
    "palace": ("宫斗", "hard_reality", "confucian_officialdom", "palace", [
        ("harem", "后宫争宠", ["palace", "politics"]),
        ("prince", "夺嫡之争", ["palace", "politics"]),
        ("female-official", "女官权谋", ["palace"]),
        ("spy-palace", "宫墙谍影", ["palace", "mystery"]),
        ("workplace-palace", "宫斗职场", ["palace", "workplace"]),
    ]),
    "mystery-family": ("推理", "hard_reality", "modern-chinese-urban", "mystery", [
        ("modern", "现代刑侦", ["mystery"]),
        ("locked", "密室本格", ["mystery"]),
        ("forensic", "法医探案", ["mystery"]),
        ("spy", "谍战风云", ["mystery", "military"]),
        ("fantasy-fair", "奇幻公平推理", ["mystery", "fantasy"]),
        ("cozy", "治愈探案", ["mystery", "slice"]),
    ]),
    "isekai-family": ("穿越", "western_fantasy", "modern-chinese-urban", "isekai", [
        ("classic", "经典异世界", ["isekai"]),
        ("book", "穿书攻略", ["isekai", "meta"]),
        ("villainess", "恶役女主", ["isekai", "romance"]),
        ("dual", "双穿对峙", ["isekai", "meta"]),
        ("detective", "穿越侦探", ["isekai", "mystery"]),
        ("otome", "乙女游戏", ["isekai", "romance"]),
    ]),
    "military": ("军事", "hard_reality", "modern-chinese-urban", "military", [
        ("special", "特种兵王", ["military"]),
        ("strategy", "战争谋略", ["military"]),
        ("tech", "科技强军", ["military"]),
        ("ancient-war", "冷兵器战场", ["military", "historical"]),
        ("interstellar-war", "星际远征军", ["military", "space"]),
    ]),
    "slice": ("生活流", "hard_reality", "modern-chinese-urban", "slice", [
        ("healing", "治愈日常", ["slice"]),
        ("food", "美食文", ["slice", "food"]),
        ("farming-modern", "现代种田", ["slice", "farming"]),
        ("pet", "萌宠日常", ["slice"]),
        ("travel", "旅行纪事", ["slice"]),
        ("bookstore", "书店日常", ["slice"]),
    ]),
    "myth": ("神话", "shanhai_zhiguai", "confucian_officialdom", "myth", [
        ("honghuang", "洪荒封神", ["myth", "sinosphere"]),
        ("shanhai", "山海异兽", ["myth", "sinosphere"]),
        ("journey", "西游变奏", ["myth"]),
        ("folk-god", "俗神崛起", ["myth", "horror"]),
        ("norse", "北欧诸神", ["myth", "anglosphere"]),
        ("greek", "奥林匹斯", ["myth", "anglosphere"]),
    ]),
    "sports": ("竞技", "hard_reality", "modern-chinese-urban", "sports", [
        ("ball", "热血球类", ["sports"]),
        ("fantasy-ball", "超能竞技", ["sports", "fantasy"]),
        ("racing", "极速竞速", ["sports"]),
        ("chess", "智力竞技", ["sports", "mystery"]),
        ("cultivation-sports", "武道赛事", ["sports", "martial"]),
    ]),
    "comedy": ("喜剧", "hard_reality", "modern-chinese-urban", "comedy", [
        ("absurdist", "荒诞日常", ["comedy"]),
        ("satire", "职场讽刺", ["comedy", "workplace"]),
        ("folk-funny", "民俗恐怖喜剧", ["comedy", "horror"]),
        ("isekai-gag", "穿越吐槽", ["comedy", "isekai"]),
        ("system-gag", "系统抬杠", ["comedy", "system"]),
    ]),
    "game-reality": ("游戏现实", "infinite_flow", "modern-chinese-urban", "system", [
        ("invasion", "游戏入侵", ["system", "wasteland"]),
        ("npc-life", "我是NPC", ["system", "meta"]),
        ("server", "全服唯一", ["system"]),
        ("bug", "BUG成神", ["system", "comedy"]),
    ]),
    "supernatural-biz": ("灵异经营", "urban_supernatural", "confucian_officialdom", "urban", [
        ("haunted-hotel", "鬼屋酒店", ["horror", "workplace"]),
        ("yin-yang-office", "阴阳事务所", ["horror", "workplace"]),
        ("temple", "庙祝日常", ["horror", "slice"]),
        ("livestream-ghost", "直播见鬼", ["horror", "comedy"]),
        ("ghost-market", "鬼市交易", ["horror", "urban"]),
    ]),
    "short-drama": ("短剧热梗", "hard_reality", "modern-chinese-urban", "romance", [
        ("hidden-identity", "隐藏身份", ["romance", "shuang"]),
        ("revenge-queen", "重生虐渣", ["romance", "revenge"]),
        ("contract-love", "契约婚姻", ["romance"]),
        ("rich-flop", "真千金逆袭", ["romance", "shuang"]),
        ("soldier-return", "兵王归来", ["urban", "military"]),
        ("doctor-god", "神医下山短剧", ["urban"]),
        ("time-loop-love", "时间循环恋爱", ["romance", "burn"]),
        ("family-war", "豪门宅斗", ["romance", "palace"]),
    ]),
    "food-biz": ("美食经营", "hard_reality", "modern-chinese-urban", "slice", [
        ("street-food", "街头小吃", ["food", "slice"]),
        ("chef-duel", "厨神对决", ["food", "sports"]),
        ("isekai-cuisine", "异界厨神", ["food", "isekai"]),
        ("restaurant", "开餐馆", ["food", "workplace"]),
        ("immortal-kitchen", "仙厨", ["food", "cultivation"]),
    ]),
    "legal-medical": ("律政医疗", "hard_reality", "modern-chinese-urban", "workplace", [
        ("prosecutor", "检察官", ["workplace", "mystery"]),
        ("defense", "刑辩律师", ["workplace", "mystery"]),
        ("er", "急诊人间", ["workplace"]),
        ("surgeon", "外科刀锋", ["workplace"]),
        ("psych", "心理诊疗", ["workplace", "mystery"]),
    ]),
    "adventure": ("冒险奇谭", "western_fantasy", "anglo-american", "fantasy", [
        ("treasure", "寻宝远征", ["adventure"]),
        ("survival-island", "荒岛求生", ["adventure", "wasteland"]),
        ("caravan", "商队纪行", ["adventure"]),
        ("sky-pirate", "空贼传奇", ["adventure", "steampunk"]),
        ("lost-city", "失落之城", ["adventure", "mystery"]),
    ]),
}

_TONE_ALLOWED: dict[str, list[str]] = {
    "xianxia": ["ascension", "demonic", "sect-war", "rogue", "sword"],
    "xuanhuan": ["empire", "talent", "forbidden"],
    "romance-cn": ["ceo", "chase", "rebirth-revenge", "stand-in", "dark"],
    "romance-fantasy": ["romantasy", "vampire"],
    "infinite": ["combat", "rule-game", "myriad", "puzzle", "lone-wolf"],
    "horror": ["rule", "folk", "haunted"],
    "apocalypse": ["zombie", "sweet", "base"],
    "urban-power": ["war-god", "tycoon", "exorcist"],
    "historical": ["isekai-hist", "farming", "three-kingdoms"],
    "cyber": ["ai-god", "palace", "noir"],
    "palace": ["harem", "prince"],
    "isekai-family": ["villainess", "book"],
    "short-drama": ["hidden-identity", "revenge-queen", "rich-flop"],
    "litrpg": ["panel", "hardcore"],
    "mystery-family": ["locked", "spy"],
    "cosmic": ["investigator", "slow-corruption"],
    "mecha": ["pilot", "war"],
    "space": ["fleet", "alien"],
}

_TONES = {
    "shuang": ("爽文", ["shuang"]),
    "nue": ("虐心", ["nue"]),
    "burn": ("烧脑", ["burn"]),
    "heal": ("治愈", ["heal"]),
    "gag": ("搞笑", ["comedy"]),
}

_TONE_BAN = {
    ("horror", "rule", "shuang"),
    ("horror", "rule", "heal"),
    ("horror", "haunted", "shuang"),
    ("romance-cn", "chase", "shuang"),
    ("romance-cn", "dark", "heal"),
    ("xianxia", "demonic", "shuang"),
    ("xianxia", "demonic", "heal"),
    ("infinite", "lone-wolf", "heal"),
    ("cosmic", "slow-corruption", "shuang"),
    ("cosmic", "slow-corruption", "gag"),
}

# 每个允许的子套路挂 1 个优先调性；未列出则默认 shuang
_TONE_PREFER = {
    "ascension": "shuang", "demonic": "nue", "sect-war": "burn",
    "rogue": "shuang", "sword": "shuang",
    "empire": "shuang", "talent": "shuang", "forbidden": "burn",
    "ceo": "shuang", "chase": "nue", "rebirth-revenge": "burn",
    "stand-in": "nue", "dark": "nue",
    "romantasy": "nue", "vampire": "nue",
    "combat": "shuang", "rule-game": "burn", "myriad": "shuang",
    "puzzle": "burn", "lone-wolf": "nue",
    "rule": "burn", "folk": "nue", "haunted": "nue",
    "zombie": "shuang", "sweet": "nue", "base": "heal",
    "war-god": "shuang", "tycoon": "shuang", "exorcist": "burn",
    "isekai-hist": "burn", "farming": "heal", "three-kingdoms": "burn",
    "ai-god": "burn", "palace": "nue", "noir": "burn",
    "harem": "nue", "prince": "burn",
    "villainess": "shuang", "book": "burn",
    "hidden-identity": "shuang", "revenge-queen": "nue", "rich-flop": "shuang",
    "panel": "shuang", "hardcore": "burn",
    "locked": "burn", "spy": "burn",
    "investigator": "burn", "slow-corruption": "nue",
    "pilot": "shuang", "war": "nue",
    "fleet": "shuang", "alien": "burn",
}

_LEGACY_IDS = {
    "mystery", "romance", "wuxia", "apocalypse-romance", "court-workplace",
    "cozy-fantasy-mystery", "cyberpunk-xianxia", "fantasy-mystery",
    "fantasy-sports", "folk-cthulhu", "game-reality-invasion",
    "historical-isekai", "historical-system", "horror-comedy",
    "infinite-dungeon", "isekai-detective", "isekai-romance",
    "meta-isekai-dual", "political-cultivation", "reborn-business-era",
    "romance-suspense", "romantasy", "sci-fi-horror", "sequence-pathway",
    "supernatural-management", "system-isekai", "tomb-exploration",
    "wuxia-steampunk", "xianxia-cthulhu",
}


@dataclass(frozen=True)
class GenreTaxon:
    id: str
    title: str
    family: str
    family_title: str
    subtrope: str
    tier: str
    tags: tuple[str, ...]
    default_culture: str
    primary_preset: str
    secondary_presets: tuple[str, ...]
    track_profile: str
    vibe: str
    legacy: bool = False
    macro_templates: tuple[str, ...] = ("save_the_cat_15",)


def _secondary_for(preset: str) -> tuple[str, ...]:
    table = {
        "xianxia_cultivation": ("shanhai_zhiguai", "wuxia_jianghu"),
        "wuxia_jianghu": ("hard_reality", "shanhai_zhiguai"),
        "western_fantasy": ("hard_reality", "infinite_flow"),
        "infinite_flow": ("post_apocalyptic", "western_fantasy"),
        "cthulhu_mythos": ("urban_supernatural", "shanhai_zhiguai"),
        "post_apocalyptic": ("hard_reality", "urban_supernatural"),
        "cyberpunk": ("post_apocalyptic", "hard_reality"),
        "hard_reality": ("urban_supernatural", "wuxia_jianghu"),
        "urban_supernatural": ("hard_reality", "cthulhu_mythos"),
        "shanhai_zhiguai": ("xianxia_cultivation", "cthulhu_mythos"),
    }
    return table.get(preset, ("hard_reality",))


def _macro_for(profile: str) -> tuple[str, ...]:
    if profile == "romance":
        return ("romance_beat", "save_the_cat_15")
    if profile in ("martial", "cultivation"):
        return ("wuxia_classic", "save_the_cat_15")
    if profile == "mystery":
        return ("save_the_cat_15", "three_act_classic")
    if profile in ("infinite", "system"):
        return ("dtg_50_30", "save_the_cat_15")
    return ("save_the_cat_15", "three_act_classic")


# legacy 29 的展示名/一句话（取自各插件 params.title + resolution_pattern，
# 进搜索索引——此前 title 用 id 原文，中文名搜不到、卡片显示原生 id）
_LEGACY_TITLES: dict[str, tuple[str, str]] = {
    "apocalypse-romance": ("末日情缘", "建立安全区 + 情感落地（或为对方牺牲）"),
    "court-workplace": ("律政职场", "上位 + 反思「变成自己讨厌的人」"),
    "cozy-fantasy-mystery": ("治愈奇幻推理", "温和的真相揭示 + 社区关系修复"),
    "cyberpunk-xianxia": ("赛博修仙", "揭露天道=AI的真相 + 选择人性飞升或数字永生"),
    "fantasy-mystery": ("奇幻推理", "排除所有不可能的魔法→唯一可能的真相"),
    "fantasy-sports": ("奇幻竞技", "在公平性质疑中证明「努力能弥补天赋差」"),
    "folk-cthulhu": ("民俗克苏鲁", "在「不可名状」面前找到东方式的应对"),
    "game-reality-invasion": ("游戏入侵现实", "打破游戏vs现实的边界 + 回答「什么是真实」"),
    "historical-isekai": ("历史穿越", "改变历史节点 + 承担蝴蝶效应后果"),
    "historical-system": ("历史系统流", "系统真相揭示 + 忠于历史还是忠于系统"),
    "horror-comedy": ("恐怖喜剧", "用荒诞方式化解恐怖 + 留一个「其实没完」的尾巴"),
    "infinite-dungeon": ("无限流", "破解主神空间真相 + 逃离或取代主神"),
    "isekai-detective": ("穿越侦探", "科学断案 + 在权力结构中推行正义"),
    "isekai-romance": ("穿越情缘", "不放弃自我的前提下找到爱情"),
    "meta-isekai-dual": ("元穿双界", "信息差消除 + 共同选择改写结局"),
    "mystery": ("公案悬疑", "真相揭示 + 正义"),
    "political-cultivation": ("权谋修仙", "实力+权术双赢 or 认清最高权力在天道"),
    "reborn-business-era": ("重生商战", "商业成功 + 弥补前世遗憾"),
    "romance-suspense": ("言情悬疑", "爱人的秘密揭晓，但性质出人意料"),
    "romance": ("古代言情", "有情人终成眷属"),
    "romantasy": ("西幻言情", "爱情与世界两全（或为一方牺牲另一方）"),
    "sci-fi-horror": ("科幻恐怖", "极少人生还 + 威胁未被真正解决"),
    "sequence-pathway": ("序列途径", "封神（序列0）+ 承担途径终极代价"),
    "supernatural-management": ("灵异经营", "主线真相 + 店铺/能力终极形态"),
    "system-isekai": ("系统穿越", "掌控/摆脱系统 + 在异世界立足"),
    "tomb-exploration": ("盗墓探险", "揭开历史真相 + 带着代价逃生"),
    "wuxia-steampunk": ("蒸汽武侠", "新旧融合的新武学 or 旧时代悲壮落幕"),
    "wuxia": ("武侠江湖", "恩怨了结/归隐/传承"),
    "xianxia-cthulhu": ("修仙克苏鲁", "觉醒真相 + 付出代价"),
}


def _legacy_defaults(lid: str) -> tuple[str, str, str, tuple[str, ...]]:
    """title_hint, preset, culture, tags — title 最终以插件为准。"""
    if lid == "infinite-dungeon":
        return "无限流", "infinite_flow", "modern-chinese-urban", ("dungeon_loop", "system")
    if lid == "mystery":
        return "公案悬疑", "hard_reality", "confucian_officialdom", ("mystery", "sinosphere")
    if "romance" in lid or lid == "romantasy":
        return lid, "hard_reality", "modern-chinese-urban", ("romance",)
    if "xianxia" in lid or "cultivation" in lid:
        return lid, "xianxia_cultivation", "confucian_officialdom", ("cultivation",)
    if "infinite" in lid or "system" in lid or "game" in lid:
        return lid, "infinite_flow", "modern-chinese-urban", ("system",)
    if "fantasy" in lid:
        return lid, "western_fantasy", "anglo-american", ("fantasy",)
    if "cthulhu" in lid or "horror" in lid or "folk" in lid:
        return lid, "cthulhu_mythos", "confucian_officialdom", ("horror",)
    if "cyber" in lid or "sci-fi" in lid:
        return lid, "cyberpunk", "modern-chinese-urban", ("cyber",)
    if "wuxia" in lid:
        return lid, "wuxia_jianghu", "jianghu-martial", ("martial",)
    if "tomb" in lid or "supernatural" in lid:
        return lid, "shanhai_zhiguai", "confucian_officialdom", ("myth",)
    if "apocalypse" in lid:
        return lid, "post_apocalyptic", "modern-chinese-urban", ("wasteland",)
    if "historical" in lid:
        return lid, "hard_reality", "confucian_officialdom", ("historical",)
    return lid, "hard_reality", "modern-chinese-urban", ("legacy",)


def expand_taxonomy() -> list[GenreTaxon]:
    out: list[GenreTaxon] = []
    seen: set[str] = set()

    for lid in sorted(_LEGACY_IDS):
        _hint, preset, culture, tags = _legacy_defaults(lid)
        title, vibe = _LEGACY_TITLES.get(lid, (_hint, f"既有题材包 {lid}"))
        out.append(GenreTaxon(
            id=lid, title=title, family="legacy", family_title="既有",
            subtrope="legacy", tier="legacy", tags=tags,
            default_culture=culture, primary_preset=preset,
            secondary_presets=_secondary_for(preset),
            track_profile="legacy", vibe=vibe,
            legacy=True, macro_templates=_macro_for("mystery"),
        ))
        seen.add(lid)

    for fam, (fam_title, preset, culture, profile, subs) in _FAMILIES.items():
        for sub_id, sub_title, tags in subs:
            gid = f"{fam}-{sub_id}"
            if gid in seen:
                continue
            title = f"{fam_title}·{sub_title}"
            out.append(GenreTaxon(
                id=gid, title=title, family=fam, family_title=fam_title,
                subtrope=sub_id, tier="base", tags=tuple(tags),
                default_culture=culture, primary_preset=preset,
                secondary_presets=_secondary_for(preset),
                track_profile=profile,
                vibe=f"{fam_title}品类下的「{sub_title}」叙事发动机",
                macro_templates=_macro_for(profile),
            ))
            seen.add(gid)

            if sub_id in _TONE_ALLOWED.get(fam, []):
                prefer = _TONE_PREFER.get(sub_id)
                for tone_id, (tone_title, tone_tags) in _TONES.items():
                    if tone_id != prefer:
                        continue
                    if (fam, sub_id, tone_id) in _TONE_BAN:
                        continue
                    tid = f"{gid}-{tone_id}"
                    if tid in seen:
                        continue
                    out.append(GenreTaxon(
                        id=tid, title=f"{title}·{tone_title}",
                        family=fam, family_title=fam_title,
                        subtrope=sub_id, tier="hot",
                        tags=tuple(dict.fromkeys([*tags, *tone_tags])),
                        default_culture=culture, primary_preset=preset,
                        secondary_presets=_secondary_for(preset),
                        track_profile=profile,
                        vibe=f"{title}的{tone_title}调性变体",
                        macro_templates=_macro_for(profile),
                    ))
                    seen.add(tid)

    extras = [
        ("fusion-cyber-xian-street", "赛博散修街头", "cyber", "赛博",
         "infinite_flow", "modern-chinese-urban", "cyber", ["cyber", "cultivation"]),
        ("fusion-rule-office", "规则怪谈职场", "horror", "恐怖",
         "urban_supernatural", "modern-chinese-urban", "horror",
         ["horror", "workplace", "rules"]),
        ("fusion-otome-war", "乙女战争", "isekai-family", "穿越",
         "western_fantasy", "anglo-american", "romance",
         ["isekai", "romance", "military"]),
        ("fusion-treasure-rebirth", "重生鉴宝", "urban-power", "都市异能",
         "hard_reality", "modern-chinese-urban", "urban", ["urban", "rebirth"]),
        ("fusion-idol-horror", "偶像怪谈", "horror", "恐怖",
         "urban_supernatural", "korean-hwarang", "horror", ["horror", "workplace"]),
        ("fusion-fleet-romance", "舰队恋歌", "space", "星际",
         "cyberpunk", "anglo-american", "romance", ["space", "romance"]),
        ("fusion-palace-system", "后宫系统", "palace", "宫斗",
         "hard_reality", "confucian_officialdom", "palace", ["palace", "system"]),
        ("fusion-beast-farm", "兽世种田", "myth", "神话",
         "western_fantasy", "anglo-american", "slice", ["fantasy", "farming"]),
        ("fusion-mecha-xian", "机甲渡劫", "mecha", "机甲",
         "cyberpunk", "confucian_officialdom", "mecha", ["mecha", "cultivation"]),
        ("fusion-spy-romance", "谍战甜宠", "mystery-family", "推理",
         "hard_reality", "modern-chinese-urban", "romance", ["mystery", "romance"]),
        ("fusion-short-xian", "短剧修仙", "short-drama", "短剧热梗",
         "xianxia_cultivation", "modern-chinese-urban", "cultivation",
         ["cultivation", "shuang", "romance"]),
        ("fusion-cozy-space", "星际治愈日常", "space", "星际",
         "cyberpunk", "anglo-american", "slice", ["space", "slice", "heal"]),
        ("fusion-legal-system", "律政系统", "legal-medical", "律政医疗",
         "hard_reality", "modern-chinese-urban", "workplace",
         ["workplace", "system", "mystery"]),
        ("fusion-food-apocalypse", "末世开食堂", "food-biz", "美食经营",
         "post_apocalyptic", "modern-chinese-urban", "slice",
         ["food", "wasteland"]),
        ("fusion-adventure-romance", "寻宝恋爱", "adventure", "冒险奇谭",
         "western_fantasy", "anglo-american", "romance",
         ["adventure", "romance"]),
    ]
    for eid, title, fam, fam_title, preset, culture, profile, tags in extras:
        if eid in seen:
            continue
        out.append(GenreTaxon(
            id=eid, title=title, family=fam, family_title=fam_title,
            subtrope="fusion", tier="fusion", tags=tuple(tags),
            default_culture=culture, primary_preset=preset,
            secondary_presets=_secondary_for(preset),
            track_profile=profile, vibe=f"蓝海融合：{title}",
            macro_templates=_macro_for(profile),
        ))
        seen.add(eid)

    return out


@lru_cache(maxsize=1)
def all_taxa() -> tuple[GenreTaxon, ...]:
    return tuple(expand_taxonomy())


def taxon_by_id(genre_id: str) -> GenreTaxon | None:
    for t in all_taxa():
        if t.id == genre_id:
            return t
    return None


# ---------- P22：三轴亲和公共函数（gacha/cross_check/macro 同源消费） ----------

def culture_for_genre(genre_id: str) -> str | None:
    """题材推荐文化（taxonomy default_culture）；未知题材 → None。"""
    t = taxon_by_id(genre_id)
    return t.default_culture if t else None


def presets_for_genre(genre_id: str) -> tuple[str, ...]:
    """题材亲和骨架列表（primary 在前 + secondary）；未知题材 → 空元组。"""
    t = taxon_by_id(genre_id)
    if not t:
        return ()
    return (t.primary_preset, *t.secondary_presets)


def macro_templates_for_genre(genre_id: str) -> tuple[str, ...]:
    """题材推荐幕结构模板列表（首个为最推荐）；未知题材 → 空元组。"""
    t = taxon_by_id(genre_id)
    return t.macro_templates if t else ()


def is_preset_compatible(genre_id: str, preset: str | None) -> bool:
    """题材×骨架亲和判定：preset 在 (primary+secondary) 内 → True；
    未知题材 / 空 preset → True（不出警）。"""
    if not preset:
        return True
    presets = presets_for_genre(genre_id)
    if not presets:
        return True
    return preset in presets


def list_taxa(
    *, q: str = "", tags: Iterable[str] | None = None,
    tier: str = "", family: str = "",
    offset: int = 0, limit: int = 24,
) -> tuple[list[GenreTaxon], int]:
    tags_set = {t.strip() for t in (tags or []) if t and t.strip()}
    qn = (q or "").strip().lower()
    rows = []
    for t in all_taxa():
        if tier and t.tier != tier:
            continue
        if family and t.family != family:
            continue
        if tags_set and not tags_set.issubset(set(t.tags)):
            continue
        if qn:
            blob = f"{t.id} {t.title} {t.family_title} {t.vibe} {' '.join(t.tags)}".lower()
            if qn not in blob:
                continue
        rows.append(t)
    total = len(rows)
    limit = max(1, min(int(limit or 24), 100))
    offset = max(0, int(offset or 0))
    return rows[offset:offset + limit], total


def taxonomy_stats() -> dict:
    rows = all_taxa()
    return {
        "total": len(rows),
        "legacy": sum(1 for t in rows if t.legacy),
        "generated": sum(1 for t in rows if not t.legacy),
        "families": len({t.family for t in rows}),
    }
