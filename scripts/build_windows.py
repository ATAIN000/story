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


================================
没有 LLM key？3 分钟申请一个（以 DeepSeek 为例）
================================

DeepSeek 便宜（写 12 章约几毛钱）、写故事够用，适合新手：

1. 打开 DeepSeek 开放平台：https://platform.deepseek.com
2. 注册并登录（手机号即可）
3. 左侧「API keys」→「创建 API key」→ 起个名字 → 复制生成的 key
   （sk- 开头，只显示一次，保存好）
4. 充一点钱：「充值」最低几元即可（按 token 计费，写故事很省）
5. 回到 StoryOS：左侧「设置」→ LLM 接入卡 → 选 DeepSeek →
   粘贴 key → 测试连接 → 保存

对应配置（设置页选 DeepSeek 会自动填好，也可手动填 .env）：
  STORY_ENGINE_LLM_BASE_URL=https://api.deepseek.com/v1
  STORY_ENGINE_LLM_API_KEY=sk-你刚复制的key
  STORY_ENGINE_LLM_MODEL=deepseek-v4-flash   # 快、便宜，量产写故事；
                                              # 要更强质量用 deepseek-v4-pro

注意：DeepSeek 旧模型 deepseek-chat 已于 2026-07 停用，
必须用显式 V4 模型 ID（deepseek-v4-flash 或 deepseek-v4-pro）。

其他 provider 同理：Moonshot（platform.moonshot.cn）、
智谱 GLM（open.bigmodel.cn）、OpenAI（platform.openai.com）——
都是「注册 → 创建 key → 填进设置页」。设置页每个 provider 都有
快捷选项，选中自动填好端点，你只需粘 key。
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
        # 重建前备份用户数据（data/ 是 exe 同级运行产物，不属于构建产物）
        data_src = DIST_DIR / "data"
        data_bak = None
        if data_src.is_dir():
            data_bak = DIST_DIR.parent / ".storyos_data_bak"
            if data_bak.exists():
                shutil.rmtree(data_bak)
            shutil.move(str(data_src), str(data_bak))
        shutil.rmtree(DIST_DIR)
        if data_bak is not None:
            DIST_DIR.mkdir(parents=True, exist_ok=True)
            shutil.move(str(data_bak), str(DIST_DIR / "data"))
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
        sys.path.insert(0, str(ROOT))   # 脚本以 scripts/ 为 sys.path[0]，需补仓库根
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
