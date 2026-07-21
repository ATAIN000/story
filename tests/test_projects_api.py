"""P10.1 测试：GET /api/projects + project.json 老项目迁移补写
P10.2 测试：POST /api/projects/open + gacha confirm project_name 扩展
P10.3 测试：GET /api/projects/{name}/export（backup 一致快照 zip）

核心用例（任务卡 ≤3）：
1. 列表含 yupei（真实 data/projects 扫描）：首次调用后 project.json 被补写，
   genre/culture 与补写口径一致（当前项目取 engine，其余取 env/内置默认），
   响应键齐全且与文件一致。
2. chapter_count/head_tick：造 2 章记录项目（含 1 条 superseded）→ count=1；
   head_tick 从 sqlite heads 表只读取出。
3. 坏目录不崩：无 story.db 的目录被跳过；坏 chapters.json/空 story.db →
   count=0/head_tick=0 且仍列出。
4. 双项目切换：建 alpha（非默认题材 isekai-romance×jianghu-martial，1 章）
   /beta（默认卡，0 章）→ open alpha → 返回 meta 正确 + 恢复 alpha 自身题材
   （engine.genre/culture 同步）+ /api/project 数据是 alpha 的；
   open 不存在/非法名 → 404。
5. confirm 带 project_name：确认后目录含 story.db + project.json（genre/
   culture/created_at/last_opened_at）+ 当前已切换。
6. confirm 重名 → 409、非法名 → 422；切换后 intervene/interventions 端点
   用新栈（介入记录随项目隔离）。
7. 导出：造小项目（events 表 3 行 + chapters.json + project.json +
   training_data）→ GET export → 200 + application/zip + zip 内含
   story.db（可 sqlite 打开且 events 数一致）/chapters.json/project.json/
   training_data/**。
8. 导出 404：项目不存在 / 非法名 / 目录无 story.db。
"""
import io
import json
import os
import sqlite3
import tempfile
import unittest
import zipfile
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

    def test_7_export_zip_consistent_snapshot(self):
        """P10.3：导出 zip 含 backup 快照 story.db + 附带文件，可解压复用。"""
        with tempfile.TemporaryDirectory() as root:
            proj = _make_project(Path(root), "exp1")
            conn = sqlite3.connect(proj / "story.db")
            conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY,"
                         " payload TEXT)")
            conn.executemany("INSERT INTO events (payload) VALUES (?)",
                             [("a",), ("b",), ("c",)])
            conn.commit()
            conn.close()
            (proj / "chapters.json").write_text(
                json.dumps([{"chapter": 1}]), encoding="utf-8")
            (proj / "project.json").write_text(
                json.dumps({"name": "exp1", "genre": "mystery"}),
                encoding="utf-8")
            training = proj / "training_data"
            training.mkdir()
            (training / "preferences.jsonl").write_text(
                '{"x": 1}\n', encoding="utf-8")
            r = self._with_projects_root(
                Path(root),
                lambda: self.client.get("/api/projects/exp1/export"))
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.headers["content-type"], "application/zip")
            self.assertIn("exp1-story.zip",
                          r.headers.get("content-disposition", ""))
            with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
                names = set(zf.namelist())
                for arc in ("story.db", "chapters.json", "project.json",
                            "training_data/preferences.jsonl"):
                    self.assertIn(arc, names)
                self.assertEqual(json.loads(zf.read("chapters.json")),
                                 [{"chapter": 1}])
                self.assertEqual(
                    json.loads(zf.read("project.json"))["name"], "exp1")
                # backup 快照：可 sqlite 打开且 events 行数与源库一致
                with tempfile.TemporaryDirectory() as ex:
                    zf.extract("story.db", ex)
                    conn = sqlite3.connect(Path(ex) / "story.db")
                    try:
                        n = conn.execute(
                            "SELECT COUNT(*) FROM events").fetchone()[0]
                    finally:
                        conn.close()
                self.assertEqual(n, 3)

    def test_8_export_404(self):
        """P10.3：项目不存在 / 非法名 / 目录无 story.db → 一律 404。"""
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "emptydir").mkdir()  # 有目录无 story.db
            def _get(n):
                return self._with_projects_root(
                    Path(root),
                    lambda: self.client.get(f"/api/projects/{n}/export"))
            self.assertEqual(_get("nope").status_code, 404)
            self.assertEqual(_get("emptydir").status_code, 404)
            self.assertEqual(_get("bad!name").status_code, 404)


