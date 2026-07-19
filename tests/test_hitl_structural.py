"""HITL structural/textual 介入测试（P5.8，Module 7 验证核心：作者改 Fabula → 系统重生成 Sjuzhet）

核心用例（用户指令：只保留核心，不穷举边界）：
1. Module 7 验证链：remove_event → 目标 rolled_back + fake regenerate_fn 调一次 + regenerated=True
2. edit 语义：旧事件 rolled_back + 新内容事件进流（顺序/内容正确）
3. textual 只记录不重生成 + 无 regenerate_fn 时 structural 不崩（待重生成）
"""
import tempfile
import unittest
from datetime import datetime
from uuid import uuid4

from story_engine.kernel import Kernel
from story_engine.kernel.embedding import Embedder
from story_engine.hitl import HumanInput, InterventionRouter
from story_engine.types import WorldEvent


class TestStructuralTextual(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kernel = Kernel(self.tmp, plugin_dir=None,
                             embedder=Embedder(mode="dummy"))
        self.regen_calls = []
        self.router = InterventionRouter(
            self.kernel, regenerate_fn=lambda: self.regen_calls.append(1))

    def tearDown(self):
        try:
            self.kernel.close()
        except Exception:
            pass

    def _commit(self, event_type="world_change", payload=None) -> WorldEvent:
        ev = WorldEvent(
            event_id=str(uuid4())[:8], event_type=event_type,
            timestamp=datetime.now().isoformat(timespec="seconds"),
            world_tick=self.kernel.query_world("next_tick"),
            branch_id="main",
            payload=payload or {"field": "f", "new_value": "v"})
        self.kernel.commit_event(ev)
        return ev

    def _active_events(self) -> list[dict]:
        return [e for e in self.kernel.query_world("all_events") if e["active"]]

    def test_module7_remove_event_rolls_back_and_regenerates(self):
        """Module 7 验证：作者改 Fabula（remove_event）→ 目标事件 rolled_back
        （projection 不再可见）→ 系统自动重生成 Sjuzhet（regenerate_fn 被调一次）"""
        e1 = self._commit(payload={"field": "f1", "new_value": "v1"})
        e2 = self._commit(payload={"field": "f2", "new_value": "v2"})
        e3 = self._commit(payload={"field": "f3", "new_value": "v3"})

        r = self.router.route(HumanInput(
            type="structural", reason="删掉多余情节",
            payload={"action": "remove_event", "event_id": e2.event_id}))

        self.assertTrue(r.ok)
        self.assertTrue(r.regenerated)
        self.assertEqual(len(self.regen_calls), 1)  # 重生成恰好一次

        # 目标事件及其下游 rolled_back：active=False，且不进 projection
        by_id = {e["event_id"]: e for e in self.kernel.query_world("all_events")}
        self.assertFalse(by_id[e2.event_id]["active"])
        self.assertFalse(by_id[e3.event_id]["active"])
        self.assertTrue(by_id[e1.event_id]["active"])
        state = self.kernel.query_world("current_state")
        self.assertIn("f1=v1", state.physical)
        self.assertNotIn("f2=v2", state.physical)
        self.assertNotIn("f3=v3", state.physical)

        # 审计事件可回放，记录回滚点
        audits = [e for e in self._active_events()
                  if e["event_type"] == "author_intervention"]
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0]["payload"]["action"], "remove_event")
        self.assertEqual(audits[0]["payload"]["rolled_back_to_tick"], 1)

    def test_edit_event_old_rolled_back_new_committed(self):
        """edit 语义：旧事件 rolled_back + 新内容事件进流（顺序正确、内容正确）"""
        e1 = self._commit(payload={"field": "f1", "new_value": "v1"})
        e2 = self._commit("character_action", {
            "agent": "包拯", "action": "查案",
            "effects": {"learn": {"包拯": ["旧线索"]}}})

        r = self.router.route(HumanInput(
            type="structural", reason="改写关键情节",
            payload={"action": "edit_event", "event_id": e2.event_id,
                     "before": {"action": "查案"},
                     "after": {"event_type": "character_action",
                               "payload": {"agent": "包拯", "action": "夜审",
                                           "effects": {"learn": {"包拯": ["新线索"]}}}}}))
        self.assertTrue(r.ok)

        by_id = {e["event_id"]: e for e in self.kernel.query_world("all_events")}
        self.assertFalse(by_id[e2.event_id]["active"])  # 旧事件 rolled_back

        # 活跃流顺序：e1 → 审计事件 → 新内容事件（tick 递增）
        active = self._active_events()
        self.assertEqual([e["event_type"] for e in active],
                         ["world_change", "author_intervention", "character_action"])
        self.assertEqual([e["world_tick"] for e in active], [1, 2, 3])
        new_ev = active[-1]
        self.assertEqual(new_ev["payload"]["action"], "夜审")
        self.assertEqual(new_ev["payload"]["replaces"], e2.event_id)

        # 新内容走通 fold：projection 里可见新认知、不见旧认知
        state = self.kernel.query_world("current_state")
        self.assertTrue(state.minds["包拯"].beliefs["新线索"])
        self.assertNotIn("旧线索", state.minds["包拯"].beliefs)

    def test_textual_records_only_and_structural_without_regen_fn(self):
        """textual：before/after/reason 进事件流 + 不触发重生成；
        无 regenerate_fn 注入时 structural 也不崩（message 注明待重生成）"""
        r = self.router.route(HumanInput(
            type="textual", reason="润色",
            payload={"chapter": 2, "before": "旧文本", "after": "新文本"}))
        self.assertTrue(r.ok)
        self.assertFalse(r.regenerated)  # textual 恒不重生成
        self.assertEqual(len(self.regen_calls), 0)  # regenerate_fn 未被调用
        self.assertIn("不重生成", r.message)

        events = [e for e in self.kernel.query_world("all_events")
                  if e["event_type"] == "author_intervention"]
        self.assertEqual(len(events), 1)
        p = events[0]["payload"]
        self.assertEqual(p["type"], "textual")
        self.assertEqual(p["chapter"], 2)
        self.assertEqual(p["before"], "旧文本")
        self.assertEqual(p["after"], "新文本")
        self.assertEqual(p["reason"], "润色")

        # 无 regenerate_fn 的 router：structural 只标记不崩，message 注明待重生成
        bare = InterventionRouter(self.kernel)
        target = self._commit(payload={"field": "f9", "new_value": "v9"})
        r2 = bare.route(HumanInput(
            type="structural", payload={"action": "remove_event",
                                        "event_id": target.event_id}))
        self.assertTrue(r2.ok)
        self.assertFalse(r2.regenerated)
        self.assertIn("待重生成", r2.message)
        by_id = {e["event_id"]: e for e in self.kernel.query_world("all_events")}
        self.assertFalse(by_id[target.event_id]["active"])


if __name__ == "__main__":
    unittest.main()
