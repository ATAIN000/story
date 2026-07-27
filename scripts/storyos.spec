# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — StoryOS 免安装文件夹（onedir）。

构建：.venv/Scripts/python.exe -m PyInstaller scripts/storyos.spec --noconfirm
产出：dist/StoryOS/StoryOS.exe（双击即用；数据写在 exe 同级 data/、logs/、.env）

收集内容：
- story_engine/plugins/**  384 个题材/文化/技能插件包（YAML 数据文件）
- frontend/dist/**         已编译前端（后端 StaticFiles 托管）
- .env.example             首启引导的 .env 模板
排除：pytest、torch/transformers（嵌入 dummy 默认，懒加载不进包）、用户 .env。
"""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules
import os

# 构建脚本以仓库根为 cwd 调用（scripts/build_windows.py cwd=ROOT），
# 直接以 cwd 定位；SPECPATH 在部分 PyInstaller 版本下会指到 workpath 副本
ROOT = os.getcwd()

block_cipher = None

datas = [
    (os.path.join(ROOT, "story_engine", "plugins"),
     "story_engine/plugins"),
    (os.path.join(ROOT, "frontend", "dist"), "frontend/dist"),
    (os.path.join(ROOT, ".env.example"), "."),
]
datas += collect_data_files("z3", include_py_files=False)

hiddenimports = collect_submodules("uvicorn") + [
    "backend.main",
    "story_engine.launcher",
    "yaml",
    "loguru",
    "httpx",
    "multipart",
]

a = Analysis(
    [os.path.join(ROOT, "story_engine", "launcher.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest", "_pytest", "unittest.mock",
        "torch", "transformers", "sentence_transformers", "fastembed",
        "pandas", "onnxruntime",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="StoryOS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,          # 保留控制台：显示地址/演示模式提示，关闭即退出
    icon=None,
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, upx_exclude=[],
    name="StoryOS",
)
