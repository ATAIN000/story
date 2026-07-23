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
                "style": "1000-1500字，节奏清晰，冲突可见，章末留钩子",
                "hard_requirements": [
                    f"紧扣题材标签：{', '.join(t.tags)}",
                    "每章推进至少一个轨道（主线或主题）",
                    "禁止无代价的万能解决方案",
                    "人物动机必须可被读者理解",
                ],
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
