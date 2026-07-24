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
  GET  /api/projects/{name}/export  【P10.3 新增】导出项目 zip（sqlite backup 一致快照 + chapters/project.json + training_data）
  POST /api/projects/import    【P10.6 新增】导入项目 zip（arcname 防穿越/炸弹粗防/名校验；重名 → 409）
  POST /api/gacha/draw         【P8.3/P8.4】抽卡开局：library 随机组合 + lock 锁栏；synth LLM 合成（mock 短路降级）
  POST /api/gacha/confirm      【P8.5】抽卡确认：synth 卡复核+落盘 plugins/genres/（原子写、重名后缀）→ reload → init
                               【P10.2】body 可选 project_name：建新项目目录（已存在 → 409）→ 整栈切换 → init
  GET  /api/macro/templates    【P17.3 新增】7 个幕结构模板列表（name + description + beat_count）
  POST /api/macro/plan         【P17.3 新增】生成宏观计划（AI/mock 兜底）→ MacroPlan dict
  GET  /api/macro/plan         【P17.3 新增】读取当前项目 macro_plan.json（无 → 404）
  POST /api/project/init       【P8.5】开局切换：重置世界 → 按 genre/culture 重建 engine 单例（进程内覆盖，不改 env/.env）
静态：/ → frontend/dist（Vue SPA）
"""
from __future__ import annotations

import asyncio
import io
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
from uuid import uuid4

import yaml
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
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
from story_engine.kernel.registry import EXTENSION_POINTS  # noqa: E402
from story_engine.llm import LLMError  # noqa: E402
from story_engine.logging_config import setup_logging  # noqa: E402
from story_engine.meta import MetaGenerator, UserIntent  # noqa: E402
from story_engine.meta.gacha import draw_card_async, derive_culture  # noqa: E402
from story_engine.meta.genre_taxonomy import (  # noqa: E402
    TAG_ZH, all_taxa, culture_for_genre, list_taxa, macro_templates_for_genre,
    presets_for_genre, taxon_by_id, taxonomy_stats)
from story_engine.macro import (  # noqa: E402
    TEMPLATES as MACRO_TEMPLATES, compute_acts as macro_compute_acts,
    generate_macro_plan, macro_plan_to_dict, check_cross_layer)
from story_engine.types import StoryEngineError  # noqa: E402
from story_engine.worldview import (  # noqa: E402
    ALL_PARAMS as WV_ALL_PARAMS, LAYERS as WV_LAYERS,
    LANGUAGE_LAYERS as WV_LANGUAGE_LAYERS,
    CHARACTER_LAYERS as WV_CHARACTER_LAYERS,
    WorldviewProfile, evaluate as wv_evaluate,
    param_values as wv_param_values,
    preset_summaries as wv_preset_summaries,
    derive_cast as wv_derive_cast,
)

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

# Phase 16：loguru 日志系统初始化（在 app 创建前）
setup_logging()

PROJECT_DIR = os.environ.get("STORY_ENGINE_PROJECT_DIR",
                             str(ROOT / "data" / "projects" / "yupei"))
FRONTEND_DIST = Path(os.environ.get("STORY_ENGINE_FRONTEND_DIST",
                                    str(ROOT / "frontend" / "dist")))

app = FastAPI(title="Story Engine", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


# ---------- P23：全局错误中文化 ----------
_422_FIELD_ZH = {
    "genre_name": "题材名", "project_name": "项目名", "template_name": "幕结构模板",
    "chapter": "章节号", "para_index": "段落号", "direction": "改写方向",
    "worldview": "世界观", "cast": "人物阵容", "tick": "tick",
    "content": "内容", "text": "文本", "macro_plan": "宏观计划",
    "base_url": "LLM 地址", "api_key": "API key", "model": "模型",
}


@app.exception_handler(RequestValidationError)
async def _validation_exc_handler(request, exc: RequestValidationError):
    """Pydantic 422 → 中文字段提示（未映射字段保留原名）。"""
    details = []
    for err in exc.errors()[:5]:
        loc = [str(x) for x in err.get("loc", []) if x not in ("body", "query")]
        field = _422_FIELD_ZH.get(loc[-1], loc[-1]) if loc else "请求体"
        msg = err.get("msg", "")
        if "Field required" in msg:
            msg = "必填"
        details.append(f"{field}：{msg}")
    return JSONResponse(
        status_code=422,
        content={"detail": "；".join(details) or "请求参数不合法"})


@app.exception_handler(Exception)
async def _unhandled_exc_handler(request, exc: Exception):
    """未捕获异常 → 日志记 traceback，前端只收中文兜底（不再漏英文原文）。"""
    logger.exception("未捕获异常 | %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误，已记录日志（logs/story_engine.log）"})

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


def _make_lazy_genesis(stack: dict):
    """P11.1 延迟解析创世工厂（backend bundle-timing 问题的解法）：
    Kernel 必须先于 StoryEngine 构造，而题材 bundle 在 engine 内 —— 工厂
    闭包在「被调用时」经 stack["engine"] 取当前 engine 的定型创世工厂。
    EventStore 懒求值（空库首次 current_state 才调用，event_store.py:139），
    且 engine 构造末尾已把 store 工厂重指为自身题材工厂，本闭包实际只覆盖
    engine 建成前的理论窗口；两层双保险，任先生效都正确。engine 为 None
    （理论窗口）时回退 mystery 静态法，与旧行为逐字一致。"""
    def _factory():
        engine = stack.get("engine")
        if engine is None:
            return StoryEngine._genesis_state()
        return engine._genesis_factory()()
    return _factory


def _build_stack(project_dir: Path, genre_name: str | None = None,
                 culture_name: str | None = None) -> dict:
    """P10.1 项目栈工厂：kernel/engine/meta_gen/pipeline/router 一处构造。

    传 initial_state_factory（P11.1 起为延迟解析闭包）：否则创世种子要靠
    engine.reset() 重建 store 才能顺带注入（P9.x 原位清库后该掩蔽效应消失，
    必须显式传）。挂载点决策（P5.10 任务卡）：engine 侧无 router/pipeline
    实例，参照 meta_gen 同款模式在 backend 侧构造。router 的 regenerate_fn /
    textual_apply_fn 均经 stack 延迟解析 engine（P10.2），切换/init 不留旧引用。
    genre_name/culture_name（P10.2 评审修复，可选只增）：显式指定题材/文化
    建 engine（projects/open 恢复项目自身题材）；缺省 None 回落 env/内置默认，
    与 StoryEngine 构造口径一致，启动路径行为不变。"""
    stack: dict = {}
    kernel = Kernel(project_dir, plugin_dir=ROOT / "story_engine" / "plugins",
                    initial_state_factory=_make_lazy_genesis(stack))
    engine = StoryEngine(kernel, genre_name=genre_name,
                         culture_name=culture_name)
    meta_gen = MetaGenerator(kernel)
    pipeline = TrainingPipeline(kernel, project_dir)
    stack.update({"kernel": kernel, "engine": engine, "meta_gen": meta_gen,
                  "pipeline": pipeline})
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
    # 先建后关（终审 fast-follow）：新栈建好前不关旧 kernel——若 _build_stack
    # 抛异常（如题材包构造期缺陷），全局仍指向完好的旧栈，不会降级
    new_stack = _build_stack(Path(project_dir), genre_name=genre_name,
                             culture_name=culture_name)
    old_kernel = kernel
    # P19.2：保留旧引擎的 runtime_overrides（项目切换后恢复到新引擎）
    old_engine_runtime = getattr(engine, "_runtime_overrides", {})
    try:
        old_kernel.close()
    except Exception:
        logger.warning("项目切换：旧 kernel close 失败（尽力继续）",
                       exc_info=True)
    _stack = new_stack
    kernel = _stack["kernel"]
    llm_client = kernel.llm
    engine = _stack["engine"]
    # P19.2：保留旧引擎的 runtime_overrides（settings 端点写的进程内覆盖），
    # 否则项目切换后 eval_enabled/ir_first 等设置丢失（测试2 evaluation=None 根因）
    try:
        engine._runtime_overrides = dict(old_engine_runtime)
    except Exception:
        pass
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


class TestLlmReq(BaseModel):
    """LLM 测试连接 body。P23 起可选 base_url/api_key：给了就用该临时配置
    实测（不写入引擎，适配在线配置「先测后存」）；不给则测当前 engine.llm
    配置。key 永不回前端（响应只 ok+latency+model+error）。"""
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None


class LlmSettingsReq(BaseModel):
    """P23：LLM 接入在线配置 body；三键全可选（空/None=保持不变），
    persist=true 时把非空键写回 .env（重启后仍生效）。"""
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    persist: bool = False


def _persist_env(updates: dict) -> None:
    """把 KEY=VALUE 写回 story-engine/.env（保留注释与其他行；无 .env 则从
    .env.example 复制后改）。与 _load_dotenv 同口径：单行 KEY=VALUE，
    # 整行注释忽略。"""
    env_path = ROOT / ".env"
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    else:
        example = ROOT / ".env.example"
        lines = (example.read_text(encoding="utf-8").splitlines()
                 if example.exists() else [])
    remaining = dict(updates)
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k in remaining:
                out.append(f"{k}={remaining.pop(k)}")
                continue
        out.append(line)
    for k, v in remaining.items():
        out.append(f"{k}={v}")
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")


