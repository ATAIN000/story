"""共享运行时状态。

所有 router 和 helper 通过此模块访问运行时单例（engine / kernel / ...），
使 _switch_to（项目切换）和 project_init 的重绑在所有模块中立即可见。
main.py 在 _load_dotenv 之后首次 import 本模块，env 变量此时已就位。
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 常量（不依赖 .env 的）
PROJECTS_ROOT = Path(os.environ.get(
    "STORY_ENGINE_PROJECTS_ROOT", str(ROOT / "data" / "projects")))
PROJECT_META_NAME = "project.json"

# 以下依赖 .env（main._load_dotenv 必须在 import 本模块之前执行）
PROJECT_DIR = os.environ.get(
    "STORY_ENGINE_PROJECT_DIR", str(ROOT / "data" / "projects" / "yupei"))
FRONTEND_DIST = Path(os.environ.get(
    "STORY_ENGINE_FRONTEND_DIST", str(ROOT / "frontend" / "dist")))

# ----- 可变运行时状态（_build_stack 构造、_switch_to 重绑） -----
stack: dict = {}
kernel = None          # type: ignore[assignment]
llm_client = None      # type: ignore[assignment]  # 老变量名，兼容引用
engine = None          # type: ignore[assignment]
meta_gen = None        # type: ignore[assignment]
training_pipeline = None  # type: ignore[assignment]
intervention_router = None  # type: ignore[assignment]
