"""P23.3 章节生成后台化 + 状态查询 测试。

验证：
- generate/async 启动后台任务 → status busy=True → 完成后 finished=True + result 有章节
- 并发锁：async 生成中再调 async / 同步 generate / 切项目 → 409
- mock engine.generate_chapter 避免真跑 10 分钟
"""
from __future__ import annotations

import asyncio
import unittest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from backend import deps
from backend.generation_state import gen_state


def _patch_engine_async(monkey_chapter_no: int = 1):
    """把 deps.engine.generate_chapter 换成立即返回假章节记录的 mock。"""
    async def _fake_generate(self, mode="auto"):
        return {"chapter": monkey_chapter_no, "title": f"第{monkey_chapter_no}章",
                "final": {"text": "假正文"}, "committed_events": [],
                "draft_results": [], "violations": [], "correction": None,
                "evaluation": None, "narrative_ir": None, "foreshadow_updates": None}
    deps.engine.generate_chapter = lambda mode="auto": _fake_generate(deps.engine, mode)
    # _next_chapter_no 读 state.narrative.chapter，patch 一下避免依赖真实状态
    state = deps.engine.kernel.query_world("current_state")
    # 用一个简单可读对象兜住 narrative.chapter
    class _N:
        chapter = monkey_chapter_no - 1
    state.narrative = _N()


class GenerationStateTest(unittest.IsolatedAsyncioTestCase):
    """直接测 GenerationState 对象（不经 HTTP，快）。"""

    def setUp(self):
        gen_state.clear()

    def tearDown(self):
        gen_state.clear()

    def test_initial_state(self):
        self.assertFalse(gen_state.busy())
        snap = gen_state.snapshot()
        self.assertFalse(snap["busy"])
        self.assertIsNone(snap["chapter_no"])
        self.assertFalse(snap["finished"])

    async def test_busy_reflects_task_state(self):
        async def _run():
            await asyncio.sleep(0.05)
        gen_state.task = asyncio.create_task(_run())
        self.assertTrue(gen_state.busy())
        await gen_state.task   # IsolatedAsyncioTestCase 提供 running loop
        self.assertFalse(gen_state.busy())

    def test_reset_status_keeps_task(self):
        gen_state.task = "sentinel"
        gen_state.chapter_no = 5
        gen_state.finished = True
        gen_state.reset_status()
        self.assertEqual(gen_state.task, "sentinel")  # reset_status 不动 task
        self.assertIsNone(gen_state.chapter_no)
        self.assertFalse(gen_state.finished)

    def test_clear_wipes_all(self):
        gen_state.task = "sentinel"
        gen_state.chapter_no = 5
        gen_state.project_name = "x"
        gen_state.clear()
        self.assertIsNone(gen_state.task)
        self.assertIsNone(gen_state.project_name)


class GenerateAsyncHTTPTest(unittest.IsolatedAsyncioTestCase):
    """经 ASGI async client 测 /generate/async + /generation-status。

    必须用 AsyncClient（同一 event loop），否则后台 create_task 绑在 TestClient
    的临时 loop 上、请求返回即销毁，无法观测 busy 态。真实 uvicorn 是单长驻 loop。
    """

    @classmethod
    def setUpClass(cls):
        cls._orig_generate = deps.engine.generate_chapter
        _patch_engine_async(1)
        from backend.main import app
        cls.app = app

    @classmethod
    def tearDownClass(cls):
        # 共享单例善后：还原 generate_chapter（字母序靠后的
        # test_ir_first_integration 等依赖真实生成路径，不还原会污染）
        deps.engine.generate_chapter = cls._orig_generate

    async def asyncSetUp(self):
        gen_state.clear()
        from httpx import AsyncClient, ASGITransport
        self._client = AsyncClient(transport=ASGITransport(app=self.app), base_url="http://test")

    async def asyncTearDown(self):
        await self._client.aclose()
        gen_state.clear()

    async def test_async_start_then_status_busy_then_finished(self):
        """启动 async → status busy=True → 等完成 → finished=True + result 有章节。"""
        from backend.routers.project import _next_chapter_no
        # 用带小延迟的 mock，确保能观测到 busy 态（立即返回的 mock 会秒完，busy 抓不到）
        async def _delayed(self, mode="auto"):
            await asyncio.sleep(0.2)
            return {"chapter": _next_chapter_no(), "title": "测试章",
                    "final": {"text": "假正文"}, "committed_events": [],
                    "draft_results": [], "violations": [], "correction": None,
                    "evaluation": None, "narrative_ir": None, "foreshadow_updates": None}
        deps.engine.generate_chapter = lambda mode="auto": _delayed(deps.engine, mode)

        expected_no = _next_chapter_no()
        r = await self._client.post("/api/project/generate/async", json={"mode": "confirm"})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body["started"])
        self.assertEqual(body["chapter_no"], expected_no)

        # 立即查 status：应 busy（mock 还在 sleep 0.2s）
        s = (await self._client.get("/api/project/generation-status")).json()
        self.assertTrue(s["busy"])
        self.assertEqual(s["chapter_no"], expected_no)

        # 等后台任务完成
        import time
        deadline = time.time() + 5
        while time.time() < deadline:
            s = (await self._client.get("/api/project/generation-status")).json()
            if s["finished"]:
                break
            await asyncio.sleep(0.05)
        self.assertTrue(s["finished"], "后台任务未在超时内完成")
        self.assertEqual(s["stage"], "done")
        self.assertIsNotNone(s["result"])

    async def test_concurrent_async_rejected_409(self):
        """async 生成中再调 async → 409。"""
        async def _slow(self, mode="auto"):
            await asyncio.sleep(10)
            return {"chapter": 1}
        deps.engine.generate_chapter = lambda mode="auto": _slow(deps.engine, mode)
        r1 = await self._client.post("/api/project/generate/async", json={"mode": "confirm"})
        self.assertEqual(r1.status_code, 200)
        r2 = await self._client.post("/api/project/generate/async", json={"mode": "confirm"})
        self.assertEqual(r2.status_code, 409)

    async def test_sync_generate_blocked_while_async_busy(self):
        """async 生成中调同步 /generate → 409（并发保护）。"""
        async def _slow(self, mode="auto"):
            await asyncio.sleep(10)
            return {"chapter": 1}
        deps.engine.generate_chapter = lambda mode="auto": _slow(deps.engine, mode)
        await self._client.post("/api/project/generate/async", json={"mode": "confirm"})
        r = await self._client.post("/api/project/generate", json={"mode": "confirm"})
        self.assertEqual(r.status_code, 409)

    async def test_await_returns_result_when_finished(self):
        """generate/await 在任务完成后返回 result。"""
        from backend.routers.project import _next_chapter_no
        async def _delayed(self, mode="auto"):
            await asyncio.sleep(0.1)
            return {"chapter": _next_chapter_no(), "title": "测试章", "final": {"text": "x"},
                    "committed_events": [], "draft_results": [], "violations": [],
                    "correction": None, "evaluation": None, "narrative_ir": None,
                    "foreshadow_updates": None}
        deps.engine.generate_chapter = lambda mode="auto": _delayed(deps.engine, mode)
        expected_no = _next_chapter_no()
        await self._client.post("/api/project/generate/async", json={"mode": "confirm"})
        r = await self._client.post("/api/project/generate/await")  # await 会等任务完成
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["chapter"], expected_no)


if __name__ == "__main__":
    unittest.main()
