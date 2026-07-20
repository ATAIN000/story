"""热修复测试：LLM 平铺 list 形态 learn 的归一（plan/generate 500 根因）"""
import tempfile
import unittest

from story_engine.types import normalize_learn, WorldEvent
from story_engine.kernel import Kernel


class TestNormalizeLearn(unittest.TestCase):
    def test_flat_list_with_prefix_assigns_to_named_characters(self):
        effects = {"learn": ["包拯得知玉佩为御赐之物，失窃事关重大",
                             "公孙策得知玉佩最后出现地点是后花园赏花宴"]}
        out = normalize_learn(effects, agent="王员外")
        self.assertEqual(out["learn"], {
            "包拯": ["玉佩为御赐之物，失窃事关重大"],
            "公孙策": ["玉佩最后出现地点是后花园赏花宴"],
        })

    def test_no_prefix_falls_back_to_agent_and_dict_wrapping(self):
        out = normalize_learn({"learn": ["玉佩失窃"]}, agent="展昭")
        self.assertEqual(out["learn"], {"展昭": ["玉佩失窃"]})
        out2 = normalize_learn({"learn": {"包拯": "玉佩失窃"}}, agent="展昭")
        self.assertEqual(out2["learn"], {"包拯": ["玉佩失窃"]})
        out3 = normalize_learn({"learn": "乱写的"}, agent="展昭")
        self.assertNotIn("learn", out3)

    def test_fold_replay_survives_flat_list_learn(self):
        """真实事件流回放：平铺 learn 不再崩溃，且认知进 projection"""
        with tempfile.TemporaryDirectory() as d:
            k = Kernel(d)
            k.store.append(WorldEvent(
                event_id="e1", event_type="character_action",
                timestamp="2026-07-20T00:00:00", world_tick=1, branch_id="main",
                payload={"agent": "王员外", "action": "报案",
                         "effects": {"learn": ["包拯得知玉佩为御赐之物"]}}))
            state = k.query_world("current_state")
            self.assertTrue(state.minds["包拯"].beliefs.get("玉佩为御赐之物"))
            k.close()


if __name__ == "__main__":
    unittest.main()
