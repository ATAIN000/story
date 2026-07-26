"""多项目管理端点（列表/切换/导出 zip/导入 zip）。"""
from __future__ import annotations

import io
import json
import logging
import os
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from backend import deps
from backend.generation_state import gen_state
from backend.helpers import (
    IMPORT_MAX_ENTRIES, IMPORT_MAX_UNPACKED,
    _build_project_zip, _count_active_chapters, _read_head_tick,
    _read_project_meta, _resolve_import_name, _write_project_meta,
    _write_json_atomic, _zip_arcname_safe, validate_project_name,
    _switch_to,
)

router = APIRouter()
logger = logging.getLogger(__name__)


class ProjectOpenReq(BaseModel):
    name: str


def _list_projects(root: Path) -> list[dict]:
    items = []
    if not Path(root).is_dir():
        return items
    current_name = Path(deps.engine.project_dir).name
    for d in sorted(Path(root).iterdir()):
        if not d.is_dir() or not (d / "story.db").exists():
            continue
        meta = _read_project_meta(d)
        if meta is None:
            if d.name == current_name:
                genre, culture = deps.engine.genre.name, deps.engine.culture.name
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


@router.get("/api/projects")
def list_projects():
    return _list_projects(deps.PROJECTS_ROOT)


@router.post("/api/projects/open")
def open_project(req: ProjectOpenReq):
    from story_engine.types import StoryEngineError
    # 生成中禁止切项目：_switch_to 会 close 旧 kernel，后台生成任务会炸
    if gen_state.busy():
        raise HTTPException(status_code=409, detail="生成进行中，请等待完成后切换项目")
    if not validate_project_name(req.name):
        raise HTTPException(status_code=404, detail=f"项目不存在：{req.name}")
    project_dir = deps.PROJECTS_ROOT / req.name
    if not (project_dir / "story.db").exists():
        raise HTTPException(status_code=404, detail=f"项目不存在：{req.name}")
    meta = _read_project_meta(project_dir) or {}
    genre = meta.get("genre") or os.environ.get("STORY_ENGINE_GENRE", "mystery")
    culture = meta.get("culture") or os.environ.get(
        "STORY_ENGINE_CULTURE", "confucian_officialdom")
    try:
        deps.engine.kernel.registry.validate_combo(genre, culture)
    except StoryEngineError as e:
        raise HTTPException(status_code=422, detail=str(e))
    _switch_to(project_dir, genre_name=genre, culture_name=culture,
               target_length=(meta.get("macro") or {}).get("total_episodes")
               or None)
    _write_project_meta(
        project_dir, name=req.name, genre=genre, culture=culture,
        last_opened_at=datetime.now().isoformat(timespec="seconds"))
    return {"ok": True, "project": deps.engine.project_snapshot()["meta"]}


@router.get("/api/projects/{name}/export")
def export_project(name: str):
    if not validate_project_name(name):
        raise HTTPException(status_code=404, detail=f"项目不存在：{name}")
    project_dir = deps.PROJECTS_ROOT / name
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


@router.post("/api/projects/import")
async def import_project(file: UploadFile = File(...),
                         name: str | None = Form(None)):
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
        target = deps.PROJECTS_ROOT / proj_name
        if target.exists() and any(target.iterdir()):
            raise HTTPException(status_code=409,
                                detail=f"项目已存在：{proj_name}")
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
        meta = _write_project_meta(
            target, name=proj_name,
            created_at=datetime.now().isoformat(timespec="seconds"))
    return {"ok": True, "name": proj_name, "genre": meta.get("genre"),
            "culture": meta.get("culture")}
