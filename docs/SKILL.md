# StoryOS 自动化生成技能 (SKILL)

## 概述

通过 API 调用 StoryOS，实现全自动化的故事项目生成流程：创建项目 → 宏观规划 → 逐章生成 → 质量监控。

## 前置条件

- StoryOS 后端运行在 `http://localhost:8111`
- 已配置 LLM API Key（`.env` 中 `STORY_ENGINE_LLM_*`）
- `STORY_ENGINE_SCRIPTED_DEMO=0`（Actor 模式）
- `STORY_ENGINE_QUALITY_GATE=1`（质量门禁开启）

## API 流程

### 1. 创建项目（抽卡开局）

```bash
# 开始抽卡 session
curl -X POST http://localhost:8111/api/gacha/begin

# 返回 {sid: "xxx"}，然后用 session 确认开工：
curl -X POST http://localhost:8111/api/gacha/{sid}/confirm \
  -H "Content-Type: application/json" \
  -d '{
    "project_name": "my-novel",
    "worldview": {"layers": {...}, "preset": "shanhai_zhiguai"},
    "cast": [...],
    "macro_plan": {...}
  }'
```

### 2. 生成宏观计划（WebSocket）

```javascript
// 连接 WebSocket 流式生成
const ws = new WebSocket(`ws://localhost:8111/api/gacha/{sid}/macro/stream`)
ws.onopen = () => ws.send(JSON.stringify({
  template_name: "save_the_cat_15",
  worldview: {layers: {...}},
  cast: [...]
}))
ws.onmessage = (ev) => {
  const msg = JSON.parse(ev.data)
  // msg.type: "delta"(流式文本) | "complete"(最终计划) | "error"
}
```

### 3. 逐章生成（异步 + WebSocket 进度）

```bash
# 生成决策卡
curl -X POST http://localhost:8111/api/project/plan

# 启动异步生成
curl -X POST http://localhost:8111/api/project/generate/async \
  -H "Content-Type: application/json" \
  -d '{"mode": "confirm"}'
# 返回 {started: true, chapter_no: 1}
```

```javascript
// WebSocket 实时进度
const ws = new WebSocket('ws://localhost:8111/api/project/generate/stream')
ws.onmessage = (ev) => {
  const msg = JSON.parse(ev.data)
  // msg.type: "progress"(stage+detail) | "status"(stage更新) | "complete"(章节记录) | "error"
}
```

```bash
# 查询生成状态（切走再回来时用）
curl http://localhost:8111/api/project/generation-status
# 返回 {busy, chapter_no, stage, stage_detail, finished, result, error, log_entries}
```

### 4. 连续生成多章

```python
import requests
import time

BASE = "http://localhost:8111"

def generate_chapters(total=12):
    for ch in range(1, total + 1):
        # Step 1: 生成决策卡
        requests.post(f"{BASE}/api/project/plan")
        
        # Step 2: 启动异步生成
        r = requests.post(f"{BASE}/api/project/generate/async",
                         json={"mode": "confirm"})
        assert r.json()["started"]
        
        # Step 3: 轮询等待完成
        while True:
            s = requests.get(f"{BASE}/api/project/generation-status").json()
            if s["finished"]:
                if s["error"]:
                    print(f"第{ch}章失败: {s['error']}")
                    break
                result = s["result"]
                text = result.get("final", {}).get("text", "")
                print(f"第{ch}章完成: {len(text)}字, title={result.get('title','')}")
                break
            time.sleep(5)  # 5秒查一次
        
        # 质量门禁会自动拦截不达标章节并重试
```

### 5. 导出故事圣经

```bash
curl -X POST http://localhost:8111/api/macro/export-bible
# 返回 {bible: "结构化故事圣经文本（Markdown）"}
```

### 6. 导出项目（ZIP）

```bash
curl -o my-novel.zip http://localhost:8111/api/projects/my-novel/export
```

## 关键约束

- **生成中禁止切换项目**：`/api/projects/open` 在生成中返回 409
- **质量门禁**：`STORY_ENGINE_QUALITY_GATE=1` 时，非叙事文本/过短章节/动作日志会被拒绝落盘并自动重试（最多2次）
- **每章约 10 分钟**（Actor 5轮 × 4角色 propose + Realizer + 验证修正）
- **并发限制**：全局只允许一个生成任务（`gen_state.busy()` 锁）

## 质量检查点

生成完成后可检查：

```bash
# 全书章节列表
curl http://localhost:8111/api/project | python -c "
import sys, json
d = json.load(sys.stdin)
for c in d.get('chapters', []):
    t = c.get('final', {}).get('text', '')
    print(f'第{c[\"no\"]}章 {c.get(\"title\",\"\")} {len(t)}字')
"

# 宏观偏差检测
curl http://localhost:8111/api/macro/deviation

# 生成进度
curl http://localhost:8111/api/macro/progress
```

## 环境变量速查

| 变量 | 默认值 | 说明 |
|---|---|---|
| `STORY_ENGINE_SCRIPTED_DEMO` | 1 | 0=Actor模式（真实LLM），1=剧本模式 |
| `STORY_ENGINE_QUALITY_GATE` | 1 | 质量门禁开关（0=测试用关闭） |
| `STORY_ENGINE_IR_FIRST` | 1 | IR-first 叙事管线 |
| `STORY_ENGINE_EVAL_ENABLED` | 1 | 自评迭代 |
| `STORY_ENGINE_ACTOR_MAX_TICKS` | 5 | 每章 Actor 轮次上限 |
| `STORY_ENGINE_ACTOR_TARGET_ACTIONS` | 2×角色数 | 行动数提前退出阈值（0=跑满上限） |
| `STORY_ENGINE_LLM_THINKING` | on | GLM 等思考开关：off=全关，creative=仅创作保留（推荐） |
| `STORY_ENGINE_EMBED_MODE` | local | 向量嵌入模式（local=dge-small-zh） |
