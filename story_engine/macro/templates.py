"""幕结构模板库 — 20 个经典/品类叙事结构 × total_episodes 自动计算 beat 章节位置

设计文档：docs/宏观叙事规划层_设计方案.md 第 3.3 节组件 2。

每个模板 = 一组 Act 定义（id/name/function/pct_range + beats）。
``compute_acts(template_name, total_episodes)`` 将百分比映射为章节区间。
"""
from __future__ import annotations

from .plan import Act, ActBeat, ActStructure


# ============================================================
# 模板定义
#
# 每个 act: (id, name, function, (start_pct, end_pct), [(beat_name, pct, desc), ...])
# ============================================================

_SAVE_THE_CAT_15 = [
    ("act_1_setup", "建置", "建立世界、角色、核心冲突", (0, 20), [
        ("opening_image", 1, "主角的日常状态/初始意象"),
        ("setup", 5, "世界观/角色/日常生活展开"),
        ("inciting_incident", 10, "打破日常的触发事件"),
        ("debate", 15, "主角犹豫是否踏上旅程"),
        ("break_into_two", 20, "主角接受挑战，进入新世界"),
    ]),
    ("act_2a_rising", "上升", "主角在目标上取得进展，但问题升级", (20, 50), [
        ("b_story", 25, "副线开启：重要关系建立"),
        ("fun_and_games", 35, "才华展示/对抗交锋/爽感段落"),
        ("midpoint", 50, "中点转折——假胜利或假败"),
    ]),
    ("act_2b_descent", "坠落", "黑暗期/假败/重新觉醒", (50, 80), [
        ("bad_guys_close_in", 58, "对手反击/证据被毁/盟友受伤"),
        ("all_is_lost", 72, "最低点——主角失去一切"),
        ("dark_night", 77, "主角自我怀疑/放弃/反思"),
        ("break_into_three", 80, "新线索出现/觉醒/重新出发"),
    ]),
    ("act_3_climax", "高潮与结局", "终极对决/真相揭露/弧光完成", (80, 100), [
        ("finale", 90, "对决/反转/真相揭露/牺牲"),
        ("final_image", 99, "新均衡/弧光完成/呼应开场"),
    ]),
]

_TRUBY_22 = [
    ("act_1_setup", "建置", "建立角色、需求、对手", (0, 25), [
        ("premise", 1, "故事前提与核心命题"),
        ("ghost_wound", 5, "角色的过去创伤（Ghost）"),
        ("story_need", 9, "角色的内在需求浮现"),
        ("desire", 13, "角色的外在欲望确立"),
        ("opponent", 17, "对手/阻力出现"),
        ("fake_ally", 21, "假盟友/复杂关系引入"),
        ("first_plan", 25, "角色制定第一个计划"),
    ]),
    ("act_2a_conflict", "冲突上升", "正面交锋与虚假胜利", (25, 55), [
        ("first_clash", 30, "与对手的首次正面交锋"),
        ("revelation", 37, "关键信息揭露"),
        ("midpoint_shift", 44, "中点转折——认知或处境反转"),
        ("apparent_victory", 50, "表面胜利——读者知道是假的"),
        ("complication", 55, "局势复杂化/新威胁"),
    ]),
    ("act_2b_crisis", "危机", "全面崩溃与自我揭露", (55, 80), [
        ("opponent_closes_in", 60, "对手步步紧逼"),
        ("second_clash", 66, "第二次交锋——主角失败"),
        ("crisis", 72, "危机到达顶点"),
        ("need_revealed", 76, "真实需求被揭示"),
        ("self_revelation", 80, "自我揭露——理解真相"),
    ]),
    ("act_3_resolution", "高潮与抉择", "道德抉择与新均衡", (80, 100), [
        ("moral_decision", 85, "关键道德选择"),
        ("thematic_climax", 92, "主题高潮——主题论证完成"),
        ("new_equilibrium", 97, "新均衡/弧光完成"),
        ("final_image", 100, "最终意象——呼应开场"),
    ]),
]

_THREE_ACT_CLASSIC = [
    ("act_1_setup", "第一幕：建置", "建立日常世界与核心冲突", (0, 25), [
        ("setup", 5, "世界观/角色/日常生活"),
        ("inciting_incident", 12, "打破日常的触发事件"),
        ("plot_point_one", 25, "第一幕转折——主角进入新世界"),
    ]),
    ("act_2_confrontation", "第二幕：对抗", "主角在目标上进展但问题升级", (25, 75), [
        ("rising_action", 35, "上升行动——冲突加剧"),
        ("midpoint", 50, "中点转折"),
        ("plot_point_two", 75, "第二幕转折——最低点"),
    ]),
    ("act_3_resolution", "第三幕：结局", "终极对决与弧光完成", (75, 100), [
        ("climax", 90, "高潮——终极对决"),
        ("resolution", 97, "结局——新均衡"),
    ]),
]

