@echo off
REM StoryOS 一键启动（Windows）：检查依赖 → 起后端 → 打开浏览器
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 python，请先安装 Python 3.11+ 并加入 PATH
    pause
    exit /b 1
)

echo 检查依赖...
pip show fastapi >nul 2>&1
if errorlevel 1 (
    echo 安装依赖中（仅首次）...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败
        pause
        exit /b 1
    )
)

echo.
echo 启动 StoryOS ... 打开 http://localhost:8111
echo 首次为 Mock 演示模式；左侧「设置」页可在线配置真实 LLM。
echo 按 Ctrl+C 停止。
echo.
start "" "http://localhost:8111"
python -m uvicorn backend.main:app --port 8111
