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
    ├── genres/                          题材插件 ×29（mystery/romance/wuxia + H7 提升的 26 个融合题材；
    │                                    STORY_ENGINE_GENRE 环境变量切换，默认 mystery；
    │                                    可选 cast: 段声明开局阵容——阵容随题材，不再恒包青天）
    ├── cultures/confucian_officialdom.yaml  文化插件（Hofstede 6维/评书扣子/原型映射）
    └── packs/                           素材包（P7：5 扩展点 7 样例 + _index.yaml 清单）

backend/main.py              FastAPI：/api/project、generate、rollback、reset、config
frontend/                    Vue 3 + Vite + Tailwind（四个可视化面板）
tests/test_engine.py         赌注1/赌注4/核心循环回归测试
```

### 素材包（Packs）

`plugins/packs/` 存放按扩展点分桶的素材包（`story.skill` / `story.language` /
`story.evaluator` / `world.rule` / `story.character.archetype`），由 `_index.yaml`
清单管理（`status: active` 加载、`draft` 跳过）。引擎启动时 registry 宽松扫描
（坏包 warning 跳过不崩），各扩展点按各自方式消费：skill 包注册进内核、language
包并入 Realizer 资源池、evaluator 包扩充 critic 维度库、world.rule 包经 genre
`rule_packs` 键显式引用合并、archetype 包注册可见（消费接线二期）。前端插件视图
经 `GET /api/config` 的 `plugins` 字段展示全部桶（扩展点分桶，含
`story.world.rule` 段 7 包）。格式规范见
`../docs/素材包体系与hermes采集计划.md`。

### 阵容插件化（Cast，P11）

开局阵容随题材，不再恒为包青天：题材 yaml 可写可选 `cast:` 结构化段
（id/role/goals/voice_hint/relations，示例见 mystery.yaml 的包青天五虎数据化）；
无 cast 段时解析 `prompt.characters` 文案（如 romance → 沈砚清/顾明璋/柳含烟）；
两者皆无回退 mock 种子阵容 + warning（不崩）。创世（genesis）与角色 spawn 均
消费解析结果——mystery 保持全量 SEED 保真（剧本演示世界零变化），其余任何
题材开局都是自己的阵容人物。契约见 `../docs/接口规范_part2.md` §11.5。

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
| POST | /api/project/plan | 两阶段生成：只产决策卡（不生成正文） |
| DELETE | /api/project/plan | 作废待批准方案 |
| POST | /api/project/rollback | 回滚到指定 tick（`{"tick": 14}`） |
| POST | /api/project/reset | 重置项目 |
| POST | /api/gacha/draw | 抽卡开局：library 返回题材列表 / synth LLM 合成（mock 恒降级） |
| POST | /api/gacha/confirm | 确认抽卡：card={genre:{name,source,yaml?}} + 可选 worldview/project_name；synth 落盘 + init 切换 |
| POST | /api/project/init | 开局切换：reset + 按 genre/culture 重建单例（进程内覆盖不写 env） |
| GET | /api/projects | 项目列表（扫描 data/projects/*，含 current 字段；老项目补写 project.json） |
| POST | /api/projects/open | 续旧切换：恢复项目自身 genre/culture 整栈重建（404 不存在 / 422 组合非法） |
| GET | /api/projects/{name}/export | 导出项目 zip（sqlite backup 一致快照 + chapters/project.json + training_data） |
| POST | /api/intervene | 作者介入统一入口（textual/structural/character/intent/evaluation） |
| GET | /api/interventions | 介入历史（author_intervention 事件流） |
| POST | /api/hitl/respond | 应答 pending 的 HITL 请求 |
| GET | /api/training/stats | 训练信号计数（skills/preferences/style + recent_skills） |
| POST | /api/paragraph/rewrite | 段落重写（Realizer 单段渲染，只读不写） |
| GET | /api/characters | 角色卡聚合（minds/关系/voice/arc） |
| POST | /api/meta/config | UserIntent → StoryConfig（Module 8 Meta-Generator） |
| GET | /api/settings | 设置视图（env+进程内覆盖；api_key 永不返回） |
| POST | /api/settings | 写进程内覆盖（eval_enabled/ir_first/eval_max_rounds；重启失效） |
| POST | /api/settings/test_llm | LLM 一次性测试连接（ok/延迟/model，key 永不回前端） |

## Phase 6：前端重做（editorial 控制台）

旧版单页 `story.html`（四个可视化面板）重做为 Vue 3 SPA，关键变化：

- **双主题**：日间/夜读（CSS 变量 + 主题切换事件，图表类组件订阅重绘）
- **七视图**：写作台（章节 binder + 手稿 + 两阶段生成）/ 决策卡 / 人物 / 世界观 / 时间线 / 伏笔账 / 插件 + 题材实验室 / 设置
- **段落操作**：改字 / 记一笔 / 重写（Realizer 单段渲染）/ 诊断 四操作直达介入流
- **两阶段生成**：plan 先产决策卡 → confirm 后生成正文（看方案再动笔）
- **介入即事件**：所有作者操作进事件流（可回放、可审计），不直接改状态

后端补量端点见 `docs/接口规范_part2.md` §9.4（P6.1–P6.10）。

## 抽卡开局（Gacha）

独立开局页：选题材 → 选世界观骨架 → 世界观+语言向导微调 → 人物原型占位 → 开工。

- **入口**：左侧 nav「开局」段（置于系统段上方）；写作台零章空态也有「抽卡开局」CTA
- **两模式**：
  - **题材选择（library）**：全量 registry 题材列表（29 个）以卡片网格展示，
    每张卡显示题材名/气质一句话/自带文化徽标/自带阵容摘要，点击选中即可；零 LLM。
    文化默认 `confucian_officialdom`（P14：不再从题材推导，语言维度已融入向导），
    世界规则由世界观向导产出（取代旧的随机抽包栏）
  - **AI 自由发挥（synth）**：LLM 以 mystery.yaml 为模板锚现场合成新题材包，H7 检查集机器校验，失败带反馈重试 1 次，仍失败自动降级为库内组合（卡面 note 说明）；mock 模式恒走库内卡（零 LLM 调用）
- **确认即入库 + 切换**：确认开工后，AI 合成的题材复核落盘 `plugins/genres/`（重名自动 -2 后缀、原子写）并 `registry.reload()` 立即可选；随后 reset 清库 + 同一 Kernel 上按新 genre/culture 重建引擎（进程内覆盖，不改 env/.env，重启回落），直接进第一章 plan。已有章节时先弹重置确认框（可取消）。确认成功后前端**整页刷新**落写作台（P11.2：刷新后 SPA 重拉配置与项目快照，状态天然对齐；失败路径不刷新，停留弹层可重试）

端点契约：`POST /api/gacha/draw`、`POST /api/gacha/confirm`、`POST /api/project/init`，见 `docs/接口规范_part2.md` §9.5。

## 世界观向导（Worldview Wizard）

抽卡确认前的第三段——世界观 + 语言文化向导，让用户从骨架或空白逐层选参数，级联校验后
注入生成管线。架构定义 15 层 86 参数（世界观 L0-L9 共 71 参数 + 语言文化 LANG1-LANG5
共 15 参数），所有取值均为合法枚举。

- **四段式向导**（抽卡页内 stage 状态机）：①题材选择（单栏卡片网格）
  → ②骨架选择（十卡 + 随机 + 空白自定义）→ ③世界观+语言文化分步向导
  （左进度轨分区展示世界观/语言文化 + 右参数卡片）→ ④人物原型占位（即将上线）
- **左栏分区**：世界观层（L0-L9）与语言文化层（LANG1-LANG5）以分隔线 +
  「语言文化」标题分区展示，同一向导页内
- **十骨架**：现实本格 / 修真问道 / 武侠江湖 / 克苏鲁神话 / 赛博朋克 / 西幻史诗 /
  山海志怪 / 无限流 / 末日废土 / 都市灵异——每骨架预填全部 71 世界观参数，选中即预填进
  向导可逐层微调；「随机骨架」从十骨架掷骰子，「空白自定义」从零逐层选
- **动态渲染**：层/参数/选项/连锁全部来自 `GET /api/worldview/schema`，前端无
  硬编码——`layers_covered` 决定哪些层已上线（当前 L0-L9 + LANG1-LANG5 全上线）
- **级联校验**：每次改选 debounce 300ms 调 `POST /api/worldview/evaluate`，
  收窄后的合法值集实时灰掉越界 chip（带原因 tooltip），已选值命中违例则标红；
  进度轨标记每层状态（done/current/todo/violation）
- **确认拦截**：确认开工前全量 evaluate，violations 非空则 toast 拦截并跳到首个
  违例所在层；通过则 confirm 携带 `worldview: {layers, preset?}` 落盘
- **双通道融合**（P12.3）：落盘的世界观档案通过两条独立通道进入生成管线——
  - **prompt 注入（软）**：`to_prompt_text()` 生成 `## 世界观设定` 段拼进章节
    生成 prompt，让 LLM 在选词/场景/氛围上贴合世界观
  - **world_rules 合并（硬）**：`to_world_rules()` 把可表达为布尔事实的设定
    （限 5 事实词汇表）翻译成 validator 可执行规则，追加进统一 world_rules 列表