_DTG_50_30 = [
    ("act_1_golden_open", "黄金开局", "快速建立冲突，爽感拉满", (0, 12), [
        ("hook", 1, "黄金钩子——开场即冲突"),
        ("inciting_incident", 5, "触发事件——身份揭露/逆袭起点"),
        ("first_victory", 12, "首次打脸——小高潮"),
    ]),
    ("act_2_escalation", "爽感密集", "密集爽点+矛盾升级", (12, 50), [
        ("power_up", 18, "实力提升/获得关键资源"),
        ("face_slap_1", 25, "大型打脸——敌人溃败"),
        ("face_slap_2", 33, "连环打脸——地位逆转"),
        ("midpoint_escalation", 42, "矛盾升级——更强对手出现"),
        ("all_is_lost", 50, "全线崩溃——假败"),
    ]),
    ("act_3_climax", "收线高潮", "真相揭露+终极对决", (50, 100), [
        ("truth_reveal", 70, "真相揭露——身世/阴谋大白"),
        ("final_showdown", 90, "终极对决——复仇/正名/逆袭完成"),
    ]),
]

_WUXIA_CLASSIC = [
    ("act_1_qi", "起", "缘起——主角登场，世界展开", (0, 20), [
        ("opening_stance", 2, "起式——主角登场，展露气度"),
        ("world_setting", 8, "江湖/朝堂背景铺陈"),
        ("master_appears", 15, "名师/引路人出现"),
    ]),
    ("act_2_cheng", "承", "承接——入门成长，初遇对手", (20, 40), [
        ("first_trial", 25, "首次试炼——显露天赋"),
        ("rival_introduced", 32, "对手/情敌登场"),
        ("skill_acquired", 38, "获得关键武功/技能/宝物"),
    ]),
    ("act_3_zhuan", "转", "转折——背叛、低谷、觉醒", (40, 75), [
        ("betrayal", 45, "背叛——信任崩塌"),
        ("lowest_point", 52, "最低点——失去一切"),
        ("hidden_truth", 60, "隐秘真相浮出水面"),
        ("breakthrough", 68, "顿悟突破——实力蜕变"),
    ]),
    ("act_4_he", "合", "收束——终极对决，尘埃落定", (75, 100), [
        ("final_battle", 85, "终极对决——恩怨了结"),
        ("resolution", 95, "收束——归隐/江湖新格局"),
    ]),
]

_ROMANCE_BEAT = [
    ("act_1_meet", "相遇", "初次相遇与吸引", (0, 25), [
        ("meet_cute", 3, "浪漫邂逅——意外相遇"),
        ("attraction_denied", 12, "吸引但否认——外部阻力"),
        ("first_kiss", 22, "第一次亲密接触"),
    ]),
    ("act_2_develop", "发展", "关系深入与矛盾爆发", (25, 60), [
        ("commitment", 30, "确认关系——甜蜜升温"),
        ("external_conflict", 40, "外部冲突——家庭/地位/误会"),
        ("misunderstanding", 50, "误解加深——信任动摇"),
        ("breakup", 58, "分手——关系破裂"),
    ]),
    ("act_3_reunion", "和解", "低谷、醒悟与重聚", (60, 100), [
        ("dark_moment", 65, "黑暗时刻——思念与后悔"),
        ("grand_gesture", 80, "盛大告白——为爱付出"),
        ("happy_ending", 95, "圆满结局——在一起"),
    ]),
]

# ============================================================
# P24 扩充：品类专用结构（23 个 track_profile 全覆盖）
# ============================================================

_HERO_JOURNEY_12 = [
    ("act_1_ordinary", "日常世界", "平凡世界与冒险召唤", (0, 15), [
        ("ordinary_world", 2, "日常世界——主角的平凡状态"),
        ("call_to_adventure", 8, "冒险召唤——命运来敲门"),
        ("refusal", 12, "拒斥召唤——恐惧与犹豫"),
        ("mentor", 15, "遇见导师——获得信念与馈赠"),
    ]),
    ("act_2_threshold", "试炼之路", "跨越门槛，历经考验", (15, 50), [
        ("crossing_threshold", 18, "跨越门槛——进入非常世界"),
        ("tests_allies_enemies", 30, "考验/盟友/敌人——新规则下的摸索"),
        ("approach", 42, "逼近虎穴——向最大挑战挺进"),
        ("ordeal", 50, "磨难——生死边缘的至暗考验"),
    ]),
    ("act_3_return", "归来", "携宝回归，完成蜕变", (50, 100), [
        ("reward", 55, "奖赏——夺得圣物/真相/力量"),
        ("road_back", 68, "归途——余波追击与最后抉择"),
        ("resurrection", 85, "复活——终极考验中涅槃"),
        ("elixir", 95, "携药归来——以蜕变之姿反哺日常世界"),
    ]),
]

_KISHOTENKETSU_4 = [
    ("act_1_ki", "起", "平静日常与人物登场", (0, 25), [
        ("introduction", 10, "起——人物与日常基调确立"),
    ]),
    ("act_2_sho", "承", "日常推进，细节累积", (25, 50), [
        ("development", 35, "承——关系/事件平稳推进"),
    ]),
    ("act_3_ten", "转", "意外转折——全篇支点", (50, 75), [
        ("twist", 60, "转——意外/错位/真相的突转"),
    ]),
    ("act_4_ketsu", "合", "收束——转折后的余味", (75, 100), [
        ("resolution", 90, "合——收束与回味，日常被重新定义"),
    ]),
]

