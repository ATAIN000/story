"""Story Engine Demo — FastAPI 后端

API：
  GET  /api/project            项目完整快照（世界状态/事件/伏笔/章节/决策卡/pending_plan）
  POST /api/project/generate   生成下一章（核心循环；body 可选 mode: auto|confirm，P6.2）
  POST /api/project/plan       【P6.2 新增】只产决策卡（两阶段生成第一步）
  DELETE /api/project/plan     【P6.2 新增】作废待批准方案
  POST /api/project/rollback   回滚到指定 tick
  POST /api/project/reset      重置项目
  GET  /api/config             运行配置（LLM 模式/插件）
  POST /api/meta/config        【v0.2 新增】UserIntent → StoryConfig（Module 8）
  POST /api/intervene          【v0.5 新增】作者介入统一入口（5 类，Module 7.1）
  GET  /api/interventions      【v0.5 新增】介入历史（author_intervention 事件流）
  POST /api/hitl/respond       【v0.5 新增】应答 pending 的 HITL 请求
  GET  /api/training/stats     【P6.1 新增】训练信号计数（skills/preferences/style）
  POST /api/paragraph/rewrite  【P6.3 新增】段落重写（Realizer 单段渲染，只读不写）
  GET  /api/characters         【P6.4 新增】角色卡聚合（minds/关系/voice/arc，只增）
静态：/ → frontend/dist（Vue SPA）
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

# 让 backend 能 import story_engine（项目根在上一级）
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from story_engine.engine import StoryEngine, StoryEngineMockEnded  # noqa: E402
from story_engine.hitl import (  # noqa: E402
    HumanInput, InterventionRouter, TrainingPipeline)
from story_engine.kernel import Kernel, LLMPool  # noqa: E402
from story_engine.llm import LLMError  # noqa: E402
from story_engine.meta import MetaGenerator, UserIntent  # noqa: E402
from story_engine.types import StoryEngineError  # noqa: E402


def _load_dotenv():
    """轻量 .env 加载（不额外引依赖）"""
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

PROJECT_DIR = os.environ.get("STORY_ENGINE_PROJECT_DIR",
                             str(ROOT / "data" / "projects" / "yupei"))
FRONTEND_DIST = Path(os.environ.get("STORY_ENGINE_FRONTEND_DIST",
                                    str(ROOT / "frontend" / "dist")))

app = FastAPI(title="Story Engine", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

# === v0.2: Kernel/User 分离 — 先建 Kernel，注入 Engine 与 MetaGenerator ===
kernel = Kernel(PROJECT_DIR, plugin_dir=ROOT / "story_engine" / "plugins")
llm_client = kernel.llm  # 保留 llm_client 变量名，老 API 引用兼容
engine = StoryEngine(kernel)
meta_gen = MetaGenerator(kernel)


def _regenerate_sync() -> None:
    """InterventionRouter.regenerate_fn 约定：无参同步 callable（P5.8）；
    engine.regenerate_current_chapter 是 async → 最小适配（P5.10 评审传导2）：
    asyncio.run 包一层。安全性：本函数只经 run_in_threadpool 在工作线程调用
    （无线程内运行中的事件循环），故 asyncio.run 合法；EventStore 为
    check_same_thread=False + 锁，跨线程 commit 安全；LLMPool 每次调用
    自建 httpx.AsyncClient，不绑定特定事件循环。"""
    asyncio.run(engine.regenerate_current_chapter())


# === v0.5: HITL（P5.10）— InterventionRouter + TrainingPipeline 挂载 ===
# 挂载点决策（任务卡落地要点）：engine 侧无 router/pipeline 实例（读 engine.py
# 确认），参照 meta_gen 同款模式在 backend 侧构造，依赖 kernel 单例 +
# regenerate_fn async 包装 + TrainingPipeline(kernel, project_dir)。
training_pipeline = TrainingPipeline(kernel, PROJECT_DIR)
intervention_router = InterventionRouter(
    kernel, pipeline=training_pipeline, regenerate_fn=_regenerate_sync,
    textual_apply_fn=engine.update_chapter_text)  # P6.1(B1)：textual 正文回写口子


class RollbackReq(BaseModel):
    tick: int


class GenerateReq(BaseModel):
    """generate 可选 body（P6.2）：mode 缺省 auto —— 无 body/旧调用逐字不变；
    confirm 复用 plan 缓存的决策卡（无缓存时等同 auto，宽容策略见 engine）"""
    mode: Literal["auto", "confirm"] = "auto"


class UserIntentReq(BaseModel):
    theme: str = ""
    culture_hint: str = ""
    language: str = "zh"
    target_length: int = 12
    platform: str = "novel"


class InterveneReq(BaseModel):
    """作者介入统一入口 body（P5.10 契约）"""
    type: str                 # intent / structural / character / textual / evaluation
    payload: dict = {}
    reason: str = ""


class HitlRespondReq(BaseModel):
    """HITL 应答 body（response 可为任意 JSON：选项/文本/结构化对象）"""
    request_id: str
    response: Any = None


class ParagraphRewriteReq(BaseModel):
    """段落重写 body（P6.3 契约）；direction 可空（引擎给默认润色方向）"""
    chapter: int
    para_index: int
    direction: str = ""


class SettingsReq(BaseModel):
    """P6.10 B9：设置覆盖 body；三键全可选，仅这三个生效（其余忽略）。"""
    eval_enabled: bool | None = None
    ir_first: bool | None = None
    eval_max_rounds: int | None = None


class TestLlmReq(BaseModel):
    """P6.10 B10：LLM 测试连接 body；三键全可选，缺省用当前配置。
    key 永不回前端（响应只 ok+latency+model+error）。"""
    base_url: str | None = None
    key: str | None = None
    model: str | None = None


@app.get("/api/config")
def config():
    return {
        "llm_mode": "mock" if llm_client.is_mock else "openai",
        "llm_model": llm_client.model,
        "base_url": llm_client.base_url if not llm_client.is_mock else None,
        "plugins": engine.registry.list_plugins(),
        "axes": {"genre": engine.genre.name,
                 "culture": engine.culture.name, "language": "zh"},
        "kernel": {
            "syscalls": __import__("story_engine.kernel", fromlist=["SYSCALL_NAMES"]).SYSCALL_NAMES,
            "actors": kernel.scheduler.list_actors(),
        },
    }


@app.get("/api/project")
def get_project():
    return engine.project_snapshot()


@app.post("/api/project/generate")
async def generate(req: GenerateReq | None = None):
    try:
        return await engine.generate_chapter(
            mode=req.mode if req is not None else "auto")
    except StoryEngineMockEnded as e:
        raise HTTPException(status_code=409, detail=str(e))
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except StoryEngineError as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------- 两阶段生成（P6.2 B3：plan → confirm，支撑「看方案→生成」工作流） ----------
@app.post("/api/project/plan")
def plan():
    """【P6.2】只产决策卡不生成章节，缓存为 pending_plan 供 confirm 复用。
    决策卡是纯规则产物（零 LLM），剧本/真实路径通用；不触碰世界状态。"""
    return engine.plan_chapter()


@app.delete("/api/project/plan")
def discard_plan():
    """【P6.2】作废待批准方案（清缓存；无缓存时幂等 ok）"""
    engine.discard_plan()
    return {"ok": True, "pending_plan": None}


@app.post("/api/project/rollback")
def rollback(req: RollbackReq):
    if req.tick < 0 or req.tick > engine.kernel.query_world("head_tick"):
        raise HTTPException(status_code=400, detail="非法 tick")
    return engine.rollback(req.tick)


@app.post("/api/project/reset")
def reset():
    return engine.reset()


@app.post("/api/meta/config")
async def meta_config(req: UserIntentReq):
    """Module 8 Meta-Generator 入口：UserIntent → StoryConfig"""
    try:
        intent = UserIntent(
            theme=req.theme, culture_hint=req.culture_hint,
            language=req.language, target_length=req.target_length,
            platform=req.platform,
        )
        cfg = await meta_gen.generate_config(intent)
        return cfg.to_dict()
    except StoryEngineError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------- HITL（P5.10，Module 7：介入即事件，可回放） ----------
INTERVENTION_TYPES = ("intent", "structural", "character", "textual", "evaluation")


@app.post("/api/intervene")
async def intervene(req: InterveneReq):
    """5 类作者介入统一入口 → InterventionResult dict。

    router.route 全程同步且可能触发章级重生成（structural → regenerate_fn），
    经 run_in_threadpool 调度：既不阻塞主事件循环，也让 _regenerate_sync 的
    asyncio.run 落在无运行中循环的工作线程（见该函数注释）。
    未知 type 在 API 层拦截 → 400；router 级失败（如目标事件不存在）
    返回 200 + ok:false（契约：InterventionResult 原样返回）。
    """
    if req.type not in INTERVENTION_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"未知介入类型「{req.type}」（支持 {'/'.join(INTERVENTION_TYPES)}）")
    result = await run_in_threadpool(
        intervention_router.route,
        HumanInput(type=req.type, payload=req.payload, reason=req.reason))
    return asdict(result)


@app.get("/api/interventions")
async def list_interventions():
    """介入历史：事件流中的 author_intervention 事件（含 active 标记）。
    query_world 无现成 predicate，按 all_events 过滤 event_type（任务卡口径）。"""
    return [e for e in kernel.query_world("all_events")
            if e.get("event_type") == "author_intervention"]


# ---------- 训练统计（P6.1 B5，支撑前端写作台训练信号计数） ----------
def _count_jsonl(path: Path) -> int:
    """jsonl 行数（文件不存在 → 0，不崩）"""
    if not path.exists():
        return 0
    return sum(1 for line in
               path.read_text(encoding="utf-8").splitlines() if line.strip())


def training_stats_snapshot(registry, training_dir: Path) -> dict:
    """B5 统计纯逻辑（独立于模块单例，便于测试）：
    skills=story.skill 注册数（Registry.list_plugins 枚举）；
    preferences/style=training_data 下两个 jsonl 行数（不存在 → 0）；
    recent_skills=最近 ≤5 条技能描述（created_at 倒序，键缺省补 ""）。"""
    training_dir = Path(training_dir)
    skill_names = registry.list_plugins("story.skill")["story.skill"]
    recent = []
    for name in skill_names:
        params = registry.get_params("story.skill", name)
        recent.append({
            "name": name,
            "source_intervention": params.get("source_intervention", ""),
            "created_at": params.get("created_at", ""),
        })
    recent.sort(key=lambda s: s["created_at"], reverse=True)
    return {
        "skills": len(skill_names),
        "preferences": _count_jsonl(training_dir / "preferences.jsonl"),
        "style": _count_jsonl(training_dir / "style.jsonl"),
        "recent_skills": recent[:5],
    }


@app.get("/api/training/stats")
def training_stats():
    """【P6.1 B5】训练信号计数：{skills, preferences, style, recent_skills}"""
    return training_stats_snapshot(kernel.registry, training_pipeline.training_dir)


# ---------- 段落重写（P6.3 B2，写作台核心卖点：Realizer 单段渲染） ----------
@app.post("/api/paragraph/rewrite")
async def paragraph_rewrite(req: ParagraphRewriteReq):
    """【P6.3】单段重写 {chapter, para_index, direction} → {original, rewritten}。

    段落协议：final.text 按 \\n\\n 切分、剔除空白块，首块标题行（^标题[:：]）
    不计入段序号，para_index 从正文第一段起 0 基（与前端工具函数一致）。
    只读不写：前端「采用」时走 textual 介入回写（P6.1 /api/intervene）。
    成本：每次重写恰好 1 次 LLM 调用，不接自评迭代（本阶段简化）。
    兜底：LLM 空稿/异常 → 200 + rewritten="" + note（不 500）；
    章节不存在/段序号越界 → 404；rolled_back 章 → 409。
    """
    result = await engine.rewrite_paragraph(
        req.chapter, req.para_index, req.direction)
    status = result["status"]
    if status == "not_found":
        raise HTTPException(
            status_code=404, detail=f"无此章节：第{req.chapter}章")
    if status == "rolled_back":
        raise HTTPException(
            status_code=409,
            detail=f"第{req.chapter}章已 rolled_back，不可重写（可回滚恢复后重试）")
    if status == "out_of_range":
        raise HTTPException(
            status_code=404,
            detail=f"段序号越界：para_index={req.para_index}"
                   f"（本章共 {result.get('para_count', 0)} 段）")
    return {k: result[k]
            for k in ("chapter", "para_index", "original", "rewritten", "note")}


# ---------- 角色卡（P6.4 B4，支撑前端人物视图） ----------
@app.get("/api/characters")
def characters():
    """【P6.4】角色卡聚合列表（按 id 排序，空项目 → []）。
    每角色 {id, role, knows, secrets, goals, relations, voice, arc}；
    voice/arc 不可得 → null（不编造，口径见 engine.characters_view docstring）。"""
    return engine.characters_view()


# ---------- 设置（P6.10 B9/B10） ----------
@app.get("/api/settings")
def settings_get():
    """【P6.10 B9】读取当前设置（env + 进程内覆盖合并后的生效值）。
    api_key 永不返回；base_url 仅返回 masked 版本。"""
    return engine.settings_view()


@app.post("/api/settings")
def settings_post(req: SettingsReq):
    """【P6.10 B9】写进程内覆盖（不写 .env、不持久化，重启后失效）。
    仅 eval_enabled / ir_first / eval_max_rounds 三键生效；返回更新后视图。"""
    patch = {k: v for k, v in {
        "eval_enabled": req.eval_enabled,
        "ir_first": req.ir_first,
        "eval_max_rounds": req.eval_max_rounds,
    }.items() if v is not None}
    return engine.apply_settings_overrides(patch)


@app.post("/api/settings/test_llm")
async def settings_test_llm(req: TestLlmReq | None = None):
    """【P6.10 B10】一次性 ping LLM —— 最小请求「请回复：好」max_tokens=10。
    body 缺省用当前 engine.llm 配置；mock 模式直接返回 ok=true。
    响应只 {ok, latency_ms, model, error?} —— key 永不回前端。"""
    import time as _time
    import httpx
    src = req or TestLlmReq()
    client = engine.llm
    base_url = (src.base_url or client.base_url).rstrip("/")
    model = src.model or client.model
    key = src.key or client.api_key
    # mock 模式：直接 ok（不构造 client）
    if client.is_mock and not src.key and not src.base_url:
        return {"ok": True, "latency_ms": 0.0, "model": client.model}
    if not key:
        return {"ok": False, "error": "未配置 API key（环境变量 STORY_ENGINE_LLM_API_KEY 为空）",
                "latency_ms": None, "model": model}
    headers = {"Authorization": f"Bearer {key}"}
    if client.user_agent:
        headers["User-Agent"] = client.user_agent
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "请回复：好"}],
        "max_tokens": 10,
    }
    if "kimi.com/coding" in base_url:
        body["temperature"] = 0.6
        body["thinking"] = {"type": "disabled"}
    t0 = _time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            r = await http.post(f"{base_url}/chat/completions",
                                headers=headers, json=body)
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"网络错误：{e.__class__.__name__}",
                "latency_ms": None, "model": model}
    latency = round((_time.perf_counter() - t0) * 1000, 1)
    if r.status_code != 200:
        return {"ok": False,
                "error": f"HTTP {r.status_code}：{r.text[:200]}",
                "latency_ms": latency, "model": model}
    return {"ok": True, "latency_ms": latency, "model": model}


@app.post("/api/hitl/respond")
async def hitl_respond(req: HitlRespondReq):
    """应答 pending 的 HITL 请求 → {ok: true}；无此 pending（id 错误/已应答/
    已超时）→ 404（与现有端点 HTTPException 风格一致）。

    保持 async 直调不进 threadpool：resolve_human_input 的 event.set 有事件
    循环线程亲和，须与 request_human_input 等待协程同线程（kernel docstring）。
    """
    if not kernel.resolve_human_input(req.request_id, req.response):
        raise HTTPException(
            status_code=404,
            detail=f"无此 pending 请求「{req.request_id}」（id 错误或已应答/超时）")
    return {"ok": True}


# ---------- 静态托管 Vue SPA ----------
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"),
              name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        file = FRONTEND_DIST / full_path
        if full_path and file.exists() and file.is_file():
            return FileResponse(file)
        return FileResponse(FRONTEND_DIST / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8111")))
