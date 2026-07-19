# 故事引擎 Story OS · 可视化控制台 Demo

> 核心哲学：**LLM 从"作者"降级为"语言层"，一致性的责任交给结构化世界模拟层。**
> 本 Demo 把《Story Engine 工程蓝图 v2.0 / 接口规范 v1.0》的核心循环做成了可运行、可观察的系统。

## 这个 Demo 演示什么

以悬疑公案《包青天·玉佩案》为例，完整跑通**核心循环**（深度验证报告验证过的唯一价值来源）：

```
Showrunner 决策卡 → LLM 生成初稿 → 事件抽取 → 7 步硬约束验证
   → 发现违规 → LLM 修正（WorldState + 违规报告为基准）→ 复验
   → commit 事件（事件溯源）→ 伏笔池更新 → snapshot
```

三章各演示一类**硬约束**违规的自动发现与自动修正：

| 章 | 违规类型 | 剧情表现 | 修正方式 |
|---|---|---|---|
| 1 报案与初审 | 认知 (Epistemic EC) | 包拯直接点破他不可能知道的赌债（worldstate_paradox 的 D 组情形） | 改为合法审问，以「袖口当票」埋伏笔 |
| 2 暗访赌坊 | 物理 (Event Calculus) | 展昭人在赌坊却出现在公堂呈证 | 补「赶回开封府」状态转移事件 |
| 3 夜审与收网 | 世界规则 (Z3 SMT) | 冤魂托梦直接定罪（Sanderson 第一律） | 梦只做氛围，定罪改为物证+人证+动机三链汇合 |

四个可视化面板：

- **核心循环**：初稿（红标违规片段）→ 7步验证明细 → 修正稿（绿标修正片段）前后对比
- **世界状态**：物理层 fluents / 关系层 CiF 强度 / 心智层 knows·doesnt_know·secrets·goals·affect / 叙事层多轨道进度与因果 DAG
- **事件时间线**：append-only 事件日志、snapshot、**可交互回滚**（回滚后重生成 = 交替时间线，旧时间线保留可见）+ CFPG 伏笔池 (F,T,P) 全生命周期
- **决策卡**：Showrunner 10 步 control loop 产物 —— 五轨道调度、Sternberg 三主因错峰、Todorov beat 规划、Snyder 15 拍覆盖、评书扣子集末钩子

## 快速开始

### Docker（推荐）

```bash
docker build -t story-engine .
docker run -p 8000:8000 story-engine
# 打开 http://localhost:8000
```

镜像内置已生成好的演示项目（3 章 + 一次回滚演示）。点「生成下一章」会提示 Mock 剧本已完结；
在时间线面板**回滚到任意 snapshot** 后可继续生成（交替时间线）。

### 接入真实 LLM（OpenAI 兼容协议）

**默认演示节奏**：前 3 章为剧本化教学演示（三类违规的教科书案例，零 API 成本），
第 4 章起真实 LLM 有机续写（设 `STORY_ENGINE_SCRIPTED_DEMO=0` 可关掉剧本全程真实生成）。

**Kimi Code 套餐 key（sk-kimi- 前缀）**——已实测打通，注意四点：

```bash
docker run -p 8000:8000 \
  -e STORY_ENGINE_LLM_MODE=openai \
  -e STORY_ENGINE_LLM_BASE_URL=https://api.kimi.com/coding/v1 \
  -e STORY_ENGINE_LLM_API_KEY=sk-kimi-你的key \
  -e STORY_ENGINE_LLM_MODEL=kimi-for-coding \
  story-engine
```

1. 端点必须带 `/coding/v1`（与 api.moonshot.cn 是**独立认证体系**，不互通）
2. 必须带 Coding-Agent User-Agent（客户端已自动处理：`claude-code/0.1.0`）
3. 思考约束：思考模式 temperature 只能 1；非思考（`thinking:disabled`）只能 0.6——客户端自动适配
4. 思考型模型会把 token 预算烧在 reasoning 上导致正文为空——客户端已加"空内容自动换参数重试"兜底
   （默认走非思考模式省钱；设 `STORY_ENGINE_LLM_THINKING=on` 启用思考模式）

⚠️ Kimi Code 套餐按周期配额，且该模型按 coding 场景设计。**写故事更推荐 Moonshot 开放平台
（platform.moonshot.cn）的 kimi-k2.6 / kimi-k3 key**——通用模型、按量计费、无 UA 特殊要求，
base_url 用 `https://api.moonshot.cn/v1` 即可。

GLM / DeepSeek / OpenAI 等任何兼容 `/chat/completions` 的 provider 同样可用。

### 本地开发

