"""HITL API 测试（P5.10：POST /api/intervene、GET /api/interventions、POST /api/hitl/respond）

核心用例（用户指令：只保留核心，不穷举边界）：
1. TestClient 三端点走通：intent 介入 → 200 + ok=True；GET 含该条；
   真实 pending（kernel.request_human_input 挂到 TestClient portal 的同一
   事件循环 —— resolve 的 event.set 有线程亲和）→ respond ok=True
2. 未知 type → 400；未知 request_id → 404
3. textual 介入经 API → training_data/style.jsonl 落盘
   （P5.9 textual→pipeline 接线缺口的端到端闭环验证）
"""
import json
import time
import unittest

from fastapi.testclient import TestClient

# P5.11：导入隔离样板（临时项目目录 + env 快照/还原）抽成 conftest 共享
# helper；kernel 单例的 close 由 conftest 挂 atexit 统一处理（本文件不再
# 自行 close——单例共享，先收尾会波及字母序靠后的 backend 使用方）
from conftest import import_backend_main

backend = import_backend_main()


class TestHitlApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._ctx = TestClient(backend.app)
        cls.client = cls._ctx.__enter__()  # __enter__ 后 client.portal 可用

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)
        # kernel.close 不在此处做：backend 单例与 test_ir_first_integration
        # 等文件共享，由 conftest 的 atexit 统一收尾

    def test_1_three_endpoints_walkthrough(self):
        # POST /api/intervene（intent 类）→ 200 + ok=True
        r = self.client.post("/api/intervene", json={
            "type": "intent", "reason": "改方向",
            "payload": {"goal_update": "主线转向复仇", "constraint": "不可写死主角"}})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"])
        event_id = body["event_id"]

        # GET /api/interventions 含该条
        r = self.client.get("/api/interventions")
        self.assertEqual(r.status_code, 200)
        match = [e for e in r.json() if e["event_id"] == event_id]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0]["payload"]["type"], "intent")
        self.assertEqual(match[0]["payload"]["goal_update"], "主线转向复仇")
        self.assertEqual(match[0]["payload"]["reason"], "改方向")

        # POST /api/hitl/respond：真实 pending。等待协程与应答端点须在
        # 同一事件循环线程（kernel.resolve_human_input docstring），
        # 故把 request_human_input 挂进 TestClient portal 的 loop
        fut = self.client.portal.start_task_soon(
            backend.deps.kernel.request_human_input,
            "选哪个走向？", {"options": ["A", "B"]}, 5.0)
        request_id = None
        for _ in range(50):  # 等 pending 落盘（记录追加在首个 await 之前）
            recs = backend.deps.kernel._read_hitl_requests()
            if recs:
                request_id = recs[0]["request_id"]
                break
            time.sleep(0.02)
        self.assertIsNotNone(request_id, "pending 记录未落盘")

        r = self.client.post("/api/hitl/respond", json={
            "request_id": request_id, "response": {"choice": "A"}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"ok": True})
        resp = fut.result(timeout=2)  # 等待协程被应答唤醒
        self.assertTrue(resp.accepted)
        self.assertEqual(resp.payload, {"choice": "A"})
        # 落盘记录由 request_human_input 自己标 answered
        self.assertEqual(
            backend.deps.kernel._read_hitl_requests()[0]["status"], "answered")

    def test_2_unknown_type_400_unknown_request_404(self):
        r = self.client.post("/api/intervene", json={
            "type": "holistic", "payload": {}, "reason": ""})
        self.assertEqual(r.status_code, 400)
        self.assertIn("未知介入类型", r.json()["detail"])

        r = self.client.post("/api/hitl/respond", json={
            "request_id": "hitl-不存在", "response": {}})
        self.assertEqual(r.status_code, 404)

    def test_3_textual_via_api_writes_style_jsonl(self):
        r = self.client.post("/api/intervene", json={
            "type": "textual", "reason": "描写太干",
            "payload": {"chapter": 2, "before": "他走了进去。",
                        "after": "他推门，闪身而入。"}})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertFalse(r.json()["regenerated"])  # textual 恒不重生成

        style_path = (backend.deps.kernel.project_dir
                      / "training_data" / "style.jsonl")
        self.assertTrue(style_path.exists())
        rows = [json.loads(line) for line in
                style_path.read_text(encoding="utf-8").splitlines()
                if line.strip()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["chapter"], 2)
        self.assertEqual(rows[0]["before"], "他走了进去。")
        self.assertEqual(rows[0]["after"], "他推门，闪身而入。")
        self.assertEqual(rows[0]["reason"], "描写太干")


if __name__ == "__main__":
    unittest.main()
