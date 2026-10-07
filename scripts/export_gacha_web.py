"""开局抽卡数据导出：story_engine 静态数据 → web/gacha/data.js

用法：.venv/Scripts/python.exe scripts/export_gacha_web.py
产出：web/gacha/data.js（window.GACHA_DATA = {...}）
题材库更新后重跑本脚本即可。
"""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from story_engine.macro.templates import TEMPLATES, compute_acts  # noqa: E402
from story_engine.meta.genre_taxonomy import macro_templates_for_genre  # noqa: E402
from story_engine.worldview.layers import ALL_PARAMS  # noqa: E402
from story_engine.worldview.presets import PRESETS  # noqa: E402

GENRES_DIR = ROOT / "story_engine" / "plugins" / "genres"
OUT_FILE = ROOT / "web" / "gacha" / "data.js"
TOTAL_EPISODES = 12

#: 世界观规则句选用的参数（有表现力、访客能感知的 10 个）
RULE_PARAM_KEYS = [
    "physics_deviation", "metaphysics", "destiny_mechanism",
    "power_source", "cost_structure", "species_diversity",
    "political_system", "core_values", "taboo_system", "hidden_truths",
]

#: 文化 → 姓名池
CULTURE_POOL = {
    "jianghu-martial": "cn", "confucian_officialdom": "cn",
    "modern-chinese-urban": "cn",
    "japanese-shinto": "jp", "korean-hwarang": "jp",
    "anglo-american": "western", "latin-mediterranean": "western",
    "scandinavian-protestant": "western",
    "arab-islamic": "other", "south-asian": "other",
    "southeast-asian": "other",
}

#: 冲突类型 → 中文词（句式填空用）
CONFLICT_WORDS = {
    "cognitive": "认知错位", "relational": "关系撕裂",
    "physical": "生死对抗", "political": "权力倾轧",
    "existential": "存在危机", "moral": "道德两难",
    "internal": "内心挣扎", "cosmic": "宇宙恐怖", "resource": "资源争夺",
}

#: 骨架模板中文名（与 backend/routers/macro.py 的 TEMPLATES_META 保持一致）
SKELETON_NAMES = {
    "save_the_cat_15": ("救猫十五拍", "Snyder 经典影视结构，15 个固定节拍点"),
    "truby_22": ("Truby 22 步", "有机故事结构，22 个关键转折"),
    "three_act_classic": ("经典三幕", "亚里士多德三幕，简洁有力"),
    "dtg_50_30": ("短剧 50+30", "80 集短剧节奏（前 50 爽感+后 30 收线）"),
    "wuxia_classic": ("武侠章回", "金圣叹评书体，武侠/公案专用"),
    "romance_beat": ("言情节拍", "言情/甜宠标准结构"),
    "hero_journey_12": ("英雄之旅", "Campbell/Vogler 十二站，奇幻/冒险/神话"),
    "kishotenketsu_4": ("起承转合", "东方四段式，日常/治愈/无强冲突"),
    "freytag_5": ("弗莱塔格金字塔", "古典五幕剧，正剧/历史/权谋"),
    "story_circle_8": ("丹·哈蒙故事环", "八步循环，科幻/赛博/机甲"),
    "mystery_fairplay_8": ("本格公平竞技", "线索全公开的推理结构，挑战读者"),
    "horror_descent_7": ("恐怖递进", "异样→规则→显形→终局，恐怖/克苏鲁"),
    "apocalypse_survival_6": ("末日生存", "崩塌→求生→立足→新秩序"),
    "urban_rise_8": ("都市逆袭", "蛰伏→打脸→博弈→登顶，都市/职场"),
    "palace_intrigue_9": ("宫廷权谋", "入局→结网→大案→登顶，宫斗/朝堂"),
    "war_campaign_6": ("战争战役", "集结→鏖战→转折→终战，军事/星际"),
    "sports_league_7": ("竞技赛季", "选拔→磨合→崛起→决赛"),
    "isekai_adapt_8": ("异界立足", "穿越→立足→世界真相→抉择"),
    "comedy_escalation_6": ("喜剧升级", "日常→荒诞→翻车→暖收"),
    "tribulation_9": ("修仙渡劫", "引气→筑基→金丹→心魔→渡劫飞升"),
    "revenge_arc_8": ("复仇弧", "血仇→隐忍→清算→了结"),
    "farming_build_6": ("种田经营", "落脚→开荒→危机→兴旺"),
    "rule_horror_8": ("规则怪谈", "规则发布→试探→崩坏→破解"),
    "unit_loop_6": ("单元循环", "快穿/诸天/单元案：框架→历练→收束→终局"),
    "angst_romance_9": ("虐恋", "甜→裂→虐→愈，追妻火葬场标配"),
    "spy_undercover_8": ("谍战潜伏", "受命→潜伏→暴露危机→归队"),
    "academy_growth_7": ("学院试炼", "入学→试炼→竞赛→毕业"),
    "dungeon_crawl_6": ("地下城攻略", "集结→下潜→深层→通关"),
    "showbiz_rise_7": ("娱乐圈星途", "起步→出道→翻红→顶流"),
    "procedural_case_6": ("刑侦程序", "案发→排查→转机→结案"),
    "court_career_8": ("朝堂仕途", "入仕→理政→中枢→拜相"),
}

