"""P3.9：Phase 3 核心验收 — 换 Genre 决策卡/prompt 差异 + 新字段 API 可见性

对应计划验收标准（见 .superpowers/sdd/briefs/task-9-brief.md）：
  ② 蓝图 Module 3：同一初始 WorldState 下 mystery vs romance →
     决策卡轨道集合 / beats 数（4 vs 5）/ 情感弧序列不同
  ④ 生成端：romance 模式 _real_generate_prompt 不含「包拯」「开封府」，
     含 romance.yaml 的 setting/characters 关键词；mystery 模式保持原意
  ⑧ 决策卡新字段（pacing/pool_stats/concreteness_curve/creative_seeds/plan_goals）
     在 engine 对外返回路径可见 —— engine.project_snapshot() 即
     GET /api/project 的响应体（backend/main.py:93-95 原样返回），
     engine.generate_chapter() 的返回即 POST /api/project/generate 的响应体
     （backend/main.py:98-101 原样返回），两者均内嵌 card.to_dict()

切 genre 用代码支持的真实机制：StoryEngine 构造时读 STORY_ENGINE_GENRE
环境变量（engine.py:83，默认 mystery），故在构造前 patching env。
"""
import asyncio
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from story_engine.engine import StoryEngine

# 决策卡 P3 新增字段（验收标准 8）
NEW_CARD_FIELDS = {"pacing", "pool_stats", "concreteness_curve",
                   "creative_seeds", "plan_goals"}


def make_engine(genre: str) -> tuple[str, StoryEngine]:
    """以指定 genre 建引擎（同一份 genesis WorldState）；env 仅在构造时读取"""
    tmp = tempfile.mkdtemp()
    with mock.patch.dict(os.environ, {"STORY_ENGINE_GENRE": genre}):
        eng = StoryEngine(tmp)
    return tmp, eng


class TestGenreSwitch(unittest.TestCase):
    """换 genre 的三项核心差异 + 决策卡新字段对外可见"""

    def setUp(self):
        self.dirs = []
        self.engines = {}
        for genre in ("mystery", "romance"):
            tmp, eng = make_engine(genre)
            self.dirs.append(tmp)
            self.engines[genre] = eng

    def tearDown(self):
        for eng in self.engines.values():
            try:
                eng.kernel.close()
            except Exception:
                pass
        for d in self.dirs:
            shutil.rmtree(d, ignore_errors=True)

    def _card(self, genre: str, episode: int = 1):
        eng = self.engines[genre]
        state = eng.kernel.query_world("current_state")
        return eng.showrunner.generate_decision_card(episode, state)

    # 验收标准 ②：决策卡结构差异
    def test_decision_card_structure_differs(self):
        m_card, r_card = self._card("mystery"), self._card("romance")

        # 轨道全集不同：mystery 五轨道 vs romance 四轨道（追求/障碍/情敌/成长）
        m_tracks = set(m_card.advance + m_card.seed + m_card.mid_touch + m_card.dormant)
        r_tracks = set(r_card.advance + r_card.seed + r_card.mid_touch + r_card.dormant)
        self.assertEqual(m_tracks, {"A", "B", "C", "D", "E"})
        self.assertEqual(r_tracks, {"A", "B", "C", "D"})

        # beats 数不同：mystery beats_per_chapter=4 / romance=5
        self.assertEqual(len(m_card.beats), 4)
        self.assertEqual(len(r_card.beats), 5)

        # 情感弧不同：逐章目标弧序列不同，且各自取自本题材 emotion_arcs
        m_arcs = [self._card("mystery", ep).target_arc for ep in (1, 2, 3)]
        r_arcs = [self._card("romance", ep).target_arc for ep in (1, 2, 3)]
        self.assertNotEqual(m_arcs, r_arcs)
        for arc in m_arcs:
            self.assertIn(arc, ["man_in_hole", "cinderella", "icarus"])
        for arc in r_arcs:
            self.assertIn(arc, ["rags_to_riches", "cinderella", "man_in_hole"])

    # 验收标准 ④：生成 prompt 随 genre 切换
    def test_generate_prompt_follows_genre(self):
        for genre in ("mystery", "romance"):
            eng = self.engines[genre]
            state = eng.kernel.query_world("current_state")
            card = eng.showrunner.generate_decision_card(1, state)
            prompt = eng._real_generate_prompt(1, card, state)
            if genre == "romance":
                # 不残留公案题材；改用 romance.yaml 的 setting/characters
                self.assertNotIn("包拯", prompt)
                self.assertNotIn("开封府", prompt)
                self.assertIn("江南水乡", prompt)          # setting
                self.assertIn("沈砚清", prompt)            # characters
                self.assertIn("顾明璋", prompt)
            else:
                # mystery 保持原意（公案题材文案）
                self.assertIn("包拯", prompt)
                self.assertIn("开封府", prompt)

    # 验收标准 ⑧：决策卡新字段在 /api 返回 JSON 中可见
    def test_card_new_fields_visible_in_api_payload(self):
        eng = self.engines["mystery"]
        # generate_chapter 的返回 = POST /api/project/generate 响应体
        rec1 = asyncio.run(eng.generate_chapter())
        rec2 = asyncio.run(eng.generate_chapter())
        self.assertTrue(NEW_CARD_FIELDS <= set(rec1["decision_card"]))
        # 首章即有真值的字段
        card1 = rec1["decision_card"]
        self.assertTrue(card1["pool_stats"])
        self.assertTrue(card1["concreteness_curve"])
        self.assertTrue(card1["plan_goals"])
        # pacing 首章为 None（无上一章），第 2 章起填真实 PacingScore
        self.assertIsNone(card1["pacing"])
        self.assertIsNotNone(rec2["decision_card"]["pacing"])

        # project_snapshot() = GET /api/project 响应体；章节记录内嵌同一决策卡
        snap = eng.project_snapshot()
        for ch in snap["chapters"]:
            self.assertTrue(NEW_CARD_FIELDS <= set(ch["decision_card"]),
                            f"第{ch['chapter']}章决策卡缺新字段")
        # 整包可 JSON 序列化（FastAPI 返回前提）
        json.dumps(snap, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
