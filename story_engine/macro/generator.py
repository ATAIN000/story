"""宏观计划 AI 生成器（generator.py）

设计文档第 5.2 节七步生成流程。
单次 LLM 大 prompt 调用 → 解析 YAML → 校验 → 构建 MacroPlan。
mock 模式或解析失败 → 规则化骨架兜底（_generate_skeleton）。

调用签名与 gacha synth 一致：kernel.llm_call(prompt, purpose=..., temperature=..., max_tokens=...)。
"""
from __future__ import annotations

import re
from typing import Any

import yaml

from .plan import (
    Act, ArcCharacter, ArcMilestone, ArcSchedule, CentralConflict,
    EpisodeOutline, ForeshadowBlueprint, ForeshadowThread, MacroPlan,
    PacingCurve, SaliencePoint, StoryBlueprint, TensionPoint,
    ThematicArgument,
)
from .templates import TEMPLATES, compute_acts


# ============================================================
# 公开入口
# ============================================================

async def generate_macro_plan(
    kernel,
    bundle,
    worldview_profile=None,
    cast_profile: list[dict] | None = None,
    template_name: str = "save_the_cat_15",
) -> MacroPlan:
    """生成宏观计划（AI 驱动 / mock 兜底）。

    参数：
      kernel: Kernel 实例（提供 kernel.llm / kernel.llm_call）
      bundle: GenreBundle（genre / genre_params）
      worldview_profile: WorldviewProfile（可选，提取 to_prompt_text）
      cast_profile: derive_cast() 返回的人物列表（可选）
      template_name: 幕结构模板名

    返回：填充完整的 MacroPlan
    """
    total_episodes = getattr(bundle, "target_length", 12)
    cast_profile = cast_profile or []

    # mock 模式直接走骨架（硬约束：mock 零 LLM 调用）
    if kernel.llm.is_mock:
        return _generate_skeleton(bundle, worldview_profile, cast_profile,
                                  template_name, total_episodes)

    # 非 mock：尝试 LLM 生成
    prompt = _build_prompt(bundle, worldview_profile, cast_profile,
                           template_name, total_episodes)
    try:
        resp = await kernel.llm_call(
            prompt, purpose="macro_plan", temperature=0.7, max_tokens=8192)
        text = getattr(resp, "text", "") or ""
        parsed = _parse_yaml(text)
        if parsed and _validate(parsed, total_episodes):
            return _build_plan(parsed, template_name, total_episodes)
    except Exception:
        pass  # 任何失败 → 兜底

    return _generate_skeleton(bundle, worldview_profile, cast_profile,
                              template_name, total_episodes)


# ============================================================
# Prompt 构建
# ============================================================

def _build_prompt(bundle, worldview_profile, cast_profile,
                  template_name: str, total_episodes: int) -> str:
    """构建 LLM 提示词：题材 + 世界观 + 人物 + 模板 → 要求输出完整宏观计划 YAML"""
    # 题材参数摘要
    genre_params = getattr(bundle, "genre_params", {}) or {}
    genre_name = getattr(bundle, "genre", "unknown")
    genre_summary = _dict_summary(genre_params, ["title", "resolution_pattern",
                                                  "pacing_curve", "main_track"])

    # 世界观摘要
    wv_text = ""
    if worldview_profile and hasattr(worldview_profile, "to_prompt_text"):
        wv_text = worldview_profile.to_prompt_text()

    # 人物摘要
    cast_text = _cast_summary(cast_profile)

    # 模板 beat 结构
    act_structure = compute_acts(template_name, total_episodes)
    beat_text = _beat_summary(act_structure)

    return f"""你是专业的故事编剧和叙事架构师。请根据以下输入，生成一份完整的宏观叙事计划。

【题材】{genre_name}
【题材参数】{genre_summary}
【总集数】{total_episodes}
【幕结构模板】{template_name}（beat 位置已按总集数映射）

【世界观设定】
{wv_text or '（未提供世界观，请自行推导基础设定）'}

【人物阵容】
{cast_text or '（未提供人物，请自行推导主角和配角）'}

【幕结构 beat 位置（必须遵循）】
{beat_text}

【输出要求】
输出完整 YAML，包含以下六个顶层键（均不可省略）：
1. story_blueprint: logline, thematic_argument(lie/truth/url), central_conflict(protagonist_want/protagonist_need/antagonist_want/stakes), story_type, total_episodes={total_episodes}, target_pace
2. act_structure: template="{template_name}", acts(每幕含 id/name/episode_range/function/beats)
3. episode_outlines: 列表，每条含 episode(1-{total_episodes})/synopsis/purpose/key_events/ends_with_hook/character_arc_focus
4. arc_schedule: characters 列表，每个含 name/archetype_arc/lie/truth/milestones(episode_range/phase/state/event/behavior)
5. foreshadow_blueprint: threads 列表，每个含 id/name/type/plant_episodes/harvest_episode/salience_ladder(ep/level/form)/spacing_rule/status
6. pacing_curve: curve_type, key_tension_points(episode/tension/reason), genre_pace_profile

只输出 YAML，不要解释、前言后语或 markdown 代码围栏。
"""


