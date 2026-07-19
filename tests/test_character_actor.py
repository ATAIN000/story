"""Phase 2 CharacterActor 测试 — SOAR + 并行 tick + recall 隔离"""
from __future__ import annotations

import asyncio
import tempfile
import unittest

from story_engine.character.actor import CharacterActor, ActorMessage
from story_engine.character.memory_banks import SemanticMemoryBanks
from story_engine.character.voice import VoiceProfile, ReflectionTrigger
from story_engine.kernel import Kernel, CharacterConfig
from story_engine.kernel.embedding import Embedder
from story_engine.types import WorldState, NarrativeState


def _run(coro):
    return asyncio.run(coro)


def _kernel(tmp: str) -> Kernel:
    return Kernel(
        tmp,
        plugin_dir=None,
        embedder=Embedder(mode="dummy", dimensions=512, lazy_load=True),
        initial_state_factory=lambda: WorldState(
            tick=0,
            narrative=NarrativeState(act=1, chapter=0, current_scene="开封府"),
        ),
    )


class TestVoiceAndReflection(unittest.TestCase):
    def test_voice_from_seed(self):
        v = VoiceProfile.from_seed("包拯", {"voice": "沉毅克制", "archetype": "判官"})
        self.assertIn("沉毅", v.prompt_snippet())

    def test_reflection_trigger(self):
        t = ReflectionTrigger()
        triggered = False
        for _ in range(8):
            if t.observe(20):
                triggered = True
                break
        self.assertTrue(triggered)


class TestCharacterActor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kernel = _kernel(self.tmp)

    def tearDown(self):
        try:
            _run(self.kernel.scheduler.stop_all())
        except Exception:
            pass
        self.kernel.close()

    def test_actor_spawn_and_send(self):
        cfg = CharacterConfig(
            character_id="包拯", archetype="判官",
            initial_goals=["查明玉佩案真相"])

        async def _tick():
            ref = self.kernel.spawn_character_actor(cfg, persona={"voice": "沉毅"})
            self.assertEqual(ref.actor_id, "包拯")
            actor = self.kernel.scheduler.get_character_actor("包拯")
            self.assertIsInstance(actor, CharacterActor)
            await actor.ensure_started()
            state = self.kernel.query_world("current_state")
            await actor.send(ActorMessage(
                type="world_tick",
                payload={"world_state": state, "chapter": 1},
            ))
            await actor.wait_idle(timeout=30)
            return list(actor.last_actions)

        actions = _run(_tick())
        self.assertGreaterEqual(len(actions), 1)
        events = self.kernel.query_world("all_events")
        self.assertTrue(any(e["event_type"] == "character_action" for e in events))

    def test_soar_propose_evaluate_decide(self):
        """单 actor 单 tick：规则兜底也能走完 SOAR"""
        async def _go():
            cfg = CharacterConfig(
                character_id="展昭", initial_goals=["护卫包拯", "查访线索"])
            self.kernel.spawn_character_actor(cfg)
            return await self.kernel.scheduler.tick_all(
                self.kernel.query_world("current_state"), chapter=1)

        actions = _run(_go())
        self.assertEqual(len(actions), 1)
        self.assertIn("展昭", actions[0]["actor_id"])

    def test_two_actors_parallel_5_ticks(self):
        """蓝图 Phase 2 验收：2+ actor × 5 tick 各自 commit"""
        async def _go():
            for cid, goals in [("包拯", ["查明玉佩案真相"]), ("展昭", ["护卫包拯"])]:
                self.kernel.spawn_character_actor(
                    CharacterConfig(character_id=cid, initial_goals=goals))

            total = []
            for i in range(5):
                batch = await self.kernel.scheduler.tick_all(
                    self.kernel.query_world("current_state"), chapter=1)
                total.extend(batch)

            banks = self.kernel._ensure_memory_banks()
            await banks.add(
                "包拯正在审理玉佩失窃案",
                bank="continuity_facts", agent_id="包拯", importance=8)
            recalled = await self.kernel.recall("包拯", "玉佩案", budget=2048)
            return total, recalled

        total, recalled = _run(_go())
        self.assertGreaterEqual(len(total), 10)  # 2 actors × 5 ticks
        events = [
            e for e in self.kernel.query_world("all_events")
            if e["event_type"] == "character_action"
        ]
        self.assertGreaterEqual(len(events), 10)
        self.assertGreaterEqual(len(recalled), 1)

    def test_actor_failure_isolation(self):
        """一个 actor 抛异常，其他仍可 tick"""
        async def _go():
            self.kernel.spawn_character_actor(
                CharacterConfig(character_id="包拯", initial_goals=["断案"]))
            self.kernel.spawn_character_actor(
                CharacterConfig(character_id="展昭", initial_goals=["护卫"]))

            bad = self.kernel.scheduler.get_character_actor("包拯")

            async def _boom(_payload):
                raise RuntimeError("simulated crash")

            bad._on_tick = _boom  # type: ignore
            actions = await self.kernel.scheduler.tick_all(
                self.kernel.query_world("current_state"), chapter=1)
            return actions, bad.error_count

        actions, err = _run(_go())
        self.assertTrue(any(a["actor_id"] == "展昭" for a in actions))
        self.assertGreaterEqual(err, 1)

    def test_recall_per_agent_isolation(self):
        async def _iso():
            banks = self.kernel._ensure_memory_banks()
            await banks.add(
                "包拯独有：掌握密折", bank="working_set",
                agent_id="包拯", importance=8)
            await banks.add(
                "展昭独有：暗访结果", bank="working_set",
                agent_id="展昭", importance=8)
            bao = await self.kernel.recall("包拯", "密折", budget=2048)
            zhan = await self.kernel.recall("展昭", "暗访", budget=2048)
            return bao, zhan

        bao, zhan = _run(_iso())
        bao_txt = " ".join(getattr(x, "content", str(x)) for x in bao)
        zhan_txt = " ".join(getattr(x, "content", str(x)) for x in zhan)
        self.assertIn("密折", bao_txt)
        self.assertNotIn("暗访结果", bao_txt)
        self.assertIn("暗访", zhan_txt)
        self.assertNotIn("密折", zhan_txt)


if __name__ == "__main__":
    unittest.main()
