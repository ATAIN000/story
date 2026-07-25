"""P6.3 测试：段落重写端点（B2：POST /api/paragraph/rewrite，Realizer 单段渲染）

核心用例（用户指令：只保留核心，不穷举边界）：
1. fake LLM 下 POST 重写：original==原段 + rewritten==fake 文本；fake 记录
   prompt，断言含 direction + 原段内容 + 前后段上下文 + purpose=rewrite_paragraph
2. 越界 para_index → 404；不存在章节 → 404
3. mock/异常兜底：llm 返回空 → 200 + rewritten 空 + note（不 500）

fake 注入：monkeypatch 内核单例实例属性 kernel.llm_call（类方法被实例属性
遮蔽），各用例 finally 还原（pop 实例属性即回到类方法），不污染共享单例。
"""
import unittest

from fastapi.testclient import TestClient

from conftest import import_backend_main

backend = import_backend_main()


class _FakeResp:
    def __init__(self, text):
        self.text = text


def _fake_llm(record: list, text: str):
    """record 收集 (prompt, purpose)；固定返回 text（模拟 LLM 响应）"""
    async def call(prompt, *, purpose="generate", temperature=0.7,
                   max_tokens=8192):
        record.append({"prompt": prompt, "purpose": purpose})
        return _FakeResp(text)
    return call


class TestParagraphRewrite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(backend.app)
        # 模块单例状态归零 + 剧本章 1（SCRIPTED_DEMO=1 离线路径）
        assert cls.client.post("/api/project/reset").status_code == 200
        assert cls.client.post("/api/project/generate").status_code == 200
        ch1 = next(c for c in cls.client.get("/api/project").json()["chapters"]
                   if c["chapter"] == 1)
        cls.paras = backend.deps.engine._split_paragraphs(ch1["final"]["text"])
        assert len(cls.paras) >= 3  # 用例 1 取中段，前后段齐备

    def tearDown(self):
        # 还原 kernel.llm_call（pop 实例属性即回类方法；共享单例不残留）
        backend.deps.kernel.__dict__.pop("llm_call", None)

    def test_1_fake_llm_rewrite_with_direction_and_context(self):
        record = []
        backend.deps.kernel.llm_call = _fake_llm(record, "【重写】包拯览状，目光沉静。")
        r = self.client.post("/api/paragraph/rewrite",
                             json={"chapter": 1, "para_index": 1,
                                   "direction": "更紧张一些"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["original"], self.paras[1])
        self.assertEqual(body["rewritten"], "【重写】包拯览状，目光沉静。")
        self.assertIsNone(body["note"])
        # 恰好 1 次 LLM 调用；prompt 含 direction + 原段 + 前后段上下文
        self.assertEqual(len(record), 1)
        self.assertEqual(record[0]["purpose"], "rewrite_paragraph")
        prompt = record[0]["prompt"]
        self.assertIn("更紧张一些", prompt)
        self.assertIn(self.paras[1], prompt)
        self.assertIn(self.paras[0], prompt)  # 前一段（衔接）
        self.assertIn(self.paras[2], prompt)  # 后一段（衔接）
        # 只读不写：正文未被改动（回写走 P6.1 textual 介入通道）
        ch1 = next(c for c in self.client.get("/api/project").json()["chapters"]
                   if c["chapter"] == 1)
        self.assertNotIn("【重写】", ch1["final"]["text"])

    def test_2_out_of_range_and_missing_chapter_404(self):
        r = self.client.post("/api/paragraph/rewrite",
                             json={"chapter": 1, "para_index": 999})
        self.assertEqual(r.status_code, 404)
        self.assertIn("越界", r.json()["detail"])
        r = self.client.post("/api/paragraph/rewrite",
                             json={"chapter": 99, "para_index": 0})
        self.assertEqual(r.status_code, 404)

    def test_3_empty_llm_fallback_200_with_note(self):
        backend.deps.kernel.llm_call = _fake_llm([], "")
        r = self.client.post("/api/paragraph/rewrite",
                             json={"chapter": 1, "para_index": 0})
        self.assertEqual(r.status_code, 200)  # 兜底不 500
        body = r.json()
        self.assertEqual(body["original"], self.paras[0])
        self.assertEqual(body["rewritten"], "")
        self.assertTrue(body["note"])


if __name__ == "__main__":
    unittest.main()