端点契约：`GET /api/worldview/schema`、`POST /api/worldview/evaluate`、
`POST /api/gacha/confirm` 的 `worldview` 扩展，见 `docs/接口规范_part2.md` §11.6。

## 多项目管理（Projects）

每个项目是一个独立目录 `data/projects/<name>/`（自带 story.db 事件溯源库 + chapters.json +
project.json 元数据 + training_data/），互不干扰；后端持有「当前项目栈」，切换即整栈重建。

- **项目页**：左侧 nav 最顶部「项目」段。卡片列表展示每个项目的题材/文化/章节数/head tick/最后打开时间，当前项目带徽标高亮
- **开新（抽卡）**：项目页「开新项目」→ 抽卡页 → 确认时选「作为新项目开局」并输项目名（字母/数字/-/_）→ 后端建独立目录并切换过去，成功后整页刷新落写作台、直接进第一章 plan；重名 409 提示改名（弹层停留不刷新，可重试）
- **续旧**：卡片「继续」→ 整栈切换到该项目，**恢复其自身题材/文化**（读 project.json，不是 env 默认），写 last_opened_at；切换成功**整页刷新**落写作台（P11.2，替代原 SPA 内跳转；失败 toast 停留本页不刷新）；当前项目卡显示「进行中」
- **导出分发**：卡片「导出」→ 下载 `{name}-story.zip`（story.db 为 sqlite backup 一致快照 + chapters.json/project.json + training_data/）；解压到 `data/projects/<name>/` 即可在任一实例打开

端点契约：`GET /api/projects`、`POST /api/projects/open`、`GET /api/projects/{name}/export` 及 `POST /api/gacha/confirm` 的 `project_name` 扩展，见 `docs/接口规范_part2.md` §9.6。

## 已知边界（下一步路线）

- Mock 剧本仅 3 章；真实 LLM 模式下违规是**有机产生**的（可能一次通过，面板会如实显示）
- 对白质量盲区（验证报告：8.3% 召回率）需 DialogueCritic —— Module 6 待建
- 记忆系统（16-bank + sqlite-vec 混合检索）、CharacterActor 完整实现为 Phase 2
- 分层 IR（bet7 部分通过）与语言 realizer 插件为 Phase 3
