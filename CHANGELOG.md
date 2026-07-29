# Changelog

本仓库遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，
版本号遵循 [语义化版本 SemVer](https://semver.org/lang/zh-CN/)：`主.次.修`
（破坏性变更 +主 / 新功能 +次 / 修复 +修；1.0 前次版本号可含较大变更）。

版本单一事实源：`story_engine/__init__.py` 的 `__version__`
（pyproject 动态读取；后端 `/api/config` 与「关于」页透传；发布打 `vX.Y.Z` git tag，
Windows 包文件名带版本号）。

## [0.3.1] - 2026-07-27

### 新增
- **参考素材注入**（宏观规划步骤）：粘贴或导入 .txt/.md 素材文件，AI 将素材中的
  角色/设定按集编排进分集梗概，confirm 落盘 `material.md`（改编/资料驱动型故事，
  如百鬼图鉴 100 集实战：93/98 只鬼正确入编）。

### 修复
- 项目导出 zip 补齐设定资产：`macro_plan.json`/`worldview.json`/`cast.json`/
  `material.md`（此前仅 chapters+project.json，导入方看不到规划图）。
- markdown 标题行（`# 标题：X`）归一化：不再被误判为无标题导致正文残留
  markdown 行且真标题丢失。

## [0.3.0] - 2026-07-27

### 新增
- 抽卡开局「幕结构模板」步骤新增**总集数约定**（1-500）：生成与确认开工全程贯通，
  落盘 project.json，重开项目自动恢复（此前恒为默认 12 集）。
- 幕结构模板库 7 → **32 个品类模板**（英雄之旅/起承转合/本格/恐怖递进/末日生存/
  都市逆袭/宫廷权谋/战争战役/竞技赛季/复仇弧/种田经营/规则怪谈/单元循环/虐恋/
  谍战潜伏/学院试炼/地下城/娱乐圈/刑侦程序/朝堂仕途等）。
- 题材 → 幕结构推荐细化到**子套路级**（50+ 条 `族:子套路` 映射 + 调性前置），
  23 个题材品类全覆盖；legacy 插件按 id 关键词推断。
- **AI 定制幕结构**（`ai_custom`）：LLM 按题材+世界观+集数现场设计专属幕结构，
  结构合法性校验（覆盖率/单调性/拍点区间）。
- **Windows 免安装包**：PyInstaller onedir（`scripts/build_windows.py --zip`），
  双击即用、首启引导、无 key 进 mock 演示模式、数据落在 exe 同级。
- 段落重写辅助信息：本章定位（标题+宏观 beat/集纲）/世界观/上一章结尾（首段）+
  人名与伏笔一致性硬约束（中英模板同步）。
- `STORY_ENGINE_LLM_THINKING`：GLM 等思考型模型开关（on/off/creative，
  creative 仅创作型调用保留思考）。

### 修复
- 大集数宏观生成流式截断：`max_tokens` 按集数动态化（400/集，封顶 128K）。
- 角色决策耗时：行动数达标提前退出（默认 2×角色数，`STORY_ENGINE_ACTOR_TARGET_ACTIONS`
  可调），propose 输出上限瘦身。
- `to_world_rules()` 超自然规则 expr 过不了加载校验门（改 narrative 信息规则）。
- 因果校验测试与 P23.5 放宽语义对齐；recap 缺席时章节衔接指令不再凭空引用前情。
- `test_generation_state` 污染共享后端单例导致顺序依赖失败。
- 打包版在线配置 LLM 写回 .env 路径错误（写进包内 `_internal`，重启失效回 mock）。
- 打包版演示模式三处：占位 key 误判、openai 默认值压制 mock、剧本章过不了质量门。

## [0.2.0] - 2026-07-26

- 宏观叙事规划层（蓝图/幕结构/分集/弧光/伏笔/节奏）+ 抽卡开局五段向导 +
  多项目管理 + 决策卡 Snyder 覆盖率 + IR-first 叙事管线 + 故事圣经导出。
（此前版本未维护本文件，历史变更见 git log。）
