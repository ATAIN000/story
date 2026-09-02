"""抽卡开局端点（session 管理 / 题材浏览 / 确认开工 / 宏观流式）。"""
from __future__ import annotations

import atexit
import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from backend import deps
from backend.helpers import (
    _make_lazy_genesis, _switch_to, _write_json_atomic, _write_project_meta,
    validate_project_name,
)
from backend.models import CrossCheckReq, DeriveCastReq

router = APIRouter()
logger = logging.getLogger(__name__)

# ---------- session 管理 ----------
_gacha_sessions: dict[str, dict] = {}
_GACHA_SESSION_TTL = 1800  # 30 分钟


def _derive_culture_for_genre(kernel, genre_name: str) -> str:
    from story_engine.meta.gacha import derive_culture
    try:
        m = kernel.registry.get_manifest("story.genre", genre_name)
        return derive_culture(m.allowed_cultures, genre_name=genre_name)
    except Exception:
        return "confucian_officialdom"


def _register_synth_card(synth_card: dict | None, genre_name: str) -> bool:
    """synth 合成卡现场注册到主 registry（内存级，重启消失）。

    卡结构：draw_card_async 返回的 card.genre = {name, source, desc, yaml}，
    yaml 是完整 genre pack（含 manifest_version/name/extension_point/params）。
    数据不完整或 name 不匹配 → False（调用方据此 422）。"""
    if not isinstance(synth_card, dict):
        return False
    yaml_pack = synth_card.get("yaml")
    if not isinstance(yaml_pack, dict):
        return False
    if not all(k in yaml_pack for k in ("name", "extension_point", "params")):
        return False
    if yaml_pack["name"] != genre_name:
        return False
    from story_engine.kernel.registry import PluginManifest
    try:
        manifest = PluginManifest.from_dict(yaml_pack)
        deps.engine.kernel.registry.register(manifest)
    except Exception:
        logger.warning("synth 卡注册失败 | genre=%s", genre_name, exc_info=True)
        return False
    logger.info("synth 合成题材现场注册 | genre=%s", genre_name)
    return True


def _create_session_engine(genre_name: str, culture: str | None = None):
    """为抽卡向导创建临时工作区 Kernel + StoryEngine。

    优化：复用主 Kernel 的 registry（384 个插件包扫描耗时数秒），
    session engine 只需独立 SQLite（EventStore），不需要重新扫描插件。
    """
    from story_engine.engine import StoryEngine
    from story_engine.kernel import Kernel
    tmp_dir = deps.PROJECTS_ROOT / f".tmp_gacha_{uuid4().hex[:8]}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    stack: dict = {}
    # 不传 plugin_dir（跳过全量扫描），构造后复用主 registry
    kernel = Kernel(
        tmp_dir, initial_state_factory=_make_lazy_genesis(stack))
    kernel.registry = deps.kernel.registry  # 复用已扫描的插件注册表
    culture = culture or _derive_culture_for_genre(kernel, genre_name)
    sess_engine = StoryEngine(kernel, genre_name=genre_name,
                              culture_name=culture)
    stack.update({"kernel": kernel, "engine": sess_engine})
    return sess_engine, kernel, tmp_dir


def _cleanup_session(sid: str) -> None:
    session = _gacha_sessions.pop(sid, None)
    if not session:
        return
    try:
        session["kernel"].close()
    except Exception:
        logger.warning("gacha session kernel close 失败（尽力继续）",
                       exc_info=True)
    tmp_dir = session.get("tmp_dir")
    if tmp_dir and Path(tmp_dir).exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _expire_old_sessions() -> None:
    now = datetime.now().timestamp()
    expired = [sid for sid, s in _gacha_sessions.items()
               if now - s.get("created_ts", now) > _GACHA_SESSION_TTL]
    for sid in expired:
        _cleanup_session(sid)


def _cleanup_all_sessions() -> None:
    for sid in list(_gacha_sessions):
        _cleanup_session(sid)


atexit.register(_cleanup_all_sessions)

GENRE_NAME_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}")


class GachaBeginReq:
    pass


from pydantic import BaseModel


class GachaBeginReq(BaseModel):
    genre_name: str
    culture: str | None = None
    # synth 合成卡（draw_card_async 返回的 card.genre，含完整 yaml）。
    # 合成题材从未注册进 registry（P20 遗留 bug：synth 卡 + 下一步 → 422），
    # begin 时带上它 → 现场注册（内存级，重启消失）再走正常流程。
    synth_card: dict | None = None