@app.get("/api/config")
def config():
    return {
        "llm_mode": "mock" if llm_client.is_mock else "openai",
        "llm_model": llm_client.model,
        "base_url": llm_client.base_url if not llm_client.is_mock else None,
        "plugins": engine.registry.list_plugins(),
        # P9.1 显示名中文化：{id: 中文 title} 合并表，纯展示层叠加（只增不改）
        "display_names": engine.kernel.registry.display_map(),
        # P23：扩展点 id → 中文标签（插件页分桶标题；registry EXTENSION_POINTS 同源）
        "extension_labels": dict(EXTENSION_POINTS),
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

# ---------- 项目名校验（P10.6：中文名放开，路径安全不退让） ----------
# 允许：中文/Unicode 字母与数字/空格/-/_（\w 即 Unicode L*/N* 加下划线），≤40 字符。
# 拒绝：空、首尾空白或点、路径分隔符（/ \）、..、控制字符、Windows 保留名。
# 只用于项目目录名；题材 id 仍是 GENRE_NAME_RE 的 slug 口径（见 gacha confirm），不动。
PROJECT_NAME_MAX_LEN = 40
PROJECT_NAME_RE = re.compile(r"[\w \-]+")
WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)})


def validate_project_name(name) -> bool:
    """项目目录名合法性。fail-closed：任何一环不过 → False（调用方定状态码）。"""
    if not isinstance(name, str) or not name or len(name) > PROJECT_NAME_MAX_LEN:
        return False
    if name != name.strip() or name.startswith(".") or name.endswith("."):
        return False
    if "/" in name or "\\" in name or ".." in name:
        return False
    if any(ord(c) < 32 or ord(c) == 127 for c in name):
        return False
    if name.split(".")[0].upper() in WINDOWS_RESERVED_NAMES:  # Windows 按点前基名判保留（CON.txt 亦拒）
        return False
    return PROJECT_NAME_RE.fullmatch(name) is not None


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


