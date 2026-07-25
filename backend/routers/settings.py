"""设置端点（LLM 配置 / 自评开关 / LLM ping）。"""
from __future__ import annotations

import time

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend import deps
from backend.helpers import _persist_env

router = APIRouter()


class SettingsReq(BaseModel):
    eval_enabled: bool | None = None
    ir_first: bool | None = None
    eval_max_rounds: int | None = None


class TestLlmReq(BaseModel):
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None


class LlmSettingsReq(BaseModel):
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    persist: bool = False


@router.get("/api/settings")
def settings_get():
    return deps.engine.settings_view()


@router.post("/api/settings")
def settings_post(req: SettingsReq):
    patch = {k: v for k, v in {
        "eval_enabled": req.eval_enabled,
        "ir_first": req.ir_first,
        "eval_max_rounds": req.eval_max_rounds,
    }.items() if v is not None}
    return deps.engine.apply_settings_overrides(patch)


@router.post("/api/settings/llm")
def settings_llm_post(req: LlmSettingsReq):
    if req.base_url is not None and req.base_url.strip():
        u = req.base_url.strip()
        if not (u.startswith("https://") or u.startswith("http://localhost")
                or u.startswith("http://127.0.0.1")):
            raise HTTPException(
                status_code=422,
                detail="base_url 必须是 https://（或本机 http://localhost）")
    view = deps.engine.apply_llm_settings({
        "base_url": req.base_url, "model": req.model, "api_key": req.api_key})
    if req.persist:
        updates = {}
        if req.base_url and req.base_url.strip():
            updates["STORY_ENGINE_LLM_BASE_URL"] = req.base_url.strip()
        if req.model and req.model.strip():
            updates["STORY_ENGINE_LLM_MODEL"] = req.model.strip()
        if req.api_key and req.api_key.strip():
            updates["STORY_ENGINE_LLM_API_KEY"] = req.api_key.strip()
            updates["STORY_ENGINE_LLM_MODE"] = "openai"
        if updates:
            _persist_env(updates)
    return view


@router.post("/api/settings/test_llm")
async def settings_test_llm(req: TestLlmReq | None = None):
    src = req or TestLlmReq()
    client = deps.engine.llm
    use_temp = bool((src.base_url or "").strip() and (src.api_key or "").strip())
    base_url = (src.base_url.strip() if use_temp else client.base_url).rstrip("/")
    model = src.model or client.model
    key = src.api_key.strip() if use_temp else client.api_key
    if client.is_mock and not use_temp:
        return {"ok": True, "latency_ms": 0.0, "model": client.model}
    if not key:
        return {"ok": False,
                "error": "未配置 API key（环境变量 STORY_ENGINE_LLM_API_KEY 为空）",
                "latency_ms": None, "model": model}
    headers = {"Authorization": f"Bearer {key}"}
    ua = client.user_agent
    if not ua and key.startswith("sk-kimi-"):
        from story_engine.kernel.llm_pool import KIMI_CODE_UA
        ua = KIMI_CODE_UA
    if ua:
        headers["User-Agent"] = ua
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "请回复：好"}],
        "max_tokens": 10,
    }
    if "kimi.com/coding" in base_url:
        body["temperature"] = 0.6
        body["thinking"] = {"type": "disabled"}
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            r = await http.post(f"{base_url}/chat/completions",
                                headers=headers, json=body)
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"网络错误：{e.__class__.__name__}",
                "latency_ms": None, "model": model}
    latency = round((time.perf_counter() - t0) * 1000, 1)
    if r.status_code != 200:
        return {"ok": False,
                "error": f"HTTP {r.status_code} {r.reason_phrase}",
                "latency_ms": latency, "model": model}
    return {"ok": True, "latency_ms": latency, "model": model}