class GachaConfirmReq(BaseModel):
    project_name: str
    worldview: dict | None = None
    cast: list | None = None
    macro_plan: dict | None = None
    total_episodes: int | None = None
    material: str | None = None


# 集数约定合法区间（短剧 1 集 ~ 长篇 500 集）
TOTAL_EPISODES_MIN, TOTAL_EPISODES_MAX = 1, 500


def _coerce_total_episodes(value, default: int = 12) -> int:
    """WS 请求里的 total_episodes 宽容解析：非 int / 越界 → 回落 default。"""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return n if TOTAL_EPISODES_MIN <= n <= TOTAL_EPISODES_MAX else default


# ---------- 剧本反推开局（先于 begin，无需 session） ----------
class ScriptAnalyzeReq(BaseModel):
    """台词脚本 + 作者补充 → 题材匹配。exclude_genres 供重 ROLL 换方向。"""
    script_text: str
    author_note: str = ""
    exclude_genres: list[str] = []


@router.post("/api/gacha/analyze_script")
async def analyze_script_endpoint(req: ScriptAnalyzeReq):
    """剧本反推：LLM 从 315 题材库匹配题材 + 推导人物原型/骨架/文化。

    无需 gacha session（先于 begin）；用主 engine 的 LLM。单次调用，
    thinking 关（script_analyze 在 _THINKING_NEVER_PREFIXES）。
    返回：genre（taxon 展开的完整题材卡）+ reason/culture/preset/
    characters/worldview_hints。解析失败/题材不在库 → 502（前端提示重试）。
    """
    from story_engine.meta.genre_taxonomy import taxon_by_id
    from story_engine.meta.script_analyze import analyze_script

    if not req.script_text or not req.script_text.strip():
        raise HTTPException(status_code=422, detail="请粘贴台词脚本")
    parsed = await analyze_script(
        req.script_text, req.author_note, deps.kernel.llm.call,
        exclude_genres=req.exclude_genres or None)
    if parsed is None:
        raise HTTPException(
            status_code=502, detail="AI 匹配失败（响应解析异常），请换个说法重试")
    taxon = taxon_by_id(parsed["genre_id"])
    if taxon is None:  # analyze 内部已做模糊回退，此处兜底
        raise HTTPException(status_code=502, detail="AI 推荐的题材不在库，请重试")
    return {
        "genre": {
            "id": taxon.id, "title": taxon.title, "family": taxon.family,
            "family_title": taxon.family_title, "tier": taxon.tier,
            "tags": list(taxon.tags), "vibe": taxon.vibe,
            "recommended_presets": [taxon.primary_preset, *taxon.secondary_presets],
            "recommended_macro_templates": list(taxon.macro_templates),
        },
        "reason": parsed["reason"],
        "culture": parsed["culture"],
        "preset": parsed["preset"],
        "characters": parsed["characters"],
        "worldview_hints": parsed["worldview_hints"],
    }


# ---------- genre 浏览 ----------
@router.get("/api/gacha/genres")
def gacha_genres(q: str = "", tags: str = "", tier: str = "",
                 family: str = "", offset: int = 0, limit: int = 24):
    from story_engine.meta.genre_taxonomy import (
        TAG_ZH, all_taxa, list_taxa, taxonomy_stats)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    rows, total = list_taxa(q=q, tags=tag_list, tier=tier,
                            family=family, offset=offset, limit=limit)
    items = [{
        "id": t.id, "title": t.title, "family": t.family,
        "family_title": t.family_title, "tier": t.tier,
        "tags": list(t.tags), "vibe": t.vibe,
        "default_culture": t.default_culture,
        "recommended_presets": [t.primary_preset, *t.secondary_presets],
        "recommended_macro_templates": list(t.macro_templates),
        "legacy": t.legacy,
    } for t in rows]
    fam_counts: dict[str, list] = {}
    tag_counts: dict[str, int] = {}
    for t in all_taxa():
        fam = fam_counts.setdefault(t.family, [t.family_title, 0])
        fam[1] += 1
        for tag in t.tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    return {
        "total": total, "offset": offset, "limit": limit,
        "items": items,
        "facets": {
            "families": [{"id": k, "title": v[0], "count": v[1]}
                         for k, v in sorted(fam_counts.items(),
                                            key=lambda kv: -kv[1][1])],
            "tags": [{"id": k, "zh": TAG_ZH.get(k, k), "count": v}
                     for k, v in sorted(tag_counts.items(),
                                        key=lambda kv: -kv[1])],
            "tiers": ["base", "hot", "fusion", "legacy"],
        },
        "tag_zh": TAG_ZH,
        "stats": taxonomy_stats(),
    }


