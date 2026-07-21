"""Story Engine Demo — FastAPI 后端

API：
  GET  /api/project            项目完整快照（世界状态/事件/伏笔/章节/决策卡/pending_plan）
  GET  /api/projects           【P10.1 新增】项目列表（扫描 data/projects/*；老项目补写 project.json）
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
  POST /api/projects/open      【P10.2 新增】切换当前项目（整栈重建+全量重绑；不存在 → 404；写 last_opened_at）
  POST /api/gacha/draw         【P8.3/P8.4】抽卡开局：library 随机组合 + lock 锁栏；synth LLM 合成（mock 短路降级）
  POST /api/gacha/confirm      【P8.5】抽卡确认：synth 卡复核+落盘 plugins/genres/（原子写、重名后缀）→ reload → init
                               【P10.2】body 可选 project_name：建新项目目录（已存在 → 409）→ 整栈切换 → init
  POST /api/project/init       【P8.5】开局切换：重置世界 → 按 genre/culture 重建 engine 单例（进程内覆盖，不改 env/.env）
静态：/ → frontend/dist（Vue SPA）
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.background import BackgroundTask
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
from story_engine.meta.gacha import draw_card_async  # noqa: E402
from story_engine.meta.genre_validator import validate_genre_pack  # noqa: E402
from story_engine.types import StoryEngineError  # noqa: E402

logger = logging.getLogger(__name__)


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
# P10.1：五件套的构造收敛为 _build_stack 工厂（启动路径行为不变），模块级
# 变量是栈内成员的别名（最小改动面：既有端点零改动）；P10.2 项目切换时整栈
# 重建并重绑别名即可。
def _make_regenerate_sync(stack: dict):
    """regenerate_fn 闭包工厂（P10.1）：经 stack["engine"] 延迟解析当前
    engine——project_init 会重绑栈内 engine，必须调用时取新引用而非构造时
    绑死（与旧 _regenerate_sync 读模块全局的行为等价）。

    InterventionRouter.regenerate_fn 约定：无参同步 callable（P5.8）；
    engine.regenerate_current_chapter 是 async → 最小适配（P5.10 评审传导2）：
    asyncio.run 包一层。安全性：本函数只经 run_in_threadpool 在工作线程调用
    （无线程内运行中的事件循环），故 asyncio.run 合法；EventStore 为
    check_same_thread=False + 锁，跨线程 commit 安全；LLMPool 每次调用
    自建 httpx.AsyncClient，不绑定特定事件循环。"""
    def _regenerate_sync() -> None:
        asyncio.run(stack["engine"].regenerate_current_chapter())
    return _regenerate_sync


def _make_textual_apply(stack: dict):
    """textual_apply_fn 闭包工厂（P10.2）：与 regenerate 同款经 stack["engine"]
    延迟解析——project_init 会重绑栈内 engine，构造时绑死 update_chapter_text
    会留旧 engine 引用（P10.1 遗留的 stale binding，本任务一并解决）。
    签名同 engine.update_chapter_text（InterventionRouter.textual_apply_fn
    约定：P6.1 B1 正文回写口子）。"""
    def _textual_apply(chapter: int, before, after) -> str:
        return stack["engine"].update_chapter_text(chapter, before, after)
    return _textual_apply


def _build_stack(project_dir: Path, genre_name: str | None = None,
                 culture_name: str | None = None) -> dict:
    """P10.1 项目栈工厂：kernel/engine/meta_gen/pipeline/router 一处构造。

    传 initial_state_factory（静态方法可直接引用）：否则创世种子要靠
    engine.reset() 重建 store 才能顺带注入（P9.x 原位清库后该掩蔽效应消失，
    必须显式传）。挂载点决策（P5.10 任务卡）：engine 侧无 router/pipeline
    实例，参照 meta_gen 同款模式在 backend 侧构造。router 的 regenerate_fn /
    textual_apply_fn 均经 stack 延迟解析 engine（P10.2），切换/init 不留旧引用。
    genre_name/culture_name（P10.2 评审修复，可选只增）：显式指定题材/文化
    建 engine（projects/open 恢复项目自身题材）；缺省 None 回落 env/内置默认，
    与 StoryEngine 构造口径一致，启动路径行为不变。"""
    kernel = Kernel(project_dir, plugin_dir=ROOT / "story_engine" / "plugins",
                    initial_state_factory=StoryEngine._genesis_state)
    engine = StoryEngine(kernel, genre_name=genre_name,
                         culture_name=culture_name)
    meta_gen = MetaGenerator(kernel)
    pipeline = TrainingPipeline(kernel, project_dir)
    stack = {"kernel": kernel, "engine": engine, "meta_gen": meta_gen,
             "pipeline": pipeline}
    stack["router"] = InterventionRouter(
        kernel, pipeline=pipeline, regenerate_fn=_make_regenerate_sync(stack),
        textual_apply_fn=_make_textual_apply(stack))
    return stack


_stack = _build_stack(Path(PROJECT_DIR))
kernel = _stack["kernel"]
llm_client = kernel.llm  # 保留 llm_client 变量名，老 API 引用兼容
engine = _stack["engine"]
meta_gen = _stack["meta_gen"]
training_pipeline = _stack["pipeline"]
intervention_router = _stack["router"]


def _switch_to(project_dir: Path, genre_name: str | None = None,
               culture_name: str | None = None) -> dict:
    """P10.2 项目切换核心：旧 kernel 尽力 close → _build_stack 整栈重建 →
    重绑全部模块级引用，不留旧栈引用。

    重绑清单：kernel / llm_client / engine / meta_gen / training_pipeline /
    intervention_router / _stack。各端点在函数体内运行时解析模块全局名，
    重绑后全部端点自动用新栈；router 的 regenerate/textual 两闭包经
    _stack 延迟解析 engine，project_init 重绑 _stack["engine"] 后依旧相干。
    旧 kernel.close() 失败只 log 不阻断（尽力释放 SQLite 句柄，Windows 文件锁
    场景下残留句柄不应卡死切换）。genre_name/culture_name（P10.2 评审修复，
    可选只增）透传 _build_stack：open 恢复项目自身题材；缺省 None 回落
    env/内置默认（gacha confirm 新建项目随后走 init 覆盖，行为不变）。"""
    global _stack, kernel, llm_client, engine, meta_gen
    global training_pipeline, intervention_router
    try:
        kernel.close()
    except Exception:
        logger.warning("项目切换：旧 kernel close 失败（尽力继续）",
                       exc_info=True)
    _stack = _build_stack(Path(project_dir), genre_name=genre_name,
                          culture_name=culture_name)
    kernel = _stack["kernel"]
    llm_client = kernel.llm
    engine = _stack["engine"]
    meta_gen = _stack["meta_gen"]
    training_pipeline = _stack["pipeline"]
    intervention_router = _stack["router"]
    return _stack


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


class GachaDrawReq(BaseModel):
    """抽卡 body（P8.3 library / P8.4 synth）：mode=library|synth；
    lock 锁定任意栏（genre/culture/archetype 为名称 str，rule_packs 为名称
    str 或 list；键缺省/值为 None 视为未锁定，宽容处理见 meta.gacha）。"""
    mode: Literal["library", "synth"] = "library"
    lock: dict[str, Any] | None = None


class TestLlmReq(BaseModel):
    """P6.10 B10：LLM 测试连接 body；只接受可选 model 覆盖。
    base_url/key 永不取自前端（防 SSRF + 系统密钥外泄）——始终用当前
    engine.llm 配置。key 永不回前端（响应只 ok+latency+model+error）。"""
    model: str | None = None


@app.get("/api/config")
def config():
    return {
        "llm_mode": "mock" if llm_client.is_mock else "openai",
        "llm_model": llm_client.model,
        "base_url": llm_client.base_url if not llm_client.is_mock else None,
        "plugins": engine.registry.list_plugins(),
        # P9.1 显示名中文化：{id: 中文 title} 合并表，纯展示层叠加（只增不改）
        "display_names": engine.kernel.registry.display_map(),
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


# ---------- 多项目管理（P10.1：project.json 元数据 + 项目列表） ----------
PROJECTS_ROOT = ROOT / "data" / "projects"
PROJECT_META_NAME = "project.json"


def _read_project_meta(project_dir: Path) -> dict | None:
    """读 project.json；缺失/损坏/非 JSON 对象 → None（调用方按需补写）。"""
    try:
        meta = json.loads(
            (Path(project_dir) / PROJECT_META_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return meta if isinstance(meta, dict) else None


def _write_project_meta(project_dir: Path, **fields) -> dict:
    """合并写 project.json（在既有元数据上更新给定字段），返回写后全文。
    字段口径（P10.1）：name/genre/culture/created_at/last_opened_at；
    gacha confirm 新项目与 projects/open 的写入 P10.2 接入。
    P10.2 顺手升级原子写：同目录 .tmp + replace（P10.1 Minor）——
    要么不写、要么写全，不留半写 JSON。"""
    meta = _read_project_meta(project_dir) or {}
    meta.update(fields)
    path = Path(project_dir) / PROJECT_META_NAME
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    return meta


def _count_active_chapters(project_dir: Path) -> int:
    """chapters.json 中非 superseded 条数；文件缺失/损坏/非数组 → 0（不崩）。"""
    try:
        chapters = json.loads(
            (Path(project_dir) / "chapters.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    if not isinstance(chapters, list):
        return 0
    return sum(1 for c in chapters
               if isinstance(c, dict) and not c.get("superseded"))


def _read_head_tick(project_dir: Path) -> int:
    """sqlite 只读连接取 heads 表 main 分支 head_tick（用完即关）；
    库打不开/无表/无行 → 0（不崩）。"""
    db_path = Path(project_dir) / "story.db"
    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT head_tick FROM heads WHERE branch_id = 'main'").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return 0
    return int(row[0]) if row else 0


def _list_projects(root: Path) -> list[dict]:
    """扫描 root 下项目目录（只认含 story.db 者），按目录名排序汇总列表项。

    缺 project.json 的老项目迁移：genre/culture 用当前 engine（当前项目）或
    env/内置默认（其余项目）推断并写回——本任务唯一的补写点。"""
    items = []
    if not Path(root).is_dir():
        return items
    current_name = Path(engine.project_dir).name
    for d in sorted(Path(root).iterdir()):
        if not d.is_dir() or not (d / "story.db").exists():
            continue
        meta = _read_project_meta(d)
        if meta is None:
            if d.name == current_name:
                genre, culture = engine.genre.name, engine.culture.name
            else:
                genre = os.environ.get("STORY_ENGINE_GENRE", "mystery")
                culture = os.environ.get("STORY_ENGINE_CULTURE",
                                         "confucian_officialdom")
            now = datetime.now().isoformat(timespec="seconds")
            meta = _write_project_meta(
                d, name=d.name, genre=genre, culture=culture,
                created_at=now, last_opened_at=now)
        items.append({
            "name": d.name,
            "genre": meta.get("genre"),
            "culture": meta.get("culture"),
            "chapter_count": _count_active_chapters(d),
            "head_tick": _read_head_tick(d),
            "last_opened_at": meta.get("last_opened_at"),
            "current": d.name == current_name,
        })
    return items


@app.get("/api/projects")
def list_projects():
    """【P10.1】项目列表：扫描 data/projects/* → [{name, genre, culture,
    chapter_count, head_tick, last_opened_at, current}]。
    坏目录不崩：无 story.db 跳过；坏 chapters.json/打不开 story.db → 计数 0。"""
    return _list_projects(PROJECTS_ROOT)


class ProjectOpenReq(BaseModel):
    name: str


@app.post("/api/projects/open")
def open_project(req: ProjectOpenReq):
    """【P10.2】切换当前项目到 data/projects/<name>：整栈重建 + 全量重绑。

    name 先过白名单（复用题材名正则，拒绝路径分隔符/穿越 → 一律 404，
    不区分「非法名」与「不存在」，不泄露目录结构）；story.db 缺失 → 404。
    切换后写 last_opened_at（原子合并写），返回 {ok, project: 快照 meta}。
    genre/culture（P10.2 评审修复）：读项目自身 project.json 恢复其题材/文化
    建新栈（缺 project.json 或缺键 → 回落 env/内置默认）——切回旧项目后继续
    生成必须用它的题材，不是 env 默认。组合合法性切换前预校验（当前 registry
    与新栈同源扫 plugins 目录，口径同 gacha confirm）：非法 → 422 且不切换，
    当前项目原样保留。不复用 project_init：其语义含 reset 清世界，会抹掉被
    恢复项目的全部数据。"""
    if not GENRE_NAME_RE.fullmatch(req.name):
        raise HTTPException(status_code=404, detail=f"项目不存在：{req.name}")
    project_dir = PROJECTS_ROOT / req.name
    if not (project_dir / "story.db").exists():
        raise HTTPException(status_code=404, detail=f"项目不存在：{req.name}")
    meta = _read_project_meta(project_dir) or {}
    genre = meta.get("genre") or os.environ.get("STORY_ENGINE_GENRE", "mystery")
    culture = meta.get("culture") or os.environ.get(
        "STORY_ENGINE_CULTURE", "confucian_officialdom")
    try:
        engine.kernel.registry.validate_combo(genre, culture)
    except StoryEngineError as e:
        raise HTTPException(status_code=422, detail=str(e))
    _switch_to(project_dir, genre_name=genre, culture_name=culture)
    _write_project_meta(
        project_dir, name=req.name,
        last_opened_at=datetime.now().isoformat(timespec="seconds"))
    return {"ok": True, "project": engine.project_snapshot()["meta"]}


# ---------- 项目导出（P10.3：一致快照 zip 分发） ----------
def _build_project_zip(project_dir: Path, name: str, work_dir: Path) -> Path:
    """在 work_dir 组装 <name>-story.zip，返回 zip 路径（调用方负责清理 work_dir）。

    一致性：story.db 经 sqlite3 backup API 落到 work_dir 再打包——WAL 模式下
    直拷主文件可能丢 wal 中未 checkpoint 的提交，backup 拿到的是完整一致快照
    （story.db-wal/shm 无需单独打）。源连接按普通读写打开：真只读（mode=ro）
    打开残留 wal 的非当前项目库可能因需 recovery 而失败（SQLITE_CANTOPEN）。
    附带文件：chapters.json/project.json 有则打、无则跳过不崩；
    training_data/ 有则整目录打（保持相对路径）；README.txt 一行解压说明。"""
    backup_db = Path(work_dir) / "story.db"
    src = sqlite3.connect(str(Path(project_dir) / "story.db"))
    try:
        dst = sqlite3.connect(str(backup_db))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    zip_path = Path(work_dir) / f"{name}-story.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(backup_db, "story.db")
        for extra in ("chapters.json", "project.json"):
            p = Path(project_dir) / extra
            if p.is_file():
                zf.write(p, extra)
        training = Path(project_dir) / "training_data"
        if training.is_dir():
            for f in sorted(training.rglob("*")):
                if f.is_file():
                    zf.write(f, "training_data/"
                             f"{f.relative_to(training).as_posix()}")
        zf.writestr("README.txt",
                    f"解压到 data/projects/{name}/ 即可；story.db 为 sqlite "
                    "backup 一致快照（无需 wal/shm）。")
    return zip_path


@app.get("/api/projects/{name}/export")
def export_project(name: str):
    """【P10.3】导出项目为 {name}-story.zip（FileResponse，application/zip）。

    name 过白名单正则（同 projects/open：非法名与不存在一律 404，不泄露目录
    结构）；story.db 缺失 → 404。zip 在临时目录组装，BackgroundTask 在响应
    发送后整目录清理；组装失败则 except 中立即清理再抛。"""
    if not GENRE_NAME_RE.fullmatch(name):
        raise HTTPException(status_code=404, detail=f"项目不存在：{name}")
    project_dir = PROJECTS_ROOT / name
    if not (project_dir / "story.db").exists():
        raise HTTPException(status_code=404, detail=f"项目不存在：{name}")
    work_dir = Path(tempfile.mkdtemp(prefix="story_export_"))
    try:
        zip_path = _build_project_zip(project_dir, name, work_dir)
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise
    return FileResponse(
        zip_path, filename=f"{name}-story.zip", media_type="application/zip",
        background=BackgroundTask(shutil.rmtree, work_dir,
                                  ignore_errors=True))


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


# ---------- 抽卡开局（P8.3 library / P8.4 synth，独立开局页：题材×文化×原型×规则） ----------
@app.post("/api/gacha/draw")
async def gacha_draw(req: GachaDrawReq):
    """【P8.3/P8.4】抽一张开局卡。library 纯 registry 读取，零 LLM；
    synth 注入 kernel.llm.call 走 LLM 合成 + 校验 + 重试 + 降级——
    mock 短路在 meta.gacha 内部、LLM 调用之前（is_mock 判据），
    mock 部署下恒降级 library 卡，本端点不做真实 LLM 调用。"""
    try:
        return await draw_card_async(engine.kernel, engine.kernel.llm.call,
                                     req.mode, req.lock)
    except StoryEngineError as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------- 抽卡确认 + 开局切换（P8.5：落盘 → reload → engine 单例重建） ----------
# 题材名白名单：落盘文件名直接由它构成，拒绝对路径/穿越字符（防路径逃逸）
GENRE_NAME_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}")


def _persist_genre_pack(pack: dict) -> str:
    """合成 genre 包落盘到 plugins/genres/，返回最终题材名。

    - 重名冲突：自动追加 -2/-3… 后缀（pack["name"] 同步改写，卡名与文件名一致）
    - activation_events 对齐最终名（库内约定 on_genre:<name>）
    - 原子写：先写同目录 .tmp 再 rename——最终路径要么不存在、要么完整，
      不会留半写文件（同目录保证同文件系统，rename 才原子）；写失败清 tmp
    """
    genres_dir = ROOT / "story_engine" / "plugins" / "genres"
    base = str(pack["name"])
    name, i = base, 2
    while (genres_dir / f"{name}.yaml").exists():
        name = f"{base}-{i}"
        i += 1
    pack["name"] = name
    pack["activation_events"] = [f"on_genre:{name}"]
    path = genres_dir / f"{name}.yaml"
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(yaml.safe_dump(pack, allow_unicode=True),
                       encoding="utf-8")
        tmp.rename(path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    return name


@app.post("/api/gacha/confirm")
def gacha_confirm(card: dict):
    """【P8.5】确认抽卡：synth 卡复核 + 落盘 + registry 重扫，然后统一走 init 切换。

    synth 卡不信任前端携带的校验结论：confirm 时先复核 manifest 层
    （name 非空字符串、extension_point 必为 story.genre —— 坏包落盘会让
    registry 加载路径 KeyError，卡死本次 reload 及之后每次重启），再 rerun
    validate_genre_pack 复核 params 子树；culture_bound 包另须卡文化命中
    allowed_cultures（口径同 registry.validate_combo），否则落盘即注册、
    init 却 422 的不一致态。任一项不过 → 422 且不落盘不切换；过了才落盘
    （重名自动后缀，原子写）并 registry.reload() 让新题材立即可用。
    library 卡跳过落盘（persisted=false）直接 init。
    响应 = init 响应 + {persisted, genre(最终名)}。

    【P10.2】body 可选 project_name（卡对象平铺的额外键，不给则现状语义）：
    给了则开新项目——白名单校验（复用题材名正则）→ 目标目录已含 story.db
    → 409「项目已存在」（在 synth 落盘之前检查，失败零副作用）；否则
    _switch_to 整栈切换到新目录（Kernel 构造自建目录/库）→ init 应用卡的
    genre/culture → 写 project.json（name/genre/culture/created_at/
    last_opened_at）→ 响应 project 键扩为 {name, genre, culture}。
    组合合法性在切换前用当前 registry 预校验（插件同源），避免切完才 422
    的半切换态。synth 落盘逻辑不变，与项目切换正交。
    """
    project_name = card.get("project_name")
    if project_name is not None:
        if not isinstance(project_name, str) \
                or not GENRE_NAME_RE.fullmatch(project_name):
            raise HTTPException(
                status_code=422,
                detail=f"项目名非法：{project_name!r}（仅限字母/数字/-/_，1-64 位）")
        if (PROJECTS_ROOT / project_name / "story.db").exists():
            raise HTTPException(status_code=409,
                                detail=f"项目已存在：{project_name}")
    g = card.get("genre") or {}
    persisted = False
    name = g.get("name")
    culture = (card.get("culture") or {}).get("name") or "confucian_officialdom"
    if g.get("source") == "synth":
        pack = g.get("yaml")
        if not isinstance(pack, dict) \
                or not isinstance(pack.get("name"), str) \
                or not pack["name"].strip():
            raise HTTPException(status_code=422,
                                detail="合成卡缺 genre.yaml 或 name 键（非空字符串）")
        if pack.get("extension_point") != "story.genre":
            raise HTTPException(
                status_code=422,
                detail=f"合成包 extension_point 须为 story.genre"
                       f"（当前：{pack.get('extension_point')!r}）")
        if not GENRE_NAME_RE.fullmatch(pack["name"]):
            raise HTTPException(
                status_code=422,
                detail=f"题材名非法：{pack['name']}（仅限字母/数字/-/_）")
        errs = validate_genre_pack(pack)
        if errs:
            raise HTTPException(status_code=422,
                                detail=f"合成包未过校验：{'；'.join(errs)}")
        allowed = pack.get("allowed_cultures") or ["*"]
        if pack.get("culture_bound") and "*" not in allowed \
                and culture not in allowed:
            raise HTTPException(
                status_code=422,
                detail=f"题材 {pack['name']} 为 culture_bound，仅允许 "
                       f"{allowed}，与卡文化 {culture} 不匹配")
        name = _persist_genre_pack(pack)
        engine.kernel.registry.reload()
        persisted = True
    if not name:
        raise HTTPException(status_code=422, detail="卡缺 genre.name")
    if project_name is not None:
        # 开新项目：组合合法性预校验（当前 registry 与新栈同源扫 plugins 目录，
        # synth 包已落盘，两边都可见）→ 整栈切换 → init 应用卡题材/文化。
        try:
            engine.kernel.registry.validate_combo(name, culture)
        except StoryEngineError as e:
            raise HTTPException(status_code=422, detail=str(e))
        project_dir = PROJECTS_ROOT / project_name
        _switch_to(project_dir)
        resp = project_init({"genre": name, "culture": culture})
        now = datetime.now().isoformat(timespec="seconds")
        _write_project_meta(project_dir, name=project_name, genre=name,
                            culture=culture, created_at=now,
                            last_opened_at=now)
        return {**resp, "persisted": persisted, "genre": name,
                "project": {"name": project_name, "genre": name,
                            "culture": culture}}
    return {**project_init({"genre": name, "culture": culture}),
            "persisted": persisted, "genre": name}


@app.post("/api/project/init")
def project_init(body: dict):
    """【P8.5】开局切换：按 genre/culture 重建 engine 单例（进程内覆盖）。

    语义决策：init = 开新局 —— 先调现有 engine.reset() 清世界状态/章节/
    pending_plan，再在同一 Kernel 上重建 StoryEngine（genre/culture 子系统
    随之重绑）。选「reset + 同 kernel 重建」而非「新建 Kernel」：模块级
    kernel/llm_client/meta_gen/training_pipeline/intervention_router 单例
    持有同一 Kernel 对象，全部保持相干，且复用已测的 reset 清库路径。
    不改 STORY_ENGINE_GENRE/CULTURE env、不写 .env（重启回落 env/默认）。
    组合合法性先校验再清库：非法 genre/culture → 422，项目原样保留。
    genre/culture 缺省回落 env/内置默认（与 engine 构造口径一致）。
    """
    global engine
    genre = body.get("genre") or os.environ.get("STORY_ENGINE_GENRE", "mystery")
    culture = body.get("culture") or os.environ.get(
        "STORY_ENGINE_CULTURE", "confucian_officialdom")
    try:
        engine.kernel.registry.validate_combo(genre, culture)
    except StoryEngineError as e:
        raise HTTPException(status_code=422, detail=str(e))
    engine.reset()
    engine = StoryEngine(engine.kernel, genre_name=genre, culture_name=culture)
    _stack["engine"] = engine  # P10.1：栈内引用同步（regenerate_fn 经栈延迟解析）
    engine.discard_plan()  # 契约：init 后 pending_plan 必空（新实例本即 None，显式兜底）
    return {"ok": True, "project": {"genre": genre, "culture": culture}}


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
    始终用 engine.llm 的 base_url/api_key（不接受前端传入——防 SSRF + 密钥外泄）。
    响应只 {ok, latency_ms, model, error?} —— key 永不回前端。"""
    import time as _time
    import httpx
    src = req or TestLlmReq()
    client = engine.llm
    base_url = client.base_url.rstrip("/")
    model = src.model or client.model
    key = client.api_key
    # mock 模式：直接 ok（不构造 client）
    if client.is_mock:
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
        # 只用 reason_phrase（无 body）：上游 LLM 错误响应可能回显请求头/body，
        # 其中可能含 Authorization Bearer 或 api_key，绝不引入前端。
        return {"ok": False,
                "error": f"HTTP {r.status_code} {r.reason_phrase}",
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
