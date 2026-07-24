#!/usr/bin/env bash
# StoryOS 一键启动（macOS/Linux）：检查依赖 → 起后端 → 打开浏览器
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    echo "[错误] 未找到 python3，请先安装 Python 3.11+"
    exit 1
fi

if ! python3 -c "import fastapi" >/dev/null 2>&1; then
    echo "安装依赖中（仅首次）..."
    pip3 install -r requirements.txt
fi

echo ""
echo "启动 StoryOS ... 打开 http://localhost:8111"
echo "首次为 Mock 演示模式；左侧「设置」页可在线配置真实 LLM。"
echo "按 Ctrl+C 停止。"
echo ""
( sleep 2 && (command -v open >/dev/null && open http://localhost:8111 || xdg-open http://localhost:8111 2>/dev/null || true) ) &
python3 -m uvicorn backend.main:app --port 8111