# ---------- begin ----------
@router.post("/api/gacha/begin")
def gacha_begin(req: GachaBeginReq):
    from story_engine.meta.genre_taxonomy import (
        macro_templates_for_genre, presets_for_genre, taxon_by_id)
    _expire_old_sessions()
    genre_name = req.genre_name
    try:
        deps.engine.kernel.registry.get_manifest("story.genre", genre_name)
    except Exception:
        # 库中无此题材：若是 synth 合成卡（带完整 yaml），现场注册再放行
        if not _register_synth_card(req.synth_card, genre_name):
            raise HTTPException(status_code=422,
                                detail=f"未知题材：{genre_name}")
    sess_engine, sess_kernel, tmp_dir = _create_session_engine(
        genre_name, req.culture)
    sid = uuid4().hex[:12]
    _gacha_sessions[sid] = {
        "engine": sess_engine, "kernel": sess_kernel,
        "tmp_dir": str(tmp_dir), "genre_name": genre_name,
        "culture": sess_engine.culture.name,
        "created_ts": datetime.now().timestamp(),
    }
    genre_title = ""
    try:
        genre_title = sess_engine.bundle.genre_params.get("title", genre_name)
    except Exception:
        genre_title = genre_name
    resp = {"session_id": sid, "genre_title": genre_title,
            "genre": genre_name, "culture": sess_engine.culture.name,
            "target_length": getattr(sess_engine.bundle,
                                     "target_length", 12)}
    taxon = taxon_by_id(genre_name)
    if taxon is not None:
        resp["recommended_presets"] = list(presets_for_genre(genre_name))
        resp["recommended_macro_templates"] = list(
            macro_templates_for_genre(genre_name))
        resp["tags"] = list(taxon.tags)
        resp["family_title"] = taxon.family_title
        try:
            cm = deps.engine.kernel.registry.get_manifest(
                "story.culture", sess_engine.culture.name)
            resp["culture_title"] = cm.params.get(
                "title", sess_engine.culture.name)
        except Exception:
            resp["culture_title"] = sess_engine.culture.name
    return resp


# ---------- cancel ----------
@router.post("/api/gacha/{sid}/cancel")
def gacha_cancel(sid: str):
    if sid not in _gacha_sessions:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    _cleanup_session(sid)
    return {"ok": True}


