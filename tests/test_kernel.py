"""Kernel 测试 — 蓝图 Module 0.1 Syscall API + 蓝图 Phase 1 验收"""
import asyncio
import tempfile
import unittest
from pathlib import Path

from story_engine.kernel import (
    Kernel, SYSCALL_NAMES, ActorRef, CharacterConfig, GenreBundle, CriticConfig,
)
from story_engine.types import WorldEvent, StoryEngineError


def _ev(tick: int, payload: dict | None = None) -> WorldEvent:
    return WorldEvent(
        event_id=f"e{tick}", event_type="world_change",
        timestamp="2026-07-19T00:00:00", world_tick=tick, branch_id="main",
        payload=payload or {"field": "demo", "new_value": "v"},
    )


class TestSyscallSignatures(unittest.TestCase):
    """蓝图 Module 0.1：14 个 syscall 全部存在且可调用"""

    def test_all_syscalls_present(self):
        for name in SYSCALL_NAMES:
            self.assertTrue(hasattr(Kernel, name), f"Kernel 缺少 syscall: {name}")

    def test_syscall_count_at_least_14(self):
        # 蓝图原文列 14 个，加 llm_call 共 15
        self.assertGreaterEqual(len(SYSCALL_NAMES), 14)

    def test_phase2_syscalls_raise_not_implemented(self):
        """branch_timeline / merge_branch 仍未实现；recall Phase 2、HITL P5.9 已实现"""
        tmp = tempfile.mkdtemp()
        from story_engine.kernel.embedding import Embedder
        k = Kernel(tmp, plugin_dir=None, embedder=Embedder(mode="dummy"))
        with self.assertRaises(NotImplementedError):
            k.branch_timeline("xxx", "test")
        with self.assertRaises(NotImplementedError):
            k.merge_branch("xxx")
        # HITL（P5.9 真实现）见 tests/test_hitl_pipeline.py
        # recall 已实现：空库返回 list
        recalled = asyncio.run(k.recall("包拯", "啥"))
        self.assertIsInstance(recalled, list)
        k.close()


class TestKernelEventFlow(unittest.TestCase):
    """蓝图 Phase 1 验收：append→snapshot→rollback→projection 一致"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kernel = Kernel(self.tmp, plugin_dir=None)

    def tearDown(self):
        try:
            self.kernel.close()
        except Exception:
            pass

    def test_commit_snapshot_rollback_query(self):
        # commit 5 个事件
        for i in range(1, 6):
            self.kernel.commit_event(_ev(i))
        self.assertEqual(self.kernel.query_world("head_tick"), 5)

        # snapshot
        snap_id = self.kernel.snapshot()
        self.assertTrue(snap_id)
        state_at_snap = self.kernel.query_world("current_state")
        snap_physical = dict(state_at_snap.physical)

        # 再 commit 3 个
        for i in range(6, 9):
            self.kernel.commit_event(_ev(i))
        self.assertEqual(self.kernel.query_world("head_tick"), 8)

        # rollback 到 5
        self.kernel.rollback(5)
        self.assertEqual(self.kernel.query_world("head_tick"), 5)

        # projection 一致
        restored = self.kernel.query_world("current_state")
        self.assertEqual(restored.physical, snap_physical)

    def test_query_world_predicates(self):
        self.kernel.commit_event(_ev(1, {"field": "x", "new_value": "1"}))
        self.assertEqual(self.kernel.query_world("head_tick"), 1)
        self.assertEqual(self.kernel.query_world("next_tick"), 2)
        snaps = self.kernel.query_world("snapshots")
        self.assertEqual(snaps, [])
        events = self.kernel.query_world("all_events")
        self.assertEqual(len(events), 1)

    def test_unknown_predicate_raises(self):
        with self.assertRaises(StoryEngineError):
            self.kernel.query_world("nonexistent_predicate")


class TestKernelPluginRegistry(unittest.TestCase):
    """蓝图 Module 0.2：register_plugin + get_plugin + validate_combo"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        plugin_dir = Path(__file__).resolve().parent.parent / "story_engine" / "plugins"
        self.kernel = Kernel(self.tmp, plugin_dir=plugin_dir)

    def tearDown(self):
        try:
            self.kernel.close()
        except Exception:
            pass

    def test_mystery_and_wuxia_loaded(self):
        genres = self.kernel.registry.list_plugins("story.genre")
        self.assertIn("mystery", genres["story.genre"])
        self.assertIn("wuxia", genres["story.genre"])

    def test_get_plugin_lazy_instantiate(self):
        m = self.kernel.get_plugin("story.genre", "mystery")
        self.assertEqual(m.name, "mystery")
        self.assertEqual(m.extension_point, "story.genre")

    def test_validate_combo_passes_for_mystery(self):
        # mystery 是 culture_bound=false，允许任意组合
        self.kernel.registry.validate_combo("mystery", "confucian_officialdom")

    def test_validate_combo_rejects_wuxia_foreign(self):
        # wuxia 是 culture_bound=true，仅允许 confucian_officialdom
        with self.assertRaises(StoryEngineError):
            self.kernel.registry.validate_combo("wuxia", "scandinavian_protestant")