_FREYTAG_5 = [
    ("act_1_exposition", "开端", "人物与局势铺陈", (0, 15), [
        ("introduction", 8, "人物/阵营/矛盾伏笔铺陈"),
        ("inciting_incident", 15, "激励事件——冲突被点燃"),
    ]),
    ("act_2_rising", "上升", "冲突逐步升级", (15, 45), [
        ("complication", 30, "纠葛加深——多方势力卷入"),
    ]),
    ("act_3_climax", "高潮", "矛盾总爆发", (45, 60), [
        ("climax", 55, "高潮——命运逆转的顶点"),
    ]),
    ("act_4_falling", "回落", "高潮后的连锁余波", (60, 85), [
        ("reversal", 70, "回落——代价显现/局势崩塌"),
    ]),
    ("act_5_denouement", "结局", "尘埃落定", (85, 100), [
        ("catastrophe_resolution", 95, "结局——悲剧收场或团圆收束"),
    ]),
]

_STORY_CIRCLE_8 = [
    ("act_1_comfort", "舒适区", "主角与未满足的需求", (0, 15), [
        ("you", 3, "主角处境——舒适区中的匮乏"),
        ("need", 12, "需求浮现——想要改变"),
    ]),
    ("act_2_search", "陌生区探索", "踏入新局，适应规则", (15, 40), [
        ("go", 18, "踏入陌生境地"),
        ("search", 30, "探索与适应——付出代价的学习"),
    ]),
    ("act_3_find", "得到与代价", "找到所求，付出沉重代价", (40, 65), [
        ("find", 45, "得到——目标物/能力/真相到手"),
        ("take", 55, "代价——得到的一切都有标价"),
    ]),
    ("act_4_return", "回归与改变", "回到原点，已然不同", (65, 100), [
        ("return", 75, "回归——带着后果回到来处"),
        ("change", 90, "改变——主角已非昔日之人"),
    ]),
]

_MYSTERY_FAIRPLAY_8 = [
    ("act_1_case", "案发", "侦探登场与案件发生", (0, 15), [
        ("detective_intro", 3, "侦探/主角能力展示"),
        ("crime", 10, "案件发生——不可能/离奇现场"),
        ("client", 15, "委托确立——调查正式开始"),
    ]),
    ("act_2_investigate", "调查", "线索与嫌疑人的公平铺陈", (15, 55), [
        ("clues", 25, "线索收集——读者与侦探信息同步"),
        ("suspects", 35, "嫌疑人轮番登场——各怀鬼胎"),
        ("red_herring", 45, "误导——最像凶手的人不是凶手"),
        ("first_reveal", 55, "第一层解答——被推翻的假说"),
    ]),
    ("act_3_dark", "迷局", "局面恶化，真凶逼近", (55, 80), [
        ("second_crime", 62, "第二案/灭口——凶手主动出击"),
        ("all_clues", 72, "全部线索到齐——挑战读者"),
        ("sleight", 78, "关键细节回收——被忽略的一幕"),
    ]),
    ("act_4_reveal", "解谜", "逻辑推演与真相大白", (80, 100), [
        ("deduction", 88, "推理秀——逻辑链条逐一闭合"),
        ("reveal", 95, "真相大白——动机与手法揭晓"),
    ]),
]

_HORROR_DESCENT_7 = [
    ("act_1_normal", "日常裂缝", "平静表面下的第一丝异样", (0, 15), [
        ("normal_world", 3, "日常确立——值得留恋的平静"),
        ("anomaly", 12, "异样初现——无法解释的小事"),
    ]),
    ("act_2_creep", "异样逼近", "规则浮现，威胁逼近", (15, 50), [
        ("first_encounter", 22, "首次遭遇——目击「不该存在之物」"),
        ("rule_discovery", 35, "发现规则——活下来必须遵守的禁忌"),
        ("escalation", 48, "升级——规则被试探/破坏"),
    ]),
    ("act_3_dread", "恐怖显形", "真相显露，退路断绝", (50, 85), [
        ("truth_hint", 58, "真相一角——恐怖的源头显露"),
        ("no_escape", 68, "无路可逃——退路被逐一封死"),
        ("confrontation", 80, "正面对峙——直面不可名状"),
    ]),
    ("act_4_end", "终局", "幸存或沉沦", (85, 100), [
        ("survive_or_fall", 92, "终局——代价惨重的幸存/沉沦"),
        ("lingering", 98, "余悸——「其实还没结束」的尾巴"),
    ]),
]

_APOCALYPSE_SURVIVAL_6 = [
    ("act_1_collapse", "崩塌", "灾变降临，秩序瓦解", (0, 15), [
        ("omen", 3, "征兆——被忽视的异常信号"),
        ("outbreak", 10, "灾变爆发——日常终结"),
        ("escape", 15, "逃生——第一波生死考验"),
    ]),
    ("act_2_wild", "求生", "资源稀缺，人性初考", (15, 45), [
        ("scarcity", 25, "物资争夺——生存规则重写"),
        ("first_loss", 35, "首次失去——同伴/家园/信念"),
        ("refuge", 45, "抵达避难所——短暂喘息"),
    ]),
    ("act_3_base", "立足", "建立据点，人心为患", (45, 70), [
        ("community", 52, "据点建设——分工与新秩序"),
        ("human_threat", 62, "人祸——比灾难更危险的是人"),
        ("base_crisis", 70, "据点危机——内忧外患总爆发"),
    ]),
    ("act_4_order", "新秩序", "决战与新世界", (70, 100), [
        ("showdown", 82, "决战——保卫/夺回家园"),
        ("new_order", 92, "新秩序——废墟上的重建与希望"),
    ]),
]

