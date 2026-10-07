# StoryOS 开局抽卡（纯前端版）设计

日期：2026-10-07
状态：已实现（2026-10-07，人工浏览器验证待用户确认）

## 背景与目标

StoryOS 完整系统（Python 后端 + LLM 生成）太重，且 LLM 开局输出趋于平庸。把开局设计抽出来做成**纯前端抽卡工具**，部署到 https://atposs.com/ 主页，让访客一键体验「题材 × 世界观 × 骨架」的组合创意，不调用任何大模型。

- 形态：**抽卡一键生成**（不做向导、不做分步），可无限重 Roll
- 产出：**完整开局包**（题材卡 + 骨架 + 世界观规则 + 主角团 + 分幕大纲 + 结尾钩子）
- 数据：**全量 315 个题材瘦身嵌入**
- 部署：两个文件（`index.html` + `data.js`），传到网站同目录即可
- 明确不做（YAGNI）：无 LLM、无后端、无转化引导 CTA、无分享图生成、无用户输入框

## 文件结构

```
scripts/export_gacha_web.py   # 导出脚本：YAML/py 数据 → web/gacha/data.js
web/gacha/index.html          # 结构 + 样式 + 抽卡逻辑（原生 JS，零依赖）
web/gacha/data.js             # 生成物：window.GACHA_DATA = {...}
```

题材库更新后重跑 `python scripts/export_gacha_web.py` 即出新 `data.js`。

## 数据导出（export_gacha_web.py）

从现有代码库读取并瘦身：

| 来源 | 取什么 |
|---|---|
| `story_engine/plugins/genres/*.yaml`（315 个） | `name`、`fusion.core_conflict`、`culture_bound`、`allowed_cultures`、`params.title`、`params.taxonomy_tags`（标签，286/315 有，缺失回退 `fusion.parent_genres`）、`params.tracks`（id/name）、`params.conflict_types`（type 映射中文词）、`params.resolution_pattern`、`params.prompt.role/setting/characters`（315/315 全有，开局包质量担当，原文展示）、`params.recommended_preset`、`params.recommended_culture` |
| `story_engine/meta/genre_taxonomy.py` | `macro_templates_for_genre(genre_id)` → 题材推荐幕结构列表（首个最推荐） |
| `story_engine/macro/templates.py`（32 个幕结构，排除 `custom`） | 经 `compute_acts(name, 12)` 预算好 12 集定位：act（name/function/episode_range）+ beats（name/ep/desc，desc 本身是中文短语）；中文显示名沿用 `backend/routers/macro.py` 的映射表 |
| `story_engine/worldview/presets.py` + `layers.py`（10 个世界观） | `key`、`name`、`vibe`；规则句从 71 个 params 里挑 10 个有表现力的键（physics_deviation/metaphysics/destiny_mechanism/power_source/cost_structure/species_diversity/political_system/core_values/taboo_system/hidden_truths），用 `layers.ALL_PARAMS` 自带的中文 label 翻译成「参数名：取值标签」 |
| 姓名库（新建，导出脚本内置） | 按 4 池分组：cn（姓+名表）/jp/western/other；另内置 culture_key → 池映射（11 个文化 yaml） |

瘦身规则：丢弃评估权重、插件清单、activation_events、phase_beats、pacing_targets 等开局包用不到的字段。预估 data.js 体积 300-500KB。

完整性校验（导出时报错而非静默跳过）：每个题材必须有 title、core_conflict、至少 1 条 track。

## 抽卡引擎（index.html 内）

1. 随机抽题材（315 均匀分布）
2. 抽世界观：题材有 `recommended_preset` 时 70% 用推荐、30% 全随机（10 个均匀）；无推荐则全随机
3. 抽骨架：题材有推荐幕结构（taxonomy）时 70% 用最推荐、30% 全随机（31 个，排除 `custom`）；12 集拍点位置已在导出时预算好
4. 人物姓名：文化取 `recommended_culture`（缺失则从 `allowed_cultures` 随机，`*` 时默认 modern-chinese-urban），按 culture → 姓名池映射抽主角/对手/盟友，三者不重名
5. 模板引擎拼装开局包并渲染

