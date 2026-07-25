"""StoryEngine — 核心循环编排器（蓝图 Module 0-6 的 demo 级整合）

Phase 1 重构（v0.2）：所有世界操作走 Kernel.syscall()，不再直接访问 EventStore。
Phase 2（v0.3）：非剧本路径改为 Director→Actor→Showrunner：
  决策卡 → spawn 5 角色 Actor → tick×N（各自 SOAR commit）→
  汇总渲染章节文本 → 7步验证（报告）→ 伏笔池 → snapshot
剧本路径（STORY_ENGINE_SCRIPTED_DEMO=1）完全保留，不依赖 Actor。
Phase 4（v0.4）：真实 LLM 路径接 evaluator 自评迭代（决策5/6，
  SCRIPTED_DEMO=0 且非 mock 且 STORY_ENGINE_EVAL_ENABLED!=0 时启用；
  自评是增强不是门禁，异常自动退回未迭代结果）。
Phase 5（v0.5）：真实 LLM 路径文本产出改 IR-first（决策6，
  SCRIPTED_DEMO=0 且非 mock 且 STORY_ENGINE_IR_FIRST!=0 时启用）：
  IRBuilder → Fabula/Sjuzhet → Narrativizer（Realizer 1 次 LLM 替代原 1 次
  生成）；空稿/异常记 warning 并回退旧路径（增强不是门禁），
  返回体只增 narrative_ir 摘要（mock/剧本路径为 None）。
Phase 11（P11.1）：Actor 阵容插件化 — 创世工厂按题材分派（_genesis_factory）：
  mystery 保持 _genesis_state 全量 SEED（剧本演示世界零变化）；其余题材走
  _make_genesis_factory(bundle)，阵容由 meta.cast.parse_cast 解析
  （cast: 段 → prompt.characters → mock 种子兜底）；spawn 改读
  state.characters/minds，任何题材不再出生包青天。

关键架构约束（worldstate_paradox）：
- 生成 prompt 不含 WorldState 秘密（doesnt_know/secret 不注入）
- 检查/修正 prompt 以 WorldState 为基准
- 修正回路是唯一价值来源（"只检查不修正"零价值）
"""
from __future__ import annotations

import copy
import json
import logging
import os
import time
import warnings
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from loguru import logger as _llog

from .kernel import Kernel
from .kernel.actor import CharacterConfig
from .creativity import ConceptualBlending
from .meta.cast import parse_cast
from .evaluator import (ChapterSpec, CriticParliament, IterationController,
                        LeaderArbiter, PresentationScorer, ProcessGate,
                        ReaderProxy)
from .llm import LLMError  # 通过 shim 兼容旧 import 路径
from .narrative import (FabulaBuilder, IRBuilder, Narrativizer,
                        SjuzhetSelector)
from .showrunner import Showrunner
from .types import (WorldEvent, WorldState, CharacterMind, Relation,
                    NarrativeState, ForeshadowTriple, Check, StoryEngineError,
                    GenreBundle, normalize_learn)
from .validator import ConsistencyValidator
from .worldview import WorldviewProfile
from . import mock_script

PLUGIN_DIR = Path(__file__).parent / "plugins"

logger = logging.getLogger(__name__)

# P3.8：题材插件缺 prompt 段（或缺键）时的通用兜底 —— 不含任何具体作品/角色名
_GENERIC_PROMPT = {
    "role": "故事作者",
    "setting": "虚构世界，遵循本题材设定",
    "characters": "以已定稿前情中登场的角色为准",
    "style": "800-1200字，叙事连贯",
    "hard_requirements": [],
}


def _mask_url(url: str) -> str:
    """P6.10 B9：base_url 脱敏展示（隐藏 host 之间的子路径细节，
    保留协议+域名首尾字符，评审意见 8 安全要求）。"""
    if not url:
        return ""
    # 只留协议 + 域名首段 + 末段，路径部分打码
    if "://" in url:
        proto, rest = url.split("://", 1)
    else:
        proto, rest = "https", url
    if "/" in rest:
        host, path = rest.split("/", 1)
    else:
        host, path = rest, ""
    host_parts = host.split(".")
    if len(host_parts) > 2:
        masked_host = ".".join([host_parts[0], "**", host_parts[-1]])
    else:
        masked_host = host
    masked_path = ("/" + path[:3] + "***") if path else ""
    return f"{proto}://{masked_host}{masked_path}"


def _make_genesis_factory(bundle: GenreBundle, project_dir: Path | None = None):
    """P11.1：bundle 感知的创世工厂 — 返回 factory() -> WorldState。

    阵容由 meta.cast.parse_cast(bundle.genre_params) 解析（L1 cast: 段 →
    L2 prompt.characters → mock 种子兜底 + warning）；characters/minds/
    relations 由 cast 组装（characters 条目含 role/voice，voice 取自
    CastMember.voice_hint，供 spawn 与角色卡视图复用）。
    narrative 段保持现值（act=1/chapter=0/tension=0.3/current_scene="开场"/
    track_progress/last_story_time），causal_links 置空（非 mock 剧本
    无预置因果链）；physical 不预置（非 mock 题材无种子 fluents）。

    P15.2：project_dir 下有 cast.json 时，用其中 cast 条目（含 persona）
    覆盖 bundle 自带阵容——characters 条目额外携带 persona 字段，
    spawn_character_actor 读取 persona 用于 Actor propose 上下文增强。
    """
    def _factory() -> WorldState:
        cast = parse_cast(bundle.genre_params)
        # P15.2：项目目录的 cast.json 覆盖（用户自定义阵容 + persona）
        cast_overrides = _load_cast_overrides(project_dir) if project_dir else []
        persona_map: dict[str, dict] = {}
        if cast_overrides:
            # cast.json 提供 id/role/goals/voice_hint/persona
            cast = _apply_cast_overrides(cast, cast_overrides, persona_map)
        state = WorldState(tick=0)
        for m in cast:
            entry: dict = {"role": m.role, "voice": m.voice_hint}
            if m.id in persona_map:
                entry["persona"] = persona_map[m.id]
            state.characters[m.id] = entry
            state.minds[m.id] = CharacterMind(
                character_id=m.id, goals=list(m.goals))
            for r in m.relations:
                state.relationships[f"{m.id}|{r['target']}"] = Relation(
                    r["type"], r["intensity"], [])
        state.narrative = NarrativeState(
            act=1, chapter=0, tension=0.3, current_scene="开场",
            track_progress={"A": 0, "B": 0, "C": 0, "D": 0, "E": 0},
            causal_links=[], last_story_time="第1日·清晨")
        return state
    return _factory


def _load_cast_overrides(project_dir: Path | None) -> list[dict]:
    """P15.2：读项目目录的 cast.json（gacha confirm 落盘的自定义阵容）。
    文件缺失/损坏/非列表 → 空列表（容忍，不崩）。"""
    if project_dir is None:
        return []
    path = Path(project_dir) / "cast.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [e for e in data if isinstance(e, dict) and e.get("id")]


def _apply_cast_overrides(cast: list, overrides: list[dict],
                          persona_map: dict[str, dict]) -> list:
    """P15.2：用 cast.json 覆盖 bundle 自带阵容。

    策略：以 overrides 的 id 为主——同名覆盖 CastMember 的 role/voice_hint/
    goals，persona 存入 persona_map；overrides 中新增的 id 追加为 CastMember。
    返回更新后的 cast 列表（persona_map 原地填充）。
    """
    from .meta.cast import CastMember
    by_id = {m.id: m for m in cast}
    for ov in overrides:
        cid = str(ov["id"]).strip()
        persona = ov.get("persona")
        if isinstance(persona, dict):
            persona_map[cid] = persona
        goals = ov.get("goals")
        if cid in by_id:
            m = by_id[cid]
            if ov.get("role"):
                m.role = str(ov["role"])
            if ov.get("voice_hint"):
                m.voice_hint = str(ov["voice_hint"])
            if isinstance(goals, list):
                m.goals = [str(g) for g in goals if str(g).strip()]
        else:
            by_id[cid] = CastMember(
                id=cid,
                role=str(ov.get("role") or ""),
                voice_hint=str(ov.get("voice_hint") or ""),
                goals=[str(g) for g in goals if str(g).strip()]
                       if isinstance(goals, list) else [],
            )
    return list(by_id.values())


class _ChapterClosingKernelView:
    """P5.6 IR-first 专用 kernel 视图：给 all_events 虚拟追加本章闭合
    narrative_beat 标记（不落库、不占 tick、不改世界状态）。

    背景：IRBuilder._chapter_slice 的章界规则要求「最后一个 chapter==k 标记
    含」作右界，而引擎在文本产出时刻本章尚未以伏笔同步 beat 收尾（产出在前、
    收尾在后），直接 build 对进行中的本章切出空区间（Actor 路径第 2 章起
    actor 事件将不可见）。虚拟闭合标记让切片覆盖「上一章收尾之后到当前日志
    末尾」= 本章已提交事件。仅 IRBuilder.build 期间使用。
    """

    def __init__(self, kernel, chapter: int):
        self._kernel = kernel
        self._chapter = chapter

    def query_world(self, key, *args, **kwargs):
        result = self._kernel.query_world(key, *args, **kwargs)
        if key == "all_events":
            return list(result) + [{
                "event_id": "_ir_chapter_close",
                "event_type": "narrative_beat",
                "timestamp": "", "world_tick": 0, "branch_id": "main",
                "payload": {"chapter": self._chapter}, "active": True,
            }]
        return result

    def __getattr__(self, name):
        return getattr(self._kernel, name)


# ============================================================
# P23.4 质量加固：章节正文质检工具函数
# ============================================================
import re as _re_qa  # 质检专用 re，避免与函数内 import re 冲突

MIN_CHAPTER_CHARS = 600   # 章节正文硬下限：低于此值视为生成失败
MAX_GEN_RETRIES = 2       # 章节生成最大重试次数


def _is_narrative_text(text: str) -> bool:
    """判别产出是否是叙事文本（非动作日志/结构化数据）。

    Actor 路径 Realizer 失败时，旧逻辑回退 _render_actor_chapter 产出
    "角色名：角色名围制…取判断"格式的动作日志，这不是小说正文。
    本函数检测此类非叙事模式，供门禁B/E使用。
    """
    if not text or len(text.strip()) < 100:
        return False
    lines = [l for l in text.split("\n") if l.strip()]
    if not lines:
        return False
    # 动作日志模式："XXX：XXX取判断/取行动/围制/serves_goal"
    action_log = sum(
        1 for l in lines
        if _re_qa.search(r"[:：].*(取判断|取行动|围制|serves_goal|motivation)", l))
    if action_log > len(lines) * 0.3:
        return False
    # 结构化数据残留：JSON / YAML / IR 骨架
    stripped = text.strip()
    if stripped.startswith(("{", "[", "---", "[beat")):
        return False
    return True


