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

from .kernel import Kernel
from .kernel.actor import CharacterConfig
from .creativity import ConceptualBlending
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


class StoryEngine:
    def __init__(self, kernel_or_dir, llm_client=None):
        """两种构造方式（向后兼容）：
        - StoryEngine(kernel: Kernel)              # 推荐：注入外部 kernel
        - StoryEngine(project_dir: str|Path, llm_client=LLMClient())  # 旧式：自建
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
                initial_state_factory=self._genesis_state,
                llm_pool=llm_pool if hasattr(llm_pool, "call") else None,
                plugin_dir=PLUGIN_DIR,
            )
            self.registry = self.kernel.registry
            self.llm = self.kernel.llm
            self.store = self.kernel.store

        # 三正交轴配置（与原版一致）
        genre_name = os.environ.get("STORY_ENGINE_GENRE", "mystery")
        culture_name = os.environ.get("STORY_ENGINE_CULTURE", "confucian_officialdom")
        self.registry.validate_combo(genre_name, culture_name)
        self.genre = self.registry.get("story.genre", genre_name)
        self.culture = self.registry.get("story.culture", culture_name)
        # P7.4 L5：rule_packs 显式引用的 world.rule 包合并进 world_rules
        #（genre params 未配置 rule_packs 时返回 params 本体，行为与现状逐字一致）
        genre_params = self._merge_world_rule_packs(self.genre.params)
        # 权威 GenreBundle 构建一次：Showrunner 决策卡与 spawn_director 共用
        self.bundle = GenreBundle(
            genre=genre_name, culture=culture_name,
            genre_params=genre_params, culture_params=self.culture.params)

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

    # ============ P7.4 L5：world.rule 素材包引用合并 ============
    def _merge_world_rule_packs(self, genre_params: dict) -> dict:
        """genre params 声明 rule_packs: [pack名] 时，把 world.rule 素材包规则
        合并进 world_rules，返回含合并结果的 params 副本；未配置 rule_packs
        时返回 params 本体（genre yaml 不加该键则行为与现状逐字一致）。

        合并语义（与 story.evaluator critic pack 同款 pack-wins）：
        - 同 id → pack 规则覆盖内嵌规则（保持内嵌原位）；内嵌没有的规则追加
        - pack 未注册 / params.rules 非列表 → warning + 跳过该包
        - 规则非映射 / 缺 id / 缺 expr → warning + 跳过该条
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
                if not isinstance(rule, dict) \
                        or not rule.get("id") or not rule.get("expr"):
                    logger.warning(
                        "world.rule 包「%s」含缺 id/expr 的规则（%r），跳过该条",
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
        return params

    # ============ 创世（seed 世界） ============
    @staticmethod
    def _genesis_state() -> WorldState:
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
        return await self._generate_chapter_actor_path(
            chapter_no, state, t0, mode=mode)

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
        self._pending_plan = card
        return card.to_dict()

    def discard_plan(self) -> None:
        """P6.2：作废缓存的待批准决策卡（DELETE /api/project/plan）"""
        self._pending_plan = None

    def _resolve_decision_card(self, chapter_no: int, state: WorldState,
                               mode: str):
        """P6.2：confirm 模式优先消费 plan 缓存的决策卡（消费即清除）；
        auto / 无缓存 / 缓存章号不匹配 → 现场产卡（现状逐字不变）。
        章号匹配的缓存在任何模式下都清除：本章一生成，旧方案即失效。"""
        pending = self._pending_plan
        if pending is not None and pending.episode == chapter_no:
            self._pending_plan = None
            if mode == "confirm":
                return pending
        return self.showrunner.generate_decision_card(chapter_no, state)

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
        # P3.7：env 门控默认关；剧本路径（mock_script）不挂 seed，保持原行为
        if not scripted:
            card = await self.showrunner.attach_creative_seed(card, chapter_no)

        # Step 1-4: 初稿 → 事件抽取 → 7步验证 → 修正回路
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

        # 标题解析（剧本章用剧本标题；真实模式从正文首行「标题：XXX」解析）
        title = mock_script.CHAPTER_TITLES.get(chapter_no)
        if not scripted:
            import re as _re
            m = _re.match(r"\s*标题[:：]\s*(.+)", final_text)
            if m:
                title = m.group(1).strip()[:12]
                final_text = final_text[m.end():].lstrip("\n")
                draft_m = _re.match(r"\s*标题[:：]\s*(.+)", draft_text)
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

    def _ir_recap(self) -> str | None:
        """P5.12 ②：IR-first Realizer prompt 的前情 recap（章节连续性上下文）。

        数据源复用 _real_generate_prompt 的既有口径：chapters.json 未
        superseded 章（最近 1-3 章，各取结尾 ~200 字）+ WorldState 伏笔池
        未回收列表。首章（无已定稿前情）→ None（narrate 收到 None 时 prompt
        与现状逐字一致）。
        """
        chapters = [c for c in self._read_chapters() if not c.get("superseded")]
        if not chapters:
            return None
        parts = [
            f"第{c['chapter']}章《{c['title']}》结尾：{c['final']['text'][-200:]}"
            for c in chapters[-3:]
        ]
        state = self.kernel.query_world("current_state")
        pending = [f for f in state.narrative.foreshadow_pool if not f.payed_off]
        if pending:
            parts.append("未回收伏笔：" + "；".join(
                f"{f.foreshadow_id}：{f.content}（触发：{f.trigger_condition}）"
                for f in pending))
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
                ir, sjuzhet, recap=self._ir_recap())
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
        # P5.11 评审传导1：Realizer 只输出正文（不产标题行），而 L5 gate 与引擎
        # 标题解析（本文件 import re as _re 两处）均约定首行「标题：XXX」——
        # 此处补上（LLM 首行已带标题则保留），否则真实 IR-first 路径 L5
        # title_format 恒 FAIL、每章保底多烧一轮修正
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
        return {
            "rounds": max(v.round for v in versions) + 1,
            "best_round": best.round,
            "gates": [asdict(g) for g in best.gates],
            "critiques": [asdict(c) for c in best.critiques],
            "revision": asdict(best.revision) if best.revision else None,
            "reader": asdict(reaction) if reaction else None,
            "score": asdict(scorer.score(best.critiques, curves)),
            "reader_predictions": predictions,
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
        # P3.7：env 门控默认关；开启时每 N 章附 1 个 CreativeSeed（失败不阻塞）
        card = await self.showrunner.attach_creative_seed(card, chapter_no)
        await self._ensure_character_actors()

        # 写入本章 brief，供角色 recall
        await self._seed_chapter_memory(chapter_no, card, state)

        pre_state = copy.deepcopy(state)
        tick_start = self.kernel.query_world("next_tick")
        max_ticks = int(os.environ.get("STORY_ENGINE_ACTOR_MAX_TICKS", "5"))
        all_actions: list[dict] = []
        for _ in range(max(1, max_ticks)):
            cur = self.kernel.query_world("current_state")
            batch = await self.kernel.scheduler.tick_all(
                cur, chapter=chapter_no, timeout=120.0)
            all_actions.extend(batch)

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
            draft_text, narrative_ir = await self._ir_first_narrate(
                chapter_no, card, close_chapter=True)
        if draft_text is None:
            draft_text = self._render_actor_chapter(chapter_no, card, all_actions)

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

        title = f"第{chapter_no}章·群像"
        import re as _re
        m = _re.match(r"\s*标题[:：]\s*(.+)", final_text)
        if m:
            title = m.group(1).strip()[:12]
            final_text = final_text[m.end():].lstrip("\n")

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
        return record

    async def _ensure_character_actors(self) -> None:
        """Director spawn：5 个种子角色（幂等）"""
        if self._actors_ready and self.kernel.scheduler._character_actors:
            return
        if self._director_ref is None:
            self._director_ref = self.kernel.spawn_director(self.bundle)
        for cid, meta in mock_script.SEED_CHARACTERS.items():
            mind = mock_script.SEED_MINDS.get(cid, {})
            if cid in self.kernel.scheduler._character_actors:
                continue
            cfg = CharacterConfig(
                character_id=cid,
                archetype=meta.get("archetype", ""),
                voice_profile={"voice": meta.get("voice", "")},
                initial_goals=list(mind.get("goals", [])),
                context_budget=8192,
            )
            persona = {**meta, "goals": mind.get("goals", [])}
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
        lines = [f"标题：第{chapter_no}章·群像", ""]
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
        return (
            f"【CHAPTER={chapter_no}】\n"
            f"你是{pcfg['role']}。背景：{pcfg['setting']}。\n"
            f"人物：{pcfg['characters']}。\n\n"
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
        prompt = (
            f"【CHAPTER={chapter_no}】\n"
            f"以下是世界状态（检查基准）：\n{self._world_state_digest(state)}\n\n"
            f"以下是生成的文本（含违规）：\n{draft_text[:2500]}\n\n"
            f"检查发现的违规：{v_text}\n\n"
            f"{fb_txt}"
            f"{task_line}"
            "- 认知违规：改为合法获知渠道（调查/证词/物证），或删去该信息\n"
            "- 物理违规：补上必要的位置转移过程\n"
            "- 世界规则违规：超自然只作氛围，破案改走证据链\n"
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
            "base_url_masked": _mask_url(self.llm.base_url),
        }

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
        """角色卡纯组装（静态，便于空态单测）；voice_hints 见 characters_view"""
        voice_hints = voice_hints or {}
        cards = []
        for cid in sorted(state.minds):
            m = state.minds[cid]
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

        self.kernel.close()
        for f in ("story.db", "story.db-wal", "story.db-shm"):
            p = self.project_dir / f
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass
        from .world.event_store import EventStore
        from .kernel.embedding import Embedder
        # 重建 store；保留 llm_pool / embedder mode
        embedder = getattr(self.kernel, "embedder", None) or Embedder(mode="dummy")
        # 若原 embedder 已 close，重新建同 mode
        mode = getattr(embedder, "mode", "dummy")
        fresh_embedder = Embedder(mode=mode, lazy_load=True)
        self.kernel.store = EventStore(
            str(self.project_dir / "story.db"),
            initial_state_factory=self._genesis_state)
        self.kernel.memory_banks = None
        self.kernel._retrieval_by_agent = {}
        self.kernel.embedder = fresh_embedder
        self.store = self.kernel.store
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

    def _read_chapters(self) -> list[dict]:
        return json.loads(self.chapters_path.read_text(encoding="utf-8"))

    def _write_chapters(self, chapters: list[dict]):
        self.chapters_path.write_text(
            json.dumps(chapters, ensure_ascii=False, indent=2), encoding="utf-8")


class StoryEngineMockEnded(Exception):
    """Mock 剧本演完，提示切换真实 LLM"""