_URBAN_RISE_8 = [
    ("act_1_low", "蛰伏", "低谷开局与转机降临", (0, 12), [
        ("humiliation", 3, "受辱——被踩在谷底的开局"),
        ("awakening", 10, "觉醒——不甘与决心"),
        ("gift", 12, "转机——异能/贵人/秘密到手"),
    ]),
    ("act_2_slap", "初露锋芒", "小胜与打脸，引起注意", (12, 40), [
        ("first_win", 18, "首胜——小试牛刀"),
        ("face_slap", 28, "打脸——轻视者付出代价"),
        ("enemy_notice", 38, "树敌——进入更强者的视野"),
    ]),
    ("act_3_game", "格局博弈", "更大舞台的明争暗斗", (40, 75), [
        ("bigger_stage", 48, "登台——进入核心圈层"),
        ("setback", 58, "重挫——被联手打压/失去依仗"),
        ("scheme", 68, "布局——暗中积蓄反击之力"),
        ("counter", 75, "反击——一举翻盘"),
    ]),
    ("act_4_top", "登顶", "终极对决与新地位", (75, 100), [
        ("final_duel", 85, "终极对决——与幕后黑手清算"),
        ("new_status", 95, "登顶——新身份/新秩序确立"),
    ]),
]

_PALACE_INTRIGUE_9 = [
    ("act_1_enter", "入局", "进入权力场，初尝荣宠与敌意", (0, 15), [
        ("entry", 3, "入宫/入朝——踏入权力漩涡"),
        ("first_favor", 10, "初宠/初功——引起注意"),
        ("enemy_made", 15, "结怨——成为某方眼中钉"),
    ]),
    ("act_2_web", "结网", "结盟与构陷的暗战", (15, 45), [
        ("alliance", 25, "结盟——找到利益共同体"),
        ("frame_up", 35, "构陷——第一次险些万劫不复"),
        ("counterplot", 45, "反将——借力打力化解危机"),
    ]),
    ("act_3_storm", "大案", "风暴中心，底牌尽出", (45, 80), [
        ("purge", 55, "大案/清洗——旧格局崩塌"),
        ("downfall", 65, "失势——跌落谷底/被打入冷宫"),
        ("secret_weapon", 72, "底牌——握有翻盘的秘密"),
        ("reversal", 80, "逆转——绝地反击一击致命"),
    ]),
    ("act_4_crown", "登顶", "权力的终点", (80, 100), [
        ("final_scheme", 88, "终极布局——清算所有对手"),
        ("throne_or_retire", 96, "登顶或归隐——权力的代价揭晓"),
    ]),
]

_WAR_CAMPAIGN_6 = [
    ("act_1_muster", "集结", "战火点燃，被迫应战", (0, 15), [
        ("call_up", 5, "征召——家园告急/临危受命"),
        ("first_skirmish", 15, "初战——血与火的第一课"),
    ]),
    ("act_2_war", "鏖战", "胜负拉锯，代价惨重", (15, 55), [
        ("victory", 25, "首胜——站稳脚跟"),
        ("defeat", 40, "惨败——轻敌/叛徒/实力差距"),
        ("lowest", 52, "最低谷——弹尽粮绝/众叛亲离"),
    ]),
    ("act_3_turn", "转折", "新策略与反攻", (55, 85), [
        ("new_strategy", 62, "顿悟——找到敌人的命门"),
        ("counteroffensive", 75, "反攻——扭转战局的关键一役"),
        ("decisive", 85, "决战——倾尽全力的一搏"),
    ]),
    ("act_4_end", "终战", "胜利或悲歌", (85, 100), [
        ("triumph_or_elegy", 95, "凯旋或悲歌——战争的最终账单"),
    ]),
]

_SPORTS_LEAGUE_7 = [
    ("act_1_select", "选拔", "天赋显露与入队", (0, 15), [
        ("talent_shown", 5, "天赋初显——惊艳或被低估"),
        ("join_team", 15, "入队——踏入竞技世界"),
    ]),
    ("act_2_train", "磨合", "苦练、首败与裂痕", (15, 50), [
        ("training", 25, "特训——汗水与短板"),
        ("first_loss", 35, "首败——被现实教育"),
        ("rift", 45, "裂痕——队内矛盾/信任危机"),
    ]),
    ("act_3_climb", "崛起", "和解与连胜", (50, 85), [
        ("comeback", 58, "和解回归——队伍重凝一心"),
        ("rival_duel", 70, "宿敌对决——跨越心魔"),
        ("semifinal", 82, "半决赛——惨胜晋级"),
    ]),
    ("act_4_final", "决赛", "巅峰之战", (85, 100), [
        ("final_match", 92, "决赛——倾其所有的巅峰对决"),
        ("championship", 98, "加冕——冠军/虽败犹荣"),
    ]),
]