class TestKernelActorScheduler(unittest.TestCase):
    """蓝图 Module 0.1 进程管理：spawn → ActorRef（Phase 2 接真实 Actor）"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kernel = Kernel(self.tmp, plugin_dir=None)

    def tearDown(self):
        try:
            self.kernel.close()
        except Exception:
            pass

    def test_spawn_character_returns_actorref(self):
        cfg = CharacterConfig(character_id="bao_zheng", archetype="judge_official")
        ref = self.kernel.spawn_character(cfg)
        self.assertIsInstance(ref, ActorRef)
        self.assertEqual(ref.actor_type, "character")
        self.assertIn("bao_zheng", ref.actor_id)

    def test_spawn_director_and_evaluator(self):
        d_ref = self.kernel.spawn_director(GenreBundle(genre="mystery", culture="confucian_officialdom"))
        e_ref = self.kernel.spawn_evaluator(CriticConfig(active_critics=["plot_coherence"]))
        self.assertEqual(d_ref.actor_type, "director")
        self.assertEqual(e_ref.actor_type, "evaluator")

    def test_send_to_mailbox(self):
        ref = self.kernel.spawn_character(CharacterConfig(character_id="test"))
        self.kernel.scheduler.send(ref, {"type": "act", "content": "hi"})
        msgs = self.kernel.scheduler.drain(ref)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["content"], "hi")

    def test_set_context_budget(self):
        ref = self.kernel.spawn_character(CharacterConfig(character_id="b", context_budget=4096))
        self.assertEqual(self.kernel.scheduler.get_context_budget(ref.actor_id), 4096)
        self.kernel.set_context_budget(ref.actor_id, 16384)
        self.assertEqual(self.kernel.scheduler.get_context_budget(ref.actor_id), 16384)


class TestLLMThinkingSwitch(unittest.TestCase):
    """STORY_ENGINE_LLM_THINKING：GLM 等渠道的思考开关（P24.8）。"""

    def _pool(self):
        from story_engine.kernel.llm_pool import LLMPool
        pool = LLMPool(mode="mock")
        pool.base_url = "https://open.bigmodel.cn/api/paas/v4"  # 非 kimi 渠道
        return pool

    def test_default_on_never_disables(self):
        import os
        os.environ.pop("STORY_ENGINE_LLM_THINKING", None)
        pool = self._pool()
        for purpose in ("propose:楚擎", "critic_judge", "realize_chapter"):
            self.assertFalse(pool._thinking_disabled(purpose))

    def test_off_disables_everything(self):
        import os
        os.environ["STORY_ENGINE_LLM_THINKING"] = "off"
        try:
            pool = self._pool()
            for purpose in ("propose:楚擎", "realize_chapter", "macro_plan"):
                self.assertTrue(pool._thinking_disabled(purpose))
        finally:
            os.environ.pop("STORY_ENGINE_LLM_THINKING", None)

    def test_creative_keeps_only_creative(self):
        import os
        os.environ["STORY_ENGINE_LLM_THINKING"] = "creative"
        try:
            pool = self._pool()
            # 创作型保留思考
            for purpose in ("realize_chapter", "correct_chapter",
                            "macro_plan", "rewrite_paragraph"):
                self.assertFalse(pool._thinking_disabled(purpose), purpose)
            # 机械性关闭
            for purpose in ("propose:楚擎", "critic_judge", "reflect:裴无咎",
                            "reader_profile"):
                self.assertTrue(pool._thinking_disabled(purpose), purpose)
        finally:
            os.environ.pop("STORY_ENGINE_LLM_THINKING", None)


if __name__ == "__main__":
    unittest.main()
