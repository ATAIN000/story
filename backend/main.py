"""Story Engine Demo — FastAPI 后端

API：
  GET  /api/project            项目完整快照（世界状态/事件/伏笔/章节/决策卡）
  POST /api/project/generate   生成下一章（核心循环）
  POST /api/project/rollback   回滚到指定 tick
  POST /api/project/reset      重置项目
  GET  /api/config             运行配置（LLM 模式/插件）
  POST /api/meta/config        【v0.2 新增】UserIntent → StoryConfig（Module 8）
静态：/ → frontend/dist（Vue SPA）
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# 让 backend 能 import story_engine（项目根在上一级）
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from story_engine.engine import StoryEngine, StoryEngineMockEnded  # noqa: E402
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


class RollbackReq(BaseModel):
    tick: int


class UserIntentReq(BaseModel):
    theme: str = ""
    culture_hint: str = ""
    language: str = "zh"
    target_length: int = 12
    platform: str = "novel"


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
async def generate():
    try:
        return await engine.generate_chapter()
    except StoryEngineMockEnded as e:
        raise HTTPException(status_code=409, detail=str(e))
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except StoryEngineError as e:
        raise HTTPException(status_code=500, detail=str(e))


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
