"""HITL 介入路由测试（P5.7：intent / character / evaluation 前 3 类核心用例）"""
import tempfile
import unittest

from story_engine.kernel import Kernel
from story_engine.kernel.embedding import Embedder
from story_engine.hitl import HumanInput, InterventionRouter


class TestInterventionRouter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kernel = Kernel(self.tmp, plugin_dir=None,
                             embedder=Embedder(mode="dummy"))
        self.router = InterventionRouter(self.kernel)

    def tearDown(self):
        try:
            self.kernel.close()
        except Exception:
            pass

    def _intervention_events(self) -> list[dict]:
        return [e for e in self.kernel.query_world("all_events")
                if e["event_type"] == "author_intervention"]

    def test_intent_records_replayable_event(self):
        """intent：route 后 author_intervention 事件进事件流（可查、payload 完整）"""
        r = self.router.route(HumanInput(
            type="intent", reason="改方向",
            payload={"goal_update": "主线转向复仇", "constraint": "不可写死主角"}))
        self.assertTrue(r.ok)
        self.assertFalse(r.regenerated)

        events = self._intervention_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_id"], r.event_id)
        p = events[0]["payload"]
        self.assertEqual(p["type"], "intent")
        self.assertEqual(p["goal_update"], "主线转向复仇")
        self.assertEqual(p["constraint"], "不可写死主角")
        self.assertEqual(p["reason"], "改方向")

    def test_character_belief_relation_fold(self):
        """character：belief/relation 变更走通 fold，projection 里 knows/relation 可见"""
        r = self.router.route(HumanInput(
            type="character", reason="作者设定",
            payload={"character": "包拯", "belief": "knows(包拯,凶手是管家)",
                     "relation": {"target": "展昭", "type": "信任", "intensity": 0.9}}))
        self.assertTrue(r.ok)

        state = self.kernel.query_world("current_state")
        self.assertTrue(state.minds["包拯"].beliefs["knows(包拯,凶手是管家)"])
        rel = state.relationships["包拯|展昭"]
        self.assertEqual(rel.type, "信任")
        self.assertAlmostEqual(rel.intensity, 0.9)
        # 审计事件也在事件流中（介入即事件，可回放）
        self.assertEqual(len(self._intervention_events()), 1)

    def test_evaluation_pipeline_injection(self):
        """evaluation：quality=high 进事件流 + 注入的 pipeline 收到调用（无 pipeline 不崩）"""

        class FakePipeline:
            def __init__(self):
                self.received = []

            def process_intervention(self, event):
                self.received.append(event)

        # 无 pipeline：跳过不崩
        r = self.router.route(HumanInput(
            type="evaluation", reason="这章好",
            payload={"chapter": 3, "quality": "high"}))
        self.assertTrue(r.ok)

        # 有 pipeline：事件流入 + process_intervention 被调
        fake = FakePipeline()
        router = InterventionRouter(self.kernel, pipeline=fake)
        r2 = router.route(HumanInput(
            type="evaluation", reason="更好",
            payload={"chapter": 4, "quality": "high", "note": "节奏佳"}))
        self.assertTrue(r2.ok)
        self.assertEqual(len(fake.received), 1)
        ev = fake.received[0]
        self.assertEqual(ev.event_type, "author_intervention")
        self.assertEqual(ev.payload["quality"], "high")
        self.assertEqual(ev.payload["chapter"], 4)

        events = self._intervention_events()
        self.assertEqual(len(events), 2)
        self.assertTrue(all(e["payload"]["type"] == "evaluation" for e in events))


if __name__ == "__main__":
    unittest.main()
