"""P10.1 测试：GET /api/projects + project.json 老项目迁移补写
P10.2 测试：POST /api/projects/open + gacha confirm project_name 扩展
P10.3 测试：GET /api/projects/{name}/export（backup 一致快照 zip）
P10.6 测试：中文项目名（confirm/open/export RFC5987）+ 项目导入 + 名校验安全面

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
9. 中文项目名（P10.6）：confirm 中文名创建成功 → open 中文名成功 →
   导出 content-disposition 走 RFC5987 filename*（quote 后的中文名不乱码）。
10. 导入（P10.6）：合法 zip（story.db + project.json + chapters.json）→
    导入成功 + 项目可 open + 重名 409；含 ../evil 条目 → 422 且零落盘；
    缺 story.db → 422。
11. 名校验安全面（P10.6）：validate_project_name 单元断言（中文放行；
    保留名 CON/aux、分隔符、穿越、首尾空白/点、超长、控制字符全拒）+
    confirm 带保留名/分隔符 → 422。
"""
import io
import json
import os
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from urllib.parse import quote

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
        saved = backend.deps.PROJECTS_ROOT
        backend.deps.PROJECTS_ROOT = root
        try:
            return fn()
        finally:
            backend.deps.PROJECTS_ROOT = saved

    def test_1_list_contains_yupei_and_backfills_project_json(self):
        meta_path = backend.deps.PROJECTS_ROOT / "yupei" / "project.json"
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
            if backend.deps.engine.project_dir.name == "yupei":
                self.assertEqual(meta["genre"], backend.deps.engine.genre.name)
                self.assertEqual(meta["culture"], backend.deps.engine.culture.name)
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
    """P10.2：open 切换 + P20 session confirm project_name（临时目录，不污染真实项目）。

    backend 单例全进程共享：每个用例 finally 必须切回原项目目录并还原
    PROJECTS_ROOT/题材，否则波及字母序靠后的 backend 用例。"""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(backend.app)
        cls.orig_dir = Path(backend.deps.engine.project_dir)
        cls.orig_genre = backend.deps.engine.genre.name
        cls.orig_culture = backend.deps.engine.culture.name
        cls.saved_root = backend.deps.PROJECTS_ROOT

    def _restore_backend(self):
        """切回共享 backend 项目并还原扫描根/题材（finally 中调用）。"""
        backend.deps.PROJECTS_ROOT = self.saved_root
        backend.helpers._switch_to(self.orig_dir)
        self.client.post("/api/project/init",
                         json={"genre": self.orig_genre,
                               "culture": self.orig_culture})

    def _session_confirm(self, project_name, genre="mystery"):
        """P20: begin → confirm 走通新 session 流程。"""
        r = self.client.post("/api/gacha/begin", json={"genre_name": genre})
        assert r.status_code == 200, r.text
        sid = r.json()["session_id"]
        r2 = self.client.post(f"/api/gacha/{sid}/confirm",
                              json={"project_name": project_name})
        return r2

    def test_4_open_switches_between_projects_and_404(self):
        with tempfile.TemporaryDirectory() as root:
            backend.deps.PROJECTS_ROOT = Path(root)
            try:
                # alpha：非默认题材（isekai-romance）
                r = self._session_confirm("alpha", genre="isekai-romance")
                self.assertEqual(r.status_code, 200, r.text)
                r = self.client.post("/api/project/generate")
                self.assertEqual(r.status_code, 200, r.text)
                # beta：默认题材
                r = self._session_confirm("beta")
                self.assertEqual(r.status_code, 200, r.text)
                # 当前在 beta；open alpha → meta 正确 + 恢复 alpha 自身题材
                r = self.client.post("/api/projects/open",
                                     json={"name": "alpha"})
                self.assertEqual(r.status_code, 200, r.text)
                body = r.json()
                self.assertTrue(body["ok"])
                self.assertEqual(body["project"]["project"], "alpha")
                self.assertEqual(body["project"]["genre"], "isekai-romance")
                self.assertEqual(body["project"]["chapter_count"], 1)
                # engine 单例同步恢复
                self.assertEqual(backend.deps.engine.genre.name, "isekai-romance")
                snap = self.client.get("/api/project").json()
                self.assertEqual(snap["meta"]["project"], "alpha")
                self.assertEqual(len(snap["chapters"]), 1)
                # open 不存在 → 404
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
            backend.deps.PROJECTS_ROOT = Path(root)
            try:
                r = self._session_confirm("gamma")
                self.assertEqual(r.status_code, 200, r.text)
                body = r.json()
                self.assertTrue(body["ok"])
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
                # 当前已切换
                self.assertEqual(backend.deps.engine.project_dir, proj)
                snap = self.client.get("/api/project").json()
                self.assertEqual(snap["meta"]["project"], "gamma")
                self.assertEqual(snap["meta"]["genre"], "mystery")
            finally:
                self._restore_backend()

    def test_6_confirm_existing_409_and_endpoints_use_new_stack(self):
        with tempfile.TemporaryDirectory() as root:
            backend.deps.PROJECTS_ROOT = Path(root)
            try:
                r = self._session_confirm("delta")
                self.assertEqual(r.status_code, 200, r.text)
                # 重名（目录已含 story.db）→ 409
                r = self._session_confirm("delta")
                self.assertEqual(r.status_code, 409, r.text)
                self.assertIn("已存在", r.json()["detail"])
                self.assertEqual(backend.deps.engine.project_dir,
                                 Path(root) / "delta")
                # 非法项目名 → 422
                r2 = self.client.post("/api/gacha/begin",
                                      json={"genre_name": "mystery"})
                sid = r2.json()["session_id"]
                r = self.client.post(f"/api/gacha/{sid}/confirm",
                                     json={"project_name": "bad name!"})
                self.assertEqual(r.status_code, 422, r.text)
                # 新栈抽查（intervene→router/pipeline，interventions→kernel）
                r = self.client.post("/api/intervene", json={
                    "type": "intent",
                    "payload": {"goal_update": "加快节奏"}, "reason": "t"})
                self.assertEqual(r.status_code, 200, r.text)
                self.assertTrue(r.json()["ok"])
                self.assertEqual(
                    len(self.client.get("/api/interventions").json()), 1)
                r = self._session_confirm("epsilon")
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