def _dict_summary(d: dict, keys: list[str]) -> str:
    parts = []
    for k in keys:
        if k in d:
            parts.append(f"{k}: {d[k]}")
    return "; ".join(parts) if parts else str(d)[:200]


def _cast_summary(cast: list[dict]) -> str:
    lines = []
    for c in cast:
        name = c.get("name", "?")
        role = c.get("role", "")
        persona = c.get("persona", {})
        lie = persona.get("arc_lie", "")
        truth = persona.get("arc_truth", "")
        want = persona.get("arc_want", "")
        need = persona.get("arc_need", "")
        arc_type = persona.get("arc_type", "")
        lines.append(
            f"- {name}（{role}）弧光类型={arc_type}; "
            f"Lie={lie}; Want={want}; Need={need}; Truth={truth}")
    return "\n".join(lines)


def _beat_summary(act_structure) -> str:
    lines = []
    for act in act_structure.acts:
        lines.append(f"  {act.name} [{act.episode_range[0]}-{act.episode_range[1]}集]: "
                     + ", ".join(f"{b.name}@{b.ep}" for b in act.beats))
    return "\n".join(lines)


# ============================================================
# 解析 + 校验
# ============================================================

def _parse_yaml(text: str) -> dict | None:
    """解析 LLM 输出的 YAML，容忍 markdown 围栏"""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[^\n]*\n", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    try:
        d = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    return d if isinstance(d, dict) else None


_REQUIRED_KEYS = {
    "story_blueprint", "act_structure", "episode_outlines",
    "arc_schedule", "foreshadow_blueprint", "pacing_curve",
}


def _validate(parsed: dict, total_episodes: int) -> bool:
    """校验：必填键齐全 + 集数匹配 + beat 位置在范围内"""
    # 必填键
    if not _REQUIRED_KEYS <= set(parsed.keys()):
        return False

    # 集数匹配
    outlines = parsed.get("episode_outlines")
    if isinstance(outlines, list) and outlines:
        episodes = [o.get("episode") for o in outlines
                    if isinstance(o, dict) and o.get("episode")]
        if episodes:
            max_ep = max(episodes)
            if max_ep > total_episodes * 1.5:  # 容忍一定偏差
                return False

    # beat 位置范围
    acts = parsed.get("act_structure", {}).get("acts", [])
    if isinstance(acts, list):
        for act in acts:
            if not isinstance(act, dict):
                continue
            er = act.get("episode_range")
            if isinstance(er, list) and len(er) == 2:
                if er[0] < 1 or er[1] > total_episodes + 1:
                    return False

    return True


# ============================================================
# 从解析的 dict 构建 MacroPlan
# ============================================================