_ISEKAI_ADAPT_8 = [
    ("act_1_cross", "穿越", "异界降临与金手指", (0, 12), [
        ("crossing", 3, "穿越——熟悉的世界消失"),
        ("confusion", 8, "错乱——新身份与生存危机"),
        ("cheat", 12, "金手指——立足之本到手"),
    ]),
    ("act_2_foothold", "立足", "适应规则，建立根基", (12, 45), [
        ("first_friend", 20, "第一个同伴/靠山"),
        ("local_rules", 30, "摸清规则——力量体系与社会结构"),
        ("first_threat", 42, "首个威胁——在异界树敌"),
    ]),
    ("act_3_truth", "世界真相", "崛起与世界之谜", (45, 80), [
        ("rise", 55, "崛起——在新世界站稳脚跟"),
        ("world_secret", 65, "世界真相——穿越并非偶然"),
        ("faction_war", 75, "阵营大战——被卷入世界格局"),
    ]),
    ("act_4_choice", "抉择", "留下或回归", (80, 100), [
        ("final_choice", 88, "终极抉择——两个世界只能选其一"),
        ("stay_or_return", 96, "归宿——留下建设或带着答案回归"),
    ]),
]

_COMEDY_ESCALATION_6 = [
    ("act_1_daily", "日常", "离谱人设与日常基调", (0, 20), [
        ("routine", 5, "日常——主角的奇葩处境"),
        ("quirk", 15, "怪癖确立——笑点的发动机"),
    ]),
    ("act_2_absurd", "荒诞", "计划失控，雪球越滚越大", (20, 55), [
        ("plan", 28, "馊主意——一个注定要翻车的计划"),
        ("escalation", 40, "升级——谎言/误会连环叠加"),
        ("out_of_control", 52, "彻底失控——局面全面崩盘"),
    ]),
    ("act_3_crash", "翻车", "穿帮与收拾残局", (55, 85), [
        ("exposure", 62, "穿帮——一切当众败露"),
        ("fallout", 72, "后果——鸡飞狗跳的烂摊子"),
        ("make_amends", 82, "补救——用更离谱的方式挽回"),
    ]),
    ("act_4_warm", "暖收", "笑过之后的温度", (85, 100), [
        ("reconciliation", 92, "和解——笑闹落定，情谊留底"),
    ]),
]

# ============================================================
# P24.5 第二批：子套路级专用结构（复仇/种田/规则怪谈/快穿/
# 虐恋/谍战/学院/地下城/娱乐圈/渡劫/刑侦/朝堂）
# ============================================================

_TRIBULATION_9 = [
    ("act_1_intro", "踏入仙途", "入门、测灵根、初次引气", (0, 12), [
        ("sect_entry", 3, "入门——拜入宗门/获得传承"),
        ("talent_test", 8, "灵根测试——天赋定位（废材或天骄）"),
        ("first_cultivate", 12, "初次突破——引气入体"),
    ]),
    ("act_2_foundation", "筑基历练", "任务、机缘、结仇", (12, 40), [
        ("mission", 18, "宗门任务——下山历练"),
        ("fortune", 25, "机缘——洞府/秘宝/高人指点"),
        ("conflict", 33, "结仇——天骄之争/夺宝之怨"),
    ]),
    ("act_3_core", "金丹风波", "结丹、心魔、大战", (40, 65), [
        ("core_form", 45, "结丹——境界大突破"),
        ("inner_demon", 52, "心魔劫——道心动摇"),
        ("war", 60, "宗门大战/正魔冲突——卷入大势"),
    ]),
    ("act_4_ascend", "渡劫飞升", "化神、天劫、道果", (65, 100), [
        ("nascent", 70, "元婴/化神——一方巨擘"),
        ("great_tribulation", 85, "九九天劫——生死一线"),
        ("ascension", 96, "飞升/道果——得证大道"),
    ]),
]

_REVENGE_ARC_8 = [
    ("act_1_wound", "血仇", "温情破碎，立誓复仇", (0, 15), [
        ("happy_before", 3, "昔日温情——将被夺走的日常"),
        ("massacre", 10, "灭门/背叛——血仇铸成"),
        ("vow", 15, "立誓——活下来只为复仇"),
    ]),
    ("act_2_hide", "隐忍", "改头换面，积蓄力量", (15, 45), [
        ("new_identity", 22, "改头换面——新身份入局"),
        ("buildup", 32, "积蓄——武功/势力/财富"),
        ("approach", 42, "接近仇人——取得信任"),
    ]),
    ("act_3_hunt", "清算", "逐一收网，身份将泄", (45, 80), [
        ("first_blood", 52, "第一个仇家伏诛"),
        ("exposure_risk", 62, "身份将泄——仇人起疑"),
        ("big_trap", 72, "反将一军——借仇人之手清障"),
    ]),
    ("act_4_end", "了结", "总清算与代价", (80, 100), [
        ("final_reckoning", 88, "总清算——首恶伏法"),
        ("price_of_revenge", 96, "复仇的代价——救赎或沉沦"),
    ]),
]