## 部分锁定

开局包拆为 **5 个可锁定区块**：题材 / 世界观 / 骨架 / 人物 / 大纲句式。

- 每个区块卡片右上角一个 🔒 锁定钮；「重 Roll」只重新随机**未锁定**的区块
- 典型玩法：题材满意后锁住题材，反复重 Roll 换世界观/人物，逐步搭出满意组合
- 大纲句式锁定 = 句式结构冻结，填空词（轨道名/角色名）仍跟随题材和人物变化（大纲是派生物，文字会随上游区块更新）
- 全部锁定时点重 Roll 给出提示「已全部锁定，先解锁再 Roll」

## 大纲模板引擎（防复读机的核心）

三层随机 + 题材自带文案兜底：

0. **题材自带文案直接展示**：`setting`（世界观简介）、`characters`（人物阵容）、`core_conflict` 都是题材 YAML 里写好的中文描述，原文呈现，质量有保证
1. **填空料来自题材自身**：track 名（主线/副线）、conflict_types 映射中文词、resolution_pattern
2. **拍点句式库**：拍点按名称/描述关键词归类（钩子/建置/触发/升级/反转/低谷/对决/收束 8 类 + 通用兜底），每类备 4 个句式变体随机选；句式中嵌入角色名、轨道名、冲突词、世界观名；骨架拍点自带的中文 desc（如「起式——主角登场，展露气度」）直接作为该拍小标题
3. **姓名随机**：按文化池抽主角/对手/盟友

降级规则：题材缺某字段时，该拍用通用句式（不含填空）。

每拍一句 = `拍点句式[随机变体].fill(轨道名, 冲突词, 世界观名词, 角色名)`。

## 开局码（哈希还原）

抽卡不用真随机，全部随机选择由**种子驱动的伪随机数发生器**（mulberry32）产出，且 **5 个区块各有独立子种子**：

- 开局码 = 5 段子种子拼接，每段 4 位 base36，中划线分隔（如 `k7x2-m9p4-q3z8-n1b6-r5t7`），显示在开局包卡片顶部
- 重 Roll 未锁定区块 = 重新生成这些区块的子种子段；锁定区块的子种子段不变——所以**部分锁定后的最终结果依然一个码完整还原**
- 还原 = 解析 5 段子种子，逐段喂给对应区块的随机流；锁定状态属于会话 UI，不进码
- 页面加载时读 URL hash（`#k7x2-m9p4-...`），有码则直接还原该开局——分享链接即分享结果
- 卡片旁一个输入框：粘贴开局码 →「还原」
- 已知限制：data.js 更新（题材库变动）后旧码可能对应不同结果，导出 .md 里也记录开局码与数据版本号

## 页面与交互

- 风格沿用 StoryOS 前端的纸质书卷风（米色底、衬线标题、橙色主按钮）
- 布局：顶部标题「StoryOS 开局抽卡」+ 一句话说明；中央大按钮「抽一个开局」；下方开局包卡片式展示
- 响应式：手机宽度可用（atposs.com 主页 iframe 嵌入或直接访问均正常）
- 按钮：「重 Roll」「复制大纲」（Markdown 文本进剪贴板）「下载 .md」「复制开局码」
- 页脚一行小字：「开局结构来自 StoryOS 题材库 · 315 题材 × 10 世界观 × 20 骨架」

## 错误处理

纯前端、无网络请求，无服务端错误面。data.js 加载失败（如文件缺失）时页面显示静态提示「数据加载失败，请检查 data.js 是否与 index.html 同目录」。

## 测试

- 导出脚本：跑一遍，断言通过，data.js 体积在预期范围
- 页面：本地浏览器打开，人工抽 20 次，检查：搭配不违逆 allowed_cultures、大纲每拍有句子且不重复感过重、姓名文化匹配、复制/下载 .md 可用、同一开局码还原结果一致、带 #码 的链接打开直接还原、锁定部分区块后重 Roll 仅刷新未锁定区块且新开局码可还原
