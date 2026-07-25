"""作者介入 / HITL 端点。"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from backend import deps
from story_engine.hitl import HumanInput

router = APIRouter()

INTERVENTION_TYPES = ("intent", "structural", "character", "textual", "evaluation")


class InterveneReq(BaseModel):
    type: str
    payload: dict = {}
    reason: str = ""


class HitlRespondReq(BaseModel):
    request_id: str
    response: Any = None


@router.post("/api/intervene")
async def intervene(req: InterveneReq):
    if req.type not in INTERVENTION_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"未知介入类型「{req.type}」（支持 {'/'.join(INTERVENTION_TYPES)}）")
    result = await run_in_threadpool(
        deps.intervention_router.route,
        HumanInput(type=req.type, payload=req.payload, reason=req.reason))
    return asdict(result)


@router.get("/api/interventions")
async def list_interventions():
    return [e for e in deps.kernel.query_world("all_events")
            if e.get("event_type") == "author_intervention"]


@router.post("/api/hitl/respond")
async def hitl_respond(req: HitlRespondReq):
    if not deps.kernel.resolve_human_input(req.request_id, req.response):
        raise HTTPException(
            status_code=404,
            detail=f"无此 pending 请求「{req.request_id}」（id 错误或已应答/超时）")
    return {"ok": True}
