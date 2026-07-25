"""世界观架构端点。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend import deps
from backend.models import CrossCheckReq, DeriveCastReq

router = APIRouter()


class WorldviewEvaluateReq(BaseModel):
    profile: dict[str, dict[str, str]] = {}


def _wv_imports():
    """延迟导入（story_engine 依赖 sys.path，由 main.py 注入）。"""
    from story_engine.worldview import (
        ALL_PARAMS as WV_ALL_PARAMS, LAYERS as WV_LAYERS,
        LANGUAGE_LAYERS as WV_LANGUAGE_LAYERS,
        CHARACTER_LAYERS as WV_CHARACTER_LAYERS,
        WorldviewProfile, evaluate as wv_evaluate,
        preset_summaries as wv_preset_summaries,
    )
    from story_engine.meta.genre_taxonomy import all_taxa
    return (WV_ALL_PARAMS, WV_LAYERS, WV_LANGUAGE_LAYERS, WV_CHARACTER_LAYERS,
            WorldviewProfile, wv_evaluate, wv_preset_summaries, all_taxa)


@router.get("/api/worldview/schema")
def worldview_schema():
    (WV_ALL_PARAMS, WV_LAYERS, WV_LANGUAGE_LAYERS, WV_CHARACTER_LAYERS,
     _Profile, _eval, wv_preset_summaries, all_taxa) = _wv_imports()
    all_layers = WV_LAYERS + WV_LANGUAGE_LAYERS + WV_CHARACTER_LAYERS
    by_preset: dict[str, list[str]] = {}
    for t in all_taxa():
        by_preset.setdefault(t.primary_preset, []).append(t.title)
    presets = []
    for p in wv_preset_summaries():
        titles = by_preset.get(p["key"], [])
        presets.append({**p, "recommended_genres": titles[:5],
                        "recommended_genres_total": len(titles)})
    return {
        "layers": all_layers,
        "param_count": len(WV_ALL_PARAMS),
        "layers_covered": [layer["id"] for layer in all_layers],
        "presets": presets,
    }


@router.post("/api/worldview/evaluate")
def worldview_evaluate_endpoint(req: WorldviewEvaluateReq):
    (_all, _layers, _lang, _char,
     WorldviewProfile, wv_evaluate, *_rest) = _wv_imports()
    flat = WorldviewProfile(layers=req.profile).as_flat()
    return wv_evaluate(flat)


@router.post("/api/worldview/derive_cast")
def derive_cast_endpoint_legacy(req: DeriveCastReq):
    raise HTTPException(
        status_code=410,
        detail="此端点已废弃，请使用 /api/gacha/{sid}/derive_cast")


@router.post("/api/worldview/cross_check")
def worldview_cross_check_endpoint_legacy(req: CrossCheckReq):
    raise HTTPException(
        status_code=410,
        detail="此端点已废弃，请使用 /api/gacha/{sid}/cross_check")