def _build_plan(parsed: dict, template_name: str, total_episodes: int) -> MacroPlan:
    """从 LLM 解析的 dict 构建 MacroPlan"""
    bp = parsed.get("story_blueprint", {})
    ta = bp.get("thematic_argument", {}) or {}
    cc = bp.get("central_conflict", {}) or {}

    blueprint = StoryBlueprint(
        logline=bp.get("logline", ""),
        thematic_argument=ThematicArgument(
            lie=ta.get("lie", ""), truth=ta.get("truth", ""),
            url=ta.get("url", "")),
        central_conflict=CentralConflict(
            protagonist_want=cc.get("protagonist_want", ""),
            protagonist_need=cc.get("protagonist_need", ""),
            antagonist_want=cc.get("antagonist_want", ""),
            stakes=cc.get("stakes", "")),
        story_type=bp.get("story_type", ""),
        total_episodes=bp.get("total_episodes", total_episodes),
        target_pace=bp.get("target_pace", "fast_escalation"),
    )

    # act_structure：优先用模板计算（保证位置正确），叠加 LLM 的 desc
    act_structure = compute_acts(template_name, total_episodes)
    _merge_act_descs(act_structure, parsed.get("act_structure", {}))

    # episode_outlines
    outlines = []
    for o in (parsed.get("episode_outlines") or []):
        if not isinstance(o, dict):
            continue
        outlines.append(EpisodeOutline(
            episode=o.get("episode", 1),
            synopsis=o.get("synopsis", ""),
            purpose=o.get("purpose", ""),
            key_events=o.get("key_events", []),
            ends_with_hook=o.get("ends_with_hook", ""),
            character_arc_focus=o.get("character_arc_focus", ""),
            flexibility=o.get("flexibility", "medium"),
        ))

    # arc_schedule
    arc_chars = []
    for c in (parsed.get("arc_schedule", {}).get("characters") or []):
        if not isinstance(c, dict):
            continue
        milestones = [
            ArcMilestone(
                episode_range=m.get("episode_range", ""),
                phase=m.get("phase", ""),
                state=m.get("state", ""),
                event=m.get("event", ""),
                behavior=m.get("behavior", ""))
            for m in (c.get("milestones") or []) if isinstance(m, dict)
        ]
        arc_chars.append(ArcCharacter(
            name=c.get("name", ""), archetype_arc=c.get("archetype_arc", ""),
            lie=c.get("lie", ""), truth=c.get("truth", ""),
            milestones=milestones))

    # foreshadow_blueprint
    threads = []
    for t in (parsed.get("foreshadow_blueprint", {}).get("threads") or []):
        if not isinstance(t, dict):
            continue
        ladder = [
            SaliencePoint(ep=s.get("ep", 0), level=s.get("level", 0.0),
                          form=s.get("form", ""))
            for s in (t.get("salience_ladder") or []) if isinstance(s, dict)
        ]
        threads.append(ForeshadowThread(
            id=t.get("id", ""), name=t.get("name", ""), type=t.get("type", ""),
            plant_episodes=t.get("plant_episodes", []),
            harvest_episode=t.get("harvest_episode", 0),
            salience_ladder=ladder, spacing_rule=t.get("spacing_rule", ""),
            status=t.get("status", "planned")))

    # pacing_curve
    pc = parsed.get("pacing_curve", {}) or {}
    tension_points = [
        TensionPoint(episode=tp.get("episode", 0),
                     tension=tp.get("tension", 0.0),
                     reason=tp.get("reason", ""))
        for tp in (pc.get("key_tension_points") or []) if isinstance(tp, dict)
    ]
    pacing = PacingCurve(
        curve_type=pc.get("curve_type", "wave_escalation"),
        key_tension_points=tension_points,
        genre_pace_profile=pc.get("genre_pace_profile", {}))

    return MacroPlan(
        blueprint=blueprint, act_structure=act_structure,
        episode_outlines=outlines, arc_schedule=ArcSchedule(characters=arc_chars),
        foreshadow_blueprint=ForeshadowBlueprint(threads=threads),
        pacing_curve=pacing,
    )


