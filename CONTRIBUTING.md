# 贡献指南

感谢你对 StoryOS 故事引擎的兴趣！这份指南帮你快速参与。

## 环境

- Python 3.11+（推荐 3.11 或 3.12）
- Node.js 18+（仅前端开发需要）
- 一个 LLM provider 的 API key（可选；不带 key 也能用 Mock 演示模式跑通）

```bash
pip install -r requirements.txt
python -m uvicorn backend.main:app --reload --port 8111

# 前端热更新开发（可选）
cd frontend && npm install && npm run dev
```

## 测试

提交前请确保测试全绿：

```bash
python -m pytest tests/ -q
```

CI（`.github/workflows/ci.yml`）会在 Python 3.11 / 3.12 两个版本上自动跑同一套测试，PR 必须通过才能合并。

## 代码规范

后端用 [ruff](https://docs.astral.sh/ruff/) 做静态检查与格式化，配置在 `pyproject.toml` 的 `[tool.ruff]` 段。提交前本地跑一次：

```bash
ruff check .
ruff format .
```

> 配置文件里默认把已知的巨型历史文件（`story_engine/worldview/layers.py` 等）放进了 `extend-exclude`，
> 是为了不一次性改动存量代码。新写的文件请保持规范。

## 提交 PR

1. 从 `main` 拉分支：`git checkout -b feat/你的改动`
2. 改动尽量小而聚焦，一个 PR 解决一个问题
3. 如果加了新功能，补上对应测试（`tests/test_*.py`）
4. PR 描述里写清楚**改了什么、为什么改、怎么测的**
5. 等 CI 跑绿，等 maintainer review

## 代码结构速览

```
story_engine/      纯 Python 核心包（不依赖 Web 框架，可独立测试）
backend/main.py    FastAPI Web 层（薄，只做 HTTP/WS 编排）
frontend/          Vue 3 SPA
tests/             pytest 测试套件
data/projects/     运行时项目数据（每项目一目录，不要提交）
```

**核心原则**：Web 层（`backend/`）保持薄，业务逻辑全部放在 `story_engine/` 核心包里，这样核心逻辑能被 `tests/` 直接覆盖，不依赖 HTTP。

## 报告问题

- Bug 请去 Issues 区开新 issue，附上：复现步骤、期望行为、实际行为、`trace_id`（日志里有）
- 新功能建议也走 Issues，先讨论再动手写

## 行为准则

请保持友善、尊重。对事不对人。不当言论会被删除。
