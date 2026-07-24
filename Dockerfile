# StoryOS — FastAPI + Vue3（前端已预构建为 frontend/dist）
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY story_engine/ story_engine/
COPY backend/ backend/
COPY frontend/dist/ frontend/dist/
COPY data/ data/

ENV STORY_ENGINE_PROJECT_DIR=/app/data/projects/yupei \
    STORY_ENGINE_FRONTEND_DIST=/app/frontend/dist \
    PORT=8111

# 镜像内含 yupei 演示项目（公案悬疑样章）；要干净初始状态：
#   docker run ... 后删除 /app/data/projects/yupei，或挂载自己的 data 目录：
#   -v $(pwd)/data:/app/data
#
# LLM 配置（推荐启动后在设置页在线配置；也可注入环境变量）：
#   -e STORY_ENGINE_LLM_MODE=openai \
#   -e STORY_ENGINE_LLM_BASE_URL=https://api.moonshot.cn/v1 \
#   -e STORY_ENGINE_LLM_API_KEY=sk-xxx \
#   -e STORY_ENGINE_LLM_MODEL=kimi-k2.6

EXPOSE 8111
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8111"]
