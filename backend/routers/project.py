"""单项目核心端点（快照/生成/规划/回滚/重置/初始化/角色/段落重写/meta/training/config）。"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from backend import deps
from backend.generation_state import gen_state, set_stage, _now_iso
from backend.helpers import _count_jsonl

logger = logging.getLogger(__name__)

router = APIRouter()


class RollbackReq(BaseModel):
    tick: int


class GenerateReq(BaseModel):
    mode: Literal["auto", "confirm"] = "auto"


class UserIntentReq(BaseModel):
    theme: str = ""
    culture_hint: str = ""
    language: str = "zh"
    target_length: int = 12
    platform: str = "novel"


class ParagraphRewriteReq(BaseModel):
    chapter: int
    para_index: int
    direction: str = ""


# ---------- config ----------
@router.get("/api/config")
def config():
    from story_engine import __version__
    from story_engine.kernel.registry import EXTENSION_POINTS
    return {
        "version": __version__,
        "llm_mode": "mock" if deps.llm_client.is_mock else "openai",
        "llm_model": deps.llm_client.model,
        "base_url": deps.llm_client.base_url if not deps.llm_client.is_mock else None,
        "plugins": deps.engine.registry.list_plugins(),
        "display_names": deps.engine.kernel.registry.display_map(),
        "extension_labels": dict(EXTENSION_POINTS),
        "axes": {"genre": deps.engine.genre.name,
                 "culture": deps.engine.culture.name, "language": "zh"},
        "kernel": {
            "syscalls": __import__("story_engine.kernel",
                                   fromlist=["SYSCALL_NAMES"]).SYSCALL_NAMES,
            "actors": deps.kernel.scheduler.list_actors(),
        },
    }


# ---------- project snapshot ----------
@router.get("/api/project")
def get_project():
    return deps.engine.project_snapshot()


# ---------- chapter generation ----------
@router.post("/api/project/generate")
async def generate(req: GenerateReq | None = None):
    from story_engine.engine import StoryEngineMockEnded
    from story_engine.llm import LLMError
    from story_engine.types import StoryEngineError
    # 并发保护：后台异步生成在跑时，拒绝同步调用（防两个生成并发写同一 engine）
    if gen_state.busy():
        raise HTTPException(status_code=409, detail="后台生成进行中，请等待完成或查询 /generation-status")
    try:
        return await deps.engine.generate_chapter(
            mode=req.mode if req is not None else "auto")
    except StoryEngineMockEnded as e:
        raise HTTPException(status_code=409, detail=str(e))
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except StoryEngineError as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------- async generation（P23.3：切走再回来状态丢失修复） ----------
def _next_chapter_no() -> int:
    """当前下一章号（state.narrative.chapter + 1 口径，与 engine 一致）。"""
    state = deps.engine.kernel.query_world("current_state")
    return state.narrative.chapter + 1


def _current_project_name() -> str:
    """锁定项目名：deps.PROJECT_DIR 的末段（项目目录名）。"""
    from pathlib import Path
    return Path(deps.PROJECT_DIR).name


@router.post("/api/project/generate/async")
async def generate_async(req: GenerateReq | None = None):
    """启动后台生成，立即返回 {started, chapter_no}。已在生成 → 409。

    后台任务持有启动时捕获的 engine 引用（engine_snapshot）；生成中禁止切项目
    （_switch_to 会 close 旧 kernel），故该引用在生成期间始终有效。
    """
    from story_engine.engine import StoryEngineMockEnded
    from story_engine.llm import LLMError
    from story_engine.types import StoryEngineError

    if gen_state.busy():
        raise HTTPException(status_code=409, detail="正在生成中")
    # 旧任务已结束（busy=False）才走到这里：直接覆盖赋值，不清场。
    # 旧实现调 clear() 会抹掉旧 task 的 finished/result，若旧 task 的 finally
    # 晚一步执行（异步竞态），会把刚启动的新任务状态也清成 finished=False。
    # 新任务赋值顺序保证：先建 task 再公开 started 标志。

    mode = req.mode if req is not None else "auto"
    gen_state.engine_snapshot = deps.engine
    gen_state.chapter_no = _next_chapter_no()
    gen_state.project_name = _current_project_name()
    gen_state.started_at = _now_iso()
    gen_state.stage = "started"
    # 重置上轮结果态（不清 task 引用，避免竞态）：上一轮 finished=True 若不清，
    # 新任务 running 期间会 busy=True 且 finished=True 的矛盾态，前端误判已完成
    gen_state.finished = False
    gen_state.result = None
    gen_state.error = None

    async def _run() -> dict:
        try:
            set_stage("generating")
            logger.info("async 生成开始 | 章=%s | mode=%s", gen_state.chapter_no, mode)
            # P1-1: 设置进度回调，engine 在关键节点调 set_stage 更新前端可见的 stage
            gen_state.engine_snapshot._progress_callback = lambda stage, detail="": set_stage(stage, detail)
            rec = await gen_state.engine_snapshot.generate_chapter(mode=mode)
            gen_state.engine_snapshot._progress_callback = None  # 清理
            gen_state.result = rec
            gen_state.stage = "done"
            logger.info("async 生成完成 | 章=%s | stage=done", gen_state.chapter_no)
            return rec
        except StoryEngineMockEnded as e:
            gen_state.error = f"剧本已完结：{e}"
            gen_state.stage = "error"
            return {"_mock_ended": True, "detail": str(e)}
        except asyncio.CancelledError:
            logger.warning("async 生成被取消 | 章=%s", gen_state.chapter_no)
            gen_state.error = "生成任务被取消"
            gen_state.stage = "cancelled"
            raise   # CancelledError 重新抛出，让 task 正确进入 cancelled 态
        except (LLMError, StoryEngineError) as e:
            gen_state.error = str(e)
            gen_state.stage = "error"
            logger.error("async 生成失败(引擎) | 章=%s | %s", gen_state.chapter_no, e)
            return {"_error": True, "detail": str(e)}
        except Exception as e:  # 兜底：任何异常都落 error，不逃逸
            gen_state.error = f"{type(e).__name__}: {e}"
            gen_state.stage = "error"
            logger.exception("async 生成异常(兜底) | 章=%s", gen_state.chapter_no)
            return {"_error": True, "detail": gen_state.error}
        finally:
            gen_state.finished = True
            logger.info("async 生成 finally | 章=%s | finished=True | stage=%s",
                        gen_state.chapter_no, gen_state.stage)

    gen_state.task = asyncio.create_task(_run(), name=f"gen-ch{gen_state.chapter_no}")
    return {"started": True, "chapter_no": gen_state.chapter_no,
            "started_at": gen_state.started_at}


@router.get("/api/project/generation-status")
def generation_status():
    """前端轮询 / 切回时查。返回完整状态快照。"""
    snap = gen_state.snapshot()
    # 若已结束且 result 被消费过（finished 但前端已 review），可加 consumed 标记
    return snap


@router.post("/api/project/generate/await")
async def generate_await():
    """等当前后台生成完成并返回结果（前端长轮询备选）。无在跑任务 → 409。"""
    if not gen_state.busy():
        # 已结束：直接返回 result/error
        if gen_state.finished:
            if gen_state.error:
                raise HTTPException(status_code=500, detail=gen_state.error)
            return gen_state.result
        raise HTTPException(status_code=409, detail="无进行中的生成")
    try:
        return await gen_state.task
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------- WebSocket 进度推送（P1-1: 替代轮询，实时显示生成步骤） ----------
@router.websocket("/api/project/generate/stream")
async def generate_stream(ws: WebSocket):
    """WebSocket 推送生成进度：前端连上后，实时收到 progress/complete/error 帧。

    前端流程：POST /generate/async 启动 → 连本 WS → 收到进度帧 → complete 收尾。
    无在跑任务时推送当前 snapshot 后关闭。
    """
    import asyncio as _aio
    await ws.accept()
    try:
        sent_count = 0  # 已推送的 log_entries 数量
        while True:
            snap = gen_state.snapshot()
            # 推送新日志条目
            logs = snap.get("log_entries") or []
            if len(logs) > sent_count:
                for entry in logs[sent_count:]:
                    await ws.send_json({"type": "progress", **entry})
                sent_count = len(logs)
            # 推送 stage 变化
            await ws.send_json({"type": "status", "stage": snap.get("stage"),
                                "detail": snap.get("stage_detail"),
                                "busy": snap.get("busy")})
            # 完成或失败
            if snap.get("finished"):
                if snap.get("error"):
                    await ws.send_json({"type": "error", "msg": snap["error"]})
                else:
                    await ws.send_json({"type": "complete", "result": snap.get("result")})
                break
            if not snap.get("busy") and not snap.get("finished"):
                # 无在跑任务（可能用户没先调 async，或后端重启丢任务）
                await ws.send_json({"type": "idle", "snapshot": snap})
                break
            await _aio.sleep(2)  # 2 秒推一次（WS 不需要像轮询那样频繁）
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.exception("generate_stream WS 异常")
        try:
            await ws.send_json({"type": "error", "msg": str(e)})
            await ws.close()
        except Exception:
            pass


# ---------- two-phase generation ----------
@router.post("/api/project/plan")
def plan():
    return deps.engine.plan_chapter()


@router.delete("/api/project/plan")
def discard_plan():
    deps.engine.discard_plan()
    return {"ok": True, "pending_plan": None}


# ---------- rollback / reset ----------
@router.post("/api/project/rollback")
def rollback(req: RollbackReq):
    # 生成中禁止回滚：改变世界状态，与后台生成并发会破坏事件溯源一致性
    if gen_state.busy():
        raise HTTPException(status_code=409, detail="生成进行中，请等待完成后回滚")
    if req.tick < 0 or req.tick > deps.engine.kernel.query_world("head_tick"):
        raise HTTPException(status_code=400, detail="非法 tick")
    return deps.engine.rollback(req.tick)


@router.post("/api/project/reset")
def reset():
    # 生成中禁止 reset：会清空世界状态，与后台生成并发会破坏一致性
    if gen_state.busy():
        raise HTTPException(status_code=409, detail="生成进行中，请等待完成后重置")
    return deps.engine.reset()


@router.post("/api/project/init")
def project_init(body: dict):
    # 生成中禁止重建 engine：与后台生成持有的 engine_snapshot 冲突
    if gen_state.busy():
        raise HTTPException(status_code=409, detail="生成进行中，请等待完成后初始化")
    from story_engine.engine import StoryEngine
    from story_engine.types import StoryEngineError
    genre = body.get("genre") or os.environ.get("STORY_ENGINE_GENRE", "mystery")
    culture = body.get("culture") or os.environ.get(
        "STORY_ENGINE_CULTURE", "confucian_officialdom")
    try:
        deps.engine.kernel.registry.validate_combo(genre, culture)
    except StoryEngineError as e:
        raise HTTPException(status_code=422, detail=str(e))
    deps.engine.reset()
    deps.engine = StoryEngine(deps.engine.kernel, genre_name=genre,
                              culture_name=culture)
    deps.stack["engine"] = deps.engine
    deps.engine.discard_plan()
    return {"ok": True, "project": {"genre": genre, "culture": culture}}


# ---------- characters ----------
@router.get("/api/characters")
def characters():
    return deps.engine.characters_view()


# ---------- paragraph rewrite ----------
@router.post("/api/paragraph/rewrite")
async def paragraph_rewrite(req: ParagraphRewriteReq):
    result = await deps.engine.rewrite_paragraph(
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


# ---------- meta config ----------
@router.post("/api/meta/config")
async def meta_config(req: UserIntentReq):
    from story_engine.meta import UserIntent
    from story_engine.types import StoryEngineError
    try:
        intent = UserIntent(
            theme=req.theme, culture_hint=req.culture_hint,
            language=req.language, target_length=req.target_length,
            platform=req.platform,
        )
        cfg = await deps.meta_gen.generate_config(intent)
        return cfg.to_dict()
    except StoryEngineError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------- training stats ----------
def training_stats_snapshot(registry, training_dir: Path) -> dict:
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


@router.get("/api/training/stats")
def training_stats():
    return training_stats_snapshot(
        deps.kernel.registry, deps.training_pipeline.training_dir)