class StoryEngine:
    def __init__(self, kernel_or_dir, llm_client=None,
                 genre_name=None, culture_name=None):
        """两种构造方式（向后兼容）：
        - StoryEngine(kernel: Kernel)              # 推荐：注入外部 kernel
        - StoryEngine(project_dir: str|Path, llm_client=LLMClient())  # 旧式：自建
        genre_name/culture_name（P8.5 可选，只增）：显式指定三正交轴题材/文化；
        缺省（None/空串）回落 env（STORY_ENGINE_GENRE/CULTURE）→ 内置默认，
        与之前行为逐字一致。抽卡 project init 用显式参数做进程内覆盖（不改 env）。
        """
        if isinstance(kernel_or_dir, Kernel):
            self.kernel = kernel_or_dir
            # 兼容老代码：self.llm / self.store / self.registry / self.project_dir 仍可访问
            self.llm = self.kernel.llm
            self.store = self.kernel.store
            self.registry = self.kernel.registry
            self.project_dir = self.kernel.project_dir
        else:
            # 旧式构造：自动建 Kernel（插件由 Kernel._load_plugins 统一加载，
            # 含 P7.1 packs 扫描 + story.skill 接线）
            self.project_dir = Path(kernel_or_dir)
            self.project_dir.mkdir(parents=True, exist_ok=True)
            from .kernel import LLMPool
            llm_pool = llm_client or LLMPool()
            self.kernel = Kernel(
                self.project_dir,
                # P11.1：延迟解析创世工厂 —— bundle 要在 Kernel 建成后才能
                # 组装（依赖 kernel.registry），工厂被调用时（EventStore 懒
                # 求值，空库首次 current_state）self.bundle 已就绪；
                # 且下方 bundle 建成后会把 store 工厂重指为定型工厂（双保险）
                initial_state_factory=lambda: self._genesis_factory()(),
                llm_pool=llm_pool if hasattr(llm_pool, "call") else None,
                plugin_dir=PLUGIN_DIR,
            )
            self.registry = self.kernel.registry
            self.llm = self.kernel.llm
            self.store = self.kernel.store

        # 三正交轴配置（P8.5：显式参数优先，缺省回落 env/内置默认，与原版一致）
        genre_name = genre_name or os.environ.get("STORY_ENGINE_GENRE", "mystery")
        culture_name = culture_name or os.environ.get(
            "STORY_ENGINE_CULTURE", "confucian_officialdom")
        self.registry.validate_combo(genre_name, culture_name)
        self.genre = self.registry.get("story.genre", genre_name)
        self.culture = self.registry.get("story.culture", culture_name)
        # P7.4 L5：rule_packs 显式引用的 world.rule 包合并进 world_rules
        #（genre params 未配置 rule_packs 时返回 params 本体，行为与现状逐字一致）
        genre_params = self._merge_world_rule_packs(self.genre.params)
        # P12.3：世界观档案的 to_world_rules() 追加进统一 world_rules 列表
        #（与 P7.4 同款合并：仅 kind=bool 且 expr 过 check_rule_expr 校验的规则
        # 才追加；同 id 不覆盖；无 profile / 无可表达规则时 genre_params 不变，
        # 行为与现状逐字一致）
        genre_params = self._merge_worldview_rules(genre_params)
        # P22：内嵌 world_rules 兜底消毒（pack/worldview 路径自带校验，内嵌规则
        # 此前无门禁——romance 的 forced_union 等超词汇表 expr 会让 Step 6
        # 在生成期 KeyError 崩溃）：kind=narrative 分流进 prompt；expr 非法
        # → warning + 拒载；全合法时返回 params 本体（零拷贝，行为不变）
        genre_params = self._sanitize_world_rules(genre_params)
        # P23.1：项目 cast.json 存在时，prompt.characters 以项目阵容为准——
        # 此前生成 prompt 的 characters 始终用题材默认文案，LLM 看不到项目
        # 实际阵容，只能现编「嫌疑人甲/乙」占位名（人物条目灌水根因之一）
        genre_params = self._merge_cast_prompt(genre_params)
        # 权威 GenreBundle 构建一次：Showrunner 决策卡与 spawn_director 共用
        self.bundle = GenreBundle(
            genre=genre_name, culture=culture_name,
            genre_params=genre_params, culture_params=self.culture.params)
        # P11.1：创世工厂按题材定型的权威接线点（bundle 建成后立即可用）。
        # EventStore 懒调用工厂（event_store.py 空库首次 current_state 才触发），
        # 构造期重指即可保证任何后续创世走本引擎题材 —— 外部注入 Kernel 时
        # （如 backend）其构造期拿到的占位工厂由此被本引擎题材工厂取代。
        self.kernel.store._initial_state_factory = self._genesis_factory()

        # 子系统（与原版一致）
        self.validator = ConsistencyValidator(
            world_rules=genre_params.get("world_rules"))
        # P3.4：event_source 供 Showrunner 量化上一章节奏（all_events 含 active 标记）
        # P3.7：ConceptualBlending（决策7，env 门控默认关）；recent_texts_source
        # 懒读 chapters.json 取最近 3 章正文供 novelty 比对（构造时 chapters_path
        # 尚未赋值，故用 lambda 延迟求值）
        blender = ConceptualBlending(
            self.kernel.llm.call, embedder=self.kernel.embedder,
            blend_domains=self.genre.get("blend_domains"))
        self.showrunner = Showrunner(
            self.bundle,
            event_source=lambda: self.kernel.query_world("all_events"),
            blender=blender,
            recent_texts_source=lambda: [
                c["final"]["text"] for c in self._read_chapters()
                if not c.get("superseded")][-3:])

        self.chapters_path = self.project_dir / "chapters.json"
        if not self.chapters_path.exists():
            self._write_chapters([])
        self._actors_ready = False
        self._director_ref = None
        # P5.6：本章 IR-first 产出的 narrative_ir 摘要（每章生成前重置；
        # 仅 IR-first 成功时非 None，mock/剧本/回退 → None）
        self._chapter_narrative_ir = None
        # P6.2：两阶段生成 — plan 端点缓存的待批准决策卡（DecisionCard | None）；
        # generate(mode="confirm") 优先消费并清除，rollback/reset 时作废
        self._pending_plan = None
        # P6.10 B9：进程内覆盖 dict（settings 端点写）— 优先级高于 env，不持久化
        # （重启失效，前端 POST 即时生效，仅当前后端进程生命周期）。
        # 键：eval_enabled / ir_first / eval_max_rounds；值为 None 表示未覆盖（落 env）。
        # mock/剧本路径不受影响（_eval_enabled/_ir_first_enabled 仍检查 SCRIPTED_DEMO/llm.is_mock）。
        self._runtime_overrides: dict[str, object | None] = {}
        self._progress_callback = None  # P1-1: 进度回调，backend 设置后 engine 在关键节点调用

    def _progress(self, stage: str, detail: str = "") -> None:
        """P1-1: 进度上报（供前端实时显示生成步骤）。backend 设 callback 后生效。"""
        if self._progress_callback:
            try:
                self._progress_callback(stage, detail)
            except Exception:
                pass  # 进度上报失败不影响生成

    # ============ P7.4 L5：world.rule 素材包引用合并 ============
    def _merge_world_rule_packs(self, genre_params: dict) -> dict:
        """genre params 声明 rule_packs: [pack名] 时，把 world.rule 素材包规则
        合并进 world_rules，返回含合并结果的 params 副本；未配置 rule_packs
        时返回 params 本体（genre yaml 不加该键则行为与现状逐字一致）。

        合并语义（与 story.evaluator critic pack 同款 pack-wins）：
        - 同 id → pack 规则覆盖内嵌规则（保持内嵌原位）；内嵌没有的规则追加
        - pack 未注册 / params.rules 非列表 → warning + 跳过该包
        - kind=narrative 规则（P21）：只要求 id+desc，不进 world_rules
          （validator 无法消费），其 desc 追加进 prompt.hard_requirements
          作为 LLM 创作约束（去重：desc 已存在则不加）
        - 其余规则非映射 / 缺 id / 缺 expr → warning + 跳过该条
        - expr 过 Z3 语法校验（ConsistencyValidator.check_rule_expr，与
          validator Step 6 同一解析路径）：非法 → 该条拒载 + warning，
          其余规则不受影响
        """
        pack_names = genre_params.get("rule_packs")
        if not pack_names:
            return genre_params
        if not isinstance(pack_names, list):
            logger.warning("rule_packs 非列表（%r），忽略", pack_names)
            return genre_params
        packs = {m.name: m for m in self.registry.pack_manifests("story.world.rule")}
        embedded = genre_params.get("world_rules") or []
        merged = list(embedded)
        slot = {r.get("id"): i for i, r in enumerate(merged)
                if isinstance(r, dict)}
        narrative_slot: dict[str, int] = {}
        narrative_rules: list[dict] = []
        for name in pack_names:
            manifest = packs.get(str(name))
            if manifest is None:
                logger.warning(
                    "rule_packs 引用的 world.rule 包「%s」未注册，跳过", name)
                continue
            rules = manifest.params.get("rules")
            if not isinstance(rules, list):
                logger.warning("world.rule 包「%s」缺 rules 列表，跳过", name)
                continue
            for rule in rules:
                if not isinstance(rule, dict) or not rule.get("id"):
                    logger.warning(
                        "world.rule 包「%s」含缺 id 的规则（%r），跳过该条",
                        name, rule)
                    continue
                # P21：narrative 规则分流——创作约束进 prompt 不进 Z3
                if rule.get("kind") == "narrative":
                    if not rule.get("desc"):
                        logger.warning(
                            "world.rule 包「%s」narrative 规则「%s」缺 desc，跳过",
                            name, rule["id"])
                        continue
                    if rule["id"] in narrative_slot:
                        narrative_rules[narrative_slot[rule["id"]]] = rule
                    else:
                        narrative_slot[rule["id"]] = len(narrative_rules)
                        narrative_rules.append(rule)
                    continue
                if not rule.get("expr"):
                    logger.warning(
                        "world.rule 包「%s」含缺 expr 的规则（%r），跳过该条",
                        name, rule)
                    continue
                if not ConsistencyValidator.check_rule_expr(rule["expr"]):
                    logger.warning(
                        "world.rule 包「%s」规则「%s」expr 非法（%r），拒载",
                        name, rule["id"], rule["expr"])
                    continue
                if rule["id"] in slot:
                    merged[slot[rule["id"]]] = rule   # 同 id：pack 覆盖内嵌
                else:
                    slot[rule["id"]] = len(merged)
                    merged.append(rule)               # 新规则追加
        params = dict(genre_params)
        params["world_rules"] = merged
        if narrative_rules:
            # 浅拷贝陷阱：必须新建 prompt dict 与 list，不得原地改 registry
            # 缓存的 manifest params（同进程多项目会互相污染、重复追加）
            prompt = dict(params.get("prompt") or {})
            hrs = list(prompt.get("hard_requirements") or [])
            for r in narrative_rules:
                if r["desc"] not in hrs:
                    hrs.append(r["desc"])
            prompt["hard_requirements"] = hrs
            params["prompt"] = prompt
        return params

    # ============ P12.3：worldview profile world_rules 合并 ============
    def _merge_worldview_rules(self, genre_params: dict) -> dict:
        """把项目 WorldviewProfile.to_world_rules() 中可表达为布尔事实的规则
        追加进 genre_params.world_rules（与 P7.4 同款合并语义）。

        - 仅 kind=bool 且 expr 过 ConsistencyValidator.check_rule_expr 的规则
          才追加（kind=narrative 无 expr，validator 不消费，跳过）
        - 同 id 已存在 → 不覆盖（worldview 规则 id 以 ``wv_`` 前缀，不与题材
          内嵌规则冲突；保守起见仍跳过同 id）
        - 无 profile / 无可表达规则 / 读取异常 → 返回 genre_params 本体
          （行为与现状逐字一致）
        """
        profile = self._read_worldview()
        if profile is None:
            return genre_params
        wv_rules = profile.to_world_rules()
        bool_rules = [r for r in wv_rules
                      if r.get("kind") == "bool" and r.get("expr")]
        if not bool_rules:
            return genre_params
        existing = genre_params.get("world_rules") or []
        slot = {r.get("id") for r in existing if isinstance(r, dict)}
        merged = list(existing)
        appended = False
        for rule in bool_rules:
            rid = rule.get("id")
            if not rid or rid in slot:
                continue
            if not ConsistencyValidator.check_rule_expr(rule["expr"]):
                logger.warning(
                    "worldview 规则「%s」expr 非法（%r），拒载",
                    rid, rule["expr"])
                continue
            slot.add(rid)
            merged.append(rule)
            appended = True
        if not appended:
            return genre_params
        params = dict(genre_params)
        params["world_rules"] = merged
        return params

    # ============ P23.1：项目阵容覆盖 prompt.characters ============
    def _merge_cast_prompt(self, genre_params: dict) -> dict:
        """cast.json 非空时，把 prompt.characters 换成项目阵容名单
        （「祁望（主角）、死者（配角）」式）；无 cast.json / 空 → 原样返回。
        必须新建 prompt dict（与 _sanitize_world_rules 同款浅拷贝纪律）。"""
        overrides = _load_cast_overrides(self.project_dir)
        if not overrides:
            return genre_params
        roster = "、".join(
            f"{ov['id']}（{str(ov.get('role') or '角色')}）" for ov in overrides)
        params = dict(genre_params)
        prompt = dict(params.get("prompt") or {})
        prompt["characters"] = roster
        params["prompt"] = prompt
        return params

    # ============ P22：内嵌 world_rules 消毒（生成期防崩） ============
    def _sanitize_world_rules(self, genre_params: dict) -> dict:
        """对最终 world_rules 列表做加载门禁（内嵌规则此前无校验，超词汇表
        expr 会让 validator Step 6 在事件校验时 KeyError）。

        - kind=narrative（有 id+desc）→ 不进 world_rules，desc 去重追加进
          prompt.hard_requirements（与 P21 pack narrative 同款分流）
        - 其余规则 expr 过 check_rule_expr；非法 → warning + 拒载
        - 全部合法且无 narrative → 返回 params 本体（零拷贝，行为逐字一致）
        """
        rules = genre_params.get("world_rules")
        if not rules:
            return genre_params
        kept: list[dict] = []
        narrative_descs: list[str] = []
        dirty = False
        for rule in rules:
            if not isinstance(rule, dict):
                dirty = True
                continue
            if rule.get("kind") == "narrative":
                dirty = True
                if rule.get("desc"):
                    narrative_descs.append(rule["desc"])
                continue
            if not ConsistencyValidator.check_rule_expr(rule.get("expr")):
                logger.warning(
                    "内嵌 world_rules 规则「%s」expr 非法（%r），拒载",
                    rule.get("id", "?"), rule.get("expr"))
                dirty = True
                continue
            kept.append(rule)
        if not dirty:
            return genre_params
        params = dict(genre_params)
        params["world_rules"] = kept
        if narrative_descs:
            prompt = dict(params.get("prompt") or {})
            hrs = list(prompt.get("hard_requirements") or [])
            for d in narrative_descs:
                if d not in hrs:
                    hrs.append(d)
            prompt["hard_requirements"] = hrs
            params["prompt"] = prompt
        return params

    # ============ 创世（seed 世界） ============
    def _genesis_factory(self):
        """P11.1：创世工厂选择（mystery 保真，其余题材阵容插件化）。

        mystery 是 mock 剧本演示世界（SCRIPTED_DEMO 剧本路径的唯一内容），
        其创世依赖全量 SEED 种子（physical/beliefs/secrets/causal_links 等
        cast 段表达不了的部分）——保持 _genesis_state 静态法，行为逐字
        零变化；其余题材走 bundle 感知的 cast 工厂（_make_genesis_factory），
        阵容由题材插件 cast:/prompt.characters 解析，不再回落包青天。

        P15.2：project_dir 传入工厂以支持 cast.json 覆盖（含 persona）。
        """
        if self.bundle.genre == "mystery":
            return StoryEngine._genesis_state
        return _make_genesis_factory(self.bundle, project_dir=self.project_dir)

    @staticmethod
    def _genesis_state() -> WorldState:
        """mock 剧本演示世界（mystery）的创世静态法 —— 全量 SEED 保真。
        P11.1 起仅 mystery 题材经 _genesis_factory 选用；新题材请走
        _make_genesis_factory(bundle)（cast 插件化路径）。"""
        state = WorldState(tick=0)
        state.physical.update(mock_script.SEED_PHYSICAL)
        state.characters.update(mock_script.SEED_CHARACTERS)
        for cid, m in mock_script.SEED_MINDS.items():
            state.minds[cid] = CharacterMind(
                character_id=cid,
                beliefs=dict(m["beliefs"]), secrets=list(m["secrets"]),
                goals=list(m["goals"]), affect=dict(m["affect"]))
        for key, r in mock_script.SEED_RELATIONS.items():
            state.relationships[key] = Relation(r["type"], r["intensity"], list(r["history"]))
        state.narrative = NarrativeState(
            act=1, chapter=0, tension=0.3, current_scene="开场",
            track_progress={"A": 0, "B": 0, "C": 0, "D": 0, "E": 0},
            causal_links=list(mock_script.SEED_CAUSAL_LINKS),
            last_story_time="第1日·清晨")
        return state

    # ============ 核心循环：生成一章 ============
    async def generate_chapter(self, mode: str = "auto") -> dict:
        t0 = time.perf_counter()
        state = self.kernel.query_world("current_state")
        chapter_no = state.narrative.chapter + 1
        trace_id = f"ch{chapter_no}-{uuid4().hex[:8]}"
        with _llog.contextualize(trace_id=trace_id):
            scripted = self._scripted(chapter_no)

            # 剧本路径：完全保留 Phase 1 行为
            if scripted:
                return await self._generate_chapter_llm_path(
                    chapter_no, state, t0, scripted=True, mode=mode)

            # SCRIPTED_DEMO=1 且 Mock 剧本已完：保持旧行为提示切换 LLM
            demo_on = os.environ.get("STORY_ENGINE_SCRIPTED_DEMO", "1") == "1"
            if demo_on and self.llm.is_mock:
                raise StoryEngineMockEnded(
                    f"Mock 剧本已完结（共{max(mock_script.DRAFTS)}章）。"
                    "配置 STORY_ENGINE_LLM_API_KEY 后切换真实 LLM 继续生成，"
                    "或设 STORY_ENGINE_SCRIPTED_DEMO=0 走 Actor 模式，"
                    "或在时间线面板回滚到任意快照重新生成。")

            # Actor 路径（STORY_ENGINE_SCRIPTED_DEMO=0）
            # P23.4 门禁E：质量不达标时重试（最多 MAX_GEN_RETRIES 次）
            last_err = None
            for attempt in range(MAX_GEN_RETRIES + 1):
                try:
                    return await self._generate_chapter_actor_path(
                        chapter_no, state, t0, mode=mode)
                except StoryEngineError as e:
                    last_err = e
                    if attempt < MAX_GEN_RETRIES:
                        _llog.warning(
                            "第{}章生成不达标(尝试{}/{})，重试: {}",
                            chapter_no, attempt + 1, MAX_GEN_RETRIES, e)
                        continue
                    raise  # 重试用完仍失败 → 报错，不落盘
            raise last_err  # 不可达（循环必 return 或 raise），保险

    # ============ P6.2：两阶段生成（plan + confirm） ============
    def plan_chapter(self) -> dict:
        """两阶段生成第一步：只产决策卡不生成章节，缓存供 confirm 复用。

        决策卡是纯规则产物（Showrunner.generate_decision_card 零 LLM 调用），
        剧本/真实路径通用。副作用说明（P6.2 调查结论）：
        generate_decision_card 只写 Showrunner 自持状态 —— _sternberg_history
        与 tracks.last_touched，两者对同集幂等（decision.py「同集重复生成时
        仍对齐上一集，幂等」，tests/test_decision_card.py 已有同集重产卡
        幂等用例）；世界状态的伏笔池只在生成时的 _apply_foreshadow_script
        改动 —— 故 plan 不污染世界状态，confirm 复用缓存卡也不会二次生效。
        """
        state = self.kernel.query_world("current_state")
        chapter_no = state.narrative.chapter + 1
        card = self.showrunner.generate_decision_card(chapter_no, state)
        # P17.4：plan 预览也注入宏观上下文（无 macro_plan → None）
        macro_ctx = self._build_macro_context(chapter_no)
        if macro_ctx is not None:
            card.macro_context = macro_ctx
            # P19.3：key_events / foreshadow 覆盖检查 → feedback 注入
            self._check_macro_coverage(card)
        self._pending_plan = card
        return card.to_dict()

    def discard_plan(self) -> None:
        """P6.2：作废缓存的待批准决策卡（DELETE /api/project/plan）"""
        self._pending_plan = None

    def _resolve_decision_card(self, chapter_no: int, state: WorldState,
                               mode: str):
        """P6.2：confirm 模式优先消费 plan 缓存的决策卡（消费即清除）；
        auto / 无缓存 / 缓存章号不匹配 → 现场产卡（现状逐字不变）。
        章号匹配的缓存在任何模式下都清除：本章一生成，旧方案即失效。
        P17.4：产卡后注入 macro_context（无 macro_plan → None，零行为变化）。"""
        pending = self._pending_plan
        if pending is not None and pending.episode == chapter_no:
            self._pending_plan = None
            if mode == "confirm":
                card = pending
            else:
                card = self.showrunner.generate_decision_card(chapter_no, state)
        else:
            card = self.showrunner.generate_decision_card(chapter_no, state)
        # P17.4：宏观上下文注入（无 macro_plan → macro_context 保持 None）
        macro_ctx = self._build_macro_context(chapter_no)
        if macro_ctx is not None:
            card.macro_context = macro_ctx
            # P19.3：key_events / foreshadow 覆盖检查 → feedback 注入
            self._check_macro_coverage(card)
        return card

    def _check_macro_coverage(self, card) -> None:
        """P19.3：检查决策卡是否覆盖宏观计划的 key_events 和 foreshadow 指令。

        未覆盖项 → 追加到 macro_context['feedback']（list[str]），供 Actor
        propose prompt 和 Realizer prompt 注入（_macro_context_text 渲染）。
        有 macro_context 但无 key_events/foreshadow 指令 → feedback 为空（零变化）。
        """
        ctx = getattr(card, "macro_context", None)
        if not ctx or not isinstance(ctx, dict):
            return
        feedback: list[str] = []

        # --- key_events 覆盖检查 ---
        required_events = ctx.get("key_events_required") or []
        if required_events:
            # 收集决策卡所有文本内容用于覆盖判断
            beat_texts = " ".join(
                str(b.get("phase", "")) + str(b.get("track_name", ""))
                + "".join(str(p) for p in b.get("primitives", []))
                for b in getattr(card, "beats", []))
            advance_txt = " ".join(getattr(card, "advance", []))
            seed_txt = " ".join(getattr(card, "seed", []))
            card_text = beat_texts + " " + advance_txt + " " + seed_txt
            for event in required_events:
                # 简单关键词匹配：event 文本的核心词是否在决策卡文本中出现
                keywords = [w for w in str(event)
                            if len(w.strip()) > 1 and w.strip()
                            not in ("的", "了", "在", "和", "与", "是", "为")]
                # 逐字检查：event 中 >= 2 个连续中文字符出现在 card_text 中
                matched = False
                event_str = str(event)
                for i in range(len(event_str) - 1):
                    if event_str[i:i+2] in card_text:
                        matched = True
                        break
                if not matched:
                    feedback.append(
                        f"宏观要求的关键事件未在决策卡中体现：{event}")

        # --- foreshadow 覆盖检查 ---
        fs_directives = ctx.get("foreshadow_directives") or []
        if fs_directives:
            active_payoff_ids = {
                p.get("foreshadow_id", "")
                for p in getattr(card, "active_payoffs", [])}
            new_fs_names = {
                f.get("content", "")[:4]
                for f in getattr(card, "new_foreshadows", [])}
            for directive in fs_directives:
                if directive.get("action") == "plant":
                    # plant 指令：检查 new_foreshadows 是否有对应条目
                    d_name = directive.get("name", "")
                    d_id = directive.get("id", "")
                    if d_id not in active_payoff_ids and not any(
                            d_name[:3] in nf for nf in new_fs_names):
                        feedback.append(
                            f"宏观要求埋设伏笔但决策卡未安排：{d_name}")

        if feedback:
            ctx["feedback"] = feedback

    async def _generate_chapter_llm_path(
        self, chapter_no: int, state: WorldState, t0: float, *, scripted: bool,
        mode: str = "auto"
    ) -> dict:
        if self.llm.is_mock and not scripted:
            raise StoryEngineMockEnded(
                f"Mock 剧本已完结（共{max(mock_script.DRAFTS)}章）。"
                "配置 STORY_ENGINE_LLM_API_KEY 后切换真实 LLM 继续生成，"
                "或在时间线面板回滚到任意快照重新生成。")

        # Step 0: Showrunner 决策卡（P6.2：confirm 模式复用 plan 缓存卡）
        card = self._resolve_decision_card(chapter_no, state, mode)
        _llog.info("决策卡生成 | 章={} | advance={} | tracks={}", chapter_no,
                   getattr(card, "advance", []), len(getattr(card, "beats", [])))
        # P3.7：env 门控默认关；剧本路径（mock_script）不挂 seed，保持原行为
        if not scripted:
            card = await self.showrunner.attach_creative_seed(card, chapter_no)

        # Step 1-4: 初稿 → 事件抽取 → 7步验证 → 修正回路
        _llog.info("生成初稿 | eval_enabled={} | ir_first={}",
                   self._eval_enabled(), self._ir_first_enabled())
        # P4.5（决策5）：真实 LLM 且自评门控通过 → 包 IterationController（best-of-K）；
        # 自评链路任何异常 → 退回未迭代结果（自评是增强不是门禁）
        evaluation = None
        self._chapter_narrative_ir = None  # P5.6：本章摘要重置（成功才置值）
        if not scripted and self._eval_enabled():
            try:
                (draft_text, draft_results, violations, correction,
                 final_text, final_events, evaluation) = \
                    await self._generate_with_evaluation(chapter_no, card, state)
            except Exception:
                evaluation = None
                (draft_text, draft_results, violations, correction,
                 final_text, final_events) = await self._generate_and_repair(
                    chapter_no, card, state)
        else:
            (draft_text, draft_results, violations, correction,
             final_text, final_events) = await self._generate_and_repair(
                chapter_no, card, state)

        # 空结果守卫
        if not final_text.strip():
            raise StoryEngineError(
                "生成结果为空 — 模型可能额度不足或思考预算耗尽。未提交任何事件，世界状态未变。")
        # P23.4 门禁C/E：字数下限 + 叙事文本质检（仅 _quality_gate_enabled 生效；
        # 测试/mock 宽松，因 fake LLM 产出可能短/结构化）
        if self._quality_gate_enabled():
            if len(final_text.strip()) < MIN_CHAPTER_CHARS:
                raise StoryEngineError(
                    f"第{chapter_no}章正文仅 {len(final_text.strip())} 字"
                    f"（下限 {MIN_CHAPTER_CHARS}）— 生成质量不达标，未落盘。")
            if not _is_narrative_text(final_text):
                raise StoryEngineError(
                    f"第{chapter_no}章最终正文未通过叙事文本质检"
                    f"（疑似动作日志/结构化数据），未落盘。")
        if not final_events:
            raise StoryEngineError(
                "事件抽取为空 — 生成文本无法解析出世界事件。未提交任何事件，世界状态未变。")

        # Step 5: commit 事件（事件溯源，通过 kernel.commit_event syscall）
        committed = []
        tick = self.kernel.query_world("next_tick")
        for ev in final_events:
            event = WorldEvent(
                event_id=str(uuid4())[:8],
                event_type=ev["event_type"],
                timestamp=datetime.now().isoformat(timespec="seconds"),
                world_tick=tick, branch_id="main",
                payload={**ev["payload"], "summary": ev.get("summary", "")})
            self.kernel.commit_event(event)
            committed.append({"event_id": event.event_id, "tick": tick,
                              "summary": ev.get("summary", ev["event_type"]),
                              "event_type": ev["event_type"]})
            tick += 1

        # Step 6: 伏笔池更新（CFPG）
        fs_updates = self._apply_foreshadow_script(chapter_no, tick)

        # Step 7: snapshot（通过 kernel.snapshot syscall）
        snapshot_id = self.kernel.snapshot()
        head = self.kernel.query_world("head_tick")

        # 标题解析（剧本章用剧本标题；真实模式从正文首行解析）。
        # 接受三种格式（与 process_gates L5 一致）：
        #   「标题：XXXX」（引擎约定，全角冒号）/ 「# XXXX」（markdown）/ 「第N章 XXXX」（纯文本）
        title = mock_script.CHAPTER_TITLES.get(chapter_no)
        if not scripted:
            import re as _re
            # P0-4: 跳过开头的 --- 分隔线
            _body = _re.sub(r"^\s*---\s*\n+", "", final_text)
            if _body != final_text:
                final_text = _body
                draft_text = _re.sub(r"^\s*---\s*\n+", "", draft_text)
            m = (_re.match(r"\s*标题[:：]\s*(.+)", final_text)
                 or _re.match(r"\s*##?\s+(.+)", final_text)
                 or _re.match(r"\s*(第[一二三四五六七八九十百零\d]+章[^\n]*)", final_text))
            if m:
                title = m.group(1).strip()[:12]
                final_text = final_text[m.end():].lstrip("\n")
                draft_m = (_re.match(r"\s*标题[:：]\s*(.+)", draft_text)
                           or _re.match(r"\s*##?\s+(.+)", draft_text)
                           or _re.match(r"\s*(第[一二三四五六七八九十百零\d]+章[^\n]*)", draft_text))
                if draft_m:
                    draft_text = draft_text[draft_m.end():].lstrip("\n")

        record = {
            "chapter": chapter_no,
            "title": title or f"第{chapter_no}章",
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
            "llm_mode": "mock" if scripted else "openai",
            "generation_mode": "scripted" if scripted else "llm",
            "decision_card": card.to_dict(),
            "draft": {
                "text": draft_text,
                "events": draft_results,
                "violation_count": len(violations),
                "violations": violations,
            },
            "correction": correction,
            "final": {"text": final_text, "committed_events": committed},
            "foreshadow_updates": fs_updates,
            "snapshot_id": snapshot_id,
            "tick_range": [committed[0]["tick"] if committed else head, head],
            # P4.5（决策6）：自评结果（mock/剧本/门控关闭/异常退回 → None），只增不改
            "evaluation": evaluation,
            # P5.6（决策6）：IR-first 摘要（beats/events/texture 等扁平小对象；
            # mock/剧本/IR_FIRST=0/回退 → None），只增不改
            "narrative_ir": self._chapter_narrative_ir,
        }
        chapters = self._read_chapters()
        chapters.append(record)
        self._write_chapters(chapters)
        _llog.info("章节提交 | 章={} | 事件={} | 时长={}ms | 修正={}",
                   chapter_no, len(committed), record["duration_ms"],
                   "是" if correction else "否")
        return record

    async def _generate_and_repair(self, chapter_no: int, card,
                                   state: WorldState) -> tuple:
        """现有生成 + L1 修正回路（原 _generate_chapter_llm_path Step 1-4 原样抽出，
        供初版/兜底复用）。返回 (draft_text, draft_results, violations,
        correction, final_text, final_events)。"""
        # Step 1: 生成初稿（生成通道 — 不含 WorldState 秘密！）
        # P5.6（决策6）：IR-first 门控通过 → IR→Realizer 产初稿（Realizer 1 次
        # LLM 替代原 1 次生成）；空稿/异常 → warning + 回退 P3.8 prompt 路径
        draft_text = await self._produce_draft_text(chapter_no, card, state)

        # Step 2: 事件抽取
        draft_events = await self._llm_extract_events(chapter_no, draft_text)

        # Step 3: 7步硬约束验证（检查通道 — 以 WorldState 为基准）
        draft_results = self._validate_event_sequence(draft_events, state)
        violations = [
            {"event": r["event_summary"], "check": c["label"], "reason": c["reason"]}
            for r in draft_results for c in r["checks"] if not c["passed"]
        ]
        _llog.info("验证结果 | 章={} | 事件={} | 违规={}", chapter_no,
                   len(draft_results), len(violations))

        # Step 4: 修正回路（修正通道 — WorldState + 违规报告）
        correction = None
        final_text, final_events = draft_text, draft_events
        if violations:
            correction = await self._llm_correct(chapter_no, draft_text, violations, state)
            final_text = correction["text"]
            final_events = correction["events"]
            recheck = self._validate_event_sequence(final_events, state)
            correction["recheck_passed"] = all(
                c["passed"] for r in recheck for c in r["checks"])
            _llog.info("修正完成 | 章={} | 复验={}", chapter_no,
                       correction["recheck_passed"])
        return (draft_text, draft_results, violations, correction,
                final_text, final_events)

    # ============ Phase 5：IR-first 文本产出（决策6，env 门控） ============
    def _ir_first_enabled(self) -> bool:
        """IR-first 门控：SCRIPTED_DEMO=0 且 llm 非 mock 且 IR_FIRST!=0（默认开）。
        三条件任一不满足 → 走现有路径原样（mock/剧本零变化）；
        IR_FIRST=0 是质量漂移逃生门（回退 P3.8 prompt 路径）。
        P6.10 B9：进程内覆盖 _runtime_overrides['ir_first'] 优先于 env
        （settings 端点写，不持久化；SCRIPTED_DEMO/llm.is_mock 仍兜底）。"""
        if not (os.environ.get("STORY_ENGINE_SCRIPTED_DEMO", "1") == "0"
                and not self.llm.is_mock):
            return False
        ov = self._runtime_overrides.get("ir_first")
        if ov is not None:
            return bool(ov)
        return os.environ.get("STORY_ENGINE_IR_FIRST", "1") != "0"

    async def _produce_draft_text(self, chapter_no: int, card,
                                  state: WorldState) -> str:
        """直接 LLM 路径初稿产出：IR-first 优先，失败回退旧生成通道。

        门控/空稿/异常三种回退都在本方法内消化（迭代器与修正回路无感知）；
        摘要状态每轮重置，防止自评异常退回复跑时残留上一轮的 stale 值。
        """
        self._chapter_narrative_ir = None
        if self._ir_first_enabled():
            text, summary = await self._ir_first_narrate(chapter_no, card)
            if text is not None:
                self._chapter_narrative_ir = summary
                return text
        return await self._llm_generate_draft(chapter_no, card, state)

    def _ir_recap(self, chapter_no: int = 1) -> str | None:
        """IR-first Realizer prompt 的前情 recap（章节连续性上下文）。

        复用 _build_chapter_context 的完整上下文（蓝图+人物状态+前情+伏笔），
        让 Realizer 拥有和 Actor 同等的上下文信息，保证正文衔接质量。
        """
        ctx = self._build_chapter_context(chapter_no)
        return ctx if ctx else None

    def _build_chapter_context(self, chapter_no: int) -> str:
        """为 Actor propose 和 Realizer 提供完整情节上下文。

        利用百万上下文窗口，注入全部可用上下文：
        - 故事蓝图（logline/central_conflict/thematic_argument）
        - 宏观计划：当前集 synopsis + key_events
        - 人物状态（每角色 knows/secrets/goals + physical 位置）
        - 前情概要（最近 3 章标题+摘要+结尾关键句）
        - 未回收伏笔
        """
        parts: list[str] = []

        # ---- 1. 故事蓝图 ----
        plan = self._read_macro_plan()
        if plan:
            bp = plan.get("blueprint", {})
            if isinstance(bp, dict):
                parts.append(f"=== 故事蓝图 ===")
                ll = bp.get("logline", "")
                if ll:
                    parts.append(f"主线：{ll}")
                cc = bp.get("central_conflict", {})
                if isinstance(cc, dict):
                    w = cc.get("protagonist_want", "")
                    n = cc.get("protagonist_need", "")
                    if w or n:
                        parts.append(f"主角想要：{w}；需要学会：{n}")
                ta = bp.get("thematic_argument", {})
                if isinstance(ta, dict) and ta.get("lie"):
                    parts.append(f"主题：从「{ta.get('lie','')}」到「{ta.get('truth','')}」")

        # ---- 2. 宏观计划：当前集 ----
        macro_ctx = self._build_macro_context(chapter_no)
        if macro_ctx:
            syn = str(macro_ctx.get("synopsis") or macro_ctx.get("beat_synopsis") or "")
            if syn:
                parts.append(f"\n=== 本章宏观方向（第{chapter_no}集）===")
                parts.append(syn[:200])

        # ---- 3. 人物状态 ----
        state = self.kernel.query_world("current_state")
        char_lines: list[str] = []
        for cid in sorted(state.minds):
            m = state.minds[cid]
            meta = state.characters.get(cid, {})
            role = meta.get("role", "")
            goals = "、".join(m.goals[:3]) if m.goals else "无"
            knows = [f for f, v in list(m.beliefs.items()) if v][:5]
            secrets = list(m.secrets)[:2]
            line = f"  {cid}（{role}）：目标=[{goals}]"
            if knows:
                line += f"；已知={knows}"
            if secrets:
                line += f"；秘密={secrets}"
            char_lines.append(line)
        # physical 状态（位置等）
        phys = sorted(k for k, v in state.physical.items() if v)
        if phys:
            char_lines.append(f"  世界状态：{phys[:10]}")
        if char_lines:
            parts.append("\n=== 人物状态 ===")
            parts.extend(char_lines)

        # ---- 4. 前情概要（最近 3 章）----
        chapters = [c for c in self._read_chapters() if not c.get("superseded")]
        if chapters:
            recent = chapters[-3:]
            parts.append("\n=== 前情概要 ===")
            for c in recent:
                t = c.get("final", {}).get("text", "")
                tail = t[-150:].replace("\n", " ") if t else ""
                parts.append(f"第{c['chapter']}章《{c.get('title','')}》：…{tail}")

        # ---- 5. 未回收伏笔 ----
        pending = [f for f in state.narrative.foreshadow_pool if not f.payed_off]
        if pending:
            parts.append("\n=== 未回收伏笔 ===")
            for f in pending:
                parts.append(f"  {f.foreshadow_id}：{f.content}（触发：{f.trigger_condition}）")

        return "\n".join(parts) if parts else ""
        return "\n".join(parts)

    async def _ir_first_narrate(self, chapter_no: int, card,
                                *, close_chapter: bool = False) -> tuple:
        """IR-first 文本产出：IRBuilder → Fabula → Sjuzhet → Narrativizer。

        IR 构建/Sjuzhet 零 LLM 调用；Narrativizer.narrate 恰好 1 次（realize），
        替代原 1 次生成调用（每章 LLM 调用数持平）。
        close_chapter=True（Actor 路径：本章事件已提交但尚未收尾）时用
        _ChapterClosingKernelView 让章切片覆盖进行中的本章事件；
        直接 LLM 路径初稿时本章事件尚不存在（抽取在初稿之后），IR 由决策卡
        beats 承载内容，不需要虚拟闭合。

        返回 (text, narrative_ir_summary)；失败一律 (None, None) + warning：
        - narrate 空稿（Realizer 侧 LLM 故障返回 ""）→ 空稿 warning
          （不能让 LLM 故障变成无声空章，评审传导1）
        - IR 链路任何意外异常 → catch + warning（增强不是门禁，同 P4.5 原则）
        调用方负责回退旧路径。
        """
        try:
            kernel = (_ChapterClosingKernelView(self.kernel, chapter_no)
                      if close_chapter else self.kernel)
            ir = IRBuilder(kernel, self.bundle).build(card, chapter_no)
            # P5.11 评审传导5：close_chapter 追加的虚拟闭合 narrative_beat 只是
            # 章切片右界标记，不该进 IR 事件列表（who=world 的合成 EventIR 是
            # Realizer prompt 噪声）；真实闭合 beat 要等本章收尾才提交，此刻切片
            # 内的 narrative_beat 必为合成标记，过滤不误伤真实事件
            ir.events = [e for e in ir.events
                         if not (e.who == "world"
                                 and e.did == "act:narrative_beat")]
            active = [e for e in self.kernel.query_world("all_events")
                      if e.get("active", True)]
            fabula = FabulaBuilder().build(active)
            sjuzhet = SjuzhetSelector().select(fabula, self.bundle)
            text = await Narrativizer(self.kernel, self.bundle).narrate(
                ir, sjuzhet, recap=self._ir_recap(chapter_no),
                worldview_text=self._worldview_prompt_text(),
                macro_text=self._card_macro_text(card))
            _llog.info("IR-first 产出 | 章={} | beats={} | events={}", chapter_no,
                       len(ir.beats), len(ir.events))
        except Exception as exc:
            warnings.warn(
                f"P5.6 IR-first 链路异常（{exc!r}），回退旧文本产出路径",
                stacklevel=2)
            return None, None
        # P5.11 评审传导4：text=None（Narrativizer 异常路径返回值）时
        # text.strip() 会 AttributeError 逃逸兜底，一行防御
        if not (text or "").strip():
            warnings.warn(
                "P5.6 IR-first 产出空稿（Realizer LLM 故障），回退旧文本产出路径",
                stacklevel=2)
            return None, None
        # 标题行约定：Realizer prompt 现要求首行产「标题：XXXX」（4-8 字真实标题，
        # 非第N章）。此处做三件事：
        # 1. 若 LLM 没产标题行（未遵守 prompt）→ 兜底补「第N章」（保 L5 gate 不 FAIL）
        # 2. 若 LLM 产了半角冒号「标题:」→ 归一化为全角「标题：」（L5 只认全角）
        # 3. LLM 已产合格标题行 → 原样保留
        import re as _re
        first_line = text.lstrip().splitlines()[0] if text.strip() else ""
        if not _re.match(r"^标题[:：]\S", first_line):
            text = f"标题：第{chapter_no}章\n\n{text}"
        elif first_line.startswith("标题:"):
            # P5.12 ④：半角冒号标题归一化为全角——keep 正则接受半角，但 L5
            # title_format（process_gates `^标题：\S+`，全角口径）只认全角，
            # 不归一化会每章保底 L5 FAIL 多烧一轮修正。首行前仅有 lstrip 空白，
            # 「标题:」首次出现必在首行，replace 一次即精准命中
            text = text.replace("标题:", "标题：", 1)
        # 摘要（扁平小对象，非全量 IR —— 快照体积控制）：
        # beats/events/dialogue 计数 + texture 8 字段值 + 语言 + sjuzhet pov/order
        texture = asdict(ir.texture)
        # 句长分布 tuple → list，与 chapters.json 落盘形态一致（JSON 无 tuple）
        texture["sentence_length_distribution"] = list(
            ir.texture.sentence_length_distribution)
        summary = {
            "beats": len(ir.beats),
            "events": len(ir.events),
            "dialogue": len(ir.dialogue_lines),
            "language": self.bundle.language,
            "texture": texture,
            "pov": sjuzhet.pov,
            "order": sjuzhet.order,
        }
        return text, summary

    # ============ Phase 4：自评迭代（决策5/6，env 门控） ============
    def _eval_enabled(self) -> bool:
        """自评门控：SCRIPTED_DEMO=0 且 llm 非 mock 且 EVAL_ENABLED!=0。
        三条件任一不满足 → 走现有路径原样（mock/剧本路径零变化）。
        P6.10 B9：进程内覆盖 _runtime_overrides['eval_enabled'] 优先于 env
        （settings 端点写，不持久化；SCRIPTED_DEMO/llm.is_mock 仍兜底）。"""
        if not (os.environ.get("STORY_ENGINE_SCRIPTED_DEMO", "1") == "0"
                and not self.llm.is_mock):
            return False
        ov = self._runtime_overrides.get("eval_enabled")
        if ov is not None:
            return bool(ov)
        return os.environ.get("STORY_ENGINE_EVAL_ENABLED", "1") != "0"

    def _quality_gate_enabled(self) -> bool:
        """P23.4 质量门禁开关：默认开（生产路径生效）；STORY_ENGINE_QUALITY_GATE=0 关。

        与 _eval_enabled 的区别：_eval_enabled 是自评迭代开关（测试也开），
        _quality_gate_enabled 是硬质量门禁开关（测试默认关，避免 fake LLM 产出
        被误拦）。生产环境两者都开；测试设 QUALITY_GATE=0 跑通管线。
        """
        return os.environ.get("STORY_ENGINE_QUALITY_GATE", "1") != "0"

    def _eval_max_rounds(self) -> int:
        """EVAL_MAX_ROUNDS 默认 3，钳 [1, 5] 防失控（决策5）。
        P6.10 B9：进程内覆盖 _runtime_overrides['eval_max_rounds'] 优先于 env。"""
        ov = self._runtime_overrides.get("eval_max_rounds")
        if ov is not None:
            try:
                return max(1, min(5, int(ov)))
            except (TypeError, ValueError):
                pass
        try:
            n = int(os.environ.get("STORY_ENGINE_EVAL_MAX_ROUNDS", "3"))
        except ValueError:
            n = 3
        return max(1, min(5, n))

    def _build_eval_controller(self) -> tuple:
        """按需构建 evaluator 组件（仅门控通过时调用，mock/剧本零开销）。
        返回 (controller, reader, scorer)。
        STORY_ENGINE_CRITIC_MODEL 是蓝图「critic 模型 ≥ generator」的预留
        配置位：LLMPool.call 暂无 model 参数，本期 critic 与 generator 同模型。
        """
        parliament = CriticParliament(kernel=self.kernel, genre=self.bundle)
        gates = ProcessGate(style=self._prompt_config()["style"],
                            validator=self.validator)
        # 决策5：persona 取 genre params reader_persona，缺省用普通类型读者
        persona = (self.bundle.genre_params.get("reader_persona")
                   or "喜欢本类型的普通读者")
        reader = ReaderProxy(persona, kernel=self.kernel)
        # P7.3：parliament 从 story.evaluator pack 收集的优先级/ blocking 规则
        # 传给 Leader（空规则 → Leader 行为与基线逐字一致）
        controller = IterationController(
            parliament,
            LeaderArbiter(insertions=parliament.leader_insertions,
                          blocking_extra=parliament.leader_blocking),
            gates, reader,
            max_rounds=self._eval_max_rounds())
        scorer = PresentationScorer(self.bundle.genre_params)
        return controller, reader, scorer

    async def _generate_with_evaluation(self, chapter_no: int, card,
                                        state: WorldState) -> tuple:
        """决策5：IterationController 包「现有生成 + L1 修正回路」，best-of-K。

        generate_fn：首轮 = _generate_and_repair 初版原样；后续轮不重走生成
        通道，由 controller 把 revision.blocking 的 must_fix 作 feedback 传入，
        复用 _llm_correct 修正通道携带。每轮完整记录（文本→事件/验证/修正），
        供 best 版本回溯出待提交事件。
        返回 _generate_and_repair 五元组（初版 draft 字段 + best 的 final）
        + evaluation dict（决策6）。best=None（全轮 gate FAIL）→ 保留初版。
        """
        controller, reader, scorer = self._build_eval_controller()
        rounds: list[dict] = []

        async def generate_fn(spec, feedback=None):
            if not rounds:
                (dtext, dresults, viols, corr, ftext, fevents) = \
                    await self._generate_and_repair(chapter_no, card, state)
                rounds.append({"text": ftext, "events": fevents,
                               "draft_text": dtext, "draft_results": dresults,
                               "violations": viols, "correction": corr})
                return ftext
            prev = rounds[-1]
            corr = await self._llm_correct(
                chapter_no, prev["text"], prev["violations"], state,
                feedback=feedback)
            recheck = self._validate_event_sequence(corr["events"], state)
            corr["recheck_passed"] = all(
                c["passed"] for r in recheck for c in r["checks"])
            rounds.append({"text": corr["text"], "events": corr["events"],
                           "draft_text": prev["text"], "draft_results": recheck,
                           "violations": prev["violations"], "correction": corr})
            return corr["text"]

        # 章节级迭代：L1/L2/L3 缺单事件/角色/beat 上下文自动跳过，L5 恒跑
        result = await controller.run(
            generate_fn, ChapterSpec(state=state, decision=card))
        _llog.info("自评迭代完成 | 章={} | 轮数={} | best_round={}", chapter_no,
                   controller.max_rounds,
                   result.best.round if result.best else None)
        evaluation = await self._assemble_evaluation(
            result, controller, reader, scorer,
            rounds[0]["text"] if rounds else "")

        r0 = rounds[0]
        best = result.best
        if best is not None:
            chosen = next(
                (r for r in reversed(rounds) if r["text"] == best.text), r0)
        else:
            chosen = r0  # 全轮 gate FAIL → 保留初版，evaluation.gates 记原因
        return (r0["draft_text"], r0["draft_results"], r0["violations"],
                r0["correction"], chosen["text"], chosen["events"], evaluation)

    async def _iterate_display_text(self, chapter_no: int, base_text: str,
                                    violations: list[dict], state: WorldState,
                                    card) -> tuple:
        """决策5 Actor 路径：事件已提交，迭代只重生成展示文本（沿用 Actor
        text-only 修正先例），critic 评估对象是文本，事件历史不改写。
        返回 (best_text, evaluation)；best=None → 保留 base_text。"""
        controller, reader, scorer = self._build_eval_controller()
        rounds: list[str] = []

        async def generate_fn(spec, feedback=None):
            if not rounds:
                rounds.append(base_text)
                return base_text
            corr = await self._llm_correct(
                chapter_no, rounds[-1], violations, state,
                feedback=feedback, with_events=False)
            text = corr["text"] if corr["text"].strip() else rounds[-1]
            rounds.append(text)
            return text

        result = await controller.run(
            generate_fn, ChapterSpec(state=state, decision=card))
        evaluation = await self._assemble_evaluation(
            result, controller, reader, scorer, base_text)
        best = result.best
        return (best.text if best is not None else base_text), evaluation

    async def _assemble_evaluation(self, result, controller, reader, scorer,
                                   initial_text: str) -> dict:
        """决策6：evaluation 返回体（只增）。

        reader 取与 best 版本对齐的反应（controller.reactions 与 versions
        平行）；get_predictions() 暂只存入返回体（反预期设计接 L4 是后续）。
        best=None（全轮 gate FAIL）时重跑规则 gate 记 FAIL 原因
        （ProcessGate 纯规则无 LLM，零成本）。
        """
        versions = result.all_versions
        best = result.best
        predictions = reader.get_predictions() if reader else []
        if best is None:
            gate_objs = []
            if controller.gates is not None and initial_text:
                gate_objs = [await controller.gates.check_l5(initial_text)]
            return {
                "rounds": controller.max_rounds,
                "best_round": None,
                "gates": [asdict(g) for g in gate_objs],
                "critiques": [],
                "revision": None,
                "reader": None,
                "score": asdict(scorer.score([], None)),
                "reader_predictions": predictions,
            }
        idx = versions.index(best)
        reactions = controller.reactions  # P5.12 ⑤：公开只读 accessor，不再碰 _reactions
        reaction = reactions[idx] if idx < len(reactions) else None
        curves = reader.get_reaction_curve() if reader else None
        score = asdict(scorer.score(best.critiques, curves))
        # P23.4 门禁D：critic 低分 → quality_flag 标记（不阻塞，供前端/用户识别）
        overall = score.get("overall", 0) if isinstance(score, dict) else 0
        quality_flag = "low_score" if isinstance(overall, (int, float)) and overall < 60 else None
        return {
            "rounds": max(v.round for v in versions) + 1,
            "best_round": best.round,
            "gates": [asdict(g) for g in best.gates],
            "critiques": [asdict(c) for c in best.critiques],
            "revision": asdict(best.revision) if best.revision else None,
            "reader": asdict(reaction) if reaction else None,
            "score": score,
            "reader_predictions": predictions,
            "quality_flag": quality_flag,
        }

    async def _generate_chapter_actor_path(
        self, chapter_no: int, state: WorldState, t0: float, *,
        mode: str = "auto"
    ) -> dict:
        """Phase 2：Director spawn → tick×N → Showrunner 汇总 → 验证报告 → snapshot

        Actor 在 SOAR apply 步已 commit_event；本路径不再二次 commit 那些事件。
        """
        # P6.2：confirm 模式复用 plan 缓存卡
        card = self._resolve_decision_card(chapter_no, state, mode)
        _llog.info("决策卡生成（Actor） | 章={} | advance={}", chapter_no,
                   getattr(card, "advance", []))
        # P3.7：env 门控默认关；开启时每 N 章附 1 个 CreativeSeed（失败不阻塞）
        card = await self.showrunner.attach_creative_seed(card, chapter_no)
        await self._ensure_character_actors()

        # P0-1: 为每个 Actor 设置上一章情节上下文（解决情节断裂）
        chapter_ctx = self._build_chapter_context(chapter_no)
        for actor in self.kernel.scheduler._character_actors.values():
            actor.chapter_context = chapter_ctx

        max_ticks = int(os.environ.get("STORY_ENGINE_ACTOR_MAX_TICKS", "5"))
        self._progress("actor_tick", f"角色决策中（{max_ticks}轮）")

        # 写入本章 brief，供角色 recall
        await self._seed_chapter_memory(chapter_no, card, state)

        pre_state = copy.deepcopy(state)
        tick_start = self.kernel.query_world("next_tick")
        all_actions: list[dict] = []
        for tick_i in range(max(1, max_ticks)):
            cur = self.kernel.query_world("current_state")
            batch = await self.kernel.scheduler.tick_all(
                cur, chapter=chapter_no, timeout=120.0)
            all_actions.extend(batch)
            self._progress("actor_tick", f"角色决策 {tick_i+1}/{max_ticks}（累计 {len(all_actions)} 行动）")
        _llog.info("Actor tick 完成 | 章={} | 行动数={}", chapter_no,
                   len(all_actions))

        # 本 tick 区间内由 Actor 提交的事件
        all_ev = self.kernel.query_world("all_events")
        actor_events = [
            e for e in all_ev
            if e.get("world_tick", 0) >= tick_start
            and e.get("event_type") == "character_action"
        ]
        draft_events = [
            {
                "event_type": e["event_type"],
                "summary": (e.get("payload") or {}).get("summary", e["event_type"]),
                "payload": e.get("payload") or {},
            }
            for e in actor_events
        ]
        # P5.6（决策6）：IR-first 门控通过 → actor 事件经 IR→Realizer 产文本，
        # 替代汇总渲染（close_chapter=True：本章事件已提交但尚未收尾，
        # 虚拟闭合让章切片覆盖本章）；空稿/异常 → warning + 回退汇总渲染
        narrative_ir = None
        draft_text = None
        if self._ir_first_enabled():
            self._progress("realizing", "正文生成中（LLM 创作）")
            draft_text, narrative_ir = await self._ir_first_narrate(
                chapter_no, card, close_chapter=True)
        # P23.4 门禁B：Realizer 失败/产出非叙事文本时的处理。
        # 生产路径（_quality_gate_enabled）：报错让上层重试（动作日志不是小说正文）。
        # 测试/mock 路径：保留回退 _render_actor_chapter（测试 fake LLM 设 is_mock=False
        #   以过自评门控，但其 Realizer 产出非真实叙事，不该被门禁拦）。
        if draft_text is None or not _is_narrative_text(draft_text):
            if self._quality_gate_enabled():
                raise StoryEngineError(
                    f"第{chapter_no}章叙事化失败：Realizer 未产出有效正文"
                    f"（LLM 异常或返回空/动作日志）。")
            # 非生产路径回退（保留旧行为供测试管线跑通）
            draft_text = self._render_actor_chapter(chapter_no, card, all_actions)

        self._progress("verifying", f"验证事件一致性（{len(draft_events)} 个事件）")
        draft_results = self._validate_event_sequence(draft_events, pre_state) if draft_events else []
        violations = [
            {"event": r["event_summary"], "check": c["label"], "reason": c["reason"]}
            for r in draft_results for c in r["checks"] if not c["passed"]
        ]

        correction = None
        final_text = draft_text
        if violations and not self.llm.is_mock:
            # 仅修正叙事文本；Actor 已提交的事件保留（event sourcing 不改写历史）
            try:
                correction = await self._llm_correct(
                    chapter_no, draft_text, violations, pre_state)
                final_text = correction["text"]
                correction["note"] = (
                    (correction.get("note") or "")
                    + "（Actor 模式：事件已提交，仅修正展示文本）"
                )
                correction["recheck_passed"] = None
            except Exception as exc:
                correction = {
                    "text": draft_text,
                    "events": draft_events,
                    "note": f"修正失败，保留 Actor 原文：{exc}",
                    "violations_addressed": 0,
                    "recheck_passed": False,
                }

        # P4.5（决策5）：Actor 路径事件已提交，自评迭代只重生成展示文本
        # （沿用上方 text-only 修正先例），critic 评估对象是文本，不重写事件历史
        evaluation = None
        if self._eval_enabled() and final_text.strip():
            try:
                final_text, evaluation = await self._iterate_display_text(
                    chapter_no, final_text, violations, pre_state, card)
            except Exception:
                evaluation = None  # 自评是增强不是门禁

        if not final_text.strip() and not all_actions:
            raise StoryEngineError(
                "Actor 模式未产生任何行动 — 请检查 LLM/规则兜底是否可用。")

        if not final_text.strip():
            final_text = self._render_actor_chapter(chapter_no, card, all_actions)

        committed = [
            {
                "event_id": e.get("event_id"),
                "tick": e.get("world_tick"),
                "summary": (e.get("payload") or {}).get("summary", e.get("event_type")),
                "event_type": e.get("event_type"),
            }
            for e in actor_events
        ]
        tick = self.kernel.query_world("next_tick")
        fs_updates = self._apply_foreshadow_script(chapter_no, tick)
        snapshot_id = self.kernel.snapshot()
        head = self.kernel.query_world("head_tick")

        title = f"第{chapter_no}章"
        import re as _re
        # P0-4: 跳过开头的 --- 分隔线（LLM 常在 markdown 标题前加 ---）
        _body = _re.sub(r"^\s*---\s*\n+", "", final_text)
        if _body != final_text:
            final_text = _body
        # 接受多种标题格式：标题：xxx / # XXX / # 第N章 xxx / 第N章 xxx
        m = _re.match(r"\s*标题[:：]\s*(.+)", final_text)
        if not m:
            m = _re.match(r"\s*##?\s+(.+)", final_text)   # 纯 markdown 标题 # XXX / ## XXX
        if not m:
            m = _re.match(r"\s*#\s*(第.+章[^\n]*)", final_text)
        if not m:
            m = _re.match(r"\s*(第.+章[^\n]*)", final_text)
        if m:
            title = m.group(1).strip()[:30]
            # 去掉已匹配的标题行（保留正文）；兼容 标题:/# /第N章/纯markdown 多格式
            final_text = _re.sub(
                r"^\s*(?:标题[:：]\s*.+|##?\s+.+|第.+章[^\n]*)\n+", "", final_text, count=1)

        record = {
            "chapter": chapter_no,
            "title": title,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
            "llm_mode": "mock" if self.llm.is_mock else "openai",
            "generation_mode": "actor",
            "actor_ticks": max_ticks,
            "actor_actions": all_actions,
            "decision_card": card.to_dict(),
            "draft": {
                "text": draft_text,
                "events": draft_results,
                "violation_count": len(violations),
                "violations": violations,
            },
            "correction": correction,
            "final": {"text": final_text, "committed_events": committed},
            "foreshadow_updates": fs_updates,
            "snapshot_id": snapshot_id,
            "tick_range": [
                committed[0]["tick"] if committed else head,
                head,
            ],
            # P4.5（决策6）：自评结果（mock/门控关闭/异常退回 → None），只增不改
            "evaluation": evaluation,
            # P5.6（决策6）：IR-first 摘要（mock/IR_FIRST=0/回退 → None），只增不改
            "narrative_ir": narrative_ir,
        }
        chapters = self._read_chapters()
        chapters.append(record)
        self._write_chapters(chapters)
        _llog.info("章节提交（Actor） | 章={} | 行动={} | 时长={}ms",
                   chapter_no, len(all_actions), record["duration_ms"])
        return record

    async def _ensure_character_actors(self) -> None:
        """Director spawn：按创世阵容建角色 Actor（幂等）。

        P11.1：阵容数据源从 mock_script.SEED_* 切换到世界状态——genesis 已把
        本题材阵容写入 state.characters/minds（mystery 走 _genesis_state 全量
        种子，值与旧 SEED_* 逐字一致；其余题材走 cast 工厂），故 spawn 行为
        对 mystery 零变化、新题材 spawn 自己的阵容。voice 取
        characters[cid]["voice"]（cast voice_hint 的落点），goals 取
        minds[cid].goals；幂等语义不变（已 spawn 的角色跳过）。
        """
        if self._actors_ready and self.kernel.scheduler._character_actors:
            return
        if self._director_ref is None:
            self._director_ref = self.kernel.spawn_director(self.bundle)
        state = self.kernel.query_world("current_state")
        for cid, meta in state.characters.items():
            if cid in self.kernel.scheduler._character_actors:
                continue
            mind = state.minds.get(cid)
            goals = list(mind.goals) if mind else []
            cfg = CharacterConfig(
                character_id=cid,
                archetype=meta.get("archetype", ""),
                voice_profile={"voice": meta.get("voice", "")},
                initial_goals=goals,
                context_budget=8192,
            )
            persona = {**meta, "goals": goals}
            self.kernel.spawn_character_actor(cfg, persona=persona)
        self._actors_ready = True

    def _prompt_config(self) -> dict:
        """P3.8：题材插件 params.prompt（五键），缺段/缺键回退通用兜底"""
        cfg = dict(_GENERIC_PROMPT)
        cfg.update(self.bundle.genre_params.get("prompt") or {})
        return cfg

    async def _seed_chapter_memory(self, chapter_no: int, card, state: WorldState) -> None:
        banks = self.kernel._ensure_memory_banks()
        advance = "、".join(card.advance) if getattr(card, "advance", None) else ""
        scene = state.narrative.current_scene or "开场"
        # P3.6：Actor brief 同步携带 planner 原语序列摘要
        prim_txt = "、".join(dict.fromkeys(
            p for b in getattr(card, "beats", []) for p in b.get("primitives", [])))
        # P3.8：brief 人物表取自题材插件 prompt.characters（缺段走兜底）
        characters = self._prompt_config()["characters"]
        brief = (
            f"第{chapter_no}章决策：场景={scene}；推进={advance}；"
            f"人物={characters}；"
            f"情感弧={getattr(card, 'target_arc', '')}；"
            f"钩子={getattr(card, 'ending_hook', {})}；原语序列={prim_txt or '无'}"
        )
        # P17.4：宏观指导注入 brief（Actor recall 可取；无 macro_plan → 缺席，零变化）
        macro_ctx = getattr(card, "macro_context", None)
        if macro_ctx:
            brief += f"；本章宏观指导：{self._macro_context_text(macro_ctx)}"
        await banks.add(
            brief, bank="chapter_briefs", agent_id="_global",
            metadata={"chapter": chapter_no}, importance=7,
        )
        await banks.add(
            f"当前场景：{scene}", bank="world_state", agent_id="_global",
            metadata={"chapter": chapter_no}, importance=6,
        )

    def _render_actor_chapter(
        self, chapter_no: int, card, actions: list[dict]
    ) -> str:
        """简化 Realizer：把各 Actor 行动摘要拼成章节正文"""
        lines = [f"标题：第{chapter_no}章", ""]
        if not actions:
            lines.append("（本轮无人行动）")
        else:
            for a in actions:
                agent = a.get("actor_id", "?")
                summary = a.get("summary") or "采取行动"
                lines.append(f"{agent}：{summary}")
            lines.append("")
            lines.append(
                f"（本章经 {len(actions)} 次角色行动推进；"
                f"情感弧目标：{getattr(card, 'target_arc', '')}）"
            )
        return "\n".join(lines)

    # ============ 剧本/真实 通道路由 ============
    def _scripted(self, chapter_no: int) -> bool:
        return (os.environ.get("STORY_ENGINE_SCRIPTED_DEMO", "1") == "1"
                and chapter_no in mock_script.DRAFTS)

    # ============ 三通道 LLM 调用（worldstate_paradox 架构） ============
    async def _llm_generate_draft(self, chapter_no: int, card, state: WorldState) -> str:
        """生成通道：只看已定稿故事与决策卡，不看 WorldState 秘密"""
        if self._scripted(chapter_no):
            return mock_script.respond("generate_chapter", f"【CHAPTER={chapter_no}】")
        resp = await self.llm.call(
            self._real_generate_prompt(chapter_no, card, state),
            purpose="generate_chapter", temperature=0.7)
        return resp.text

    def _real_generate_prompt(self, chapter_no: int, card, state: WorldState) -> str:
        chapters = [c for c in self._read_chapters() if not c.get("superseded")]
        history = "\n\n".join(
            f"【第{c['chapter']}章《{c['title']}》】\n{c['final']['text'][-600:]}"
            for c in chapters[-3:])
        pending = [f for f in state.narrative.foreshadow_pool if not f.payed_off]
        pending_txt = "；".join(
            f"{f.foreshadow_id}：{f.content}（触发：{f.trigger_condition}）" for f in pending)
        track_names = {t.id: t.name for t in self.showrunner.tracks.values()}
        advance_txt = "、".join(track_names.get(t, t) for t in card.advance)
        # P3.6：planner 原语序列摘要（决策卡 beats[].primitives，按 beat 顺序去重）
        prim_txt = " → ".join(dict.fromkeys(
            p for b in card.beats for p in b.get("primitives", [])))
        # P3.7：CreativeSeed → 「可选灵感」段（仅门控开启且挂载成功时非空；
        # 明示"可参考可忽略"，不进入硬要求，最小侵入既有 prompt）
        inspire_txt = ""
        if getattr(card, "creative_seeds", None):
            s = card.creative_seeds[0]
            domains = " × ".join(s.get("domains", []))
            inspire_txt = (
                f"可选灵感（可参考可忽略）：{domains} —— {s.get('emergent', '')[:200]}\n")
        # P5.12 ①：intent 介入消费 —— 决策卡 author_intent → 本章调度段首行
        # （硬指令语气；无介入事件时为 None，prompt 与现状逐字一致）
        intent_txt = ""
        if getattr(card, "author_intent", None):
            intent_txt = f"作者意图（必须遵循）：{card.author_intent}\n"
        # P3.8：生成文案从题材插件 params.prompt 渲染（缺段/缺键走通用兜底）；
        # 「章末留钩子 + 首行标题格式」是引擎级约定（标题行由引擎解析），
        # 统一追加在插件 hard_requirements 之后
        pcfg = self._prompt_config()
        hard_reqs = [pcfg["style"], *(pcfg.get("hard_requirements") or []),
                     "章末留钩子",
                     "第一行写：标题：XXXX（不超过八字），空一行后接正文"]
        hard_txt = "\n".join(f"{i}. {req}" for i, req in enumerate(hard_reqs, 1))
        # P12.3：世界观设定段（双通道融合）；无 profile / 空文本时整段缺席，
        # prompt 与现状逐字一致
        wv_text = self._worldview_prompt_text()
        wv_txt = (f"=== 世界观设定 ===\n{wv_text}\n\n" if wv_text else "")
        # P17.4：宏观指导段（从 card.macro_context 提取；None/空 → 缺席，零变化）
        macro_ctx = getattr(card, "macro_context", None)
        macro_txt = ""
        if macro_ctx:
            mt = self._macro_context_text(macro_ctx)
            if mt:
                macro_txt = f"=== 本章宏观指导 ===\n{mt}\n\n"
        return (
            f"【CHAPTER={chapter_no}】\n"
            f"你是{pcfg['role']}。背景：{pcfg['setting']}。\n"
            f"人物：{pcfg['characters']}。\n\n"
            f"{wv_txt}{macro_txt}"
            f"=== 已定稿前情 ===\n{history or '（开篇）'}\n\n"
            f"=== 本章调度 ===\n{intent_txt}推进轨道：{advance_txt}\n"
            f"原语序列：{prim_txt or '无'}\n"
            f"{inspire_txt}"
            f"情感弧目标：{card.target_arc}　集末钩子：{card.ending_hook['style']}\n"
            f"待回收伏笔（尽量以自然方式兑现其一）：{pending_txt or '无'}\n\n"
            f"=== 硬要求 ===\n{hard_txt}")

    async def _llm_extract_events(self, chapter_no: int, text: str) -> list[dict]:
        if self._scripted(chapter_no):
            return self._parse_events_json(
                mock_script.respond("extract_events", f"【CHAPTER={chapter_no}】"))
        resp = await self.llm.call(
            self._real_extract_prompt(chapter_no, text),
            purpose="extract_events", temperature=0.2)
        return self._parse_events_json(resp.text)

    def _real_extract_prompt(self, chapter_no: int, text: str,
                             purpose: str = "extract_events") -> str:
        state = self.kernel.query_world("current_state")
        at_fluents = sorted(f for f in state.physical if f.startswith("at("))
        knows = "; ".join(
            f"{cid}知道[{', '.join(f for f, v in m.beliefs.items() if v)}]"
            for cid, m in state.minds.items())
        # P3.8：实体名册与活跃目标改从 WorldState 动态取（题材无关，不再写死）
        roster = "/".join(state.characters) or "（无）"
        goals = " ".join(
            f"{cid}[{','.join(m.goals)}]" for cid, m in state.minds.items())
        return (
            f"【CHAPTER={chapter_no}】\n"
            "从下面的章节文本抽取「世界事件序列」，只输出 JSON 数组。每个事件：\n"
            '{"event_type": "character_action|world_change|narrative_beat", "summary": "一句话", "payload": {...}}\n'
            "payload 按需包含：\n"
            '- agent, action, story_time（故事内时间，格式「第N日·X时」，时辰用子丑寅卯辰巳午未申酉戌亥）\n'
            '- physical_preconditions: ["at(人,地)"]（该行动发生所需的位置前提）\n'
            '- effects: {"set_fluents": ["at(人,地)"], "unset_fluents": [...], "learn": {"角色": ["事实"]}}\n'
            '- requires_knowing: ["事实"]（角色说出/使用该信息，前提是他已经知道）\n'
            '- motivation（该行动的动机，须能追溯到已确立的前因）\n'
            '- serves_goal（从各角色活跃目标里选）\n'
            '- has_supernatural: true/false（是否出现超自然）\n'
            '- is_resolution: true/false（该事件是否直接解决案件）\n'
            "每个事件开头通常先有一个 world_change 推进故事时间；"
            "位置变化必须有对应事件（人不可能瞬移）。\n\n"
            f"实体名册：{roster}\n"
            f"当前位置事实：{', '.join(at_fluents)}\n"
            f"当前故事时间：{state.narrative.last_story_time}\n"
            f"各角色已确立的认知：{knows}\n"
            f"角色活跃目标：{goals}\n\n"
            f"=== 章节文本 ===\n{text[:3000]}\n\n只输出 JSON 数组，不要解释。")

    def _world_rule_correction_hint(self) -> str:
        """按文化 supernatural_tolerance 生成「世界规则违规」的修正指引。

        公案/现代（低容忍）：超自然只作氛围，破案/解谜走证据链。
        修仙/玄幻/神话（高容忍）：超自然是核心设定，保持其体系自洽即可。
        中间值：超自然允许但需有体系约束。
        """
        try:
            tol = float(self.culture.params.get("supernatural_tolerance", 0.5))
        except (TypeError, ValueError):
            tol = 0.5
        if tol >= 0.7:
            return "超自然力量是本世界核心设定，保持其体系自洽（代价/来源/限制一致）"
        if tol <= 0.4:
            return "超自然只作氛围，关键推进走证据链/合理调查"
        return "超自然元素允许，但需有内在体系约束，不可随意破规"

    async def _llm_correct(self, chapter_no: int, draft_text: str,
                           violations: list[dict], state: WorldState,
                           feedback: list[str] | None = None,
                           with_events: bool = True) -> dict:
        """修正通道：WorldState + 违规报告（对照基准，针对性修正）

        P4.5（决策5）：feedback 为自评 Leader 仲裁的 must_fix，拼进修正 prompt
        （复用本设施，不新建通道）；with_events=False 跳过修正后的事件重抽取
        （Actor 展示文本迭代只要文本，省 1 次 LLM 调用）。
        两者均为可选参数，缺省调用行为与原样逐字一致。
        """
        v_text = "；".join(f"{v['event']}——{v['reason']}" for v in violations) or "无"
        fb_txt = ""
        task_line = "修正这些违规，保持叙事质量与篇幅。规则：\n"
        if feedback:
            fb_txt = ("自评反馈（必须逐条处理）：\n"
                      + "\n".join(f"- {f}" for f in feedback) + "\n\n")
            task_line = "修正上述违规与自评反馈，保持叙事质量与篇幅。规则：\n"
        # 世界规则违规修正指引：按文化 supernatural_tolerance 动态生成。
        # 旧实现硬编码「超自然只作氛围，破案改走证据链」——这是公案专属规则，
        # 对修仙/玄幻/神话会错误压制超自然元素（那些题材超自然是核心非氛围）。
        wrule = self._world_rule_correction_hint()
        prompt = (
            f"【CHAPTER={chapter_no}】\n"
            f"以下是世界状态（检查基准）：\n{self._world_state_digest(state)}\n\n"
            f"以下是生成的文本（含违规）：\n{draft_text[:2500]}\n\n"
            f"检查发现的违规：{v_text}\n\n"
            f"{fb_txt}"
            f"{task_line}"
            "- 认知违规：改为合法获知渠道（调查/证词/物证），或删去该信息\n"
            "- 物理违规：补上必要的位置转移过程\n"
            f"- 世界规则违规：{wrule}\n"
            "只输出修正后的正文（保留首行标题）。")
        if self._scripted(chapter_no):
            note = mock_script.CORRECTIONS[chapter_no]["note"]
            return {"text": mock_script.respond("correct_chapter", f"【CHAPTER={chapter_no}】"),
                    "events": self._parse_events_json(
                        mock_script.respond("extract_corrected_events", f"【CHAPTER={chapter_no}】")),
                    "note": note, "violations_addressed": len(violations)}
        resp = await self.llm.call(prompt, purpose="correct_chapter", temperature=0.5)
        if not with_events:
            return {"text": resp.text, "events": [],
                    "note": "LLM 对照世界状态修正（仅展示文本）",
                    "violations_addressed": len(violations)}
        resp_events = await self.llm.call(
            self._real_extract_prompt(chapter_no, resp.text),
            purpose="extract_corrected_events", temperature=0.2)
        return {"text": resp.text,
                "events": self._parse_events_json(resp_events.text),
                "note": "LLM 对照世界状态修正",
                "violations_addressed": len(violations)}

    # ============ 验证（对事件序列逐步检查） ============
    def _validate_event_sequence(self, events: list[dict],
                                 base_state: WorldState) -> list[dict]:
        """对候选事件序列逐个验证（scratch state 随事件推进，模拟世界演化）"""
        scratch = copy.deepcopy(base_state)
        results = []
        tick = self.kernel.query_world("next_tick")
        for ev in events:
            event = WorldEvent(
                event_id="candidate", event_type=ev["event_type"],
                timestamp=datetime.now().isoformat(timespec="seconds"),
                world_tick=tick, branch_id="main", payload=ev["payload"])
            verdict = self.validator.validate(event, scratch)
            results.append({
                "event_summary": ev.get("summary", ev["event_type"]),
                "event_type": ev["event_type"],
                "passed": verdict.passed,
                "checks": [asdict(c) for c in verdict.checks],
            })
            scratch.apply(event)
            tick += 1
        return results

    # ============ 伏笔池（CFPG） ============
    def _apply_foreshadow_script(self, chapter_no: int, current_tick: int) -> dict:
        """更新伏笔池。Mock 模式按剧本；真实模式按决策卡计划。"""
        state = self.kernel.query_world("current_state")
        pool = state.narrative.foreshadow_pool

        if self._scripted(chapter_no):
            script = mock_script.FORESHADOW_SCRIPT.get(chapter_no, {"planted": [], "payed": []})
            planted_specs, payed_ids = script["planted"], script["payed"]
        else:
            card = self.showrunner.generate_decision_card(chapter_no, state)
            planted_specs = [
                {"foreshadow_id": f"F{len(pool)+i+1}", "content": p.get("content", ""),
                 "trigger_condition": p.get("trigger", ""), "payoff": p.get("payoff", ""),
                 "required": True}
                for i, p in enumerate(card.new_foreshadows)]
            payed_ids = [p["foreshadow_id"] for p in card.active_payoffs]

        planted = []
        for spec in planted_specs:
            fs = ForeshadowTriple(
                foreshadow_id=spec["foreshadow_id"], content=spec["content"],
                planted_at_tick=current_tick, planted_chapter=chapter_no,
                trigger_condition=spec["trigger_condition"], payoff=spec["payoff"],
                required=spec.get("required", True))
            pool.append(fs)
            planted.append(asdict(fs))
        payed = []
        for fid in payed_ids:
            for fs in pool:
                if fs.foreshadow_id == fid and not fs.payed_off:
                    fs.payed_off = True
                    fs.payed_at_chapter = chapter_no
                    payed.append(asdict(fs))

        # 伏笔池变化通过 narrative_beat 事件持久化（event sourcing）
        event = WorldEvent(
            event_id=str(uuid4())[:8], event_type="narrative_beat",
            timestamp=datetime.now().isoformat(timespec="seconds"),
            world_tick=self.kernel.query_world("next_tick"), branch_id="main",
            payload={"chapter": chapter_no,
                     "foreshadow_sync": [asdict(fs) for fs in pool]})
        self.kernel.commit_event(event)
        return {"planted": planted, "payed_off": payed}

    # ============ 查询接口（给 FastAPI） ============
    def project_snapshot(self) -> dict:
        state = self.kernel.query_world("current_state")
        head = self.kernel.query_world("head_tick")
        chapters = self._read_chapters()
        for ch in chapters:
            ch["rolled_back"] = bool(ch.get("superseded")) or ch["tick_range"][1] > head
        return {
            "meta": {
                "project": self.project_dir.name,
                "genre": self.genre.name, "culture": self.culture.name,
                "language": "zh",
                "llm_mode": "mock" if self.llm.is_mock else "openai",
                "llm_model": self.llm.model,
                "head_tick": head,
                "chapter_count": state.narrative.chapter,
            },
            "world_state": self._present_world_state(state),
            "events": self.kernel.query_world("all_events"),
            "snapshots": self.kernel.query_world("snapshots"),
            "chapters": chapters,
            "call_log": self.llm.call_log[-30:],
            # P6.2：待批准决策卡（两阶段生成第一步缓存；无 → None），只增不改
            "pending_plan": (self._pending_plan.to_dict()
                             if self._pending_plan is not None else None),
        }

    def settings_view(self) -> dict:
        """P6.10 B9：设置面板只读视图（GET /api/settings 返回此结构）。

        返回当前生效值（覆盖优先于 env），api_key/base_url 不在此暴露——
        base_url_masked 仅给前端展示（key 永不出后端，评审意见 8 安全要求）。
        """
        return {
            "eval_enabled": self._eval_enabled_gate(),
            "ir_first": self._ir_first_gate(),
            "eval_max_rounds": self._eval_max_rounds(),
            "llm_mode": "mock" if self.llm.is_mock else "openai",
            "llm_model": self.llm.model,
            "llm_configured": bool(self.llm.api_key),
            "base_url_masked": _mask_url(self.llm.base_url),
        }

    def apply_llm_settings(self, patch: dict) -> dict:
        """P23：LLM 接入在线配置（进程内覆盖；持久化与否由调用方决定）。
        就地更新 LLMPool 单例属性（全栈单例相干，无需重启）；
        空值=保持不变；给了 api_key 即切 openai 模式（is_mock 读 mode+key）。
        返回更新后的 settings_view。"""
        llm = self.llm
        base_url = (patch.get("base_url") or "").strip()
        if base_url:
            llm.base_url = base_url.rstrip("/")
        model = (patch.get("model") or "").strip()
        if model:
            llm.model = model
        api_key = (patch.get("api_key") or "").strip()
        if api_key:
            llm.api_key = api_key
            llm.mode = "openai"
            # 与 LLMPool.__init__ 同款：sk-kimi- key 自动补 Coding-Agent UA
            if not llm.user_agent and api_key.startswith("sk-kimi-"):
                from .kernel.llm_pool import KIMI_CODE_UA
                llm.user_agent = KIMI_CODE_UA
        return self.settings_view()

    def _eval_enabled_gate(self) -> bool:
        """裸 EVAL_ENABLED 门控（不管 SCRIPTED_DEMO/llm.is_mock）—给 settings_view
        展示开关当前值；_eval_enabled（实际生成时调用）仍含三条件兜底。"""
        ov = self._runtime_overrides.get("eval_enabled")
        if ov is not None:
            return bool(ov)
        return os.environ.get("STORY_ENGINE_EVAL_ENABLED", "1") != "0"

    def _ir_first_gate(self) -> bool:
        """裸 IR_FIRST 门控（同 _eval_enabled_gate 口径）。"""
        ov = self._runtime_overrides.get("ir_first")
        if ov is not None:
            return bool(ov)
        return os.environ.get("STORY_ENGINE_IR_FIRST", "1") != "0"

    def apply_settings_overrides(self, patch: dict) -> dict:
        """P6.10 B9：写进程内覆盖（POST /api/settings），不写 .env 不持久化。
        仅认三个键；非法值忽略（保持原覆盖/默认），返回更新后的 settings_view。"""
        if "eval_enabled" in patch:
            self._runtime_overrides["eval_enabled"] = bool(patch["eval_enabled"])
        if "ir_first" in patch:
            self._runtime_overrides["ir_first"] = bool(patch["ir_first"])
        if "eval_max_rounds" in patch:
            try:
                n = int(patch["eval_max_rounds"])
            except (TypeError, ValueError):
                n = None
            if n is not None:
                self._runtime_overrides["eval_max_rounds"] = max(1, min(5, n))
        return self.settings_view()

    def rollback(self, to_tick: int) -> dict:
        self.kernel.rollback(to_tick)
        # P6.2：时间线改动作废待批准方案（缓存卡对应旧时间线的下一章）
        self._pending_plan = None
        chapters = self._read_chapters()
        changed = False
        for ch in chapters:
            if ch["tick_range"][1] > to_tick and not ch.get("superseded"):
                ch["superseded"] = True
                changed = True
        if changed:
            self._write_chapters(chapters)
        return self.project_snapshot()

    async def regenerate_current_chapter(self) -> dict:
        """P5.8：structural 介入后的章级重生成入口（供 InterventionRouter
        regenerate_fn 注入；router 侧要求无参同步调用，async 接线由调用方包装）。

        前置：InterventionRouter 已把改动点及其下游事件标 rolled_back
        （kernel.rollback，head 回移）。本入口负责：
        1. 把 chapters.json 里被回滚的章节记录标 superseded（同 rollback() 口径，
           否则重生成后新旧两条同章记录并存、且旧记录会因 head 回升显示为未回滚）；
        2. 按当前 projection 重跑本章（generate_chapter 章号取自
           state.narrative.chapter + 1，回滚后自然重跑进行中的本章）。
        与蓝图「从改动点精准重放下游」的简化差：只重跑当前章，不做跨章连锁重放。
        """
        head = self.kernel.query_world("head_tick")
        chapters = self._read_chapters()
        changed = False
        for ch in chapters:
            if ch["tick_range"][1] > head and not ch.get("superseded"):
                ch["superseded"] = True
                changed = True
        if changed:
            self._write_chapters(chapters)
        return await self.generate_chapter()

    def update_chapter_text(self, chapter: int, before, after) -> str:
        """P6.1(B1)：textual 介入的单章正文回写公开口子（chapters.json 唯一
        写入口 _write_chapters 之上；供 InterventionRouter textual 路由经
        backend 以 textual_apply_fn 注入调用）。

        语义：该章 final.text 中 before 首次出现处替换为 after，chapters.json
        其余字段不动。返回状态字符串（写章本身之外的判定都在这里，router 只
        负责按状态选 message）：
          "updated"     正文已更新
          "miss"        before 为空或未命中（正文不动，由调用方仅留痕）
          "rolled_back" 命中章全部已 rolled_back（superseded 或 tick_range 尾
                        超过 head，与 project_snapshot 的 rolled_back 口径一致）
          "not_found"   无此章号记录
        同章号可能有多条记录（重生成后旧记录 superseded 并存）：只在 active
        记录上替换（取最新一条）。IO 失败向上抛，由调用方降级（仅留痕 + log）。
        """
        chapters = self._read_chapters()
        head = self.kernel.query_world("head_tick")
        matches = [ch for ch in chapters
                   if str(ch.get("chapter")) == str(chapter)]
        if not matches:
            return "not_found"
        active = [ch for ch in matches
                  if not ch.get("superseded") and ch["tick_range"][1] <= head]
        if not active:
            return "rolled_back"
        target = active[-1]
        text = (target.get("final") or {}).get("text") or ""
        if not before or before not in text:
            return "miss"
        target["final"]["text"] = text.replace(before, after, 1)
        self._write_chapters(chapters)
        return "updated"

    # ============ P6.3：段落重写（B2，写作台核心卖点） ============
    @staticmethod
    def _split_paragraphs(text: str) -> list[str]:
        """段落协议（P6.3，与前端写作台工具函数约定一致，接口文档注明）：
        final.text 按 \\n\\n 切分，剔除空白块；首块若为标题行（^标题[:：]）
        不计入段序号——para_index 从正文第一段起 0 基。"""
        import re as _re
        paras = [p.strip() for p in text.split("\n\n")]
        paras = [p for p in paras if p]
        if paras and _re.match(r"^标题[:：]", paras[0]):
            paras = paras[1:]
        return paras

    @staticmethod
    def _chapter_ir_context(rec: dict) -> str:
        """单段重写的本章骨架摘要 —— 复用 chapters.json 既有记录：决策卡
        beats + narrative_ir 摘要（pov/order/计数，仅 IR-first 章有）。
        比 realizer._ir_summary 简化：不重建全量 IR（chapters.json 只存
        摘要；重跑 IRBuilder 切章事件成本高，段级任务用不上）。"""
        lines = []
        for b in (rec.get("decision_card") or {}).get("beats") or []:
            prims = ",".join(str(p) for p in (b.get("primitives") or [])) or "-"
            lines.append(
                f"[{b.get('beat_id', '?')}] phase={b.get('phase', '?')} "
                f"tension={b.get('tension', '?')} "
                f"track={b.get('track_name', '')} primitives={prims}")
        ir = rec.get("narrative_ir")
        if ir:
            lines.append(
                f"[ir] pov={ir.get('pov')} order={ir.get('order')} "
                f"beats={ir.get('beats')} events={ir.get('events')} "
                f"dialogue={ir.get('dialogue')}")
        return "\n".join(lines) or "（无骨架记录）"

    async def rewrite_paragraph(self, chapter: int, para_index: int,
                                direction: str = "", *, llm_call=None) -> dict:
        """P6.3(B2)：段落重写 —— Realizer 单段渲染（IR 摘要 + 方向 +
        前后段上下文），返回 {original, rewritten} diff 对。

        - 只读不写：本方法不回写正文；前端「采用」时走 textual 介入通道
          （P6.1 update_chapter_text，before=original 首现处替换）。
        - 成本：恰好 1 次 LLM 调用（realizer.rewrite_paragraph）；不接
          critic 自评迭代（本阶段简化：单段重写不过议会，注释见 realizer）。
        - llm_call：测试 fake 注入点（critic/realizer 同款 callable 风格）；
          None → kernel.llm_call。
        返回 dict：
          status="ok"           {chapter, para_index, original, rewritten, note}
                                rewritten="" 时 note 说明（LLM 空稿/异常兜底，
                                不抛错，前端统一按空重写处理）
          status="not_found"    无此章号记录 → 端点 404
          status="rolled_back"  命中章全部已 rolled_back（判据同
                                update_chapter_text / project_snapshot）→ 409
          status="out_of_range" para_index 越界（含负数），带 para_count → 404
        """
        chapters = self._read_chapters()
        head = self.kernel.query_world("head_tick")
        matches = [ch for ch in chapters
                   if str(ch.get("chapter")) == str(chapter)]
        if not matches:
            return {"status": "not_found"}
        active = [ch for ch in matches
                  if not ch.get("superseded") and ch["tick_range"][1] <= head]
        if not active:
            return {"status": "rolled_back"}
        target = active[-1]
        paras = self._split_paragraphs(
            (target.get("final") or {}).get("text") or "")
        if para_index < 0 or para_index >= len(paras):
            return {"status": "out_of_range", "para_count": len(paras)}
        realizer = Narrativizer(
            self.kernel, self.bundle, llm_call=llm_call
        ).select_realizer(self.bundle.language)
        rewritten = await realizer.rewrite_paragraph(
            ir_context=self._chapter_ir_context(target),
            original=paras[para_index],
            prev_para=paras[para_index - 1] if para_index > 0 else None,
            next_para=(paras[para_index + 1]
                       if para_index + 1 < len(paras) else None),
            direction=direction, bundle=self.bundle)
        note = None
        if not rewritten:
            note = ("LLM 空稿或调用异常（mock/未配置/网络故障），本次未产出"
                    "重写文本；原段未改动，可重试")
        return {"status": "ok", "chapter": target["chapter"],
                "para_index": para_index, "original": paras[para_index],
                "rewritten": rewritten, "note": note}

    # ============ P6.4：角色卡聚合（B4，支撑前端人物视图） ============
    def characters_view(self) -> list[dict]:
        """GET /api/characters 的组装逻辑：世界状态投影 → 角色卡列表（按 id 排序，
        空项目 → []）。数据源全部真实可查，不编造：
        - knows/secrets/goals/role：state.minds + state.characters
          （与 _present_world_state 的 minds 投影同口径：knows=beliefs 真值键）
        - relations：state.relationships（键 "A|B" 拆对，note=history 末条，无 → None）
        - voice：Actor 声音档案 VoiceProfile.voice_hint（经 _actor_voice_hints 取
          scheduler._character_actors；仅 Actor 路径生成后进程内存活）。Actor 不可得
          时回退 state.characters 的 seed voice 串 —— 即 VoiceProfile.from_seed 的
          同源数据（voice_hint 正是由它构造）；两者皆无 → None
        - arc：恒 None —— 已核 mystery.yaml/romance.yaml 的 tracks 只有
          id/name/arc_type/archetype/progress，无角色↔轨道显式绑定，不猜测
        """
        state = self.kernel.query_world("current_state")
        return self._characters_view(state, self._actor_voice_hints())

    def _actor_voice_hints(self) -> dict[str, str]:
        """存活 CharacterActor 的 VoiceProfile.voice_hint（无 Actor/无 hint → 不含该键）"""
        hints = {}
        actors = getattr(self.kernel.scheduler, "_character_actors", None) or {}
        for cid, actor in actors.items():
            hint = getattr(getattr(actor, "voice", None), "voice_hint", "")
            if hint:
                hints[cid] = hint
        return hints

    @staticmethod
    def _characters_view(state: WorldState,
                         voice_hints: dict[str, str] | None = None) -> list[dict]:
        """角色卡纯组装（静态，便于空态单测）；voice_hints 见 characters_view

        P23.1 白名单过滤：事件流里出现的任意 agent 字符串都会自动建 mind
        （types.py WorldState.apply），群体/机构/占位名（「评议会」「嫌疑人甲」
        「角色」）由此灌进人物列表。过滤规则：只保留 ①在阵容册
        （state.characters）内，或 ②有目标/秘密等实质心智内容的 mind；
        仅持有零散信念的裸 mind（多为噪音）不展示。"""
        voice_hints = voice_hints or {}
        cards = []
        for cid in sorted(state.minds):
            m = state.minds[cid]
            if cid not in state.characters and not m.goals and not m.secrets:
                continue
            relations = []
            for key in sorted(state.relationships):
                pair = key.split("|")
                if len(pair) != 2 or cid not in pair:
                    continue
                r = state.relationships[key]
                relations.append({
                    "target": pair[1] if pair[0] == cid else pair[0],
                    "type": r.type,
                    "intensity": r.intensity,
                    "note": r.history[-1] if r.history else None,
                })
            voice = (voice_hints.get(cid)
                     or state.characters.get(cid, {}).get("voice") or None)
            cards.append({
                "id": cid,
                "role": state.characters.get(cid, {}).get("role", ""),
                "knows": [f for f, v in m.beliefs.items() if v],
                "secrets": list(m.secrets),
                "goals": list(m.goals),
                "relations": relations,
                "voice": voice,
                "arc": None,
            })
        return cards

    def reset(self) -> dict:
        # 停掉 Actor 循环
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self.kernel.scheduler.stop_all())
            else:
                loop.run_until_complete(self.kernel.scheduler.stop_all())
        except Exception:
            self.kernel.scheduler._character_actors.clear()
        self._actors_ready = False
        self._director_ref = None

        # 原位清库（热修复 2026-07-21：旧实现 kernel.close()+unlink(story.db)+
        # 重建 EventStore——Windows 下任何占用连接都会让 unlink 静默失败，
        # 造成「chapters 清空但旧事件全保留」的半重置（用户抽卡开局实测踩中）。
        # 原位 DELETE 经 store 自有连接，不受文件锁影响，失败显式上抛）
        self.kernel.store.clear_all()
        # 保证创世种子工厂指向本引擎题材工厂（P11.1：mystery 静态法 /
        # 其余题材 cast 工厂，由 _genesis_factory 选定）：直接构造 Kernel
        # 的路径（如 backend/main.py）默认是占位工厂，旧实现靠重建 store
        # 顺带修正，原位清库后必须显式对齐，否则种子角色/关系/目标丢失
        self.kernel.store._initial_state_factory = self._genesis_factory()
        if self.kernel.memory_banks is not None:
            self.kernel.memory_banks.clear()
        self.kernel._retrieval_by_agent = {}
        self._write_chapters([])
        self._pending_plan = None  # P6.2：重置作废待批准方案
        return self.project_snapshot()

    # ============ 展示层辅助 ============
    def _present_world_state(self, state: WorldState) -> dict:
        minds = {}
        for cid, m in state.minds.items():
            known = [f for f, v in m.beliefs.items() if v]
            minds[cid] = {
                "knows": known, "secrets": m.secrets,
                "goals": m.goals, "affect": m.affect,
                "role": state.characters.get(cid, {}).get("role", ""),
            }
        all_facts = set()
        for m in state.minds.values():
            all_facts.update(f for f, v in m.beliefs.items() if v)
            all_facts.update(m.secrets)
        for cid in minds:
            minds[cid]["doesnt_know"] = sorted(
                f for f in all_facts
                if f not in state.minds[cid].beliefs
                and f not in state.minds[cid].secrets)
        return {
            "tick": state.tick,
            "physical": sorted(k for k, v in state.physical.items() if v),
            "relationships": [
                {"pair": k, "type": r.type, "intensity": r.intensity,
                 "history": r.history}
                for k, r in state.relationships.items()],
            "minds": minds,
            "narrative": {
                "act": state.narrative.act, "chapter": state.narrative.chapter,
                "tension": state.narrative.tension,
                "current_scene": state.narrative.current_scene,
                "track_progress": state.narrative.track_progress,
                "causal_links": state.narrative.causal_links,
                "last_story_time": state.narrative.last_story_time,
            },
            "foreshadows": [asdict(fs) for fs in state.narrative.foreshadow_pool],
            "characters": state.characters,
        }

    def _world_state_digest(self, state: WorldState) -> str:
        parts = []
        for cid, m in state.minds.items():
            known = [f for f, v in m.beliefs.items() if v]
            parts.append(f"{cid}: knows={known}, secrets={m.secrets}")
        return "\n".join(parts)

    @staticmethod
    def _parse_events_json(text: str) -> list[dict]:
        text = text.strip()
        if "```" in text:
            import re as _re
            m = _re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
            if m:
                text = m.group(1).strip()
        start, end = text.find("["), text.rfind("]")
        if start >= 0 and end > start:
            text = text[start:end + 1]
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            import re as _re
            try:
                data = json.loads(_re.sub(r",(\s*[}\]])", r"\1", text))
            except (json.JSONDecodeError, TypeError):
                return []
        if not isinstance(data, list):
            return []
        events = [e for e in data
                  if isinstance(e, dict) and "event_type" in e and "payload" in e]
        # LLM 偶发把 effects.learn 写成平铺 list——提交前归一（防 fold 崩溃）
        for e in events:
            payload = e.get("payload")
            if isinstance(payload, dict) and "effects" in payload:
                payload["effects"] = normalize_learn(
                    payload.get("effects"), payload.get("agent") or "world")
        return events

    def _read_worldview(self) -> WorldviewProfile | None:
        """P12.3：读项目 worldview.json → WorldviewProfile；无文件/异常 → None。

        无文件时返回 None（双通道融合的「无 profile」路径：prompt 与现状逐字
        一致，world_rules 不追加）。文件存在但格式异常 → warning + None（增强
        不是门禁，世界观缺失不应阻塞生成主路径）。
        """
        path = self.project_dir / "worldview.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            warnings.warn(f"worldview.json 读取失败（{exc!r}），忽略", stacklevel=2)
            return None
        layers = data.get("layers") if isinstance(data, dict) else None
        if not isinstance(layers, dict) or not layers:
            return None
        return WorldviewProfile(layers=layers)

    def _worldview_prompt_text(self) -> str | None:
        """P12.3：WorldviewProfile.to_prompt_text()；空文本 → None（无段注入）。"""
        profile = self._read_worldview()
        if profile is None:
            return None
        text = profile.to_prompt_text()
        return text or None

    def _read_macro_plan(self) -> dict | None:
        """P17.4：读项目 macro_plan.json → dict；无文件/异常 → None。

        无文件时返回 None（宏观注入的「无计划」路径：macro_context 全程 None，
        所有 prompt 与现状逐字一致）。文件存在但格式异常 → warning + None。
        """
        path = self.project_dir / "macro_plan.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            warnings.warn(f"macro_plan.json 读取失败（{exc!r}），忽略",
                          stacklevel=2)
            return None
        return data if isinstance(data, dict) else None

    def _build_macro_context(self, chapter_no: int) -> dict | None:
        """P17.4：从 macro_plan 提取当前章节的宏观上下文 → dict（供 DecisionCard。

        macro_context 注入）；无 macro_plan 或当前集无匹配信息 → None（行为零变化）。

        提取内容（设计文档 4.3 节）：
        - act/beat/beat_description/beat_position：从 act_structure 定位当前章所在幕与 beat
        - episode_synopsis/key_events_required：从 episode_outlines 取当前集梗概
        - arc_directives：从 arc_schedule 取当前集所在里程碑的角色行为指导
        - foreshadow_directives：从 foreshadow_blueprint 取当前集应埋/收的伏笔
        - pacing_directive：从 pacing_curve 取当前集张力目标
        """
        plan = self._read_macro_plan()
        if plan is None:
            return None
        ctx: dict = {
            "act": "", "beat": "", "beat_description": "",
            "beat_position": "", "episode_synopsis": "",
            "arc_directives": [], "foreshadow_directives": [],
            "pacing_directive": {}, "key_events_required": [],
        }
        # --- 幕 + beat 定位 ---
        act_struct = plan.get("act_structure") or {}
        for act in act_struct.get("acts") or []:
            rng = act.get("episode_range") or []
            if len(rng) == 2 and rng[0] <= chapter_no <= rng[1]:
                ctx["act"] = act.get("name", "")
                ctx["beat_position"] = f"{rng[0]}-{rng[1]}"
                # 当前集最近的 beat（ep <= chapter_no 中最大者）
                best_beat = None
                for b in act.get("beats") or []:
                    try:
                        ep = int(b.get("ep", 0))
                    except (ValueError, TypeError):
                        continue
                    if ep <= chapter_no and (best_beat is None
                                             or ep > int(best_beat.get("ep", 0))):
                        best_beat = b
                if best_beat:
                    ctx["beat"] = best_beat.get("name", "")
                    ctx["beat_description"] = best_beat.get("desc", "")
                break
        # --- 分集梗概 ---
        for ep in plan.get("episode_outlines") or []:
            if ep.get("episode") == chapter_no:
                ctx["episode_synopsis"] = ep.get("synopsis", "")
                ctx["key_events_required"] = list(ep.get("key_events") or [])
                break
        # --- 角色弧光指导 ---
        for char in (plan.get("arc_schedule") or {}).get("characters") or []:
            for ms in char.get("milestones") or []:
                rng = ms.get("episode_range", "")
                if self._ep_in_range(chapter_no, rng):
                    ctx["arc_directives"].append({
                        "character": char.get("name", ""),
                        "phase": ms.get("phase", ""),
                        "behavior": ms.get("behavior", ""),
                    })
        # --- 伏笔指导 ---
        for thread in (plan.get("foreshadow_blueprint") or {}).get("threads") or []:
            plants = thread.get("plant_episodes") or []
            harvest = thread.get("harvest_episode", 0)
            if chapter_no in plants or chapter_no == harvest:
                ctx["foreshadow_directives"].append({
                    "id": thread.get("id", ""),
                    "name": thread.get("name", ""),
                    "action": "harvest" if chapter_no == harvest else "plant",
                })
        # --- 节奏张力 ---
        for tp in (plan.get("pacing_curve") or {}).get("key_tension_points") or []:
            if tp.get("episode") == chapter_no:
                ctx["pacing_directive"] = {
                    "tension": tp.get("tension", 0.0),
                    "reason": tp.get("reason", ""),
                }
                break
        return ctx

    @staticmethod
    def _ep_in_range(ep: int, rng: str) -> bool:
        """解析 '1-3' / '5' 形式的章节范围，判断 ep 是否在内。"""
        if not rng:
            return False
        parts = str(rng).split("-")
        try:
            if len(parts) == 1:
                return ep == int(parts[0])
            return int(parts[0]) <= ep <= int(parts[1])
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _card_macro_text(card) -> str | None:
        """P17.4：从 DecisionCard.macro_context 提取 prompt 文本段。

        无 macro_context / 空文本 → None（Realizer prompt 与现状逐字一致）。
        """
        ctx = getattr(card, "macro_context", None)
        if not ctx:
            return None
        text = StoryEngine._macro_context_text(ctx)
        return text or None

    @staticmethod
    def _macro_context_text(ctx: dict) -> str:
        """P17.4：macro_context dict → prompt 可用文本段（beat/arc/foreshadow/tension）。

        供 Actor brief 和 Realizer/生成 prompt 的宏观指导段使用；空 ctx → 空串。
        """
        parts = []
        if ctx.get("beat"):
            desc = ctx.get("beat_description", "")
            parts.append(f"当前 beat={ctx['beat']}" + (f"（{desc}）" if desc else ""))
        if ctx.get("episode_synopsis"):
            parts.append(f"集纲={ctx['episode_synopsis']}")
        if ctx.get("key_events_required"):
            parts.append(f"关键事件={', '.join(ctx['key_events_required'])}")
        for arc in ctx.get("arc_directives") or []:
            parts.append(f"{arc.get('character', '')}弧光-{arc.get('phase', '')}：{arc.get('behavior', '')}")
        for fs in ctx.get("foreshadow_directives") or []:
            action = "回收" if fs.get("action") == "harvest" else "埋设"
            parts.append(f"{action}伏笔-{fs.get('name', '')}")
        pace = ctx.get("pacing_directive") or {}
        if pace.get("reason"):
            parts.append(f"张力目标={pace['reason']}")
        # P19.3：key_events / foreshadow 覆盖反馈注入 prompt
        for fb in ctx.get("feedback") or []:
            parts.append(f"⚠{fb}")
        return "；".join(parts)

    def _read_chapters(self) -> list[dict]:
        return json.loads(self.chapters_path.read_text(encoding="utf-8"))

    def _write_chapters(self, chapters: list[dict]):
        self.chapters_path.write_text(
            json.dumps(chapters, ensure_ascii=False, indent=2), encoding="utf-8")


class StoryEngineMockEnded(Exception):
    """Mock 剧本演完，提示切换真实 LLM"""