_FARMING_BUILD_6 = [
    ("act_1_settle", "落脚", "落地生根，第一桶金", (0, 15), [
        ("arrival", 4, "落脚——来到新天地/接手烂摊子"),
        ("first_field", 12, "第一块田/第一单生意"),
    ]),
    ("act_2_expand", "开荒", "技术立身，产业扩张", (15, 50), [
        ("technique", 25, "新技术/新菜谱/新门路"),
        ("neighbors", 35, "邻里与伙伴——关系网成形"),
        ("expand", 48, "产业扩张——规模初显"),
    ]),
    ("act_3_crisis", "危机", "天灾人祸，守护家业", (50, 80), [
        ("disaster", 58, "天灾/同行打压/官府刁难"),
        ("guard", 68, "守护——全家/全庄共渡难关"),
        ("breakthrough", 76, "口碑打响——品牌立住"),
    ]),
    ("act_4_thrive", "兴旺", "产业帝国/桃源建成", (80, 100), [
        ("prosperity", 90, "兴旺——产业帝国或世外桃源落成"),
    ]),
]

_RULE_HORROR_8 = [
    ("act_1_enter", "入局", "进入怪谈，规则发布", (0, 12), [
        ("arrival", 3, "进入怪谈空间——回不去的门"),
        ("rules_given", 10, "规则发布——必须遵守的条款"),
    ]),
    ("act_2_test", "试探", "违反的代价与边界", (12, 45), [
        ("first_violation", 18, "首起违反——目睹代价"),
        ("rule_test", 28, "试探边界——规则的缝隙"),
        ("false_safe", 38, "虚假安全区——信错规则"),
    ]),
    ("act_3_collapse", "崩坏", "规则矛盾，真相浮现", (45, 80), [
        ("rule_conflict", 50, "规则互相矛盾——必有真伪"),
        ("truth_layer", 62, "第二层规则/世界真相"),
        ("hunt", 74, "大清洗——「它」开始收网"),
    ]),
    ("act_4_solve", "破解", "漏洞与终局", (80, 100), [
        ("loophole", 85, "找到规则漏洞/源头"),
        ("escape_or_become", 95, "逃出——或成为怪谈的一部分"),
    ]),
]

_UNIT_LOOP_6 = [
    ("act_1_frame", "框架确立", "循环机制与首个单元", (0, 10), [
        ("premise", 3, "机制确立——快穿/诸天/单元剧框架"),
        ("first_task", 10, "首个单元开启"),
    ]),
    ("act_2_units", "单元历练", "节奏成形，主线伏笔", (10, 55), [
        ("unit_pattern", 20, "单元节奏成形——进入/任务/脱离"),
        ("growth", 35, "能力/羁绊/道具跨单元累积"),
        ("mainline_hint", 48, "主线伏笔——单元间的异常关联"),
    ]),
    ("act_3_converge", "收束", "主线入侵单元", (55, 85), [
        ("anomaly", 62, "异常单元——主线强势入侵"),
        ("truth", 74, "机制/幕后真相揭晓"),
        ("final_unit", 84, "最终单元——所有伏笔汇入"),
    ]),
    ("act_4_end", "终局", "循环了结", (85, 100), [
        ("mainline_resolve", 93, "主线了结——脱离循环或接管机制"),
    ]),
]

_ANGST_ROMANCE_9 = [
    ("act_1_sweet", "甜", "相遇高甜，埋下隐患", (0, 20), [
        ("meet", 4, "相遇——命中注定的心动"),
        ("sweet", 15, "高甜升温——糖里埋刀"),
    ]),
    ("act_2_crack", "裂", "裂痕与误会", (20, 45), [
        ("crack", 25, "裂痕——隐瞒/替身/门第之见"),
        ("misunderstanding", 35, "误会种成——信任的蛀虫"),
        ("hurt", 44, "第一次重伤——真心被负"),
    ]),
    ("act_3_break", "虐", "决裂与火葬场", (45, 75), [
        ("separation", 52, "分离/决裂——最痛的一刀"),
        ("chase_fail", 62, "追妻/追夫火葬场——被拒门外"),
        ("truth", 72, "真相大白——原来错怪了TA"),
    ]),
    ("act_4_heal", "愈", "赎罪与结局", (75, 100), [
        ("redemption", 84, "赎罪——用行动付出代价"),
        ("reunion_or_be", 94, "破镜重圆（HE）或相忘江湖（BE）"),
    ]),
]

_SPY_UNDERCOVER_8 = [
    ("act_1_mission", "受命", "接受任务，伪装就位", (0, 12), [
        ("assignment", 4, "受命——九死一生的任务"),
        ("cover", 12, "伪装就位——新身份滴水不漏"),
    ]),
    ("act_2_infiltrate", "潜伏", "入网取信，情报初获", (12, 45), [
        ("contact", 20, "接头——打入敌方网络"),
        ("trust", 30, "取得信任——与虎谋皮"),
        ("intel", 40, "第一份关键情报送出"),
    ]),
    ("act_3_crisis", "暴露危机", "怀疑、牺牲、将计就计", (45, 80), [
        ("suspicion", 52, "被怀疑——特务头子的试探"),
        ("compromise", 62, "线人暴露/牺牲——断线之痛"),
        ("double_game", 72, "将计就计——借刀反杀"),
    ]),
    ("act_4_extract", "归队", "决胜情报与撤离", (80, 100), [
        ("final_intel", 86, "决定性情报——扭转战局"),
        ("extraction", 95, "撤离归队——或继续潜伏（开放结局）"),
    ]),
]

