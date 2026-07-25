"""backend 包入口。

导入 backend 包即触发 backend.main 加载（app / deps / helpers / routers 就位）。
测试通过 backend.app / backend.deps / backend.helpers / backend.routers 访问。
"""
from __future__ import annotations

# 导入 main 触发完整初始化（_load_dotenv → 构造栈 → app）
from backend import main, deps, helpers, models  # noqa: F401
from backend.main import app  # noqa: F401