class TestProjectOpenAndConfirmSwitch(unittest.TestCase):
    """P10.2：open 切换 + confirm project_name（临时目录，不污染真实项目）。

    backend 单例全进程共享：每个用例 finally 必须切回原项目目录（兼 close
    临时项目 kernel——Windows 文件锁下 TemporaryDirectory 才能清理）并还原
    PROJECTS_ROOT/题材，否则波及字母序靠后的 backend 用例。"""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(backend.app)
        cls.orig_dir = Path(backend.engine.project_dir)
        cls.orig_genre = backend.engine.genre.name
        cls.orig_culture = backend.engine.culture.name
        cls.saved_root = backend.PROJECTS_ROOT

    def _restore_backend(self):
        """切回共享 backend 项目并还原扫描根/题材（finally 中调用）。"""
        backend.PROJECTS_ROOT = self.saved_root
        backend._switch_to(self.orig_dir)
        self.client.post("/api/project/init",
                         json={"genre": self.orig_genre,
                               "culture": self.orig_culture})

    @staticmethod
    def _card(project_name=None, genre="mystery",
              culture="confucian_officialdom"):
        card = {"mode": "library",
                "genre": {"name": genre, "source": "library", "desc": "d"},
                "culture": {"name": culture},
                "archetype": {"name": ""}, "rule_packs": [], "note": None}
        if project_name is not None:
            card["project_name"] = project_name
        return card

    def test_4_open_switches_between_projects_and_404(self):
        with tempfile.TemporaryDirectory() as root:
            backend.PROJECTS_ROOT = Path(root)
            try:
                # alpha：非默认题材/文化（isekai-romance×jianghu-martial，区别于
                # env 默认 mystery×confucian_officialdom，open 恢复题材才可判别；
                # 不选 romance：其 world_rules 引用 WORLD_FACT_TYPES 未声明的事实，
                # 生成即 KeyError——既有缺陷，本任务不修）
                # 确认建项目并生成 1 章；beta：默认卡，0 章
                r = self.client.post("/api/gacha/confirm",
                                     json=self._card("alpha",
                                                     genre="isekai-romance",
                                                     culture="jianghu-martial"))
                self.assertEqual(r.status_code, 200, r.text)
                r = self.client.post("/api/project/generate")
                self.assertEqual(r.status_code, 200, r.text)
                r = self.client.post("/api/gacha/confirm",
                                     json=self._card("beta"))
                self.assertEqual(r.status_code, 200, r.text)
                # 当前在 beta；open alpha → meta 正确 + 恢复 alpha 自身题材
                # （非 env 默认）+ 当前数据是 alpha 的
                r = self.client.post("/api/projects/open",
                                     json={"name": "alpha"})
                self.assertEqual(r.status_code, 200, r.text)
                body = r.json()
                self.assertTrue(body["ok"])
                self.assertEqual(body["project"]["project"], "alpha")
                self.assertEqual(body["project"]["genre"], "isekai-romance")
                self.assertEqual(body["project"]["culture"], "jianghu-martial")
                self.assertEqual(body["project"]["chapter_count"], 1)
                # engine 单例同步恢复（后续 generate 用 alpha 题材而非 env 默认）
                self.assertEqual(backend.engine.genre.name, "isekai-romance")
                self.assertEqual(backend.engine.culture.name, "jianghu-martial")
                snap = self.client.get("/api/project").json()
                self.assertEqual(snap["meta"]["project"], "alpha")
                self.assertEqual(snap["meta"]["genre"], "isekai-romance")
                self.assertEqual(len(snap["chapters"]), 1)
                # open 不存在 → 404；路径穿越式非法名同样 404（不泄露目录结构）
                r = self.client.post("/api/projects/open",
                                     json={"name": "nope"})
                self.assertEqual(r.status_code, 404)
                r = self.client.post("/api/projects/open",
                                     json={"name": "../alpha"})
                self.assertEqual(r.status_code, 404)
            finally:
                self._restore_backend()

    def test_5_confirm_with_project_name_creates_switches_and_writes_meta(self):
        with tempfile.TemporaryDirectory() as root:
            backend.PROJECTS_ROOT = Path(root)
            try:
                r = self.client.post("/api/gacha/confirm",
                                     json=self._card("gamma"))
                self.assertEqual(r.status_code, 200, r.text)
                body = r.json()
                self.assertTrue(body["ok"])
                self.assertFalse(body["persisted"])  # library 卡不落盘
                self.assertEqual(body["project"],
                                 {"name": "gamma", "genre": "mystery",
                                  "culture": "confucian_officialdom"})
                proj = Path(root) / "gamma"
                self.assertTrue((proj / "story.db").exists())
                meta = json.loads(
                    (proj / "project.json").read_text(encoding="utf-8"))
                self.assertEqual(meta["name"], "gamma")
                self.assertEqual(meta["genre"], "mystery")
                self.assertEqual(meta["culture"], "confucian_officialdom")
                for k in ("created_at", "last_opened_at"):
                    self.assertTrue(meta.get(k))
                # 当前已切换（模块级 engine 与端点同栈）
                self.assertEqual(backend.engine.project_dir, proj)
                snap = self.client.get("/api/project").json()
                self.assertEqual(snap["meta"]["project"], "gamma")
                self.assertEqual(snap["meta"]["genre"], "mystery")
            finally:
                self._restore_backend()

    def test_6_confirm_existing_409_and_endpoints_use_new_stack(self):
        with tempfile.TemporaryDirectory() as root:
            backend.PROJECTS_ROOT = Path(root)
            try:
                r = self.client.post("/api/gacha/confirm",
                                     json=self._card("delta"))
                self.assertEqual(r.status_code, 200, r.text)
                # 重名（目录已含 story.db）→ 409，且当前项目不被切走
                r = self.client.post("/api/gacha/confirm",
                                     json=self._card("delta"))
                self.assertEqual(r.status_code, 409, r.text)
                self.assertIn("已存在", r.json()["detail"])
                self.assertEqual(backend.engine.project_dir,
                                 Path(root) / "delta")
                # 非法项目名 → 422
                r = self.client.post("/api/gacha/confirm",
                                     json=self._card("bad name!"))
                self.assertEqual(r.status_code, 422, r.text)
                # 新栈抽查（intervene→router/pipeline，interventions→kernel）：
                # delta 留 1 条介入；epsilon 0 条；open 回 delta 又见 1 条
                r = self.client.post("/api/intervene", json={
                    "type": "intent",
                    "payload": {"goal_update": "加快节奏"}, "reason": "t"})
                self.assertEqual(r.status_code, 200, r.text)
                self.assertTrue(r.json()["ok"])
                self.assertEqual(
                    len(self.client.get("/api/interventions").json()), 1)
                r = self.client.post("/api/gacha/confirm",
                                     json=self._card("epsilon"))
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(
                    self.client.get("/api/interventions").json(), [])
                r = self.client.post("/api/projects/open",
                                     json={"name": "delta"})
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(
                    len(self.client.get("/api/interventions").json()), 1)
            finally:
                self._restore_backend()


if __name__ == "__main__":
    unittest.main()
