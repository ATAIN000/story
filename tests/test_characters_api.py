"""P6.4 测试：角色卡聚合端点（B4：GET /api/characters）

核心用例（用户指令：只保留核心，不穷举边界）：
1. 生成 1 章后 GET /api/characters：含包拯等 SEED_CHARACTERS，字段齐全
   （knows/goals 非空、role 正确、voice 为种子声音串、arc=None——
   genre yaml tracks 无角色↔轨道显式绑定，不编造）
2. relations 结构正确：target/type 字符串、intensity 数值型，含创世种子关系
3. 空世界状态 → [] 不崩（纯函数层验证；API 单例创世即带种子角色，无空项目路径）
"""
import unittest

from fastapi.testclient import TestClient

from conftest import import_backend_main
from story_engine.engine import StoryEngine
from story_engine.types import WorldState

backend = import_backend_main()


class TestCharactersApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(backend.app)
        # 模块单例状态归零（同 test_plan_confirm 口径），再生成剧本第 1 章（离线）
        r = cls.client.post("/api/project/reset")
        assert r.status_code == 200
        r = cls.client.post("/api/project/generate")
        assert r.status_code == 200

    @classmethod
    def tearDownClass(cls):
        # 共享单例善后：复位到 0 章 pristine 态（test_ir_first_integration 等
        # 字母序靠后的使用方依赖「无章节」初态，不善后会造成状态污染）
        r = cls.client.post("/api/project/reset")
        assert r.status_code == 200

    def test_1_cards_cover_seed_characters(self):
        r = self.client.get("/api/characters")
        self.assertEqual(r.status_code, 200)
        cards = r.json()
        by_id = {c["id"]: c for c in cards}
        for cid in ("包拯", "展昭", "公孙策", "刘伯", "王员外"):
            self.assertIn(cid, by_id)
        # 顺序稳定：按 id 排序
        self.assertEqual([c["id"] for c in cards], sorted(by_id))
        bao = by_id["包拯"]
        self.assertEqual(bao["role"], "开封府尹")
        self.assertIn("玉佩失窃", bao["knows"])     # 第 1 章剧本 learn 事实
        self.assertTrue(bao["goals"])               # 创世种子目标
        self.assertEqual(bao["voice"], "沉毅克制，少言而中")  # 种子声音串（非编造）
        self.assertIsNone(bao["arc"])               # yaml tracks 无角色绑定 → null

    def test_2_relations_shape(self):
        cards = self.client.get("/api/characters").json()
        bao = {c["id"]: c for c in cards}["包拯"]
        self.assertTrue(bao["relations"])
        for rel in bao["relations"]:
            self.assertIsInstance(rel["target"], str)
            self.assertIsInstance(rel["type"], str)
            self.assertIsInstance(rel["intensity"], (int, float))
        targets = {rel["target"] for rel in bao["relations"]}
        self.assertIn("展昭", targets)  # 创世种子关系 包拯|展昭

    def test_3_empty_world_state_returns_empty_list(self):
        self.assertEqual(StoryEngine._characters_view(WorldState()), [])


if __name__ == "__main__":
    unittest.main()