#: 姓名库（4 池）
NAME_POOLS = {
    "cn": {
        "surnames": ["沈", "顾", "陆", "江", "苏", "叶", "林", "秦", "楚", "萧",
                     "程", "韩", "赵", "卫", "霍", "冷", "燕", "洛", "白", "岳"],
        "given": ["惊鸿", "照影", "无缺", "问舟", "清商", "鹤鸣", "观澜", "逐月",
                  "拾遗", "忘机", "疏影", "孤鸿", "踏雪", "折柳", "听澜", "望舒",
                  "承影", "含光", "静姝", "扶摇", "灵犀", "沧海", "云归", "雨眠",
                  "长歌", "未央", "青崖", "明远", "知微", "既白"],
    },
    "jp": {
        "surnames": ["佐藤", "铃木", "高桥", "田中", "渡边", "伊藤", "山本",
                     "中村", "小林", "加藤", "清水", "森", "宫崎", "藤原", "雪村"],
        "given": ["莲", "翔太", "健", "悠真", "拓海", "凛", "樱", "千鹤",
                  "葵", "美咲", "雪乃", "遥", "真昼", "灯", "枫"],
    },
    "western": {
        "given": ["亚瑟", "艾登", "莱昂", "卡尔", "维克多", "伊森", "卢卡斯",
                  "奥利弗", "塞德里克", "罗兰", "艾拉", "薇拉", "莉娅", "索菲",
                  "艾琳娜", "塞西莉亚", "伊芙", "萝丝", "格蕾丝", "奥黛丽"],
        "family": ["布莱克", "怀特", "格雷", "斯通", "费尔法克斯", "霍桑",
                   "兰开斯特", "温莎", "德维尔", "莫顿", "克劳斯", "斯坦恩",
                   "奥克利", "瑞文", "霍尔特"],
    },
    "other": {
        "names": ["阿米尔", "拉贾", "卡马尔", "桑托斯", "伊布拉欣", "法蒂玛",
                  "莱拉", "祖莱卡", "阿里", "奥马尔", "拉维", "普丽娅", "阿妮塔",
                  "德维", "拉娜", "哈桑", "娜迪亚", "塔拉", "维克拉姆", "索拉雅",
                  "占蓬", "阮文诚", "茜拉", "巴育", "诺拉", "卡玛拉", "阿迪",
                  "布迪", "莎莉", "丹增"],
    },
}


def _value_label(param_key: str, value: str) -> str:
    param = ALL_PARAMS.get(param_key) or {}
    for opt in param.get("options", []):
        if opt.get("value") == value:
            return opt.get("label", value)
    return value


def export_worldviews() -> list[dict]:
    out = []
    for p in PRESETS:
        rules = []
        for key in RULE_PARAM_KEYS:
            val = p["params"].get(key)
            if val is None:
                continue
            rules.append(f"{ALL_PARAMS[key]['label']}：{_value_label(key, val)}")
        out.append({"key": p["key"], "name": p["name"],
                    "vibe": p["vibe"], "rules": rules})
    return out


def export_skeletons() -> list[dict]:
    out = []
    for name in TEMPLATES:
        if name in ("custom", "ai_custom"):
            continue
        cn, brief = SKELETON_NAMES.get(name, (name, ""))
        st = compute_acts(name, TOTAL_EPISODES)
        acts = [{
            "name": a.name, "function": a.function, "range": a.episode_range,
            "beats": [{"name": b.name, "ep": int(b.ep), "desc": b.desc}
                      for b in a.beats],
        } for a in st.acts]
        out.append({"id": name, "name": cn, "brief": brief, "acts": acts})
    return out


def export_genres() -> list[dict]:
    out = []
    for f in sorted(GENRES_DIR.glob("*.yaml")):
        raw = yaml.safe_load(f.read_text(encoding="utf-8"))
        params = raw.get("params") or {}
        prompt = params.get("prompt") or {}
        fusion = raw.get("fusion") or {}
        gid = raw["name"]
        title = params.get("title")
        # 3 个 legacy 基类题材（mystery/romance/wuxia）无 fusion 段，
        # core_conflict 回退到 prompt.setting（前提简介，315/315 都有）
        core = fusion.get("core_conflict") or prompt.get("setting", "")
        tracks = [{"id": t["id"], "name": t["name"]}
                  for t in params.get("tracks") or []]
        if not title or not core or not tracks:
            raise SystemExit(f"题材 {gid} 缺 title/core_conflict/tracks，导出中止")
        tags = params.get("taxonomy_tags") or fusion.get("parent_genres") or []
        conflict_words = [CONFLICT_WORDS.get(c["type"], c["type"])
                          for c in params.get("conflict_types") or []]
        out.append({
            "id": gid,
            "title": title,
            "tags": tags,
            "coreConflict": core,
            "setting": prompt.get("setting", ""),
            "characters": prompt.get("characters", ""),
            "role": prompt.get("role", ""),
            "tracks": tracks,
            "conflictWords": conflict_words,
            "resolution": params.get("resolution_pattern", ""),
            "recommendedPreset": params.get("recommended_preset"),
            "recommendedCulture": params.get("recommended_culture"),
            "recommendedTemplates": list(macro_templates_for_genre(gid)),
        })
    return out


def main() -> None:
    data = {
        "version": datetime.date.today().isoformat(),
        "totalEpisodes": TOTAL_EPISODES,
        "genres": export_genres(),
        "worldviews": export_worldviews(),
        "skeletons": export_skeletons(),
        "namePools": NAME_POOLS,
        "culturePool": CULTURE_POOL,
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(
        "window.GACHA_DATA = "
        + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    size_kb = OUT_FILE.stat().st_size // 1024
    print(f"导出完成：{OUT_FILE.name}  题材 {len(data['genres'])}  "
          f"世界观 {len(data['worldviews'])}  骨架 {len(data['skeletons'])}  "
          f"体积 {size_kb}KB")


if __name__ == "__main__":
    main()
