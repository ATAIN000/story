"""测试全局 fixture：强制 dummy embedding，避免拉本地模型。"""
from __future__ import annotations

import os

# 必须在 import Embedder / Kernel 之前生效
os.environ["STORY_ENGINE_EMBED_MODE"] = "dummy"
os.environ.setdefault("STORY_ENGINE_EMBED_DIMENSIONS", "512")
# 老测试默认走剧本路径
os.environ.setdefault("STORY_ENGINE_SCRIPTED_DEMO", "1")
