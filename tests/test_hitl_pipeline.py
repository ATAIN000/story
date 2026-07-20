"""HITL TrainingPipeline + Kernel.request_human_input 测试（P5.9，Module 7.2）

核心用例（用户指令：只保留核心，不穷举边界）：
1. high 质量 evaluation 介入 → 技能注册 story.skill + preferences.jsonl 落盘一行；
   pipeline 依赖抛错时异常不传播 → router 仍 ok
2. textual 介入 → style.jsonl 落盘（before/after/reason 完整）
   （直接喂 pipeline 验证通路；router→pipeline 的 textual 接线由 P5.10 补齐，
   端到端闭环见 tests/test_hitl_api.py）
3. request_human_input：pending 落盘 → resolve_human_input 应答返回；
   超时路径返回 None（timeout=0.1s）
"""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from story_engine.kernel import Kernel
from story_engine.kernel.actor import HumanResponse
from story_engine.kernel.embedding import Embedder
from story_engine.hitl import HumanInput, InterventionRouter, TrainingPipeline


class _KernelBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kernel = Kernel(self.tmp, plugin_dir=None,
                             embedder=Embedder(mode="dummy"))

    def tearDown(self):
        try:
            self.kernel.close()
        except Exception:
            pass

    def _read_jsonl(self, name: str) -> list[dict]:
        path = Path(self.tmp) / "training_data" / name
        if not path.exists():
            return []
        return [json.loads(line) for line in
                path.read_text(encoding="utf-8").splitlines() if line.strip()]


class TestTrainingPipeline(_KernelBase):
    def setUp(self):
        super().setUp()
        self.pipeline = TrainingPipeline(self.kernel, self.tmp)
        self.router = InterventionRouter(self.kernel, pipeline=self.pipeline)

    def test_high_quality_evaluation_registers_skill_and_preference(self):
        r = self.router.route(HumanInput(
            type="evaluation", reason="这段好",
            payload={"chapter": 1, "quality": "high", "note": "节奏紧凑"}))
        self.assertTrue(r.ok)

        # 技能注册（实际路径：Registry 支持 story.skill 动态注册）
        skills = self.kernel.registry.list_plugins("story.skill")["story.skill"]
        self.assertEqual(len(skills), 1)
        self.assertTrue(skills[0].startswith("author_skill_"))
        params = self.kernel.registry.get_params("story.skill", skills[0])
        self.assertEqual(params["source_intervention"], r.event_id)
        self.assertIn("节奏紧凑", params["pattern"])
        self.assertTrue(params["placeholder"])  # 占位技能，非真实训练

        # preferences.jsonl 落盘一行
        prefs = self._read_jsonl("preferences.jsonl")
        self.assertEqual(len(prefs), 1)
        self.assertEqual(prefs[0]["chapter"], 1)
        self.assertEqual(prefs[0]["quality"], "high")
        self.assertEqual(prefs[0]["note"], "节奏紧凑")
        self.assertEqual(prefs[0]["intervention_event"], r.event_id)

        # pipeline 异常不向 router 传播（容错策略：pipeline 内吞掉）
        broken = TrainingPipeline(None, self.tmp)  # kernel=None → 注册必炸
        router2 = InterventionRouter(self.kernel, pipeline=broken)
        r2 = router2.route(HumanInput(
            type="evaluation",
            payload={"chapter": 2, "quality": "high", "note": "x"}))
        self.assertTrue(r2.ok)

    def test_textual_records_style(self):
        # 直接喂 pipeline 验证通路（router→pipeline 的 textual 接线由 P5.10 补齐）
        self.pipeline.process_intervention({
            "type": "textual", "chapter": 2,
            "before": "他走了进去。", "after": "他推门，闪身而入。",
            "reason": "描写太干",
        })
        styles = self._read_jsonl("style.jsonl")
        self.assertEqual(len(styles), 1)
        self.assertEqual(styles[0]["chapter"], 2)
        self.assertEqual(styles[0]["before"], "他走了进去。")
        self.assertEqual(styles[0]["after"], "他推门，闪身而入。")
        self.assertEqual(styles[0]["reason"], "描写太干")


class TestRequestHumanInput(_KernelBase):
    def _requests(self) -> list[dict]:
        path = Path(self.tmp) / "hitl_requests.json"
        return json.loads(path.read_text(encoding="utf-8")) \
            if path.exists() else []

    def test_pending_resolve_and_timeout(self):
        async def run():
            # resolve 路径：另一协程读 pending 记录后写入应答
            async def resolve_later():
                await asyncio.sleep(0.05)
                req = self._requests()[0]
                self.assertEqual(req["status"], "pending")  # pending 已落盘
                ok = self.kernel.resolve_human_input(
                    req["request_id"], {"choice": "A"})
                self.assertTrue(ok)

            task = asyncio.create_task(resolve_later())
            resp = await self.kernel.request_human_input(
                "选哪个走向？", {"options": ["A", "B"]}, timeout=2.0)
            await task
            self.assertIsInstance(resp, HumanResponse)
            self.assertTrue(resp.accepted)
            self.assertEqual(resp.payload, {"choice": "A"})
            self.assertEqual(self._requests()[0]["status"], "answered")

            # 超时路径：timeout=0.1s → None，记录标 timeout
            resp2 = await self.kernel.request_human_input(
                "没人答", {}, timeout=0.1)
            self.assertIsNone(resp2)
            self.assertEqual(self._requests()[1]["status"], "timeout")

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