def _merge_act_descs(act_structure, llm_structure: dict) -> None:
    """用 LLM 产出的 beat desc 覆盖模板的默认 desc（按 beat name 匹配）"""
    llm_acts = llm_structure.get("acts", []) if isinstance(llm_structure, dict) else []
    name_to_desc: dict[str, str] = {}
    for la in llm_acts:
        if not isinstance(la, dict):
            continue
        for b in (la.get("beats") or []):
            if isinstance(b, dict) and b.get("desc"):
                name_to_desc[b.get("name", "")] = b["desc"]
    for act in act_structure.acts:
        for beat in act.beats:
            if beat.name in name_to_desc:
                beat.desc = name_to_desc[beat.name]


# ============================================================
# 规则化骨架兜底（mock 模式 / LLM 失败）
# ============================================================

def _generate_skeleton(bundle, worldview_profile, cast_profile,
                       template_name: str, total_episodes: int) -> MacroPlan:
    """规则化生成骨架 MacroPlan（无 LLM）：模板 beats + 通用文案 + 从 cast 推导弧光"""
    # ---- Blueprint ----
    main_char = cast_profile[0] if cast_profile else {}
    main_persona = main_char.get("persona", {}) if main_char else {}
    lie = main_persona.get("arc_lie", "孤独是唯一的出路")
    truth = main_persona.get("arc_truth", "连接才是真正的力量")
    want = main_persona.get("arc_want", "达成目标")
    need = main_persona.get("arc_need", "理解他人的价值")

    genre_name = getattr(bundle, "genre", "unknown")
    blueprint = StoryBlueprint(
        logline=f"一个{lie}的主角，在{genre_name}的世界中学会{truth}",
        thematic_argument=ThematicArgument(lie=lie, truth=truth,
                                           url=f"{lie}才是对的"),
        central_conflict=CentralConflict(
            protagonist_want=want, protagonist_need=need,
            antagonist_want=f"阻止{want}", stakes=f"如果失败，{truth}将永远无法实现"),
        story_type="growth",
        total_episodes=total_episodes,
        target_pace="fast_escalation",
    )

    # ---- Act Structure ----
    act_structure = compute_acts(template_name, total_episodes)

    # ---- Episode Outlines（从 beats 展开）----
    outlines: list[EpisodeOutline] = []
    for ep in range(1, total_episodes + 1):
        beat = _find_beat_for_ep(act_structure, ep)
        outlines.append(EpisodeOutline(
            episode=ep,
            synopsis=f"第{ep}集：{beat.desc}" if beat else f"第{ep}集：剧情推进",
            purpose=beat.name if beat else "rising_action",
            key_events=[beat.desc] if beat else ["剧情推进"],
            ends_with_hook=f"留下悬念，引向第{ep + 1}集" if ep < total_episodes else "故事完结",
            character_arc_focus=main_char.get("name", "主角"),
            flexibility="high" if not beat else "medium",
        ))

    # ---- Arc Schedule（从 cast 推导）----
    arc_chars: list[ArcCharacter] = []
    for c in cast_profile:
        persona = c.get("persona", {})
        milestones = _derive_milestones(
            persona.get("arc_lie", ""), persona.get("arc_truth", ""),
            total_episodes, act_structure)
        arc_chars.append(ArcCharacter(
            name=c.get("name", "角色"),
            archetype_arc=persona.get("arc_type", "positive_change"),
            lie=persona.get("arc_lie", ""),
            truth=persona.get("arc_truth", ""),
            milestones=milestones,
        ))

    # ---- Foreshadow Blueprint（2 条基础伏笔）----
    threads = [
        ForeshadowThread(
            id="FS_001", name="主线悬念", type="main_mystery",
            plant_episodes=[1, max(1, total_episodes // 3)],
            harvest_episode=max(1, total_episodes * 4 // 5),
            salience_ladder=[
                SaliencePoint(ep=1, level=0.2, form="初次暗示"),
                SaliencePoint(ep=max(1, total_episodes // 3), level=0.5, form="线索浮现"),
                SaliencePoint(ep=max(1, total_episodes * 4 // 5), level=1.0, form="真相揭露"),
            ],
            spacing_rule="max_5_eps", status="planned"),
        ForeshadowThread(
            id="FS_002", name="角色秘密", type="character_secret",
            plant_episodes=[max(1, total_episodes // 4)],
            harvest_episode=max(1, total_episodes * 3 // 4),
            salience_ladder=[
                SaliencePoint(ep=max(1, total_episodes // 4), level=0.3, form="一个细节"),
                SaliencePoint(ep=max(1, total_episodes * 3 // 4), level=1.0, form="秘密揭露"),
            ],
            spacing_rule="max_8_eps", status="planned"),
    ]

    # ---- Pacing Curve（模板锚点插值）----
    tension_points = _derive_tension_points(total_episodes, act_structure)

    return MacroPlan(
        blueprint=blueprint,
        act_structure=act_structure,
        episode_outlines=outlines,
        arc_schedule=ArcSchedule(characters=arc_chars),
        foreshadow_blueprint=ForeshadowBlueprint(threads=threads),
        pacing_curve=PacingCurve(
            curve_type="wave_escalation",
            key_tension_points=tension_points,
            genre_pace_profile={"type": genre_name,
                                "micro_rhythm": "3-5集一小高潮",
                                "buffer_rule": "高强度冲突后必须有缓冲"}),
    )


def _find_beat_for_ep(act_structure, ep: int):
    """找到 episode ep 所在的 beat（取该 act 中 ep ≤ 目标 且最接近的 beat）"""
    for act in act_structure.acts:
        start, end = act.episode_range
        if start <= ep <= end:
            # 找该 act 中 ep 最接近的 beat
            best = None
            best_dist = 999
            for beat in act.beats:
                try:
                    beat_ep = int(beat.ep)
                except (ValueError, TypeError):
                    continue
                dist = abs(beat_ep - ep)
                if dist < best_dist:
                    best = beat
                    best_dist = dist
            return best or act.beats[0]
    return act_structure.acts[-1].beats[-1] if act_structure.acts else None


def _derive_milestones(lie: str, truth: str, total: int,
                       act_structure) -> list[ArcMilestone]:
    """从弧光定义 × 幕结构推导基础里程碑"""
    milestones = [
        ArcMilestone(episode_range=f"1-{max(1, total // 5)}", phase="setup",
                     state=f"完全被Lie控制" if lie else "初始状态",
                     behavior="拒绝改变"),
        ArcMilestone(episode_range=f"{max(1, total // 5 + 1)}-{max(2, total // 2)}",
                     phase="crack", state="第一次动摇", event="关键事件冲击",
                     behavior="开始犹豫"),
        ArcMilestone(episode_range=f"{max(2, total // 2 + 1)}-{max(3, total * 3 // 4)}",
                     phase="relapse", state="被强化Lie", event="遭遇挫折",
                     behavior="退回旧模式"),
        ArcMilestone(episode_range=f"{max(3, total * 3 // 4 + 1)}-{total}",
                     phase="truth_embrace",
                     state=f"拥抱Truth" if truth else "觉醒",
                     event="理解真相", behavior="彻底转变"),
    ]
    return milestones


def _derive_tension_points(total: int, act_structure) -> list[TensionPoint]:
    """从幕结构推导基础张力锚点"""
    # 取每幕第一个 beat 和最后一个 beat 作为锚点
    points: list[TensionPoint] = []
    for act in act_structure.acts:
        start, end = act.episode_range
        points.append(TensionPoint(
            episode=start, tension=0.5,
            reason=f"{act.name}开始"))
        points.append(TensionPoint(
            episode=end, tension=0.8,
            reason=f"{act.name}结束"))
    # 最后一集
    if points:
        points[-1] = TensionPoint(
            episode=total, tension=0.3, reason="结局——归于平静")
    return points
