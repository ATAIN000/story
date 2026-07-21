"""热修复测试：reset 原位清库（占用连接下也必须清干净）

根因：旧实现 kernel.close()+unlink(story.db)+重建——Windows 下任何占用
连接都会让 unlink 静默失败，造成「chapters 清空但旧事件全保留」的半重置
（抽卡开局实测：init 后旧 150 事件仍在，新章节编号延续、旧阵容延续）。
"""
import os
import sqlite3
import tempfile
import unittest

from story_engine.engine import StoryEngine
from story_engine.types import WorldEvent


def _ev(tick: int, agent: str) -> WorldEvent:
    return WorldEvent(
        event_id=f"e{tick}", event_type="character_action",
        timestamp="2026-07-21T00:00:00", world_tick=tick, branch_id="main",
        payload={"agent": agent, "action": "测试", "effects": {}})


class TestResetInPlace(unittest.TestCase):
    def test_reset_clears_events_even_when_db_occupied(self):
        with tempfile.TemporaryDirectory() as d:
            eng = StoryEngine(d)
            eng.kernel.commit_event(_ev(1, "包拯"))
            self.assertGreaterEqual(eng.kernel.query_world("head_tick"), 1)
            # 模拟占用连接（actor 任务/第二读者未及时关闭的场景）
            leak = sqlite3.connect(os.path.join(d, "story.db"), check_same_thread=False)
            leak.execute("PRAGMA journal_mode=WAL")
            try:
                eng.reset()
            finally:
                leak.close()
            # 事件/章节/head 全部清零（旧实现此处会残留全部事件）
            self.assertEqual(eng.kernel.query_world("head_tick"), 0)
            self.assertEqual(eng._read_chapters(), [])
            conn = sqlite3.connect(os.path.join(d, "story.db"))
            n = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            conn.close()
            self.assertEqual(n, 0)
            # 重置后 store 仍可用，可继续正常写入
            eng.kernel.commit_event(_ev(1, "展昭"))
            self.assertEqual(eng.kernel.query_world("head_tick"), 1)
            eng.kernel.close()

    def test_memory_banks_cleared(self):
        import asyncio

        with tempfile.TemporaryDirectory() as d:
            eng = StoryEngine(d)
            banks = eng.kernel._ensure_memory_banks()
            asyncio.run(banks.add("玉佩失窃", bank="working_set", agent_id="包拯"))
            before = banks._conn.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0]
            self.assertGreaterEqual(before, 1)
            eng.reset()
            after = banks._conn.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0]
            self.assertEqual(after, 0)
            eng.kernel.close()


if __name__ == "__main__":
    unittest.main()
