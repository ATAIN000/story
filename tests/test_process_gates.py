"""P4.1 过程 Gate 核心用例（L1 复用验证 / L5 三规则 / L2 规则真实生效）"""
from __future__ import annotations

import asyncio
import unittest

from story_engine.character import CharacterActor
from story_engine.evaluator import ProcessGate
from story_engine.kernel.actor import CharacterConfig
from story_engine.types import WorldEvent, WorldState, CharacterMind


def ev(payload, tick=1):
    return WorldEvent(f"e{tick}", "character_action",
                      "2026-07-19T00:00:00", tick, "main", payload)


def chapter(body: str, title: str = "标题：夜审赌坊") -> str:
    return f"{title}\n\n{body}"


class TestProcessGates(unittest.TestCase):
    """只保留核心用例（用户指令）：不穷举边界"""

    def test_l1_reuses_validator(self):
        """L1 复用 ConsistencyValidator 真验：合法 PASS / 认知违规 FAIL 带原因"""
        gate = ProcessGate()
        state = WorldState()
        state.minds["包拯"] = CharacterMind("包拯", goals=["查明玉佩案真相"])
        state.narrative.causal_links = ["玉佩失窃→王员外报案"]

        ok = asyncio.run(gate.check_l1(ev({
            "agent": "包拯", "motivation": "玉佩失窃",
            "serves_goal": "查明玉佩案真相"}), state))
        self.assertEqual(ok.layer, "L1")
        self.assertTrue(ok.passed, ok.failures)

        bad = asyncio.run(gate.check_l1(ev({
            "agent": "包拯", "requires_knowing": ["刘伯赌债"]}), state))
        self.assertFalse(bad.passed)
        self.assertIn("epistemic", bad.failures)
        self.assertIn("刘伯赌债", bad.failures["epistemic"])

    def test_l5_three_rules(self):
        """L5 三规则各一断言：首行标题 / genre style 字数区间 / 无半截句"""
        gate = ProcessGate(style="800-1200字，文白相间，叙事节奏如评书")
        body = "包拯端坐开封府，展昭侍立一旁。" * 60   # ~900 字，落在区间内
        ok = asyncio.run(gate.check_l5(chapter(body)))
        self.assertTrue(ok.passed, ok.failures)

        no_title = asyncio.run(gate.check_l5(chapter(body, title="夜审赌坊")))
        self.assertIn("title_format", no_title.failures)

        short = asyncio.run(gate.check_l5(chapter("包拯端坐。")))
        self.assertIn("word_count", short.failures)
        self.assertNotIn("title_format", short.failures)   # 规则相互独立

        truncated_body = "包拯端坐开封府，展昭侍立一旁" * 65  # 字数达标但无句末标点
        cut = asyncio.run(gate.check_l5(chapter(truncated_body)))
        self.assertIn("truncated", cut.failures)
        self.assertNotIn("word_count", cut.failures)

    def test_l2_goal_mismatch_fails(self):
        """L2 规则真实生效：声明目标不在角色卡活跃目标中 → FAIL"""
        character = CharacterActor(
            CharacterConfig(character_id="包拯", initial_goals=["查明玉佩案真相"]),
            None, persona={"role": "开封府尹", "archetype": "判官",
                           "voice": "沉毅克制，少言而中"})
        gate = ProcessGate()

        bad = asyncio.run(gate.check_l2(
            {"action": "包拯连夜查封赌坊", "summary": "为私情查封赌坊",
             "serves_goal": "报复赌场旧怨"}, character))
        self.assertFalse(bad.passed)
        self.assertIn("goal_aligned", bad.failures)
        self.assertIn("报复赌场旧怨", bad.failures["goal_aligned"])

        ok = asyncio.run(gate.check_l2(
            {"action": "包拯提审刘伯", "summary": "循证问话",
             "serves_goal": "查明玉佩案真相"}, character))
        self.assertTrue(ok.passed, ok.failures)


if __name__ == "__main__":
    unittest.main()