def _write_json_atomic(path: Path, data: dict) -> None:
    """原子写 JSON 到任意路径（同目录 .tmp + replace，与 _write_project_meta
    同口径）。P12.2 供 worldview.json 落盘复用：要么不写、要么写全。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


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

    name 先过 validate_project_name（P10.6 起支持中文名；拒绝路径分隔符/穿越
    → 一律 404，不区分「非法名」与「不存在」，不泄露目录结构）；story.db 缺失 → 404。
    切换后写 last_opened_at（原子合并写），返回 {ok, project: 快照 meta}。
    genre/culture（P10.2 评审修复）：读项目自身 project.json 恢复其题材/文化
    建新栈（缺 project.json 或缺键 → 回落 env/内置默认）——切回旧项目后继续
    生成必须用它的题材，不是 env 默认。组合合法性切换前预校验（当前 registry
    与新栈同源扫 plugins 目录，口径同 gacha confirm）：非法 → 422 且不切换，
    当前项目原样保留。不复用 project_init：其语义含 reset 清世界，会抹掉被
    恢复项目的全部数据。"""
    if not validate_project_name(req.name):
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
    # 回写解析出的 genre/culture（终审 Minor 1：手工拷入的外部项目目录缺
    # project.json 时，列表/下次 open 才能稳定显示与恢复同一题材）
    _write_project_meta(
        project_dir, name=req.name, genre=genre, culture=culture,
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

    name 过 validate_project_name（P10.6 起支持中文名；非法名与不存在一律 404，
    不泄露目录结构）；story.db 缺失 → 404。zip 在临时目录组装，BackgroundTask 在响应
    发送后整目录清理；组装失败则 except 中立即清理再抛。中文名文件名由
    Starlette 自动走 RFC5987 filename*=utf-8''<quoted>，浏览器下载不乱码。"""
    if not validate_project_name(name):
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


# ---------- 项目导入（P10.6：zip 入库；防穿越/防炸弹/重名 409） ----------
IMPORT_MAX_ENTRIES = 200                      # 炸弹粗防 1：条目数上限
IMPORT_MAX_UNPACKED = 200 * 1024 * 1024       # 炸弹粗防 2：解压总尺寸上限


def _zip_arcname_safe(arcname: str) -> bool:
    """zip 条目名防穿越：拒绝空名、绝对路径（/ \\ 开头）、盘符（C:…）、
    反斜杠、NUL/控制字符、冒号（Windows ADS/盘符变体）、任何 .. 段。"""
    if not arcname or arcname.startswith(("/", "\\")):
        return False
    if "\\" in arcname or ":" in arcname:
        return False
    if any(ord(c) < 32 or ord(c) == 127 for c in arcname):
        return False
    return ".." not in arcname.split("/")


def _resolve_import_name(zf: zipfile.ZipFile, form_name: str | None,
                         upload_name: str | None) -> str | None:
    """导入项目名取参顺序：表单 name → zip 内 project.json.name → zip 文件名去后缀。
    只负责取名，合法性由 validate_project_name 统一判。"""
    if form_name and form_name.strip():
        return form_name.strip()
    if "project.json" in zf.namelist():
        try:
            meta = json.loads(zf.read("project.json").decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            meta = None
        if isinstance(meta, dict) and isinstance(meta.get("name"), str) \
                and meta["name"].strip():
            return meta["name"].strip()
    base = Path(upload_name or "").name          # 剥掉浏览器可能带的路径
    return re.sub(r"\.zip$", "", base, flags=re.IGNORECASE) or None


@app.post("/api/projects/import")
async def import_project(file: UploadFile = File(...),
                         name: str | None = Form(None)):
    """【P10.6】导入项目 zip（本平台导出的 -story.zip 或同构包）到
    data/projects/<name>。不入栈不切换（open 是显式动作）。

    安全面（任一不过 → 422，落盘前全检完，零副作用）：
    - 合法 zip 且根级含 story.db（文件条目，非目录）；
    - 每个 arcname 过 _zip_arcname_safe（防解压逃逸到项目目录外）；
    - 炸弹粗防：条目数 >200 或声明解压总尺寸 >200MB → 422；逐条实写时按
      实际字节累计复核（声明值可伪造），超限中断并清掉已写内容；
    - 项目名过 validate_project_name；目标目录已存在且非空 → 409。
    落盘后 zip 无 project.json 时补写（name/created_at 必填；genre/culture
    留空走默认——列表/open 的既有推断口径接管）。返回 {ok, name, genre, culture}
    （genre/culture 取自落盘后的 project.json，缺省 → null）。"""
    blob = await file.read()
    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=422, detail="不是合法的 zip 文件")
    with zf:
        entries = [i for i in zf.infolist() if not i.is_dir()]
        if "story.db" not in {i.filename for i in entries}:
            raise HTTPException(status_code=422,
                                detail="zip 根级缺 story.db（非项目包）")
        for i in entries:
            if not _zip_arcname_safe(i.filename):
                raise HTTPException(
                    status_code=422,
                    detail=f"zip 含非法条目名（防穿越）：{i.filename!r}")
        if len(entries) > IMPORT_MAX_ENTRIES:
            raise HTTPException(
                status_code=422,
                detail=f"zip 条目过多（{len(entries)} > {IMPORT_MAX_ENTRIES}）")
        declared = sum(i.file_size for i in entries)
        if declared > IMPORT_MAX_UNPACKED:
            raise HTTPException(status_code=422,
                                detail="zip 解压后总尺寸超限（>200MB）")
        proj_name = _resolve_import_name(zf, name, file.filename)
        if not validate_project_name(proj_name):
            raise HTTPException(
                status_code=422,
                detail=f"项目名非法：{proj_name!r}（允许中文/字母/数字/空格/-/_，"
                       "1-40 字符；不含路径分隔符/.. /Windows 保留名）")
        target = PROJECTS_ROOT / proj_name
        if target.exists() and any(target.iterdir()):
            raise HTTPException(status_code=409,
                                detail=f"项目已存在：{proj_name}")
        # 落盘：逐条解压（arcname 已过检，纯相对路径）；失败清现场
        created = not target.exists()
        target.mkdir(parents=True, exist_ok=True)
        done: list[Path] = []
        actual = 0
        try:
            for i in entries:
                data = zf.read(i)
                actual += len(data)
                if actual > IMPORT_MAX_UNPACKED:
                    raise HTTPException(
                        status_code=422,
                        detail="zip 实际解压尺寸超限（>200MB）")
                dest = target / i.filename
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                done.append(dest)
        except Exception:
            if created:
                shutil.rmtree(target, ignore_errors=True)
            else:
                for p in done:
                    p.unlink(missing_ok=True)
            raise
    meta = _read_project_meta(target)
    if meta is None:
        # zip 无 project.json：补写最小元数据；genre/culture 留空走默认
        meta = _write_project_meta(
            target, name=proj_name,
            created_at=datetime.now().isoformat(timespec="seconds"))
    return {"ok": True, "name": proj_name, "genre": meta.get("genre"),
            "culture": meta.get("culture")}


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


# ---------- 世界观架构（P12.2：L0-L3 全量参数 + 跨层一致性校验） ----------
@app.get("/api/worldview/schema")
def worldview_schema():
    """【P12.2 / P14】返回世界观 10 层架构定义 + 语言文化 5 层 + 十骨架摘要。

    前端据此渲染向导：``layers`` 是 L0-L9 + LANG1-LANG5 的完整参数/枚举/连锁描述；
    ``layers_covered`` 为当前已数据化层（L0-L9 + LANG1-LANG5）。
    ``param_count`` 为当前已数据化参数总数（L0-L9 合计 71 + LANG1-LANG5 合计 15 = 86）。
    """
    all_layers = WV_LAYERS + WV_LANGUAGE_LAYERS + WV_CHARACTER_LAYERS
    # P22：每个骨架附 recommended_genres（taxonomy 同源，primary 优先，截断 5 + 总数）
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


class WorldviewEvaluateReq(BaseModel):
    """POST /api/worldview/evaluate body：``profile`` 为分层结构
    ``{L0: {param: value}, ...}``（容忍部分填写/未知层键，见 WorldviewProfile）。"""
    profile: dict[str, dict[str, str]] = {}


@app.post("/api/worldview/evaluate")
def worldview_evaluate_endpoint(req: WorldviewEvaluateReq):
    """【P12.2】评估世界观 profile 的跨层一致性 → {allowed, violations}。

    分层 profile 经 :class:`WorldviewProfile` 扁平化后喂给纯函数
    :func:`evaluate`；``allowed`` 为被谓词收窄后的合法值集（未触发的参数
    取全集），``violations`` 为 profile 中已设值命中某谓词 disallow/require
    的明细（{param, value, message}）。
    """
    flat = WorldviewProfile(layers=req.profile).as_flat()
    return wv_evaluate(flat)


class DeriveCastReq(BaseModel):
    """POST /api/gacha/{sid}/derive_cast body：worldview 与 language 的分层 profile，
    均可选（容忍空/部分填写）。"""
    worldview: dict[str, dict[str, str]] = {}
    language: dict[str, dict[str, str]] = {}


@app.post("/api/worldview/derive_cast")
def derive_cast_endpoint_legacy(req: DeriveCastReq):
    """已废弃：P20 起改用 /api/gacha/{sid}/derive_cast。保留 410 告知前端升级。"""
    raise HTTPException(status_code=410, detail="此端点已废弃，请使用 /api/gacha/{sid}/derive_cast")


class CrossCheckReq(BaseModel):
    worldview: dict | None = None
    cast: list | None = None


@app.post("/api/worldview/cross_check")
def worldview_cross_check_endpoint_legacy(req: CrossCheckReq):
    """已废弃：P20 起改用 /api/gacha/{sid}/cross_check。保留 410 告知前端升级。"""
    raise HTTPException(status_code=410, detail="此端点已废弃，请使用 /api/gacha/{sid}/cross_check")


# ---------- 抽卡开局（P20：临时工作区 session 管理） ----------
_gacha_sessions: dict[str, dict] = {}
_GACHA_SESSION_TTL = 1800  # 30 分钟


def _derive_culture_for_genre(kernel, genre_name: str) -> str:
    """从题材 allowed_cultures 推导最匹配的文化（P20 session engine 构造用）。"""
    try:
        m = kernel.registry.get_manifest("story.genre", genre_name)
        return derive_culture(m.allowed_cultures, genre_name=genre_name)
    except Exception:
        return "confucian_officialdom"


def _create_session_engine(genre_name: str, culture: str | None = None):
    """P20：为抽卡向导创建临时工作区 Kernel + StoryEngine（用用户选的题材）。

    返回 (engine, kernel, tmp_dir)。临时目录在 data/projects/.tmp_gacha_<uuid>/，
    由调用方在 cancel/confirm/expire 时清理。
    """
    tmp_dir = PROJECTS_ROOT / f".tmp_gacha_{uuid4().hex[:8]}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    stack: dict = {}
    kernel = Kernel(
        tmp_dir, plugin_dir=ROOT / "story_engine" / "plugins",
        initial_state_factory=_make_lazy_genesis(stack))
    culture = culture or _derive_culture_for_genre(kernel, genre_name)
    sess_engine = StoryEngine(kernel, genre_name=genre_name,
                              culture_name=culture)
    stack.update({"kernel": kernel, "engine": sess_engine})
    return sess_engine, kernel, tmp_dir


def _cleanup_session(sid: str) -> None:
    """清理 session 关联的临时目录 + kernel 句柄（cancel/confirm/expire 调用）。"""
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
    """清理超过 TTL 的过期 session（begin 时顺带调用）。"""
    now = datetime.now().timestamp()
    expired = [sid for sid, s in _gacha_sessions.items()
               if now - s.get("created_ts", now) > _GACHA_SESSION_TTL]
    for sid in expired:
        _cleanup_session(sid)


import atexit


def _cleanup_all_sessions() -> None:
    for sid in list(_gacha_sessions):
        _cleanup_session(sid)


atexit.register(_cleanup_all_sessions)


class GachaBeginReq(BaseModel):
    """P20：开局向导入口 body"""
    genre_name: str
    culture: str | None = None


class GachaConfirmReq(BaseModel):
    """P20：开局确认 body"""
    project_name: str
    worldview: dict | None = None
    cast: list | None = None
    macro_plan: dict | None = None


@app.get("/api/gacha/genres")
def gacha_genres(q: str = "", tags: str = "", tier: str = "",
                 family: str = "", offset: int = 0, limit: int = 24):
    """【P22】题材浏览：搜索（title/id/tag/vibe）+ 多 tag（逗号分隔，AND）
    + tier/family 筛选 + 分页；facets 供前端 tag 云与族分层。"""
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


@app.post("/api/gacha/begin")
def gacha_begin(req: GachaBeginReq):
    """P20：进入抽卡向导 → 创建临时工作区 engine（用用户选的题材）。

    返回 {session_id, genre_title}。后续 derive_cast / cross_check /
    macro stream 全用 session_id 路由到正确的临时 engine。
    """
    _expire_old_sessions()
    genre_name = req.genre_name
    try:
        engine.kernel.registry.get_manifest("story.genre", genre_name)
    except Exception:
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
            "genre": genre_name, "culture": sess_engine.culture.name}
    # P22：三轴摘要（taxonomy 同源）——推荐骨架/宏观模板/标签/文化显示名
    taxon = taxon_by_id(genre_name)
    if taxon is not None:
        resp["recommended_presets"] = list(presets_for_genre(genre_name))
        resp["recommended_macro_templates"] = list(
            macro_templates_for_genre(genre_name))
        resp["tags"] = list(taxon.tags)
        resp["family_title"] = taxon.family_title
        try:
            cm = engine.kernel.registry.get_manifest(
                "story.culture", sess_engine.culture.name)
            resp["culture_title"] = cm.params.get(
                "title", sess_engine.culture.name)
        except Exception:
            resp["culture_title"] = sess_engine.culture.name
    return resp


@app.post("/api/gacha/{sid}/cancel")
def gacha_cancel(sid: str):
    """P20：取消 session → 清理临时目录 + kernel 句柄。"""
    if sid not in _gacha_sessions:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    _cleanup_session(sid)
    return {"ok": True}


@app.post("/api/gacha/{sid}/confirm")
def gacha_session_confirm(sid: str, req: GachaConfirmReq):
    """P20：确认开工 → rename 临时目录 → 写落盘文件 → _switch_to 新项目。

    流程：
    1. 校验 project_name
    2. worldview 校验（如有）
    3. rename tmp_dir → data/projects/<project_name>/
    4. 写 worldview.json / cast.json / macro_plan.json / project.json
    5. _switch_to 切换到新项目（用 session 的 genre/culture）
    6. 清理 session
    """
    global engine
    session = _gacha_sessions.get(sid)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")

    def _fail(detail, code=422):
        """验证失败时先清理 session（释放 SQLite 句柄）再抛异常。"""
        _cleanup_session(sid)
        raise HTTPException(status_code=code, detail=detail)

    if not validate_project_name(req.project_name):
        _fail(f"项目名非法：{req.project_name!r}（允许中文/字母/数字/空格/-/_，"
              "1-40 字符；不含路径分隔符/.. /Windows 保留名）")
    target_dir = PROJECTS_ROOT / req.project_name
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
        engine.kernel.registry.validate_combo(genre_name, culture)
    except StoryEngineError as e:
        _cleanup_session(sid)
        raise HTTPException(status_code=422, detail=str(e))
    # 先关 session kernel（释放 SQLite 句柄），再 rename
    try:
        session["kernel"].close()
    except Exception:
        logger.warning("confirm: session kernel close 失败（尽力继续）",
                       exc_info=True)
    try:
        tmp_dir.rename(target_dir)
    except OSError:
        # rename 失败（跨盘符等），用 shutil.move
        shutil.move(str(tmp_dir), str(target_dir))
    _gacha_sessions.pop(sid, None)
    # 整栈切换到新项目（用 session 的 genre/culture）
    _switch_to(target_dir, genre_name=genre_name, culture_name=culture)
    now = datetime.now().isoformat(timespec="seconds")
    _write_project_meta(target_dir, name=req.project_name, genre=genre_name,
                        culture=culture, created_at=now, last_opened_at=now)
    # worldview 落盘
    if wv_layers is not None:
        _write_json_atomic(
            target_dir / "worldview.json",
            {"layers": wv_layers, "preset": wv_preset,
             "created_at": datetime.now().isoformat(timespec="seconds")})
        _write_project_meta(
            target_dir,
            worldview={"preset": wv_preset,
                       "param_count": wv_param_count})
    # cast 落盘
    cast_data = req.cast
    if cast_data is not None and isinstance(cast_data, list):
        _write_json_atomic(target_dir / "cast.json", cast_data)
    elif not cast_data:
        # 自动推导阵容
        try:
            derived = wv_derive_cast(
                wv_layers, None, engine.bundle.genre_params)
        except Exception:
            derived = None
        if derived:
            cast_data = [
                {"id": c.get("name", ""), "role": c.get("role", ""),
                 "persona": c.get("persona", {})}
                for c in derived if c.get("name")]
            _write_json_atomic(target_dir / "cast.json", cast_data)
    # macro_plan 落盘
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
    # project_init 重置世界（新 kernel 已由 _switch_to 构造，这里清状态）
    engine.reset()
    engine.discard_plan()
    return {"ok": True, "project": {"name": req.project_name,
                                     "genre": genre_name,
                                     "culture": culture}}


# ---------- P20 session-based derive_cast / cross_check ----------
@app.post("/api/gacha/{sid}/derive_cast")
def gacha_session_derive_cast(sid: str, req: DeriveCastReq):
    """P20：从世界观推导阵容，用 session engine 的题材 params。"""
    session = _gacha_sessions.get(sid)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    genre_params = getattr(session["engine"].bundle, "genre_params", None)
    return {"cast": wv_derive_cast(req.worldview, req.language, genre_params)}


@app.post("/api/gacha/{sid}/cross_check")
def gacha_session_cross_check(sid: str, req: CrossCheckReq):
    """P20：跨层冲突检测，用 session engine 的题材 params。"""
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
        wv_preset = req.worldview.get("preset") \
            if isinstance(req.worldview, dict) else None
    cast_profile = req.cast if isinstance(req.cast, list) else None
    warnings = check_cross_layer(
        genre_params, wv_profile, cast_profile, genre_name,
        wv_preset=wv_preset)
    return {"warnings": [
        {"type": w.type, "severity": w.severity, "title": w.title,
         "description": w.description, "suggestion": w.suggestion}
        for w in warnings
    ]}


# ---------- P20 WebSocket 宏观计划流式生成 ----------
@app.websocket("/api/gacha/{sid}/macro/stream")
async def macro_stream(ws: WebSocket, sid: str):
    """P20：WebSocket 宏观计划流式生成。

    前端发 {template_name, worldview?, cast?, conflict_warnings?}；
    后端逐 chunk send_json({"type":"delta","text":"..."})；
    完成后 send_json({"type":"complete","plan":{...}})。
    """
    await ws.accept()
    session = _gacha_sessions.get(sid)
    if not session:
        await ws.send_json({"type": "error",
                            "msg": "会话不存在或已过期"})
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
    if template not in MACRO_TEMPLATES:
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
    total_episodes = getattr(bundle, "target_length", 12)
    try:
        # mock 模式：直接骨架兜底，不流式（mock 也模拟流式体验）
        if sess_kernel.llm.is_mock:
            plan = _generate_skeleton_macro(
                bundle, wv_profile, cast_profile, template, total_episodes)
            # 模拟流式：把 YAML 文本切块推送
            plan_dict = macro_plan_to_dict(plan)
            import json as _json
            plan_text = _json.dumps(plan_dict, ensure_ascii=False, indent=2)
            for i in range(0, len(plan_text), 80):
                await ws.send_json({"type": "delta",
                                    "text": plan_text[i:i + 80]})
                await asyncio.sleep(0.03)
            await ws.send_json({"type": "complete", "plan": plan_dict})
            await ws.close()
            return
        # real 模式：LLM 流式
        prompt = _build_macro_prompt(
            bundle, wv_profile, cast_profile, template, total_episodes,
            conflict_warnings)
        full_text = ""
        try:
            async for chunk in sess_kernel.llm.call_stream(
                    prompt, purpose="macro_plan", temperature=0.7,
                    max_tokens=8192):
                full_text += chunk
                await ws.send_json({"type": "delta", "text": chunk})
        except Exception as e:
            await ws.send_json({"type": "error",
                                "msg": f"LLM 流式调用失败：{e}"})
            # mock 兜底
            plan = _generate_skeleton_macro(
                bundle, wv_profile, cast_profile, template, total_episodes)
            await ws.send_json({"type": "complete",
                                "plan": macro_plan_to_dict(plan)})
            await ws.close()
            return
        # 解析 + 校验
        plan = _parse_and_validate_macro(full_text, template, total_episodes)
        if plan is None:
            # 解析失败 → mock 兜底
            await ws.send_json({"type": "error",
                                "msg": "LLM 输出解析失败，使用骨架兜底"})
            plan = _generate_skeleton_macro(
                bundle, wv_profile, cast_profile, template, total_episodes)
        await ws.send_json({"type": "complete",
                            "plan": macro_plan_to_dict(plan)})
        await ws.close()
    except WebSocketDisconnect:
        return
    except Exception as e:
        logger.exception("macro_stream 未捕获异常 | sid={}", sid)
        try:
            await ws.send_json({"type": "error",
                                "msg": f"宏观生成失败：{e}"})
            plan = _generate_skeleton_macro(
                bundle, wv_profile, cast_profile, template, total_episodes)
            await ws.send_json({"type": "complete",
                                "plan": macro_plan_to_dict(plan)})
            await ws.close()
        except Exception:
            try:
                await ws.close()
            except Exception:
                pass


def _build_macro_prompt(bundle, worldview_profile, cast_profile,
                        template_name, total_episodes, conflict_warnings):
    """复用 macro.generator._build_prompt 构建 LLM 提示词。"""
    from story_engine.macro.generator import _build_prompt
    return _build_prompt(bundle, worldview_profile, cast_profile,
                         template_name, total_episodes, conflict_warnings)


def _generate_skeleton_macro(bundle, worldview_profile, cast_profile,
                             template_name, total_episodes):
    """复用 macro.generator._generate_skeleton 生成骨架兜底。"""
    from story_engine.macro.generator import _generate_skeleton
    return _generate_skeleton(bundle, worldview_profile, cast_profile,
                              template_name, total_episodes)


def _parse_and_validate_macro(text, template_name, total_episodes):
    """复用 macro.generator._parse_yaml + _validate + _build_plan。"""
    from story_engine.macro.generator import (
        _parse_yaml, _validate, _build_plan)
    parsed = _parse_yaml(text)
    if parsed and _validate(parsed, total_episodes):
        return _build_plan(parsed, template_name, total_episodes)
    return None


# ---------- 题材列表：P22 起由前部 /api/gacha/genres（搜索/筛选/分页）提供 ----------
# （旧 P20 平铺版端点已删——同名路由先注册先匹配，平铺 315 卡不可用）


@app.post("/api/gacha/synth")
async def gacha_synth():
    """P20：synth 合成新题材（保留旧能力，前端「让 AI 自由发挥」按钮调用）。
    mock 模式下恒降级 library 卡。"""
    try:
        return await draw_card_async(engine.kernel, engine.kernel.llm.call,
                                     "synth")
    except StoryEngineError as e:
        raise HTTPException(status_code=500, detail=str(e))


# 题材名白名单（synth 落盘用）
GENRE_NAME_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}")


# ---------- 宏观规划（P17.3：宏观叙事规划层端点） ----------
TEMPLATES_META = {
    "save_the_cat_15": ("救猫十五拍", "Snyder 经典影视结构，15 个固定节拍点"),
    "truby_22": ("Truby 22 步", "有机故事结构，22 个关键转折"),
    "three_act_classic": ("经典三幕", "亚里士多德三幕，简洁有力"),
    "dtg_50_30": ("短剧 50+30", "80 集短剧节奏（前 50 爽感+后 30 收线）"),
    "wuxia_classic": ("武侠章回", "金圣叹评书体，武侠/公案专用"),
    "romance_beat": ("言情节拍", "言情/甜宠标准结构"),
    "custom": ("自定义", "用户自定义幕结构"),
}


@app.get("/api/macro/templates")
def macro_templates(genre: str = ""):
    """【P17.3】返回 7 个幕结构模板列表（name + description + beat_count）。

    beat_count 取模板定义的 beat 总数（不含 act 级别元数据），供前端展示卡面。
    【P22】可选 ?genre= 时按 taxonomy 标记 recommended（前端据此置顶/高亮）。
    """
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
    return {"templates": items}


class MacroPlanReq(BaseModel):
    template_name: str = "save_the_cat_15"
    worldview: dict | None = None
    cast: list | None = None
    regenerate_component: str | None = None       # P18.2: 单组件重摇
    conflict_warnings: list | None = None         # P18.2: ③.5 冲突标记注入
    existing_plan: dict | None = None             # P18.2: 单组件重摇时的已有计划


@app.post("/api/macro/plan")
async def macro_plan_generate_legacy(req: MacroPlanReq):
    """已废弃：P20 起开局向导宏观生成改用 WebSocket /api/gacha/{sid}/macro/stream。
    保留 410 告知前端升级。"""
    raise HTTPException(
        status_code=410,
        detail="此端点已废弃，请使用 WebSocket /api/gacha/{sid}/macro/stream")


@app.get("/api/macro/plan")
def macro_plan_get():
    """【P17.3】读取当前项目的 macro_plan.json；无文件 → 404。"""
    path = Path(engine.project_dir) / "macro_plan.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="当前项目无宏观计划")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("macro_plan.json 读取失败 | %r", exc)
        raise HTTPException(
            status_code=500, detail="宏观计划文件读取失败（文件损坏，详见日志）")


@app.get("/api/macro/progress")
def macro_progress():
    """【P18.3】宏观进度：当前章节 / beat / 伏笔状态 / 弧光阶段。

    从 macro_plan.json + 项目已写章节列表推导当前进度快照。
    """
    plan_path = Path(engine.project_dir) / "macro_plan.json"
    if not plan_path.exists():
        raise HTTPException(status_code=404, detail="当前项目无宏观计划")
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("macro_plan.json 读取失败 | %r", exc)
        raise HTTPException(
            status_code=500, detail="宏观计划文件读取失败（文件损坏，详见日志）")

    chapters = getattr(engine, "project", None)
    chapter_count = 0
    if chapters and isinstance(chapters, dict):
        chapter_count = len(chapters.get("chapters") or [])
    current_ep = chapter_count + 1

    # 当前 beat / act
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

    # 当前集梗概
    current_synopsis = ""
    current_key_events: list = []
    for ep in plan.get("episode_outlines") or []:
        if ep.get("episode") == current_ep:
            current_synopsis = ep.get("synopsis", "")
            current_key_events = list(ep.get("key_events") or [])
            break

    # 伏笔状态
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

    # 弧光阶段
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


@app.get("/api/macro/deviation")
def macro_deviation():
    """【P18.3】偏差检测：实际（已写章节）vs 计划（macro_plan）对比。

    返回各集的 key_events 覆盖情况、伏笔执行状态、弧光阶段达成度。
    """
    plan_path = Path(engine.project_dir) / "macro_plan.json"
    if not plan_path.exists():
        raise HTTPException(status_code=404, detail="当前项目无宏观计划")
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("macro_plan.json 读取失败 | %r", exc)
        raise HTTPException(
            status_code=500, detail="宏观计划文件读取失败（文件损坏，详见日志）")

    chapters = getattr(engine, "project", None)
    chapter_count = 0
    if chapters and isinstance(chapters, dict):
        chapter_count = len(chapters.get("chapters") or [])

    # key_events 覆盖
    episode_coverage: list[dict] = []
    for ep in plan.get("episode_outlines") or []:
        ep_num = ep.get("episode", 0)
        episode_coverage.append({
            "episode": ep_num,
            "planned_key_events": list(ep.get("key_events") or []),
            "status": "written" if ep_num <= chapter_count else "not_written",
        })

    # 伏笔偏差
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

    # 弧光偏差
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


def _ep_in_range(ep: int, rng: str) -> bool:
    """解析 '1-3' / '5' 形式的章节范围"""
    if not rng:
        return False
    parts = str(rng).split("-")
    try:
        if len(parts) == 1:
            return ep == int(parts[0])
        return int(parts[0]) <= ep <= int(parts[1])
    except (ValueError, TypeError):
        return False


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


@app.post("/api/settings/llm")
def settings_llm_post(req: LlmSettingsReq):
    """【P23】LLM 接入在线配置：LLMPool 单例就地更新立即生效（无需重启）；
    persist=true 时把非空键写回 .env（重启后仍生效）。api_key 永不返回。
    空/None 键 = 保持不变；给了 api_key 即切 openai 模式。"""
    if req.base_url is not None and req.base_url.strip():
        u = req.base_url.strip()
        if not (u.startswith("https://") or u.startswith("http://localhost")
                or u.startswith("http://127.0.0.1")):
            raise HTTPException(
                status_code=422,
                detail="base_url 必须是 https://（或本机 http://localhost）")
    view = engine.apply_llm_settings({
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


@app.post("/api/settings/test_llm")
async def settings_test_llm(req: TestLlmReq | None = None):
    """【P6.10 B10 / P23】一次性 ping LLM —— 最小请求「请回复：好」max_tokens=10。
    body 给了 base_url/api_key 就用该临时配置实测（不写入引擎，「先测后存」）；
    缺省测当前 engine.llm 配置；mock 模式（且无临时 key）直接返回 ok=true。
    响应只 {ok, latency_ms, model, error?} —— key 永不回前端。"""
    import time as _time
    import httpx
    src = req or TestLlmReq()
    client = engine.llm
    use_temp = bool((src.base_url or "").strip() and (src.api_key or "").strip())
    base_url = (src.base_url.strip() if use_temp else client.base_url).rstrip("/")
    model = src.model or client.model
    key = src.api_key.strip() if use_temp else client.api_key
    # mock 模式：直接 ok（不构造 client）
    if client.is_mock and not use_temp:
        return {"ok": True, "latency_ms": 0.0, "model": client.model}
    if not key:
        return {"ok": False, "error": "未配置 API key（环境变量 STORY_ENGINE_LLM_API_KEY 为空）",
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
