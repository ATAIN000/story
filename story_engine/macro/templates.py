"""幕结构模板库 — 7 个经典叙事结构 × total_episodes 自动计算 beat 章节位置

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
    "custom": _CUSTOM,
}


# ============================================================
# 计算：百分比 → 章节位置
# ============================================================

def _pct_to_ep(pct: float, total: int) -> int:
    """百分比 → 章节号（1-based，最小 1）"""
    return max(1, min(total, round(pct / 100 * total)))


def compute_acts(template_name: str, total_episodes: int) -> ActStructure:
    """按模板 + 总集数计算幕结构，返回填充好的 ActStructure。

    每个 beat 的 ep 为 "{ep}" 单点；act 的 episode_range 为 [start_ep, end_ep]。
    末幕 end_ep 恒等于 total_episodes（避免 round 截断导致最后一集丢失）。
    """
    raw = TEMPLATES.get(template_name)
    if raw is None:
        raise ValueError(f"未知幕结构模板：{template_name}（可选：{sorted(TEMPLATES)}）")

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
