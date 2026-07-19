"""StoryEngine — 核心循环编排器（蓝图 Module 0-6 的 demo 级整合）

Phase 1 重构（v0.2）：所有世界操作走 Kernel.syscall()，不再直接访问 EventStore。
Phase 2（v0.3）：非剧本路径改为 Director→Actor→Showrunner：
  决策卡 → spawn 5 角色 Actor → tick×N（各自 SOAR commit）→
  汇总渲染章节文本 → 7步验证（报告）→ 伏笔池 → snapshot
剧本路径（STORY_ENGINE_SCRIPTED_DEMO=1）完全保留，不依赖 Actor。
Phase 4（v0.4）：真实 LLM 路径接 evaluator 自评迭代（决策5/6，
  SCRIPTED_DEMO=0 且非 mock 且 STORY_ENGINE_EVAL_ENABLED!=0 时启用；
  自评是增强不是门禁，异常自动退回未迭代结果）。

关键架构约束（worldstate_paradox）：
- 生成 prompt 不含 WorldState 秘密（doesnt_know/secret 不注入）
- 检查/修正 prompt 以 WorldState 为基准
- 修正回路是唯一价值来源（"只检查不修正"零价值）
"""
from __future__ import annotations

import copy
import json
import os
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .kernel import Kernel
from .kernel.actor import CharacterConfig
from .creativity import ConceptualBlending
from .evaluator import (ChapterSpec, IterationController, LeaderArbiter,
                        PresentationScorer, ProcessGate, ReaderProxy)
from .evaluator.critic_parliament import CriticParliament  # __init__ 未导出
from .llm import LLMError  # 通过 shim 兼容旧 import 路径
from .registry import ExtensionRegistry, PluginManifest
from .showrunner import Showrunner
from .types import (WorldEvent, WorldState, CharacterMind, Relation,
                    NarrativeState, ForeshadowTriple, Check, StoryEngineError,
                    GenreBundle)
from .validator import ConsistencyValidator
from . import mock_script

PLUGIN_DIR = Path(__file__).parent / "plugins"