# ---------- confirm ----------
@router.post("/api/gacha/{sid}/confirm")
def gacha_session_confirm(sid: str, req: GachaConfirmReq):
    from story_engine.types import StoryEngineError
    from story_engine.worldview import (
        WorldviewProfile, evaluate as wv_evaluate, derive_cast as wv_derive_cast)

    session = _gacha_sessions.get(sid)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")

    def _fail(detail, code=422):
        _cleanup_session(sid)
        raise HTTPException(status_code=code, detail=detail)

    if not validate_project_name(req.project_name):
        _fail(f"项目名非法：{req.project_name!r}（允许中文/字母/数字/空格/-/_，"
              "1-40 字符；不含路径分隔符/.. /Windows 保留名）")
    if req.total_episodes is not None and not (
            TOTAL_EPISODES_MIN <= req.total_episodes <= TOTAL_EPISODES_MAX):
        _fail(f"total_episodes 须在 {TOTAL_EPISODES_MIN}-"
              f"{TOTAL_EPISODES_MAX} 之间")
    target_dir = deps.PROJECTS_ROOT / req.project_name
    if target_dir.exists() and any(target_dir.iterdir()):
        _fail(f"项目已存在：{req.project_name}", code=409)
    # worldview 校验
    wv_layers: dict | None = None
    wv_preset: str | None = None
    wv_param_count = 0
    if req.worldview is not None:
        wv = req.worldview
        if not isinstance(wv, dict):
            _fail("worldview 必须是对象")
        wv_layers = wv.get("layers") or {}
        if not isinstance(wv_layers, dict):
            _fail("worldview.layers 必须是对象")
        wv_preset = wv.get("preset")
        flat = WorldviewProfile(layers=wv_layers).as_flat()
        wv_param_count = len(flat)
        result = wv_evaluate(flat)
        if result["violations"]:
            _fail({"message": "世界观存在跨层一致性违例",
                   "violations": result["violations"]})
    # rename tmp_dir → target_dir
    tmp_dir = Path(session["tmp_dir"])
    genre_name = session["genre_name"]
    culture = session["culture"]
    try:
        deps.engine.kernel.registry.validate_combo(genre_name, culture)
    except StoryEngineError as e:
        _cleanup_session(sid)
        raise HTTPException(status_code=422, detail=str(e))
    try:
        session["kernel"].close()
    except Exception:
        logger.warning("confirm: session kernel close 失败（尽力继续）",
                       exc_info=True)
    try:
        tmp_dir.rename(target_dir)
    except OSError:
        shutil.move(str(tmp_dir), str(target_dir))
    _gacha_sessions.pop(sid, None)
    # 集数约定：宏观计划蓝图里的 total_episodes 优先（与落盘 artifact 一致，
    # 防"生成后改了集数却没重摇"导致 plan 与引擎集数分叉），其次用户显式约定
    plan_eps = None
    if isinstance(req.macro_plan, dict):
        bp_eps = (req.macro_plan.get("blueprint") or {}).get("total_episodes")
        if isinstance(bp_eps, int) and bp_eps > 0:
            plan_eps = bp_eps
    eff_episodes = plan_eps or req.total_episodes
    _switch_to(target_dir, genre_name=genre_name, culture_name=culture,
               target_length=eff_episodes)
    now = datetime.now().isoformat(timespec="seconds")
    _write_project_meta(target_dir, name=req.project_name, genre=genre_name,
                        culture=culture, created_at=now, last_opened_at=now)
    if wv_layers is not None:
        _write_json_atomic(
            target_dir / "worldview.json",
            {"layers": wv_layers, "preset": wv_preset,
             "created_at": datetime.now().isoformat(timespec="seconds")})
        _write_project_meta(
            target_dir,
            worldview={"preset": wv_preset,
                       "param_count": wv_param_count})
    cast_data = req.cast
    if cast_data is not None and isinstance(cast_data, list):
        _write_json_atomic(target_dir / "cast.json", cast_data)
    elif not cast_data:
        try:
            derived = wv_derive_cast(
                wv_layers, None, deps.engine.bundle.genre_params)
        except Exception:
            derived = None
        if derived:
            cast_data = [
                {"id": c.get("name", ""), "role": c.get("role", ""),
                 "persona": c.get("persona", {})}
                for c in derived if c.get("name")]
            _write_json_atomic(target_dir / "cast.json", cast_data)
    macro_plan_data = req.macro_plan
    if macro_plan_data is not None and isinstance(macro_plan_data, dict):
        _write_json_atomic(target_dir / "macro_plan.json", macro_plan_data)
        _write_project_meta(
            target_dir,
            macro={"template": macro_plan_data.get("act_structure", {})
                                      .get("template", ""),
                   "total_episodes": macro_plan_data.get("blueprint", {})
                                      .get("total_episodes", 0),
                   "has_plan": True})
    elif req.total_episodes:
        # 跳过宏观计划也落盘集数约定（写作台/宏观导出/重开项目均依赖它）
        _write_project_meta(
            target_dir,
            macro={"template": "", "total_episodes": req.total_episodes,
                   "has_plan": False})
    # P25: 参考素材落盘 material.md（请求体优先，其次宏观生成时暂存的）
    material = req.material if isinstance(req.material, str) \
        and req.material.strip() else session.get("material")
    if material:
        (target_dir / "material.md").write_text(
            material, encoding="utf-8")
    # Phase 4：项目层 patch 模板（用户可在此覆盖题材默认 params；
    # engine 构建 bundle 时项目层最优先，不动全局题材库）
    patches_file = target_dir / "patches.yaml"
    if not patches_file.exists():
        patches_file.write_text(
            "# 项目层 patch（覆盖题材默认，engine 构建时最优先应用）\n"
            "# 用法：在 params 下写要覆盖的键（深合并），例：\n"
            "# params:\n"
            "#   beats_per_chapter: 5          # 每章节拍数\n"
            "#   prompt:\n"
            "#     style: \"1000-1500字，文白相间\"   # 覆盖题材文风\n"
            f"# 当前题材: {genre_name} | 文化: {culture}\n"
            "params: {}\n",
            encoding="utf-8")
    deps.engine.reset()
    deps.engine.discard_plan()
    return {"ok": True, "project": {"name": req.project_name,
                                     "genre": genre_name,
                                     "culture": culture}}


