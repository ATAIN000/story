"""宏观规划端点。"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend import deps
from backend.helpers import _ep_in_range

router = APIRouter()
logger = logging.getLogger(__name__)

TEMPLATES_META = {
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
    "ai_custom": ("✦ AI 定制结构", "LLM 按题材+世界观+集数现场生成专属幕结构"),
    "custom": ("自定义", "用户自定义幕结构"),
}


class MacroPlanReq(BaseModel):
    template_name: str = "save_the_cat_15"
    worldview: dict | None = None
    cast: list | None = None
    regenerate_component: str | None = None
    conflict_warnings: list | None = None
    existing_plan: dict | None = None


def _macro_imports():
    from story_engine.macro import (
        TEMPLATES as MACRO_TEMPLATES, generate_macro_plan,
        macro_plan_to_dict, check_cross_layer)
    from story_engine.meta.genre_taxonomy import macro_templates_for_genre
    return MACRO_TEMPLATES, macro_templates_for_genre


@router.get("/api/macro/templates")
def macro_templates(genre: str = ""):
    MACRO_TEMPLATES, macro_templates_for_genre = _macro_imports()
    from story_engine.macro import AI_CUSTOM_TEMPLATE
    recommended = set(macro_templates_for_genre(genre)) if genre else set()
    items = []
    for name, acts in MACRO_TEMPLATES.items():
        beat_count = sum(len(beats) for _, _, _, _, beats in acts)
        meta = TEMPLATES_META.get(name, (name, ""))
        items.append({
            "name": name,
            "title": meta[0],
            "description": meta[1],
            "beat_count": beat_count,
            "recommended": name in recommended,
        })
    # AI 定制结构：不在内置模板库（无固定拍点），卡片固定追加、永不标推荐
    meta = TEMPLATES_META[AI_CUSTOM_TEMPLATE]
    items.append({
        "name": AI_CUSTOM_TEMPLATE,
        "title": meta[0],
        "description": meta[1],
        "beat_count": 0,
        "recommended": False,
    })
    return {"templates": items}


@router.post("/api/macro/plan")
async def macro_plan_generate_legacy(req: MacroPlanReq):
    raise HTTPException(
        status_code=410,
        detail="此端点已废弃，请使用 WebSocket /api/gacha/{sid}/macro/stream")


def _read_macro_plan() -> dict:
    path = Path(deps.engine.project_dir) / "macro_plan.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="当前项目无宏观计划")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("macro_plan.json 读取失败 | %r", exc)
        raise HTTPException(
            status_code=500, detail="宏观计划文件读取失败（文件损坏，详见日志）")


@router.get("/api/macro/plan")
def macro_plan_get():
    return _read_macro_plan()


@router.post("/api/macro/export-bible")
async def export_bible():
    """导出故事圣经：调 LLM 把世界观+文化+人物+宏观计划融合成结构化故事提示词。

    用户可复制给别的 AI Agent 用——输出是纯文本，包含世界观概述、文化设定、
    人物卡、故事梗概、叙事风格、创作约束等完整设定。
    """
    import asyncio
    project_dir = Path(deps.engine.project_dir)

    # 读取全部设定文件
    def _read_json(filename):
        p = project_dir / filename
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    macro = _read_json("macro_plan.json")
    cast = _read_json("cast.json")
    worldview = _read_json("worldview.json")
    project = _read_json("project.json")

    if not macro:
        raise HTTPException(status_code=404, detail="当前项目无宏观计划，无法导出")

    # 拼接完整上下文
    context_parts = []

    # 1. 基本信息
    if project:
        context_parts.append(f"题材：{project.get('genre','')}")
        context_parts.append(f"文化：{project.get('culture','')}")
        context_parts.append(f"总集数：{project.get('macro',{}).get('total_episodes', 12)}")

    # 2. 世界观
    if worldview and worldview.get("layers"):
        wv_lines = []
        for layer, params in worldview["layers"].items():
            for k, v in params.items():
                wv_lines.append(f"  {k}: {v}")
        context_parts.append("=== 世界观设定 ===\n" + "\n".join(wv_lines))

    # 3. 人物
    if cast:
        cast_lines = []
        for c in cast:
            p = c.get("persona", {})
            cast_lines.append(
                f"  {c.get('name','')}（{c.get('role','')}）："
                f"原型={p.get('pearson_primary','')}, 九型={p.get('enneagram_type','')}, "
                f"矛盾={p.get('mckee_contradiction_text','')}, "
                f"弧光={p.get('arc_type','')}, "
                f"Lie={p.get('arc_lie',p.get('arc_lie_text',''))}, "
                f"Want={p.get('arc_want',p.get('arc_want_text',''))}, "
                f"Need={p.get('arc_need',p.get('arc_need_text',''))}"
            )
        context_parts.append("=== 人物阵容 ===\n" + "\n".join(cast_lines))

    # 4. 宏观计划
    bp = macro.get("blueprint", {})
    if bp:
        context_parts.append("=== 故事蓝图 ===")
        context_parts.append(f"  主线：{bp.get('logline','')}")
        cc = bp.get("central_conflict", {})
        if cc:
            context_parts.append(f"  主角想要：{cc.get('protagonist_want','')}")
            context_parts.append(f"  主角需要：{cc.get('protagonist_need','')}")
            context_parts.append(f"  反派想要：{cc.get('antagonist_want','')}")
            context_parts.append(f"  代价：{cc.get('stakes','')}")
        ta = bp.get("thematic_argument", {})
        if ta:
            context_parts.append(f"  谎言：{ta.get('lie','')}")
            context_parts.append(f"  真相：{ta.get('truth','')}")

    # 5. 分集梗概
    eps = macro.get("episode_outlines", [])
    if eps:
        ep_lines = []
        for e in eps:
            ep_lines.append(
                f"  第{e.get('episode','')}集 [{e.get('purpose','')}]: "
                f"{e.get('synopsis','')}"
            )
        context_parts.append("=== 分集梗概 ===\n" + "\n".join(ep_lines))

    # 6. 伏笔
    fs = macro.get("foreshadow_blueprint", {})
    if fs.get("threads"):
        fs_lines = []
        for t in fs["threads"]:
            fs_lines.append(f"  {t.get('name','')}（{t.get('type','')}）：{t.get('form','') if 'form' in t else ''}")
        context_parts.append("=== 伏笔布局 ===\n" + "\n".join(fs_lines))

    context = "\n\n".join(str(p) for p in context_parts)

    # LLM 生成故事圣经
    prompt = (
        "你是一位专业的小说世界观架构师。请根据以下项目的全部设定数据，"
        "生成一份**结构化的故事圣经**（Story Bible），"
        "让任何 AI Agent 拿到这份文档后都能直接开始创作高质量的故事章节。\n\n"
        "输出格式要求（Markdown）：\n"
        "# 故事圣经\n\n"
        "## 一、世界概述（300字以内的世界观总述，让读者快速理解世界基调）\n"
        "## 二、世界观设定（结构化列出力量体系/政治/经济/文化/历史等关键设定）\n"
        "## 三、人物设定（每人一个小节：名字/身份/性格/弧光/动机/矛盾）\n"
        "## 四、故事梗概（一句话核心+三幕式概述）\n"
        "## 五、分集大纲（每集一行：集号+核心事件+角色焦点）\n"
        "## 六、叙事风格（文风/节奏/视角/禁忌）\n"
        "## 七、创作约束（AI 创作时必须遵守的规则）\n\n"
        "要求：内容充实具体，不要空洞模板。直接从设定数据中提炼。\n\n"
        f"=== 项目设定数据 ===\n{context}"
    )

    try:
        resp = await deps.engine.llm.call(
            prompt, purpose="export_bible", temperature=0.5)
        text = resp.text if hasattr(resp, "text") else str(resp)
        return {"bible": text.strip()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM 生成故事圣经失败：{e}")


@router.get("/api/macro/progress")
def macro_progress():
    plan = _read_macro_plan()
    chapters = getattr(deps.engine, "project", None)
    chapter_count = 0
    if chapters and isinstance(chapters, dict):
        chapter_count = len(chapters.get("chapters") or [])
    current_ep = chapter_count + 1

    current_act = ""
    current_beat = ""
    current_beat_desc = ""
    for act in (plan.get("act_structure") or {}).get("acts") or []:
        rng = act.get("episode_range") or []
        if len(rng) == 2 and rng[0] <= current_ep <= rng[1]:
            current_act = act.get("name", "")
            best = None
            for b in act.get("beats") or []:
                try:
                    ep = int(b.get("ep", 0))
                except (ValueError, TypeError):
                    continue
                if ep <= current_ep and (best is None or ep > int(best.get("ep", 0))):
                    best = b
            if best:
                current_beat = best.get("name", "")
                current_beat_desc = best.get("desc", "")
            break

    current_synopsis = ""
    current_key_events: list = []
    for ep in plan.get("episode_outlines") or []:
        if ep.get("episode") == current_ep:
            current_synopsis = ep.get("synopsis", "")
            current_key_events = list(ep.get("key_events") or [])
            break

    foreshadow_status: list[dict] = []
    for t in (plan.get("foreshadow_blueprint") or {}).get("threads") or []:
        plants = t.get("plant_episodes") or []
        harvest = t.get("harvest_episode", 0)
        if harvest and harvest <= chapter_count:
            status = "harvested"
        elif any(p <= chapter_count for p in plants):
            status = "planted"
        else:
            status = "pending"
        foreshadow_status.append({
            "id": t.get("id", ""), "name": t.get("name", ""),
            "status": status,
            "plant_episodes": plants, "harvest_episode": harvest,
        })

    arc_phases: list[dict] = []
    for char in (plan.get("arc_schedule") or {}).get("characters") or []:
        for ms in char.get("milestones") or []:
            rng = ms.get("episode_range", "")
            if _ep_in_range(current_ep, rng):
                arc_phases.append({
                    "character": char.get("name", ""),
                    "phase": ms.get("phase", ""),
                    "state": ms.get("state", ""),
                    "behavior": ms.get("behavior", ""),
                })
                break

    return {
        "current_episode": current_ep,
        "total_episodes": (plan.get("blueprint") or {}).get("total_episodes", 0),
        "chapters_written": chapter_count,
        "current_act": current_act,
        "current_beat": current_beat,
        "current_beat_description": current_beat_desc,
        "current_synopsis": current_synopsis,
        "current_key_events": current_key_events,
        "foreshadow_status": foreshadow_status,
        "arc_phases": arc_phases,
    }


@router.get("/api/macro/deviation")
def macro_deviation():
    plan = _read_macro_plan()
    chapters = getattr(deps.engine, "project", None)
    chapter_count = 0
    if chapters and isinstance(chapters, dict):
        chapter_count = len(chapters.get("chapters") or [])

    episode_coverage: list[dict] = []
    for ep in plan.get("episode_outlines") or []:
        ep_num = ep.get("episode", 0)
        episode_coverage.append({
            "episode": ep_num,
            "planned_key_events": list(ep.get("key_events") or []),
            "status": "written" if ep_num <= chapter_count else "not_written",
        })

    foreshadow_deviation: list[dict] = []
    for t in (plan.get("foreshadow_blueprint") or {}).get("threads") or []:
        plants = t.get("plant_episodes") or []
        harvest = t.get("harvest_episode", 0)
        all_eps = sorted(set(plants + [harvest]))
        missed = [e for e in all_eps if e and e <= chapter_count]
        foreshadow_deviation.append({
            "id": t.get("id", ""), "name": t.get("name", ""),
            "plant_episodes": plants, "harvest_episode": harvest,
            "expected_by_now": missed,
            "status": "on_track" if missed else "pending",
        })

    arc_deviation: list[dict] = []
    for char in (plan.get("arc_schedule") or {}).get("characters") or []:
        for ms in char.get("milestones") or []:
            rng = ms.get("episode_range", "")
            parts = str(rng).split("-")
            try:
                end_ep = int(parts[-1]) if parts else 0
            except (ValueError, TypeError):
                end_ep = 0
            if end_ep and end_ep <= chapter_count:
                arc_deviation.append({
                    "character": char.get("name", ""),
                    "phase": ms.get("phase", ""),
                    "episode_range": rng,
                    "status": "expected_met",
                })

    written = chapter_count
    total = (plan.get("blueprint") or {}).get("total_episodes", 0)
    return {
        "chapters_written": written,
        "total_planned": total,
        "progress_pct": round(written / total * 100, 1) if total else 0,
        "episode_coverage": episode_coverage,
        "foreshadow_deviation": foreshadow_deviation,
        "arc_deviation": arc_deviation,
    }
