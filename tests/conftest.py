"""测试全局 fixture：强制 dummy embedding，避免拉本地模型。"""
from __future__ import annotations

import atexit
import os
import sys
import tempfile
from pathlib import Path

# 必须在 import Embedder / Kernel 之前生效
os.environ["STORY_ENGINE_EMBED_MODE"] = "dummy"
os.environ.setdefault("STORY_ENGINE_EMBED_DIMENSIONS", "512")
# 老测试默认走剧本路径
os.environ.setdefault("STORY_ENGINE_SCRIPTED_DEMO", "1")

_backend_module = None


def import_backend_main():
    """导入 backend.main 的隔离 helper（P5.11 抽取，原 test_hitl_api 头部样板，
    供任何需要 TestClient 的测试文件共享）。

    - STORY_ENGINE_PROJECT_DIR 指到临时目录，避免测试事件写入真实项目
      data/projects/yupei（backend 模块级单例按环境变量定项目目录）
    - backend.main 导入时会 _load_dotenv()（.env 含真实 LLM key 等），
      os.environ.setdefault 会污染同进程其他测试（实测：key 泄漏使
      LLMPool.is_mock 变 False，test_engine 的 StoryEngineMockEnded 断言失败）。
      导入前快照、导入后还原：backend 单例在导入时已捕获所需配置，还原不影响
      后续使用。注意：backend 侧 LLM 配置按 .env 真实值生效，经 API 触发章节
      生成的用例须确保走剧本（SCRIPTED_DEMO=1 且章号在剧本内）等离线路径。
    - backend.main 是模块级单例，进程内只导入一次，重复调用返回同一模块；
      kernel.close() 统一挂 atexit——各测试文件不得自行 close（单例共享，
      先收尾的文件会关掉 SQLite 连接，波及字母序靠后的使用方）。
    """
    global _backend_module
    if _backend_module is not None:
        return _backend_module
    saved_env = dict(os.environ)
    os.environ["STORY_ENGINE_PROJECT_DIR"] = tempfile.mkdtemp(
        prefix="story_engine_backend_")
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import backend.main as backend
    os.environ.clear()
    os.environ.update(saved_env)
    atexit.register(_close_backend_kernel, backend)
    _backend_module = backend
    return backend


def _close_backend_kernel(backend) -> None:
    try:
        backend.kernel.close()
    except Exception:
        pass
