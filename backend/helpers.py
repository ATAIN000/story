"""纯工具函数 + 栈管理（_build_stack / _switch_to）+ 闭包工厂。

所有函数要么是纯 I/O 工具，要么通过 deps 访问可变状态。
router 和 main.py 共同依赖此模块。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from backend import deps

logger = logging.getLogger(__name__)

# ---------- 项目名校验 ----------
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
    if name.split(".")[0].upper() in WINDOWS_RESERVED_NAMES:
        return False
    return PROJECT_NAME_RE.fullmatch(name) is not None


# ---------- project.json 元数据 ----------
def _read_project_meta(project_dir: Path) -> dict | None:
    try:
        meta = json.loads(
            (Path(project_dir) / deps.PROJECT_META_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return meta if isinstance(meta, dict) else None


def _write_project_meta(project_dir: Path, **fields) -> dict:
    meta = _read_project_meta(project_dir) or {}
    meta.update(fields)
    path = Path(project_dir) / deps.PROJECT_META_NAME
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


# ---------- zip 安全 ----------
IMPORT_MAX_ENTRIES = 200
IMPORT_MAX_UNPACKED = 200 * 1024 * 1024


def _zip_arcname_safe(arcname: str) -> bool:
    if not arcname or arcname.startswith(("/", "\\")):
        return False
    if "\\" in arcname or ":" in arcname:
        return False
    if any(ord(c) < 32 or ord(c) == 127 for c in arcname):
        return False
    return ".." not in arcname.split("/")


def _resolve_import_name(zf: zipfile.ZipFile, form_name: str | None,
                         upload_name: str | None) -> str | None:
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
    base = Path(upload_name or "").name
    return re.sub(r"\.zip$", "", base, flags=re.IGNORECASE) or None


def _build_project_zip(project_dir: Path, name: str, work_dir: Path) -> Path:
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


# ---------- misc 纯函数 ----------
def _count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in
               path.read_text(encoding="utf-8").splitlines() if line.strip())


def _ep_in_range(ep: int, rng: str) -> bool:
    if not rng:
        return False
    parts = str(rng).split("-")
    try:
        if len(parts) == 1:
            return ep == int(parts[0])
        return int(parts[0]) <= ep <= int(parts[1])
    except (ValueError, TypeError):
        return False


def _persist_env(updates: dict) -> None:
    env_path = deps.ROOT / ".env"
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    else:
        example = deps.ROOT / ".env.example"
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


# ---------- 闭包工厂 ----------
def _make_regenerate_sync(stack: dict):
    def _regenerate_sync() -> None:
        asyncio.run(stack["engine"].regenerate_current_chapter())
    return _regenerate_sync


def _make_textual_apply(stack: dict):
    def _textual_apply(chapter: int, before, after) -> str:
        return stack["engine"].update_chapter_text(chapter, before, after)
    return _textual_apply


def _make_lazy_genesis(stack: dict):
    def _factory():
        from story_engine.engine import StoryEngine
        engine = stack.get("engine")
        if engine is None:
            return StoryEngine._genesis_state()
        return engine._genesis_factory()()
    return _factory


# ---------- 栈管理 ----------
def _build_stack(project_dir: Path, genre_name: str | None = None,
                 culture_name: str | None = None) -> dict:
    """项目栈工厂：kernel/engine/meta_gen/pipeline/router 一处构造。"""
    from story_engine.engine import StoryEngine
    from story_engine.hitl import InterventionRouter, TrainingPipeline
    from story_engine.kernel import Kernel
    from story_engine.meta import MetaGenerator

    stack: dict = {}
    kernel = Kernel(project_dir, plugin_dir=deps.ROOT / "story_engine" / "plugins",
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


def _switch_to(project_dir: Path, genre_name: str | None = None,
               culture_name: str | None = None) -> dict:
    """项目切换核心：旧 kernel 尽力 close → _build_stack 整栈重建 →
    重绑 deps 全部引用，不留旧栈引用。"""
    new_stack = _build_stack(Path(project_dir), genre_name=genre_name,
                             culture_name=culture_name)
    old_kernel = deps.kernel
    old_engine_runtime = getattr(deps.engine, "_runtime_overrides", {})
    try:
        old_kernel.close()
    except Exception:
        logger.warning("项目切换：旧 kernel close 失败（尽力继续）",
                       exc_info=True)
    deps.stack = new_stack
    deps.kernel = new_stack["kernel"]
    deps.llm_client = deps.kernel.llm
    deps.engine = new_stack["engine"]
    try:
        deps.engine._runtime_overrides = dict(old_engine_runtime)
    except Exception:
        pass
    deps.meta_gen = new_stack["meta_gen"]
    deps.training_pipeline = new_stack["pipeline"]
    deps.intervention_router = new_stack["router"]
    return new_stack