_ACADEMY_GROWTH_7 = [
    ("act_1_enroll", "入学", "考核入学，阵营初分", (0, 15), [
        ("entrance", 4, "入学考核——崭露头角或吊车尾"),
        ("class_split", 12, "分班/舍友/阵营——人际格局"),
    ]),
    ("act_2_trial", "试炼", "课程、对手、实战", (15, 50), [
        ("courses", 22, "课程与短板——成长的阵痛"),
        ("club_rival", 32, "社团/对手——既是竞争也是羁绊"),
        ("field_trial", 45, "野外/实战试炼——第一次见血"),
    ]),
    ("act_3_tournament", "竞赛", "选拔、黑幕、决战", (50, 85), [
        ("selection", 58, "院内选拔——拿到大赛入场券"),
        ("conspiracy", 68, "赛事黑幕/学院秘辛浮出水面"),
        ("finals", 80, "联赛决战——为校而战"),
    ]),
    ("act_4_graduate", "毕业", "真相与传承", (85, 100), [
        ("truth", 90, "学院真相/传承揭晓"),
        ("graduation", 97, "毕业——带着羁绊走向更大世界"),
    ]),
]

_DUNGEON_CRAWL_6 = [
    ("act_1_assemble", "集结", "组队入城", (0, 12), [
        ("call", 4, "招募/组队——各怀绝技的同伴"),
        ("entrance", 12, "入城——第一层的风土人情"),
    ]),
    ("act_2_descend", "下潜", "分层攻略，战利与减员", (12, 50), [
        ("floors", 22, "分层攻略——每层的规则与生态"),
        ("loot", 32, "战利品与减员——收益伴随代价"),
        ("mid_boss", 46, "中层守关——团战的洗礼"),
    ]),
    ("act_3_depths", "深层", "团灭危机与真相", (50, 85), [
        ("wipe_risk", 58, "团灭危机——绝境中的抉择"),
        ("dungeon_secret", 68, "地下城真相——它为何存在"),
        ("bottom", 80, "抵达最底层"),
    ]),
    ("act_4_clear", "通关", "决战与回归", (85, 100), [
        ("final_boss", 90, "通关之战——倾尽所有的配合"),
        ("surface", 97, "重返地表——带回的改变"),
    ]),
]

_SHOWBIZ_RISE_7 = [
    ("act_1_trainee", "起步", "小透明与首次登台", (0, 15), [
        ("trainee", 4, "练习生/十八线——无人问津"),
        ("first_stage", 12, "首次登台/试镜——一鸣惊人或惨遭嘲笑"),
    ]),
    ("act_2_debut", "出道", "小火与全网黑", (15, 45), [
        ("debut", 20, "出道——正式进入名利场"),
        ("small_fire", 30, "小火——第一个代表作"),
        ("smear", 42, "黑料/全网黑——资本与对家的绞杀"),
    ]),
    ("act_3_comeback", "翻红", "实力打脸，爆款登顶", (45, 80), [
        ("clarify", 55, "澄清/实力打脸——舆论反转"),
        ("big_work", 65, "爆款作品——现象级出圈"),
        ("rival_fall", 75, "对家塌房/资本博弈胜出"),
    ]),
    ("act_4_top", "顶流", "封神与传承", (80, 100), [
        ("award", 88, "封后/封帝——奖项加身"),
        ("legacy", 96, "顶流——从棋子到执棋人"),
    ]),
]

_PROCEDURAL_CASE_6 = [
    ("act_1_report", "案发", "报案与专案组", (0, 15), [
        ("report", 4, "报案/发现现场——案件立案"),
        ("team", 12, "专案组分工——各展所长"),
    ]),
    ("act_2_legwork", "排查", "走访、技侦、错案", (15, 50), [
        ("interviews", 22, "走访排查——人海中捞针"),
        ("forensics", 33, "技术证据——法医/痕检的突破"),
        ("wrong_suspect", 46, "抓错人——侦查方向被带偏"),
    ]),
    ("act_3_turn", "转机", "关键物证与收网", (50, 85), [
        ("new_evidence", 58, "关键物证——被忽略的细节"),
        ("profile", 68, "真凶侧写——画像闭合"),
        ("net", 78, "收网布控"),
    ]),
    ("act_4_close", "结案", "抓捕与法理人情", (85, 100), [
        ("arrest", 88, "抓捕/庭审——证据链闭环"),
        ("reflection", 96, "结案——法理与人情的余思"),
    ]),
]

_COURT_CAREER_8 = [
    ("act_1_start", "入仕", "科举与外放", (0, 15), [
        ("exam", 4, "科举/举荐——踏入仕途"),
        ("county", 12, "外放基层——天高皇帝远"),
    ]),
    ("act_2_govern", "理政", "政绩与党争", (15, 45), [
        ("governance", 22, "政绩——断案/赈灾/屯田"),
        ("faction", 32, "党争上门——被迫站队"),
        ("crisis", 44, "大案/边患——临危受命"),
    ]),
    ("act_3_court", "中枢", "入京博弈，起落沉浮", (45, 80), [
        ("capital", 52, "入京——中枢的权力游戏"),
        ("purge", 62, "政敌发难——贬谪/下狱"),
        ("turnaround", 74, "翻案/军功——王者归来"),
    ]),
    ("act_4_peak", "拜相", "不世之功与身后名", (80, 100), [
        ("reform", 88, "变法/平乱——不世之功"),
        ("legacy", 96, "拜相/归隐——盖棺论定"),
    ]),
]

