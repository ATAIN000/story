"""P6.10 测试：设置端点（B9 GET/POST /api/settings）+ LLM 测试连接（B10）

核心用例（用户指令：只写核心）：
1. GET /api/settings 返回 6 字段结构；base_url_masked 不含完整 URL；
   api_key 永不在响应中。
2. POST /api/settings 写进程内覆盖：关 eval_enabled 后再 GET 反映新值；
   原始 _eval_enabled（mock 路径）仍保持 False（SCRIPTED_DEMO/llm.is_mock 兜底）。
3. POST /api/settings/test_llm mock 模式 → ok=true（不实际请求网络）；
   响应只 {ok, latency_ms, model, error?}，无 key。
"""
import unittest

from fastapi.testclient import TestClient

from conftest import import_backend_main

backend = import_backend_main()


class TestSettingsApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(backend.app)
        # 清掉之前的覆盖（其他用例可能写过）
        backend.engine._runtime_overrides = {}

    @classmethod
    def tearDownClass(cls):
        # 复位进程内覆盖（共享单例，字母序靠后的使用方不被污染）
        backend.engine._runtime_overrides = {}

    def test_1_get_shape_and_no_key(self):
        r = self.client.get("/api/settings")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        # 7 字段结构（P23 起 +llm_configured）
        for k in ("eval_enabled", "ir_first", "eval_max_rounds",
                  "llm_mode", "llm_model", "llm_configured",
                  "base_url_masked"):
            self.assertIn(k, body)
        # api_key 永不出现
        self.assertNotIn("api_key", body)
        self.assertNotIn("key", body)
        # base_url_masked 是字符串（可能为空）
        self.assertIsInstance(body["base_url_masked"], str)
        # eval_max_rounds 钳 [1,5]
        self.assertTrue(1 <= body["eval_max_rounds"] <= 5)

    def test_2_post_overrides_reflected_and_eval_still_mock_gated(self):
        # POST 关 eval_enabled
        r = self.client.post("/api/settings", json={"eval_enabled": False})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["eval_enabled"])
        # 再次 GET 反映覆盖
        body = self.client.get("/api/settings").json()
        self.assertFalse(body["eval_enabled"])
        # 引擎生成路径：mock/SCRIPTED_DEMO 兜底 → _eval_enabled 仍 False
        # （即覆盖写了，但实际生成时仍被 SCRIPTED_DEMO/llm.is_mock 兜底，
        # 这是设计意图——评审意见：mock 路径不受覆盖影响）
        self.assertFalse(backend.engine._eval_enabled())
        # ir_first 覆盖 + eval_max_rounds 钳位
        self.client.post("/api/settings",
                         json={"ir_first": True, "eval_max_rounds": 99})
        body = self.client.get("/api/settings").json()
        self.assertTrue(body["ir_first"])
        self.assertEqual(body["eval_max_rounds"], 5)  # 钳到 5

    def test_3_test_llm_mock_ok_no_key(self):
        # mock 模式（无 key/base_url）→ ok=true 不走网络
        r = self.client.post("/api/settings/test_llm", json={})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"])
        # 响应只含 {ok, latency_ms, model, error?}，无 key
        self.assertNotIn("key", body)
        self.assertNotIn("api_key", body)
        self.assertIn("model", body)

    # ---------- P23：在线 LLM 配置 + 错误中文化 ----------

    def test_4_llm_settings_inprocess_override(self):
        old_model = backend.engine.llm.model
        old_url = backend.engine.llm.base_url
        try:
            r = self.client.post("/api/settings/llm", json={
                "base_url": "https://api.deepseek.com/v1",
                "model": "deepseek-chat"})
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertEqual(body["llm_model"], "deepseek-chat")
            self.assertIn("llm_configured", body)
            self.assertNotIn("api_key", body)
            # 非法 base_url → 422 中文提示
            r = self.client.post("/api/settings/llm",
                                 json={"base_url": "http://evil.example.com"})
            self.assertEqual(r.status_code, 422)
            self.assertIn("https", r.json()["detail"])
        finally:
            backend.engine.llm.base_url = old_url
            backend.engine.llm.model = old_model

    def test_5_validation_422_chinese(self):
        # P23：Pydantic 422 → 中文字段名（不再漏英文 Field required）
        r = self.client.post("/api/gacha/begin", json={})
        self.assertEqual(r.status_code, 422)
        self.assertIn("题材名", r.json()["detail"])

    def test_6_persist_env_roundtrip(self):
        # P23：_persist_env 写回 .env（保留注释行、替换已有键、追加新键）
        import tempfile
        from pathlib import Path
        saved_root = backend.ROOT
        tmp = Path(tempfile.mkdtemp())
        (tmp / ".env").write_text("# 注释行\nFOO=1\n", encoding="utf-8")
        try:
            backend.ROOT = tmp
            backend._persist_env({"FOO": "2", "BAR": "x"})
            text = (tmp / ".env").read_text(encoding="utf-8")
            self.assertIn("# 注释行", text)
            self.assertIn("FOO=2", text)
            self.assertNotIn("FOO=1", text)
            self.assertIn("BAR=x", text)
        finally:
            backend.ROOT = saved_root


if __name__ == "__main__":
    unittest.main()
