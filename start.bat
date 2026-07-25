@echo off
chcp 65001 >nul 2>&1
REM StoryOS 一键启动（Windows）
REM 自动创建 .venv 虚拟环境 → 安装依赖 → 起后端 → 打开浏览器
cd /d "%~dp0"

REM ---- 查找 Python 3.11+ ----
set "PY="
for %%c in (python py) do (
    %%c -c "import sys; exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
    if not errorlevel 1 (
        set "PY=%%c"
        goto found
    )
)
echo [错误] 未找到 Python 3.11+，请先安装并加入 PATH
pause
exit /b 1

:found

REM ---- 检测国内网络 → 阿里源 ----
set "PIP_MIRROR="
ping -n 1 -w 2000 mirrors.aliyun.com >nul 2>&1
if not errorlevel 1 (
    echo [检测] 国内网络环境，使用阿里 PyPI 源加速
    set "PIP_MIRROR=-i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com"
)

REM ---- 创建虚拟环境 ----
if not exist ".venv\Scripts\activate.bat" (
    echo 创建虚拟环境 .venv ...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo [错误] 虚拟环境创建失败
        pause
        exit /b 1
    )
)
call .venv\Scripts\activate.bat

REM ---- 安装依赖 ----
python -c "import fastapi" >nul 2>&1
if errorlevel 1 (
    echo 安装依赖中（首次较慢，约 2-3 分钟）...
    call pip install %PIP_MIRROR% -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败
        pause
        exit /b 1
    )
)

REM ---- 启动 ----
echo.
echo 启动 StoryOS ... 打开 http://localhost:8111
echo 首次为 Mock 演示模式；左侧「设置」页可在线配置真实 LLM。
echo 按 Ctrl+C 停止。
echo.
start "" "http://localhost:8111"
python -m uvicorn backend.main:app --port 8111
