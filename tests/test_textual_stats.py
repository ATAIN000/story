"""P6.1 测试：textual 正文回写（B1）+ 训练统计端点（B5）

核心用例（用户指令：只保留核心，不穷举边界）：
1. textual 回写：剧本路径生成 1 章 → textual 介入（before 取自正文片段）
   → 章节正文已替换（其余字段不动）+ 事件在流 + message 标明正文已更新
2. before 未命中：事件照记、正文不变、message 注明仅留痕；rolled_back 章回绝
3. training/stats：受控 registry + 两个 jsonl → 计数正确 + recent_skills 结构
   + 空目录零值不崩；端点本身经 TestClient 走通
"""
import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from conftest import import_backend_main
from story_engine.engine import StoryEngine
from story_engine.hitl import HumanInput, InterventionRouter
from story_engine.kernel.registry import ExtensionRegistry, PluginManifest

backend = import_backend_main()


class TestTextualWriteback(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.engine = StoryEngine(self.tmp)  # 剧本路径（SCRIPTED_DEMO=1）
        self.rec = asyncio.run(self.engine.generate_chapter())
        self.router = InterventionRouter(
            self.engine.kernel,
            textual_apply_fn=self.engine.update_chapter_text)

    def tearDown(self):
        try:
            self.engine.kernel.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _chapter_record(self, chapter: int) -> dict:
        chapters = json.loads(
            (Path(self.tmp) / "chapters.json").read_text(encoding="utf-8"))
        return next(c for c in chapters if c["chapter"] == chapter)

    def _intervention_events(self) -> list[dict]:
        return [e for e in self.engine.kernel.query_world("all_events")
                if e["event_type"] == "author_intervention"]

    def test_1_textual_rewrites_chapter_text(self):
        old_text = self.rec["final"]["text"]
        before = old_text[20:46]
        after = "【作者改字】"
        r = self.router.route(HumanInput(
            type="textual", reason="润色",
            payload={"chapter": 1, "before": before, "after": after}))
        self.assertTrue(r.ok)
        self.assertFalse(r.regenerated)
        self.assertIn("正文已更新", r.message)

        # chapters.json 正文已替换（首次出现处），其余字段不动
        ch = self._chapter_record(1)
        self.assertEqual(ch["final"]["text"],
                         old_text.replace(before, after, 1))
        self.assertEqual(ch["title"], self.rec["title"])
        self.assertEqual(ch["tick_range"], self.rec["tick_range"])

        # 事件照记（介入即事件，可回放）
        events = self._intervention_events()
        self.assertEqual(len(events), 1)
        p = events[0]["payload"]
        self.assertEqual(p["type"], "textual")
        self.assertEqual(p["chapter"], 1)
        self.assertEqual(p["before"], before)
        self.assertEqual(p["after"], after)

    def test_2_miss_records_only_and_rolled_back_rejected(self):
        old_text = self._chapter_record(1)["final"]["text"]

        # before 未命中：事件照记、正文不变、message 注明仅留痕
        r = self.router.route(HumanInput(
            type="textual", reason="润色",
            payload={"chapter": 1, "before": "正文中不存在的片段", "after": "x"}))
        self.assertTrue(r.ok)
        self.assertIn("仅留痕", r.message)
        self.assertEqual(self._chapter_record(1)["final"]["text"], old_text)
        self.assertEqual(len(self._intervention_events()), 1)

        # rolled_back 章（回滚到 0 → 章标 superseded）→ 回绝，不记新事件
        self.engine.rollback(0)
        r2 = self.router.route(HumanInput(
            type="textual", reason="润色",
            payload={"chapter": 1, "before": old_text[20:46], "after": "x"}))
        self.assertFalse(r2.ok)
        self.assertIsNone(r2.event_id)
        self.assertIn("rolled_back", r2.message)
        self.assertEqual(len(self._intervention_events()), 1)  # 未新增


class TestTrainingStats(unittest.TestCase):
    def test_3_stats_counts_recent_skills_and_zero(self):
        # 端点走通（模块单例，数据值不限定，只验结构与类型）
        client = TestClient(backend.app)
        resp = client.get("/api/training/stats")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(
            set(body), {"skills", "preferences", "style", "recent_skills"})
        self.assertIsInstance(body["skills"], int)
        self.assertIsInstance(body["recent_skills"], list)

        # 纯逻辑受控验证：2 个 story.skill + preferences 2 行 + style 3 行
        reg = ExtensionRegistry()
        for i in (1, 2):
            reg.register(PluginManifest(
                name=f"author_skill_t{i}", extension_point="story.skill",
                params={"source_intervention": f"ev{i}",
                        "created_at": f"2026-07-20T00:00:0{i}"}))
        tmp = Path(tempfile.mkdtemp())
        try:
            tdir = tmp / "training_data"
            tdir.mkdir()
            (tdir / "preferences.jsonl").write_text(
                '{"chapter": 1}\n{"chapter": 2}\n', encoding="utf-8")
            (tdir / "style.jsonl").write_text(
                '{"chapter": 1}\n' * 3, encoding="utf-8")
            snap = backend.routers.project.training_stats_snapshot(reg, tdir)
            self.assertEqual(snap["skills"], 2)
            self.assertEqual(snap["preferences"], 2)
            self.assertEqual(snap["style"], 3)
            # recent_skills：created_at 倒序，三键齐全
            self.assertEqual(len(snap["recent_skills"]), 2)
            first = snap["recent_skills"][0]
            self.assertEqual(first, {
                "name": "author_skill_t2",
                "source_intervention": "ev2",
                "created_at": "2026-07-20T00:00:02"})

            # 空目录/空 registry：零值不崩
            zero = backend.routers.project.training_stats_snapshot(
                ExtensionRegistry(), tmp / "不存在")
            self.assertEqual(zero, {"skills": 0, "preferences": 0,
                                    "style": 0, "recent_skills": []})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