# P3.8：题材插件缺 prompt 段（或缺键）时的通用兜底 —— 不含任何具体作品/角色名
_GENERIC_PROMPT = {
    "role": "故事作者",
    "setting": "虚构世界，遵循本题材设定",
    "characters": "以已定稿前情中登场的角色为准",
    "style": "800-1200字，叙事连贯",
    "hard_requirements": [],
}


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
            # 旧式构造：自动建 Kernel
            self.project_dir = Path(kernel_or_dir)
            self.project_dir.mkdir(parents=True, exist_ok=True)
            self.registry = ExtensionRegistry()
            for path in PLUGIN_DIR.rglob("*.yaml"):
                self.registry.register(PluginManifest.load(path))
            from .kernel import LLMPool
            llm_pool = llm_client or LLMPool()
            self.kernel = Kernel(
                self.project_dir,
                initial_state_factory=self._genesis_state,
                llm_pool=llm_pool if hasattr(llm_pool, "call") else None,
                plugin_dir=PLUGIN_DIR,
            )
            # 插件可能被 Kernel 又加载一遍，但 register 是幂等 dict-set，覆盖即可
            self.registry = self.kernel.registry
            self.llm = self.kernel.llm
            self.store = self.kernel.store

        # 三正交轴配置（与原版一致）
        genre_name = os.environ.get("STORY_ENGINE_GENRE", "mystery")
        culture_name = os.environ.get("STORY_ENGINE_CULTURE", "confucian_officialdom")
        self.registry.validate_combo(genre_name, culture_name)
        self.genre = self.registry.get("story.genre", genre_name)
        self.culture = self.registry.get("story.culture", culture_name)
        # 权威 GenreBundle 构建一次：Showrunner 决策卡与 spawn_director 共用
        self.bundle = GenreBundle(
            genre=genre_name, culture=culture_name,
            genre_params=self.genre.params, culture_params=self.culture.params)

        # 子系统（与原版一致）
        self.validator = ConsistencyValidator(
            world_rules=self.genre.get("world_rules"))
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
    async def generate_chapter(self) -> dict:
        t0 = time.perf_counter()
        state = self.kernel.query_world("current_state")
        chapter_no = state.narrative.chapter + 1
        scripted = self._scripted(chapter_no)

        # 剧本路径：完全保留 Phase 1 行为
        if scripted:
            return await self._generate_chapter_llm_path(
                chapter_no, state, t0, scripted=True)

        # SCRIPTED_DEMO=1 且 Mock 剧本已完：保持旧行为提示切换 LLM
        demo_on = os.environ.get("STORY_ENGINE_SCRIPTED_DEMO", "1") == "1"
        if demo_on and self.llm.is_mock:
            raise StoryEngineMockEnded(
                f"Mock 剧本已完结（共{max(mock_script.DRAFTS)}章）。"
                "配置 STORY_ENGINE_LLM_API_KEY 后切换真实 LLM 继续生成，"
                "或设 STORY_ENGINE_SCRIPTED_DEMO=0 走 Actor 模式，"
                "或在时间线面板回滚到任意快照重新生成。")

        # Actor 路径（STORY_ENGINE_SCRIPTED_DEMO=0）
        return await self._generate_chapter_actor_path(chapter_no, state, t0)

    async def _generate_chapter_llm_path(
        self, chapter_no: int, state: WorldState, t0: float, *, scripted: bool
    ) -> dict:
        if self.llm.is_mock and not scripted:
            raise StoryEngineMockEnded(
                f"Mock 剧本已完结（共{max(mock_script.DRAFTS)}章）。"
                "配置 STORY_ENGINE_LLM_API_KEY 后切换真实 LLM 继续生成，"
                "或在时间线面板回滚到任意快照重新生成。")

        # Step 0: Showrunner 决策卡
        card = self.showrunner.generate_decision_card(chapter_no, state)
        # P3.7：env 门控默认关；剧本路径（mock_script）不挂 seed，保持原行为
        if not scripted:
            card = await self.showrunner.attach_creative_seed(card, chapter_no)

        # Step 1-4: 初稿 → 事件抽取 → 7步验证 → 修正回路
        # P4.5（决策5）：真实 LLM 且自评门控通过 → 包 IterationController（best-of-K）；
        # 自评链路任何异常 → 退回未迭代结果（自评是增强不是门禁）
        evaluation = None
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
        draft_text = await self._llm_generate_draft(chapter_no, card, state)

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

    # ============ Phase 4：自评迭代（决策5/6，env 门控） ============
    def _eval_enabled(self) -> bool:
        """自评门控：SCRIPTED_DEMO=0 且 llm 非 mock 且 EVAL_ENABLED!=0。
        三条件任一不满足 → 走现有路径原样（mock/剧本路径零变化）。"""
        return (os.environ.get("STORY_ENGINE_SCRIPTED_DEMO", "1") == "0"
                and not self.llm.is_mock
                and os.environ.get("STORY_ENGINE_EVAL_ENABLED", "1") != "0")

    @staticmethod
    def _eval_max_rounds() -> int:
        """EVAL_MAX_ROUNDS 默认 3，钳 [1, 5] 防失控（决策5）"""
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
        controller = IterationController(
            parliament, LeaderArbiter(), gates, reader,
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

        reader 取与 best 版本对齐的反应（controller._reactions 与 versions
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
        reaction = (controller._reactions[idx]
                    if idx < len(controller._reactions) else None)
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
        self, chapter_no: int, state: WorldState, t0: float
    ) -> dict:
        """Phase 2：Director spawn → tick×N → Showrunner 汇总 → 验证报告 → snapshot

        Actor 在 SOAR apply 步已 commit_event；本路径不再二次 commit 那些事件。
        """
        card = self.showrunner.generate_decision_card(chapter_no, state)
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
            f"=== 本章调度 ===\n推进轨道：{advance_txt}\n"
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
        }

    def rollback(self, to_tick: int) -> dict:
        self.kernel.rollback(to_tick)
        chapters = self._read_chapters()
        changed = False
        for ch in chapters:
            if ch["tick_range"][1] > to_tick and not ch.get("superseded"):
                ch["superseded"] = True
                changed = True
        if changed:
            self._write_chapters(chapters)
        return self.project_snapshot()

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
        return [e for e in data
                if isinstance(e, dict) and "event_type" in e and "payload" in e]

    def _read_chapters(self) -> list[dict]:
        return json.loads(self.chapters_path.read_text(encoding="utf-8"))

    def _write_chapters(self, chapters: list[dict]):
        self.chapters_path.write_text(
            json.dumps(chapters, ensure_ascii=False, indent=2), encoding="utf-8")


class StoryEngineMockEnded(Exception):
    """Mock 剧本演完，提示切换真实 LLM"""