class TestChineseNameAndImport(unittest.TestCase):
    """P10.6：中文项目名 + 项目导入 + 名校验安全面（临时目录，纪律同
    TestProjectOpenAndConfirmSwitch：finally 切回原项目并还原 PROJECTS_ROOT）。"""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(backend.app)
        cls.orig_dir = Path(backend.deps.engine.project_dir)
        cls.orig_genre = backend.deps.engine.genre.name
        cls.orig_culture = backend.deps.engine.culture.name
        cls.saved_root = backend.deps.PROJECTS_ROOT

    def _restore_backend(self):
        backend.deps.PROJECTS_ROOT = self.saved_root
        backend.helpers._switch_to(self.orig_dir)
        self.client.post("/api/project/init",
                         json={"genre": self.orig_genre,
                               "culture": self.orig_culture})

    def _session_confirm(self, project_name, genre="mystery"):
        """P20: begin → confirm。"""
        r = self.client.post("/api/gacha/begin", json={"genre_name": genre})
        assert r.status_code == 200, r.text
        sid = r.json()["session_id"]
        return self.client.post(f"/api/gacha/{sid}/confirm",
                                json={"project_name": project_name})

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

    @staticmethod
    def _zip_bytes(entries: dict) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for arc, data in entries.items():
                zf.writestr(arc, data)
        return buf.getvalue()

    def _post_import(self, filename: str, payload: bytes):
        return self.client.post(
            "/api/projects/import",
            files={"file": (filename, payload, "application/zip")})

    def test_9_chinese_project_name_confirm_open_export(self):
        """中文名全链路：session confirm 建项目 → open 切换 → 导出 zip RFC5987。"""
        with tempfile.TemporaryDirectory() as root:
            backend.deps.PROJECTS_ROOT = Path(root)
            try:
                name = "末日情缘一号"
                r = self._session_confirm(name)
                self.assertEqual(r.status_code, 200, r.text)
                self.assertTrue((Path(root) / name / "story.db").exists())
                # open 中文名 → 200，meta 项目名一致
                r = self.client.post("/api/projects/open",
                                     json={"name": name})
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(r.json()["project"]["project"], name)
                # 导出中文名
                r = self.client.get(f"/api/projects/{quote(name)}/export")
                self.assertEqual(r.status_code, 200, r.text)
                cd = r.headers.get("content-disposition", "")
                self.assertIn("filename*=utf-8''", cd)
                self.assertIn(quote(f"{name}-story.zip"), cd)
                with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
                    self.assertIn("story.db", zf.namelist())
            finally:
                self._restore_backend()

    def test_10_import_project_zip(self):
        """导入：合法 zip → 200 + 可 open + 重名 409；穿越/缺 story.db → 422。"""
        with tempfile.TemporaryDirectory() as root:
            backend.deps.PROJECTS_ROOT = Path(root)
            try:
                payload = self._zip_bytes({
                    "story.db": b"",
                    "project.json": json.dumps(
                        {"name": "imported-01", "genre": "mystery",
                         "culture": "confucian_officialdom"}),
                    "chapters.json": "[]",
                })
                r = self._post_import("imported-01-story.zip", payload)
                self.assertEqual(r.status_code, 200, r.text)
                body = r.json()
                self.assertTrue(body["ok"])
                self.assertEqual(body["name"], "imported-01")
                self.assertEqual(body["genre"], "mystery")
                proj = Path(root) / "imported-01"
                self.assertTrue((proj / "story.db").exists())
                self.assertTrue((proj / "chapters.json").exists())
                # 导入的项目可 open（整栈切换成功）
                r = self.client.post("/api/projects/open",
                                     json={"name": "imported-01"})
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(r.json()["project"]["project"], "imported-01")
                # 重名（目录已存在且非空）→ 409
                r = self._post_import("imported-01.zip", payload)
                self.assertEqual(r.status_code, 409, r.text)
                # 含 ../evil 穿越条目 → 422，且零落盘
                evil = self._zip_bytes(
                    {"story.db": b"", "../evil.txt": b"x"})
                r = self._post_import("evil.zip", evil)
                self.assertEqual(r.status_code, 422, r.text)
                self.assertFalse((Path(root) / "evil").exists())
                self.assertFalse((Path(root).parent / "evil.txt").exists())
                # 缺根级 story.db → 422
                nodb = self._zip_bytes({"chapters.json": "[]"})
                r = self._post_import("nodb.zip", nodb)
                self.assertEqual(r.status_code, 422, r.text)
                self.assertFalse((Path(root) / "nodb").exists())
            finally:
                self._restore_backend()

    def test_11_project_name_validation_security(self):
        """名校验：中文/空格/-/_ 放行；保留名/分隔符/穿越/首尾白点/超长/
        控制字符全拒；session confirm 集成面 422。"""
        v = backend.helpers.validate_project_name
        for ok in ("末日情缘一号", "alpha", "my story", "a-b_c", "故事 2 号",
                   "x" * 40):
            self.assertTrue(v(ok), ok)
        for bad in ("", "x" * 41, " lead", "trail ", ".dot", "dot.",
                    "a/b", "a\\b", "..", "a..b", "CON", "aux", "Com1",
                    "lpt9", "a\tb", "a\nb"):
            self.assertFalse(v(bad), bad)
        with tempfile.TemporaryDirectory() as root:
            backend.deps.PROJECTS_ROOT = Path(root)
            try:
                for bad in ("CON", "aux", "a/b"):
                    r1 = self.client.post("/api/gacha/begin",
                                          json={"genre_name": "mystery"})
                    sid = r1.json()["session_id"]
                    r = self.client.post(f"/api/gacha/{sid}/confirm",
                                         json={"project_name": bad})
                    self.assertEqual(r.status_code, 422, f"{bad}: {r.text}")
                # open 非法名仍一律 404（不泄露目录结构）
                r = self.client.post("/api/projects/open",
                                     json={"name": "a/b"})
                self.assertEqual(r.status_code, 404)
            finally:
                self._restore_backend()


if __name__ == "__main__":
    unittest.main()

# ---------- P25：Windows 打包支持 ----------

def test_projects_root_env_override():
    """deps.PROJECTS_ROOT 支持 STORY_ENGINE_PROJECTS_ROOT 覆盖（打包数据根外指）。"""
    import os
    import subprocess
    import sys
    import tempfile
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory() as td:
        env = dict(os.environ)
        env["STORY_ENGINE_PROJECTS_ROOT"] = "X:/story_custom_projects"
        env["STORY_ENGINE_PROJECT_DIR"] = td
        env["STORY_ENGINE_EMBED_MODE"] = "dummy"
        r = subprocess.run(
            [sys.executable, "-X", "utf8", "-c",
             "import backend.deps as d; print(d.PROJECTS_ROOT)"],
            capture_output=True, text=True, cwd=root, env=env, timeout=300)
    assert r.returncode == 0, r.stderr[-500:]
    assert "story_custom_projects" in r.stdout
