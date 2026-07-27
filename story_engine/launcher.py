"""StoryOS 桌面启动器（PyInstaller 入口 / 源码直接运行亦可）。

职责（薄引导，业务全在 backend.main）：
  1. 解析两个根：资源根（冻结包的 sys._MEIPASS / 源码仓库根）与
     数据根（exe 同级目录，可写：.env / data/projects / logs）
  2. 首启引导：数据根无 .env → 从内置 .env.example 复制；未配 API key
     → 演示模式（mock，离线可跑通全流程）
  3. 端口：8111 起向上找空闲端口；启动后自动开浏览器
  4. 以对象方式 uvicorn 跑 backend.main:app（避免冻结包内字符串再导入）
"""
from __future__ import annotations

import os
import shutil
import socket
import sys
import threading
import webbrowser
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS",
                           Path(__file__).resolve().parent.parent))
# 数据根：冻结时 = exe 同级（可写）；源码运行时 = 仓库根（开发行为不变）
HOME = Path(sys.executable).resolve().parent if FROZEN else BUNDLE_ROOT


def _load_dotenv(path: Path) -> None:
    """轻量 .env 注入（setdefault，不覆盖已存在的环境变量）。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def _bootstrap_env() -> dict:
    """首启引导 + 路径接线，返回启动信息（供控制台打印）。"""
    env_file = HOME / ".env"
    if not env_file.exists():
        example = BUNDLE_ROOT / ".env.example"
        if example.exists():
            shutil.copy(example, env_file)
    _load_dotenv(env_file)
    # 在线配置（设置页 persist）写回的目标 .env 必须与本文件一致——
    # 缺省 _persist_env 会写进包内 _internal/.env，重启即丢
    os.environ.setdefault("STORY_ENGINE_DOTENV", str(env_file))

    projects_root = HOME / "data" / "projects"
    projects_root.mkdir(parents=True, exist_ok=True)
    (HOME / "logs").mkdir(exist_ok=True)
    os.environ.setdefault("STORY_ENGINE_PROJECTS_ROOT", str(projects_root))
    # 初始项目目录：已有项目取第一个，否则给个空目录（懒建库）
    existing = [d for d in sorted(projects_root.iterdir())
                if d.is_dir() and (d / "story.db").exists()] \
        if projects_root.exists() else []
    default_project = existing[0] if existing else projects_root / "我的故事"
    os.environ.setdefault("STORY_ENGINE_PROJECT_DIR", str(default_project))
    os.environ.setdefault("STORY_ENGINE_FRONTEND_DIST",
                          str(BUNDLE_ROOT / "frontend" / "dist"))
    # 分发版默认 dummy 嵌入（不拉本地模型；要高级记忆检索自行改 local）
    os.environ.setdefault("STORY_ENGINE_EMBED_MODE", "dummy")

    key = os.environ.get("STORY_ENGINE_LLM_API_KEY", "").strip()
    # .env.example 的占位符（"sk-在这里填你的…"）不算真 key
    demo = (not key) or ("填你的" in key) or ("在这里" in key)
    if demo:
        # .env.example 默认 STORY_ENGINE_LLM_MODE=openai；无 key 时 openai
        # 模式必失败——演示模式直接强制 mock（用户配上 key 即自动转真实）
        os.environ["STORY_ENGINE_LLM_MODE"] = "mock"
        # mock 剧本章仅数百字，过不了 P23.4 字数下限——演示模式关质量门
        os.environ.setdefault("STORY_ENGINE_QUALITY_GATE", "0")
    return {"demo": demo, "env_file": env_file}


def _free_port(preferred: int = 8111, tries: int = 20) -> int:
    for port in range(preferred, preferred + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"端口 {preferred}-{preferred + tries - 1} 均被占用")


def main() -> None:
    os.chdir(HOME)  # 日志等相对路径产物锚定到数据根（logs/ 为 cwd 相对）
    info = _bootstrap_env()
    port = _free_port()
    url = f"http://127.0.0.1:{port}"

    print("=" * 56)
    print("  StoryOS 故事工作台")
    print(f"  数据目录：{HOME}")
    print(f"  访问地址：{url}")
    if info["demo"]:
        print("  模式：演示（未配置 LLM key，剧本生成）")
        print(f"  配置真实 LLM：编辑 {info['env_file']} 后重启")
    else:
        print("  模式：真实 LLM")
    print("  关闭本窗口即退出。浏览器未自动打开请手动访问上述地址。")
    print("=" * 56)

    threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    import uvicorn
    from backend.main import app
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
