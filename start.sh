#!/usr/bin/env bash
# StoryOS 一键启动（macOS/Linux）
# 自动创建 .venv 虚拟环境 → 安装依赖 → 起后端 → 打开浏览器
set -e
cd "$(dirname "$0")"

# ---- 查找 Python ----
PY=""
for cmd in python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        ver=$("$cmd" -c 'import sys; print(sys.version_info >= (3, 11))' 2>/dev/null || echo "False")
        if [ "$ver" = "True" ]; then PY="$cmd"; break; fi
    fi
done
if [ -z "$PY" ]; then
    echo "[错误] 未找到 Python 3.11+，请先安装"
    exit 1
fi

# ---- 检测国内网络 → 阿里源 ----
PIP_INDEX=""
if curl -s --connect-timeout 3 https://mirrors.aliyun.com >/dev/null 2>&1; then
    echo "[检测] 国内网络环境，使用阿里 PyPI 源加速"
    PIP_INDEX="-i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com"
fi

# ---- 创建虚拟环境 ----
if [ ! -d ".venv" ]; then
    echo "创建虚拟环境 .venv ..."
    "$PY" -m venv .venv
fi
# 激活
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
else
    echo "[错误] 虚拟环境创建失败"
    exit 1
fi

# ---- 安装依赖 ----
python -c "import fastapi" 2>/dev/null || {
    echo "安装依赖中（首次较慢，约 2-3 分钟）..."
    if [ -n "$PIP_INDEX" ]; then
        pip install $PIP_INDEX -r requirements.txt
    else
        pip install -r requirements.txt
    fi
}

# ---- 启动 ----
echo ""
echo "启动 StoryOS ... 打开 http://localhost:8111"
echo "首次为 Mock 演示模式；左侧「设置」页可在线配置真实 LLM。"
echo "按 Ctrl+C 停止。"
echo ""
( sleep 2 && (command -v open >/dev/null && open http://localhost:8111 || xdg-open http://localhost:8111 2>/dev/null || true) ) &
python -m uvicorn backend.main:app --port 8111
