"""P6.2 测试：两阶段生成（B3：plan + confirm 模式）

核心用例（用户指令：只保留核心，不穷举边界）：
1. plan 端点：返回决策卡（含 beats/tracks）+ 不产新章节 + snapshot 出现 pending_plan
2. confirm 流程：plan → generate(mode=confirm) → 章节决策卡与 plan 相同
   + pending_plan 已清除
3. auto 零变化 + 副作用验证：无 plan 时 confirm 宽容等同 auto（无 body 旧调用
   不变）；plan 后 auto generate 伏笔池计数与剧本一致（不重复种伏笔）+ pending 清除
"""
import unittest

from fastapi.testclient import TestClient

from conftest import import_backend_main

backend = import_backend_main()


class TestPlanConfirm(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(backend.app)
        # 模块单例状态归零（reset 不动 registry/training 文件，对后续用例无影响）
        r = cls.client.post("/api/project/reset")
        assert r.status_code == 200

    def _snapshot(self) -> dict:
        return self.client.get("/api/project").json()

    def test_1_plan_returns_card_without_chapter(self):
        before = self._snapshot()["meta"]["chapter_count"]
        r = self.client.post("/api/project/plan")
        self.assertEqual(r.status_code, 200)
        card = r.json()
        # 决策卡关键字段
        self.assertEqual(card["episode"], before + 1)
        self.assertTrue(card["beats"])
        self.assertTrue(card["advance"])
        self.assertTrue(card["track_names"])
        # 不产新章节 + snapshot 出现 pending_plan
        snap = self._snapshot()
        self.assertEqual(snap["meta"]["chapter_count"], before)
        self.assertEqual(snap["pending_plan"], card)

    def test_2_confirm_consumes_pending_plan(self):
        card = self.client.post("/api/project/plan").json()
        r = self.client.post("/api/project/generate", json={"mode": "confirm"})
        self.assertEqual(r.status_code, 200)
        rec = r.json()
        # 生成章节的决策卡与 plan 相同（复用缓存卡，未重新产卡）
        self.assertEqual(rec["chapter"], card["episode"])
        self.assertEqual(rec["decision_card"], card)
        # pending_plan 已清除
        self.assertIsNone(self._snapshot()["pending_plan"])

    def test_3_auto_unchanged_and_no_double_side_effect(self):
        # 无 pending plan 时 confirm 宽容等同 auto（策略选择，见报告）
        r = self.client.post("/api/project/generate", json={"mode": "confirm"})
        self.assertEqual(r.status_code, 200)
        ch = r.json()["chapter"]
        # plan 后 auto generate（无 body = 旧调用方式，现状逐字不变）
        card = self.client.post("/api/project/plan").json()
        self.assertEqual(card["episode"], ch + 1)
        r = self.client.post("/api/project/generate")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["chapter"], ch + 1)
        snap = self._snapshot()
        self.assertIsNone(snap["pending_plan"])  # auto 生成后缓存方案同样失效
        # 副作用验证：剧本路径伏笔池只由 FORESHADOW_SCRIPT 种/收 ——
        # 按剧本口径重放到当前章，plan 的两次产卡未造成重复伏笔
        from story_engine import mock_script
        total = snap["meta"]["chapter_count"]
        planted, payed = [], set()
        for c in range(1, total + 1):
            script = mock_script.FORESHADOW_SCRIPT.get(c, {"planted": [], "payed": []})
            planted += [p["foreshadow_id"] for p in script["planted"]]
            payed |= set(script["payed"])
        fs = snap["world_state"]["foreshadows"]
        self.assertEqual(len(fs), len(planted))
        self.assertEqual(sum(1 for f in fs if not f["payed_off"]),
                         len(planted) - len(payed))


if __name__ == "__main__":
    unittest.main()
