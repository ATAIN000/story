#!/usr/bin/env python
"""Windows 免安装包构建脚本（PyInstaller onedir）。

用法（仓库根目录）：
    .venv/Scripts/python.exe scripts/build_windows.py [--zip]

流程：
  1. 确保 pyinstaller 可用（缺则提示 pip install）
  2. 前端 dist 存在性检查（缺则提示先 npm run build）
  3. 清理并运行 PyInstaller（scripts/storyos.spec）
  4. 写使用说明到 dist/StoryOS/使用说明.txt；--zip 时打 zip
产出：dist/StoryOS/（StoryOS.exe 双击即用）
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT / "dist" / "StoryOS"
SPEC = ROOT / "scripts" / "storyos.spec"

README = """StoryOS 故事工作台 · 使用说明
================================

1. 双击 StoryOS.exe 启动（首次约 10-20 秒，控制台窗口会显示访问地址）。
2. 浏览器会自动打开 http://127.0.0.1:8111（端口被占用时自动顺延）。
3. 未配置 LLM key 时进入【演示模式】：全流程可点，章节为剧本生成。
4. 配置真实 LLM：编辑本目录下的 .env（首启自动生成），填入
   STORY_ENGINE_LLM_BASE_URL / STORY_ENGINE_LLM_API_KEY /
   STORY_ENGINE_LLM_MODEL，保存后重启 StoryOS.exe。
5. 你的所有数据都在本目录下：data/projects（项目）、logs（日志）。
   整个文件夹可随意移动/备份；删除即完全卸载。
6. 关闭黑色控制台窗口即退出程序。

注意：请把整个 StoryOS 文件夹解压到你有写权限的位置
（桌面/文档/D 盘等），不要直接放在 Program Files 里运行。
"""


def main() -> int:
    make_zip = "--zip" in sys.argv
    if not (ROOT / "frontend" / "dist" / "index.html").exists():
        print("× 缺 frontend/dist，先 cd frontend && npm run build")
        return 1
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("× 缺 pyinstaller：.venv/Scripts/pip.exe install pyinstaller")
        return 1

    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    print("→ PyInstaller 构建中（几分钟）…")
    r = subprocess.run(
        [sys.executable, "-m", "PyInstaller", str(SPEC), "--noconfirm",
         "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build")],
        cwd=ROOT)
    if r.returncode != 0:
        print("× 构建失败")
        return r.returncode

    (DIST_DIR / "使用说明.txt").write_text(README, encoding="utf-8")
    print(f"√ 产出：{DIST_DIR}")

    if make_zip:
        from story_engine import __version__
        zip_path = ROOT / "dist" / f"StoryOS-windows-v{__version__}.zip"
        if zip_path.exists():
            zip_path.unlink()
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(DIST_DIR.rglob("*")):
                if p.is_file():
                    zf.write(p, p.relative_to(DIST_DIR.parent))
        print(f"√ 打包：{zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