# ---------- session-based derive_cast / cross_check ----------
@router.post("/api/gacha/{sid}/derive_cast")
async def gacha_session_derive_cast(sid: str, req: DeriveCastReq):
    from story_engine.worldview import derive_cast as wv_derive_cast
    from story_engine.worldview.derive_cast import name_cast_with_llm
    session = _gacha_sessions.get(sid)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    sess_engine = session["engine"]
    genre_params = getattr(sess_engine.bundle, "genre_params", None)
    genre_name = getattr(sess_engine.bundle, "genre", "")
    cast = wv_derive_cast(req.worldview, req.language, genre_params)
    # placeholder 角色用 LLM 起名（mock 模式跳过，不阻塞）
    if any(c.get("placeholder") for c in cast):
        llm = session["kernel"].llm
        if not llm.is_mock:
            cast = await name_cast_with_llm(
                cast, req.worldview, genre_params, llm.call,
                genre_name=genre_name)
    return {"cast": cast}


@router.post("/api/gacha/{sid}/cross_check")
def gacha_session_cross_check(sid: str, req: CrossCheckReq):
    from story_engine.macro import check_cross_layer
    from story_engine.worldview import WorldviewProfile
    session = _gacha_sessions.get(sid)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    bundle = session["engine"].bundle
    genre_params = getattr(bundle, "genre_params", None) or {}
    genre_name = getattr(bundle, "genre", "")
    wv_profile = None
    wv_preset = None
    if req.worldview and isinstance(req.worldview.get("layers"), dict):
        wv_profile = WorldviewProfile(layers=req.worldview["layers"])
        wv_preset = req.worldview.get("preset")
    elif req.worldview:
        wv_profile = req.worldview
        wv_preset = (req.worldview.get("preset")
                     if isinstance(req.worldview, dict) else None)
    cast_profile = req.cast if isinstance(req.cast, list) else None
    warnings = check_cross_layer(
        genre_params, wv_profile, cast_profile, genre_name,
        wv_preset=wv_preset)
    return {"warnings": [
        {"type": w.type, "severity": w.severity, "title": w.title,
         "description": w.description, "suggestion": w.suggestion}
        for w in warnings
    ]}


# ---------- macro 内部辅助 ----------
def _build_macro_prompt(bundle, worldview_profile, cast_profile,
                        template_name, total_episodes, conflict_warnings,
                        material=None):
    from story_engine.macro.generator import _build_prompt
    return _build_prompt(bundle, worldview_profile, cast_profile,
                         template_name, total_episodes, conflict_warnings,
                         material_text=material)


def _generate_skeleton_macro(bundle, worldview_profile, cast_profile,
                             template_name, total_episodes):
    from story_engine.macro.generator import _generate_skeleton
    return _generate_skeleton(bundle, worldview_profile, cast_profile,
                              template_name, total_episodes)


def _parse_and_validate_macro(text, template_name, total_episodes):
    from story_engine.macro.generator import _parse_yaml, _validate, _build_plan
    parsed = _parse_yaml(text)
    if parsed and _validate(parsed, total_episodes,
                            template_name=template_name):
        return _build_plan(parsed, template_name, total_episodes)
    return None


