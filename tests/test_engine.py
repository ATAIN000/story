"""核心测试 — 复跑赌注1（Z3 硬约束）与赌注4（事件溯源）的验证标准"""
import asyncio
import shutil
import tempfile
import unittest

from story_engine.engine import StoryEngine, StoryEngineMockEnded
from story_engine.types import WorldEvent, WorldState, CharacterMind
from story_engine.validator import ConsistencyValidator


def ev(payload, tick=1):
    return WorldEvent(f"e{tick}", "character_action",
                      "2026-07-19T00:00:00", tick, "main", payload)


class TestBet1HardConstraints(unittest.TestCase):
    """赌注1：Z3 SMT 硬约束 10/10（5 类规则 × PASS/FAIL）"""

    def setUp(self):
        self.v = ConsistencyValidator()
        self.state = WorldState()
        self.state.physical["at(展昭,聚宝赌坊)"] = True
        self.state.minds["包拯"] = CharacterMind("包拯", goals=["查明玉佩案真相"])
        self.state.narrative.last_story_time = "第2日·辰时"
        self.state.narrative.causal_links = ["玉佩失窃→王员外报案"]

    def test_sanderson_fail(self):
        r = self.v.validate(ev({"has_supernatural": True, "is_resolution": True}), self.state)
        self.assertFalse(r.passed)
        self.assertIn("world_rule", r.failures)

    def test_sanderson_pass(self):
        # 鬼神只造氛围不解决剧情 → 合法
        r = self.v.validate(ev({"has_supernatural": True, "is_resolution": False}), self.state)
        self.assertTrue(r.passed)

    def test_epistemic_fail(self):
        r = self.v.validate(ev({"agent": "包拯", "requires_knowing": ["刘伯赌债"]}), self.state)
        self.assertFalse(r.passed)
        self.assertIn("epistemic", r.failures)

    def test_epistemic_pass(self):
        self.state.minds["包拯"].beliefs["刘伯赌债"] = True
        r = self.v.validate(ev({"agent": "包拯", "requires_knowing": ["刘伯赌债"]}), self.state)
        self.assertTrue(r.passed)

    def test_physical_fail(self):
        r = self.v.validate(ev({"agent": "展昭", "physical_preconditions": ["at(展昭,开封府)"]}), self.state)
        self.assertFalse(r.passed)

    def test_physical_pass(self):
        r = self.v.validate(ev({"agent": "展昭", "physical_preconditions": ["at(展昭,聚宝赌坊)"]}), self.state)
        self.assertTrue(r.passed)

    def test_temporal_fail(self):
        r = self.v.validate(ev({"story_time": "第1日·午时"}), self.state)
        self.assertFalse(r.passed)

    def test_temporal_pass(self):
        r = self.v.validate(ev({"story_time": "第2日·午时"}), self.state)
        self.assertTrue(r.passed)

    def test_causal_fail(self):
        r = self.v.validate(ev({"agent": "包拯", "motivation": "无端猜疑"}), self.state)
        self.assertFalse(r.passed)

    def test_causal_and_intention_pass(self):
        r = self.v.validate(ev({"agent": "包拯", "motivation": "玉佩失窃",
                                "serves_goal": "查明玉佩案真相"}), self.state)
        self.assertTrue(r.passed)


class TestBet4EventSourcing(unittest.TestCase):
    """赌注4：append → snapshot → append → rollback → projection 一致"""

    def test_snapshot_rollback_consistency(self):
        tmp = tempfile.mkdtemp()
        try:
            eng = StoryEngine(tmp)
            asyncio.run(eng.generate_chapter())
            snap_id = eng.store.snapshot()
            tick_at_snap = eng.store.head_tick()
            state_at_snap = eng.store.current_state().to_dict()

            asyncio.run(eng.generate_chapter())
            self.assertGreater(eng.store.head_tick(), tick_at_snap)

            eng.rollback(tick_at_snap)
            restored = eng.store.current_state().to_dict()
            self.assertEqual(state_at_snap["physical"], restored["physical"])
            self.assertEqual(state_at_snap["minds"], restored["minds"])
            self.assertEqual(state_at_snap["tick"], restored["tick"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestCoreLoop(unittest.TestCase):
    """核心循环：3 章各抓 1 处违规，修正后复验全过"""

    def test_three_chapters(self):
        tmp = tempfile.mkdtemp()
        try:
            eng = StoryEngine(tmp)
            expected = ["认知 (Epistemic EC)", "物理 (Event Calculus)", "世界规则 (Z3 SMT)"]
            for i, label in enumerate(expected, start=1):
                rec = asyncio.run(eng.generate_chapter())
                self.assertEqual(rec["draft"]["violation_count"], 1)
                self.assertEqual(rec["draft"]["violations"][0]["check"], label)
                self.assertTrue(rec["correction"]["recheck_passed"])
            snap = eng.project_snapshot()
            self.assertEqual(snap["meta"]["chapter_count"], 3)
            # 4 个伏笔，3 个已回收
            fs = snap["world_state"]["foreshadows"]
            self.assertEqual(len(fs), 4)
            self.assertEqual(sum(1 for f in fs if f["payed_off"]), 3)
            with self.assertRaises(StoryEngineMockEnded):
                asyncio.run(eng.generate_chapter())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