```bash
pip install -r requirements.txt

# 后端（http://localhost:8111，同时托管前端构建产物）
python -m uvicorn backend.main:app --reload --port 8111

# 前端开发（可选，热更新，端口 3111 代理到 8111）
cd frontend && npm install && npm run dev
# 前端构建：npm run build
```

### 运行测试

```bash
python -m pytest tests/ -q    # 100+ 测试：赌注/核心循环/内核/角色/元生成 + Phase 3（genre 插件/决策卡/pacing/原语/planner/概念整合/换题材验收）
```

## 架构（与蓝图 Module 对应）

```
story_engine/                ← 纯 Python 核心包（不依赖 Web 框架）
├── types.py                 全局类型系统（WorldEvent/WorldState/CFPG/CharacterMind）
├── event_store.py           Module 1.1 事件溯源（SQLite WAL / snapshot / 多 timeline 回滚）
├── validator.py             Module 1.3 七步硬约束验证管线
│                            时序TKG → 物理EC → 认知Epistemic → 因果DAG → 意图IPOCL → Z3 SMT → 软判定
├── registry.py              Module 0.2 扩展点注册表（8 扩展点，YAML manifest 懒加载）
├── llm.py                   Module 0.4 LLMClient（mock / openai 兼容双模式，调用留痕）
├── showrunner/              Module 3  多轨道调度器子包（10 步 control loop → 决策卡；tracks/decision/pacing）
├── engine.py                核心循环编排器（生成/检查/修正三通道分离 — worldstate_paradox）
├── mock_script.py           《玉佩案》3 章剧本（含三类违规的教科书式演示）
└── plugins/
    ├── genres/mystery.yaml              题材插件·悬疑公案（五轨道/世界规则/评估权重/禁忌）
    ├── genres/romance.yaml              题材插件·古代言情（四轨道/phase_beats/pacing_targets，Phase 3 新增）
    ├── genres/wuxia.yaml                题材插件·武侠（culture_bound 组合校验示例）
    └── cultures/confucian_officialdom.yaml  文化插件（Hofstede 6维/评书扣子/原型映射）

backend/main.py              FastAPI：/api/project、generate、rollback、reset、config
frontend/                    Vue 3 + Vite + Tailwind（四个可视化面板）
tests/test_engine.py         赌注1/赌注4/核心循环回归测试
```

## 关键设计决策（来自调研与验证报告）

1. **三通道分离**（worldstate_paradox 的架构解）：生成 prompt 不含 WorldState 秘密
   （doesnt_know/secret 不注入）；检查与修正 prompt 以 WorldState 为基准。
2. **修正回路 = 100% 价值来源**：只检查不修正是零价值——本 Demo 的每章都展示完整闭环。
3. **状态外部化**：轨道进度/伏笔债/Sternberg 主因维护在显式数据结构，不靠 LLM 注意力。
4. **事件溯源的 git 语义**：事件只追加永不修改；回滚移动 head 指针并开启新 timeline，
   同一 tick 以最新 timeline 为准，旧时间线保留可审计。

## v3.0 蓝图对齐情况

| v3.0 修正 | 状态 |
|---|---|
| 赌注2 Culture-bound genre（culture_bound + allowed_cultures 白名单 + 组合校验） | ✅ 已落地（含 wuxia.yaml 示例） |
| 赌注5 Critic 维度按类型裁剪（active_critics 从 Genre 插件加载） | ✅ 已落地（mystery 4 维） |
| 赌注5 Critic 议会串联模式（单 judge 粗筛 → 多 critic 精审 + 共振加权） | 📋 Phase 3（Module 6） |
| 赌注6 IR 双层结构 / Realizer 共创者 / Subtext interlingua | 📋 Phase 3（Module 5） |
| 赌注7 混合检索（关键词倒排+向量保召回，三因子只排序） | 📋 Phase 2（记忆系统） |

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/config | 运行配置（LLM 模式、插件、三轴） |
| GET | /api/project | 项目完整快照（世界状态/事件/伏笔/章节/决策卡） |
| POST | /api/project/generate | 生成下一章（核心循环） |
| POST | /api/project/rollback | 回滚到指定 tick（`{"tick": 14}`） |
| POST | /api/project/reset | 重置项目 |

## 已知边界（下一步路线）

- Mock 剧本仅 3 章；真实 LLM 模式下违规是**有机产生**的（可能一次通过，面板会如实显示）
- 对白质量盲区（验证报告：8.3% 召回率）需 DialogueCritic —— Module 6 待建
- 记忆系统（16-bank + sqlite-vec 混合检索）、CharacterActor 完整实现为 Phase 2
- 分层 IR（bet7 部分通过）与语言 realizer 插件为 Phase 3
