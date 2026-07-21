"""P10.1 测试：GET /api/projects + project.json 老项目迁移补写

核心用例（任务卡 ≤3）：
1. 列表含 yupei（真实 data/projects 扫描）：首次调用后 project.json 被补写，
   genre/culture 与补写口径一致（当前项目取 engine，其余取 env/内置默认），
   响应键齐全且与文件一致。
2. chapter_count/head_tick：造 2 章记录项目（含 1 条 superseded）→ count=1；
   head_tick 从 sqlite heads 表只读取出。
3. 坏目录不崩：无 story.db 的目录被跳过；坏 chapters.json/空 story.db →
   count=0/head_tick=0 且仍列出。
"""
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from conftest import import_backend_main

backend = import_backend_main()


def _make_project(root: Path, name: str) -> Path:
    """造最小项目目录：空 story.db（由调用方按需建表）"""
    d = root / name
    d.mkdir()
    (d / "story.db").write_bytes(b"")
    return d


class TestProjectsApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(backend.app)

    def _with_projects_root(self, root: Path, fn):
        """临时把扫描根指到测试目录（模块级常量，用完还原）"""
        saved = backend.PROJECTS_ROOT
        backend.PROJECTS_ROOT = root
        try:
            return fn()
        finally:
            backend.PROJECTS_ROOT = saved

    def test_1_list_contains_yupei_and_backfills_project_json(self):
        meta_path = backend.PROJECTS_ROOT / "yupei" / "project.json"
        pre_existed = meta_path.exists()
        r = self.client.get("/api/projects")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        names = [p["name"] for p in body]
        self.assertIn("yupei", names)
        yupei = next(p for p in body if p["name"] == "yupei")
        # 响应键齐全
        for k in ("name", "genre", "culture", "chapter_count",
                  "head_tick", "last_opened_at", "current"):
            self.assertIn(k, yupei)
        # 补写已发生：project.json 存在，genre/culture 非空且响应与文件一致
        self.assertTrue(meta_path.exists())
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        for k in ("name", "genre", "culture", "created_at", "last_opened_at"):
            self.assertIn(k, meta)
        self.assertEqual(meta["name"], "yupei")
        self.assertEqual(yupei["genre"], meta["genre"])
        self.assertEqual(yupei["culture"], meta["culture"])
        # 首次补写（文件原先不存在）时口径：yupei 非当前项目（测试单例项目
        # 目录是临时目录）→ env/内置默认；是当前项目 → engine.genre/culture
        if not pre_existed:
            if backend.engine.project_dir.name == "yupei":
                self.assertEqual(meta["genre"], backend.engine.genre.name)
                self.assertEqual(meta["culture"], backend.engine.culture.name)
            else:
                self.assertEqual(
                    meta["genre"],
                    os.environ.get("STORY_ENGINE_GENRE", "mystery"))
                self.assertEqual(
                    meta["culture"],
                    os.environ.get("STORY_ENGINE_CULTURE",
                                   "confucian_officialdom"))

    def test_2_chapter_count_and_head_tick(self):
        with tempfile.TemporaryDirectory() as root:
            proj = _make_project(Path(root), "demo")
            # heads 表：main → 42
            conn = sqlite3.connect(proj / "story.db")
            conn.execute("CREATE TABLE heads (branch_id TEXT PRIMARY KEY,"
                         " head_tick INTEGER)")
            conn.execute("INSERT INTO heads VALUES ('main', 42)")
            conn.commit()
            conn.close()
            # 2 条章记录，1 条 superseded → count=1
            (proj / "chapters.json").write_text(json.dumps([
                {"chapter": 1, "superseded": True},
                {"chapter": 2},
            ]), encoding="utf-8")
            items = self._with_projects_root(
                Path(root), lambda: self.client.get("/api/projects").json())
            self.assertEqual(len(items), 1)
            item = items[0]
            self.assertEqual(item["name"], "demo")
            self.assertEqual(item["chapter_count"], 1)
            self.assertEqual(item["head_tick"], 42)
            self.assertFalse(item["current"])
            # 缺 project.json → 列表时补写
            self.assertTrue((proj / "project.json").exists())

    def test_3_bad_dirs_skipped_or_zero_count(self):
        with tempfile.TemporaryDirectory() as root:
            # 无 story.db → 不是项目，跳过
            (Path(root) / "not_a_project").mkdir()
            # story.db 存在但为空文件（无 heads 表）+ chapters.json 损坏
            bad = _make_project(Path(root), "badchapters")
            (bad / "chapters.json").write_text("{not json", encoding="utf-8")
            r = self._with_projects_root(
                Path(root), lambda: self.client.get("/api/projects"))
            self.assertEqual(r.status_code, 200)
            items = r.json()
            self.assertEqual([p["name"] for p in items], ["badchapters"])
            self.assertEqual(items[0]["chapter_count"], 0)
            self.assertEqual(items[0]["head_tick"], 0)


if __name__ == "__main__":
    unittest.main()