# ---------- WebSocket 宏观计划流式生成 ----------
@router.websocket("/api/gacha/{sid}/macro/stream")
async def macro_stream(ws: WebSocket, sid: str):
    import asyncio
    from story_engine.macro import (
        TEMPLATES as MACRO_TEMPLATES, macro_plan_to_dict)
    from story_engine.worldview import WorldviewProfile

    await ws.accept()
    session = _gacha_sessions.get(sid)
    if not session:
        await ws.send_json({"type": "error", "msg": "会话不存在或已过期"})
        await ws.close()
        return
    try:
        req_data = await ws.receive_json()
    except WebSocketDisconnect:
        await ws.close()
        return
    except Exception:
        await ws.send_json({"type": "error", "msg": "需发送 JSON 请求体"})
        await ws.close()
        return
    template = req_data.get("template_name", "save_the_cat_15")
    if template not in MACRO_TEMPLATES and template != "ai_custom":
        await ws.send_json({"type": "error",
                            "msg": f"未知幕结构模板：{template}"})
        await ws.close()
        return
    bundle = session["engine"].bundle
    sess_kernel = session["kernel"]
    wv_profile = None
    wv_data = req_data.get("worldview")
    if wv_data and isinstance(wv_data, dict) \
            and isinstance(wv_data.get("layers"), dict):
        wv_profile = WorldviewProfile(layers=wv_data["layers"])
    cast_profile = req_data.get("cast")
    if not isinstance(cast_profile, list):
        cast_profile = []
    conflict_warnings = req_data.get("conflict_warnings")
    if not isinstance(conflict_warnings, list):
        conflict_warnings = None
    # P25: 参考素材（如百鬼图鉴），注入宏观 prompt；同时暂存 session 供 confirm 落盘
    material = req_data.get("material")
    if not isinstance(material, str) or not material.strip():
        material = None
    session["material"] = material
    total_episodes = _coerce_total_episodes(
        req_data.get("total_episodes"),
        getattr(bundle, "target_length", 12))
    try:
        if sess_kernel.llm.is_mock:
            plan = _generate_skeleton_macro(
                bundle, wv_profile, cast_profile, template, total_episodes)
            plan_dict = macro_plan_to_dict(plan)
            plan_text = json.dumps(plan_dict, ensure_ascii=False, indent=2)
            for i in range(0, len(plan_text), 80):
                await ws.send_json({"type": "delta",
                                    "text": plan_text[i:i + 80]})
                await asyncio.sleep(0.03)
            await ws.send_json({"type": "complete", "plan": plan_dict})
            await ws.close()
            return
        prompt = _build_macro_prompt(
            bundle, wv_profile, cast_profile, template, total_episodes,
            conflict_warnings, material=material)
        from story_engine.macro.generator import macro_max_tokens
        full_text = ""
        try:
            async def _notify_thinking():
                """GLM thinking 首次检出 → 前端显示「深度构思中」（不再 3-5 分钟黑屏）。"""
                try:
                    await ws.send_json({"type": "thinking"})
                except Exception:
                    pass
            async for chunk in sess_kernel.llm.call_stream(
                    prompt, purpose="macro_plan", temperature=0.7,
                    max_tokens=macro_max_tokens(total_episodes),
                    on_thinking=_notify_thinking):
                full_text += chunk
                await ws.send_json({"type": "delta", "text": chunk})
        except Exception as e:
            # P23.4 质量加固：非 mock 模式不再用骨架兜底（空模板无剧情价值）
            await ws.send_json({"type": "error",
                                "msg": f"LLM 流式调用失败：{e}。请重试宏观规划。"})
            await ws.close()
            return
        plan = _parse_and_validate_macro(full_text, template, total_episodes)
        if plan is None:
            # P23.4：解析/验证失败（含空模板拦截）→ 报错让用户重试，不兜底骨架
            await ws.send_json({"type": "error",
                                "msg": "LLM 输出解析失败或内容不充实，请重试宏观规划。"})
            await ws.close()
            return
        await ws.send_json({"type": "complete",
                            "plan": macro_plan_to_dict(plan)})
        await ws.close()
    except WebSocketDisconnect:
        return
    except Exception as e:
        logger.exception("macro_stream 未捕获异常 | sid=%s", sid)
        try:
            # P23.4：非 mock 不兜底骨架
            await ws.send_json({"type": "error",
                                "msg": f"宏观生成失败：{e}。请重试。"})
            await ws.close()
        except Exception:
            try:
                await ws.close()
            except Exception:
                pass


# ---------- synth ----------
@router.post("/api/gacha/synth")
async def gacha_synth():
    from story_engine.meta.gacha import draw_card_async
    from story_engine.types import StoryEngineError
    try:
        return await draw_card_async(
            deps.kernel, deps.kernel.llm.call, "synth")
    except StoryEngineError as e:
        raise HTTPException(status_code=500, detail=str(e))
