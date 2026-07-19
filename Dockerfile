# Story Engine Demo — FastAPI + Vue3（前端已预构建为 frontend/dist）
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
    PORT=8000

# LLM 配置（可选；不配置则 Mock 模式跑通全流程）：
#   -e STORY_ENGINE_LLM_MODE=openai \
#   -e STORY_ENGINE_LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4 \
#   -e STORY_ENGINE_LLM_API_KEY=xxx \
#   -e STORY_ENGINE_LLM_MODEL=glm-4-flash

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
