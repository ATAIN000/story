"""StoryOS · Story Engine — FastAPI 后端入口。

职责（薄层）：
  1. 引导：sys.path / .env / 日志
  2. 构造运行时栈（engine/kernel/router…）
  3. 创建 app、CORS、全局异常处理
  4. 注册 APIRouter（各功能域拆到 backend/routers/）
  5. 托管前端 SPA 静态资源

业务逻辑全部在 story_engine/ 核心包；HTTP/WS 编排在各 router。
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# ---- 引导：让 backend 能 import story_engine（项目根在上一级） ----
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_dotenv():
    """轻量 .env 加载（不额外引依赖）。必须在 import deps 之前执行。"""
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

# deps 在 import 时读取 os.environ（.env 已注入）
from backend import deps  # noqa: E402
from backend.helpers import _build_stack  # noqa: E402

# 日志初始化（app 创建前）
from story_engine.logging_config import setup_logging  # noqa: E402
setup_logging()

logger = logging.getLogger(__name__)

# ---- 构造初始运行时栈 ----
deps.stack = _build_stack(Path(deps.PROJECT_DIR))
deps.kernel = deps.stack["kernel"]
deps.llm_client = deps.kernel.llm
deps.engine = deps.stack["engine"]
deps.meta_gen = deps.stack["meta_gen"]
deps.training_pipeline = deps.stack["pipeline"]
deps.intervention_router = deps.stack["router"]

# ---- FastAPI app ----
from fastapi import FastAPI  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402

app = FastAPI(title="Story Engine", version=__import__("story_engine").__version__)
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


# ---------- 全局错误中文化 ----------
_422_FIELD_ZH = {
    "genre_name": "题材名", "project_name": "项目名", "template_name": "幕结构模板",
    "chapter": "章节号", "para_index": "段落号", "direction": "改写方向",
    "worldview": "世界观", "cast": "人物阵容", "tick": "tick",
    "content": "内容", "text": "文本", "macro_plan": "宏观计划",
    "base_url": "LLM 地址", "api_key": "API key", "model": "模型",
}


@app.exception_handler(RequestValidationError)
async def _validation_exc_handler(request, exc: RequestValidationError):
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
    logger.exception("未捕获异常 | %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误，已记录日志（logs/story_engine.log）"})


# ---- 注册 APIRouters ----
from backend.routers import (  # noqa: E402
    gacha, hitl, macro, project, projects, settings, worldview)

app.include_router(project.router)
app.include_router(projects.router)
app.include_router(worldview.router)
app.include_router(gacha.router)
app.include_router(macro.router)
app.include_router(hitl.router)
app.include_router(settings.router)


# ---- 静态托管 Vue SPA（必须最后注册：catch-all 路由） ----
if deps.FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=deps.FRONTEND_DIST / "assets"),
              name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        if full_path.startswith("api/"):
            from fastapi import HTTPException
            raise HTTPException(status_code=404)
        file = deps.FRONTEND_DIST / full_path
        if full_path and file.exists() and file.is_file():
            return FileResponse(file)
        return FileResponse(deps.FRONTEND_DIST / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8111")))