_CUSTOM = [
    ("act_1", "第一幕", "建置与触发", (0, 33), [
        ("setup", 10, "世界观与角色建立"),
        ("inciting_incident", 25, "触发事件"),
    ]),
    ("act_2", "第二幕", "对抗与转折", (33, 66), [
        ("midpoint", 50, "中点转折"),
        ("all_is_lost", 60, "最低点"),
    ]),
    ("act_3", "第三幕", "高潮与结局", (66, 100), [
        ("climax", 85, "终极高潮"),
    ]),
]

TEMPLATES: dict[str, list] = {
    "save_the_cat_15": _SAVE_THE_CAT_15,
    "truby_22": _TRUBY_22,
    "three_act_classic": _THREE_ACT_CLASSIC,
    "dtg_50_30": _DTG_50_30,
    "wuxia_classic": _WUXIA_CLASSIC,
    "romance_beat": _ROMANCE_BEAT,
    "hero_journey_12": _HERO_JOURNEY_12,
    "kishotenketsu_4": _KISHOTENKETSU_4,
    "freytag_5": _FREYTAG_5,
    "story_circle_8": _STORY_CIRCLE_8,
    "mystery_fairplay_8": _MYSTERY_FAIRPLAY_8,
    "horror_descent_7": _HORROR_DESCENT_7,
    "apocalypse_survival_6": _APOCALYPSE_SURVIVAL_6,
    "urban_rise_8": _URBAN_RISE_8,
    "palace_intrigue_9": _PALACE_INTRIGUE_9,
    "war_campaign_6": _WAR_CAMPAIGN_6,
    "sports_league_7": _SPORTS_LEAGUE_7,
    "isekai_adapt_8": _ISEKAI_ADAPT_8,
    "comedy_escalation_6": _COMEDY_ESCALATION_6,
    "tribulation_9": _TRIBULATION_9,
    "revenge_arc_8": _REVENGE_ARC_8,
    "farming_build_6": _FARMING_BUILD_6,
    "rule_horror_8": _RULE_HORROR_8,
    "unit_loop_6": _UNIT_LOOP_6,
    "angst_romance_9": _ANGST_ROMANCE_9,
    "spy_undercover_8": _SPY_UNDERCOVER_8,
    "academy_growth_7": _ACADEMY_GROWTH_7,
    "dungeon_crawl_6": _DUNGEON_CRAWL_6,
    "showbiz_rise_7": _SHOWBIZ_RISE_7,
    "procedural_case_6": _PROCEDURAL_CASE_6,
    "court_career_8": _COURT_CAREER_8,
    "custom": _CUSTOM,
}


# ============================================================
# 计算：百分比 → 章节位置
# ============================================================

#: AI 定制幕结构（P24.5）：LLM 按题材现场设计 act/beats，不套用内置模板
AI_CUSTOM_TEMPLATE = "ai_custom"


def _pct_to_ep(pct: float, total: int) -> int:
    """百分比 → 章节号（1-based，最小 1）"""
    return max(1, min(total, round(pct / 100 * total)))


def _acts_from_raw(raw: list, total_episodes: int,
                   template_name: str) -> ActStructure:
    acts: list[Act] = []
    for i, (act_id, name, function, (s_pct, e_pct), beat_defs) in enumerate(raw):
        start_ep = _pct_to_ep(s_pct, total_episodes)
        # 末幕的 end_ep 恒等于 total_episodes
        if i == len(raw) - 1:
            end_ep = total_episodes
        else:
            end_ep = _pct_to_ep(e_pct, total_episodes)
        beats = [
            ActBeat(name=b_name, ep=str(_pct_to_ep(b_pct, total_episodes)),
                    desc=b_desc)
            for b_name, b_pct, b_desc in beat_defs
        ]
        acts.append(Act(
            id=act_id, name=name, episode_range=[start_ep, end_ep],
            function=function, beats=beats,
        ))
    return ActStructure(template=template_name, acts=acts)


def compute_acts(template_name: str, total_episodes: int) -> ActStructure:
    """按模板 + 总集数计算幕结构，返回填充好的 ActStructure。

    每个 beat 的 ep 为 "{ep}" 单点；act 的 episode_range 为 [start_ep, end_ep]。
    末幕 end_ep 恒等于 total_episodes（避免 round 截断导致最后一集丢失）。
    """
    raw = TEMPLATES.get(template_name)
    if raw is None:
        raise ValueError(f"未知幕结构模板：{template_name}（可选：{sorted(TEMPLATES)}）")
    return _acts_from_raw(raw, total_episodes, template_name)


def compute_ai_custom_acts(act_defs: list, total_episodes: int) -> ActStructure:
    """AI 定制幕结构：LLM 产出的百分比定义（与内置模板同款 raw 形状）
    → ActStructure（template=ai_custom）。"""
    return _acts_from_raw(act_defs, total_episodes, AI_CUSTOM_TEMPLATE)
