# tests/test_gacha.py
import os, unittest, yaml
from pathlib import Path
from story_engine.meta.genre_validator import validate_genre_pack

class TestGenreValidator(unittest.TestCase):
    def test_mystery_passes(self):
        d = yaml.safe_load(Path("story_engine/plugins/genres/mystery.yaml").read_text(encoding="utf-8"))
        self.assertEqual(validate_genre_pack(d), [])

    def test_broken_pack_reports_each_error(self):
        bad = {"name": "x", "extension_point": "story.genre", "params": {
            "tracks": [{"id": "A", "name": "n", "arc_type": "Serialized", "archetype": "Bad", "progress": 0.0, "last_touched": 0}],
            "beats_per_chapter": 4, "payoff_window": 2,
            "world_rules": [{"id": "r", "kind": "bool", "desc": "d", "expr": "not(alien_fact)"}],
            "evaluation_weights": {"情节连贯": 0.5},
        }}
        errors = validate_genre_pack(bad)
        self.assertTrue(any("tracks" in e and "≥3" in e for e in errors))       # 轨道不足
        self.assertTrue(any("archetype" in e for e in errors))                  # 非法原型
        self.assertTrue(any("main_track" in e for e in errors))                 # 缺 main_track
        self.assertTrue(any("prompt" in e for e in errors))                     # 缺 prompt 段
        self.assertTrue(any("phase_beats" in e for e in errors))                # 缺 phase_beats
        self.assertTrue(any("alien_fact" in e for e in errors))                 # 超词汇表
        self.assertTrue(any("evaluation_weights" in e for e in errors))         # 权重和≠1


class TestRegistryReload(unittest.TestCase):
    PLUGIN_DIR = Path(__file__).resolve().parent.parent / "story_engine" / "plugins"
    PROBE = PLUGIN_DIR / "genres" / "reload-probe.yaml"

    def tearDown(self):
        # 探针文件落在真实 plugins 目录，任何失败路径都必须清掉
        if self.PROBE.exists():
            self.PROBE.unlink()

    def test_reload_picks_up_new_genre(self):
        import tempfile
        from story_engine.kernel import Kernel
        with tempfile.TemporaryDirectory() as d:
            k = Kernel(d, plugin_dir=self.PLUGIN_DIR)
            try:
                before = set(k.registry.list_plugins("story.genre")["story.genre"])
                src = yaml.safe_load(
                    (self.PLUGIN_DIR / "genres" / "romance.yaml").read_text(encoding="utf-8"))
                src["name"] = "reload-probe"
                src["activation_events"] = ["on_genre:reload-probe"]
                self.PROBE.write_text(yaml.safe_dump(src, allow_unicode=True), encoding="utf-8")
                k.registry.reload()
                after = set(k.registry.list_plugins("story.genre")["story.genre"])
                self.assertIn("reload-probe", after)
                self.assertNotIn("reload-probe", before)
                self.assertTrue(before <= after)  # 重扫不丢既有题材
            finally:
                k.close()

    def test_reload_idempotent_without_changes(self):
        import tempfile
        from story_engine.kernel import Kernel
        with tempfile.TemporaryDirectory() as d:
            k = Kernel(d, plugin_dir=self.PLUGIN_DIR)
            try:
                before = k.registry.list_plugins()
                k.registry.reload()
                self.assertEqual(k.registry.list_plugins(), before)
            finally:
                k.close()


class TestGachaDraw(unittest.TestCase):
    PLUGIN_DIR = Path(__file__).resolve().parent.parent / "story_engine" / "plugins"

    def _kernel(self, tmpdir, **kw):
        from story_engine.kernel import Kernel
        return Kernel(tmpdir, plugin_dir=self.PLUGIN_DIR, **kw)

    def test_draw_library_returns_genre_list(self):
        import tempfile
        from story_engine.meta.gacha import draw_card
        with tempfile.TemporaryDirectory() as d:
            k = self._kernel(d)
            try:
                result = draw_card(k, None, "library", None)
                self.assertEqual(result["mode"], "library")
                self.assertIn("genres", result)
                self.assertTrue(result["genres"])
                # 每条题材卡结构完整
                for item in result["genres"]:
                    for key in ("name", "title", "desc", "culture_title", "cast_summary"):
                        self.assertIn(key, item)
            finally:
                k.close()

    def test_draw_mock_never_calls_llm(self):
        import tempfile
        from story_engine.kernel import LLMPool
        from story_engine.meta.gacha import draw_card
        calls = []

        async def fake(*a, **kw):
            calls.append(1)

        with tempfile.TemporaryDirectory() as d:
            # 显式 mock pool（不依赖环境变量）：synth 模式 + 注入 fake，
            # mock 短路在注入点之前 → 恒降级精简卡，零 LLM 调用（硬约束）
            k = self._kernel(d, llm_pool=LLMPool(mode="mock"))
            try:
                card = draw_card(k, fake, "synth", None)
                self.assertEqual(calls, [])
                self.assertTrue(card["note"])       # 降级说明
                self.assertNotIn("culture", card)   # P13：精简卡无 culture 栏
                self.assertNotIn("archetype", card)
                self.assertNotIn("rule_packs", card)
            finally:
                k.close()

    def test_draw_endpoint_mock_draw_never_calls_llm(self):
        # synth 端点 + mock 池：恒降级精简卡（硬约束：零 LLM 调用）。
        # 测试进程内 backend 单例按 .env 真实配置为非 mock（见 conftest），
        # 故临时把 pool.mode 拨回 mock 验证短路，finally 还原。
        from fastapi.testclient import TestClient
        from conftest import import_backend_main
        backend = import_backend_main()
        pool = backend.deps.engine.kernel.llm
        saved_mode = pool.mode
        pool.mode = "mock"
        try:
            assert pool.is_mock
            c = TestClient(backend.app)
            r = c.post("/api/gacha/synth")
            self.assertEqual(r.status_code, 200, r.text)
            card = r.json()
            self.assertNotIn("culture", card)   # P13：精简卡
            self.assertTrue(card["note"])
        finally:
            pool.mode = saved_mode

    def test_draw_endpoint_returns_genre_list(self):
        from fastapi.testclient import TestClient
        from conftest import import_backend_main
        backend = import_backend_main()
        c = TestClient(backend.app)
        r = c.get("/api/gacha/genres")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        # P22：浏览版端点——分页 items + facets（旧平铺 {mode, genres} 已废弃）
        self.assertGreaterEqual(body["total"], 300)
        self.assertIn("items", body)
        self.assertTrue(body["items"])
        self.assertIn("facets", body)
        # 每条题材卡结构完整
        for item in body["items"]:
            for key in ("id", "title", "vibe", "tier", "tags",
                        "default_culture", "recommended_presets"):
                self.assertIn(key, item)


# P8.4：可通过校验的合成包（VALID_YAML，供 synth 用例复用）
VALID_YAML = """manifest_version: 1
name: test-synth
extension_point: story.genre
activation_events: ["on_genre:test-synth"]
culture_bound: false
allowed_cultures: ["*"]
params:
  tracks:
    - {id: A, name: 主线, arc_type: Serialized, archetype: Quest, progress: 0.0, last_touched: 0}
    - {id: B, name: 副线, arc_type: Serialized, archetype: Monster, progress: 0.0, last_touched: 0}
    - {id: C, name: 主题, arc_type: Serialized, archetype: Rebirth, progress: 0.0, last_touched: 0}
  main_track: A
  theme_track: C
  beats_per_chapter: 4
  payoff_window: 2
  prompt:
    role: 测试作者
    setting: 测试设定
    characters: 甲、乙
    style: 800-1200字
    hard_requirements: [规则一]
  phase_beats:
    equilibrium: [{id: b1, desc: d, primitive: GoalFormation}]
    disruption: [{id: b2, desc: d, primitive: Conflict}]
    recognition: [{id: b3, desc: d, primitive: Revelation}]
    repair: [{id: b4, desc: d, primitive: Sacrifice}]
    new_equilibrium: [{id: b5, desc: d, primitive: Recognition}]
  evaluation_weights: {情节连贯: 1.0}
  active_critics: [plot_coherence]
"""


class TestGachaSynth(unittest.TestCase):
    """P8.4：synth 模式（LLM 合成 + 校验 + 重试 + 降级）。
    非 mock 路径用 LLMPool(mode="openai") + 伪 api_key 令 is_mock=False，
    LLM 调用全程走注入的 fake，不触网。"""

    PLUGIN_DIR = Path(__file__).resolve().parent.parent / "story_engine" / "plugins"

    def _kernel(self, tmpdir, **kw):
        from story_engine.kernel import Kernel
        return Kernel(tmpdir, plugin_dir=self.PLUGIN_DIR, **kw)

    def _real_pool_kernel(self, tmpdir):
        from story_engine.kernel import LLMPool
        k = self._kernel(tmpdir, llm_pool=LLMPool(mode="openai"))
        k.llm.api_key = "sk-fake"  # is_mock=False；调用走注入 fake，不触网
        return k

    def test_synth_genre_pack_parse_and_validate(self):
        from story_engine.meta.gacha import synth_genre_pack
        pack, err = synth_genre_pack(VALID_YAML)
        self.assertIsNotNone(pack)
        self.assertIsNone(err)
        self.assertEqual(pack["name"], "test-synth")
        # 围栏容忍：```yaml 包裹同样解析
        fenced, err_f = synth_genre_pack(f"```yaml\n{VALID_YAML}```\n")
        self.assertIsNotNone(fenced)
        self.assertIsNone(err_f)
        # 校验不过 → (None, 错误描述)
        bad_pack, err2 = synth_genre_pack("params: {}")
        self.assertIsNone(bad_pack)
        self.assertTrue(err2)

    def test_synth_retry_then_success(self):
        import asyncio, tempfile
        from types import SimpleNamespace
        from story_engine.meta.gacha import draw_card_async
        texts = ["params: {}", VALID_YAML]  # 首次不过校验 → 带错误反馈重试 → 成功
        calls = []

        async def fake(prompt, **kw):
            calls.append(prompt)
            return SimpleNamespace(text=texts[len(calls) - 1])

        with tempfile.TemporaryDirectory() as d:
            k = self._real_pool_kernel(d)
            try:
                card = asyncio.run(draw_card_async(k, fake, "synth", None))
                self.assertEqual(len(calls), 2)
                self.assertIn("未过校验", calls[1])  # 重试提示词带错误反馈
                self.assertIn("mystery", calls[0])   # 模板锚注入
                self.assertEqual(card["mode"], "synth")
                self.assertEqual(card["genre"]["source"], "synth")
                self.assertEqual(card["genre"]["name"], "test-synth")
                self.assertEqual(card["genre"]["yaml"]["name"], "test-synth")
                self.assertIsNone(card["note"])
            finally:
                k.close()

    def test_synth_degrades_after_two_failures(self):
        import asyncio, tempfile
        from types import SimpleNamespace
        from story_engine.meta.gacha import draw_card_async
        calls = []

        async def fake(prompt, **kw):
            calls.append(prompt)
            return SimpleNamespace(text="这不是 yaml")

        with tempfile.TemporaryDirectory() as d:
            k = self._real_pool_kernel(d)
            try:
                card = asyncio.run(draw_card_async(k, fake, "synth", None))
                self.assertEqual(len(calls), 2)  # 重试仅 1 次
                self.assertEqual(card["mode"], "library")          # 降级仍是合法卡
                self.assertEqual(card["genre"]["source"], "library")
                self.assertIn("AI 合成失败", card["note"])
                # P13：精简卡无 culture/archetype/rule_packs
                self.assertNotIn("culture", card)
                self.assertNotIn("archetype", card)
                self.assertNotIn("rule_packs", card)
            finally:
                k.close()


class TestSynthCardBegin(unittest.TestCase):
    """synth 合成卡 begin：合成题材从未注册进 registry（P20 遗留 422 bug），
    begin 带 synth_card → 现场注册（内存级）再走正常流程。"""

    def _backend(self):
        from conftest import import_backend_main
        return import_backend_main()

    @staticmethod
    def _synth_card(yaml_pack):
        return {"name": yaml_pack["name"], "source": "synth",
                "desc": "测试合成", "yaml": yaml_pack}

    def test_begin_with_synth_card_registers_and_creates_session(self):
        """带完整 yaml 的 synth_card → 200 + session 创建 + registry 可查。"""
        import tempfile
        import yaml as _yaml
        from fastapi.testclient import TestClient
        backend = self._backend()
        saved_root = backend.deps.PROJECTS_ROOT
        c = TestClient(backend.app)
        with tempfile.TemporaryDirectory() as root:
            backend.deps.PROJECTS_ROOT = Path(root)
            pack = _yaml.safe_load(VALID_YAML)
            card = self._synth_card(pack)
            try:
                r = c.post("/api/gacha/begin",
                           json={"genre_name": "test-synth",
                                 "synth_card": card})
                self.assertEqual(r.status_code, 200, r.text)
                sid = r.json()["session_id"]
                self.assertTrue(sid)
                # registry 里已能查到合成题材
                m = backend.deps.engine.kernel.registry.get_manifest(
                    "story.genre", "test-synth")
                self.assertEqual(m.name, "test-synth")
                # 清理 session（释放临时目录句柄）
                c.post(f"/api/gacha/{sid}/cancel")
            finally:
                backend.deps.PROJECTS_ROOT = saved_root

    def test_begin_synth_card_incomplete_yaml_422(self):
        """synth_card 缺 params → 422 未知题材。"""
        from fastapi.testclient import TestClient
        backend = self._backend()
        c = TestClient(backend.app)
        r = c.post("/api/gacha/begin",
                   json={"genre_name": "nonexistent-synth",
                         "synth_card": {"name": "nonexistent-synth",
                                        "yaml": {"name": "nonexistent-synth",
                                                 "extension_point": "story.genre"}}})
        self.assertEqual(r.status_code, 422)
        self.assertIn("未知题材", r.json()["detail"])

    def test_begin_synth_card_name_mismatch_422(self):
        """yaml.name 与 genre_name 不一致 → 422。"""
        import yaml as _yaml
        from fastapi.testclient import TestClient
        backend = self._backend()
        c = TestClient(backend.app)
        card = self._synth_card(_yaml.safe_load(VALID_YAML))
        r = c.post("/api/gacha/begin",
                   json={"genre_name": "other-name", "synth_card": card})
        self.assertEqual(r.status_code, 422)



class TestGachaSessionFlow(unittest.TestCase):
    """P20：session 模式抽卡开局（begin → derive_cast → confirm）。

    旧 confirm 的 synth 落盘 + init 切换路径已删除（P20 全部走临时工作区）。
    这里测试 session begin/confirm 全链路，用 library 题材走通。
    backend 单例全进程共享：finally 必须切回原项目并清理。
    """

    def _backend(self):
        from conftest import import_backend_main
        return import_backend_main()

    def _restore(self, backend, orig_dir):
        """切回原项目（兼清临时项目 kernel）。"""
        from fastapi.testclient import TestClient
        backend.helpers._switch_to(orig_dir)

    def test_begin_creates_session_and_confirm_creates_project(self):
        """begin → 拿到 session_id → confirm 建新项目并切换。"""
        import tempfile
        from fastapi.testclient import TestClient
        from conftest import import_backend_main
        backend = self._backend()
        orig_dir = Path(backend.deps.engine.project_dir)
        orig_genre = backend.deps.engine.genre.name
        orig_culture = backend.deps.engine.culture.name
        saved_root = backend.deps.PROJECTS_ROOT
        c = TestClient(backend.app)
        with tempfile.TemporaryDirectory() as root:
            backend.deps.PROJECTS_ROOT = Path(root)
            try:
                # begin
                r = c.post("/api/gacha/begin",
                           json={"genre_name": "mystery"})
                self.assertEqual(r.status_code, 200, r.text)
                body = r.json()
                sid = body["session_id"]
                self.assertTrue(sid)
                self.assertEqual(body["genre"], "mystery")
                # confirm
                r2 = c.post(f"/api/gacha/{sid}/confirm",
                            json={"project_name": "test-proj"})
                self.assertEqual(r2.status_code, 200, r2.text)
                body2 = r2.json()
                self.assertTrue(body2["ok"])
                self.assertEqual(body2["project"]["name"], "test-proj")
                self.assertTrue((Path(root) / "test-proj" / "story.db").exists())
                # engine 已切换
                self.assertEqual(backend.deps.engine.genre.name, "mystery")
            finally:
                self._restore(backend, orig_dir)
                backend.deps.PROJECTS_ROOT = saved_root
                c.post("/api/project/init",
                       json={"genre": orig_genre, "culture": orig_culture})

    def test_cancel_cleans_up_session(self):
        """begin → cancel → session 不存在。"""
        from fastapi.testclient import TestClient
        from conftest import import_backend_main
        backend = self._backend()
        c = TestClient(backend.app)
        r = c.post("/api/gacha/begin", json={"genre_name": "mystery"})
        self.assertEqual(r.status_code, 200, r.text)
        sid = r.json()["session_id"]
        # cancel
        r2 = c.post(f"/api/gacha/{sid}/cancel")
        self.assertEqual(r2.status_code, 200, r2.text)
        # 再 cancel → 404
        r3 = c.post(f"/api/gacha/{sid}/cancel")
        self.assertEqual(r3.status_code, 404)

    def test_confirm_with_worldview_and_cast_persists_files(self):
        """confirm 携带 worldview + cast → 落盘 worldview.json + cast.json。"""
        import json as _json
        import tempfile
        from fastapi.testclient import TestClient
        from conftest import import_backend_main
        backend = self._backend()
        orig_dir = Path(backend.deps.engine.project_dir)
        orig_genre = backend.deps.engine.genre.name
        orig_culture = backend.deps.engine.culture.name
        saved_root = backend.deps.PROJECTS_ROOT
        c = TestClient(backend.app)
        with tempfile.TemporaryDirectory() as root:
            backend.deps.PROJECTS_ROOT = Path(root)
            try:
                r = c.post("/api/gacha/begin", json={"genre_name": "mystery"})
                sid = r.json()["session_id"]
                r2 = c.post(f"/api/gacha/{sid}/confirm", json={
                    "project_name": "wv-proj",
                    "worldview": {
                        "layers": {"L0": {"metaphysics": "materialist",
                                          "consciousness_nature": "emergent"}},
                        "preset": "sci-fi-hard",
                    },
                    "cast": [
                        {"id": "主角", "role": "主角",
                         "persona": {"pearson_primary": "seeker"}},
                    ],
                })
                self.assertEqual(r2.status_code, 200, r2.text)
                proj = Path(root) / "wv-proj"
                wv_file = proj / "worldview.json"
                cast_file = proj / "cast.json"
                self.assertTrue(wv_file.exists())
                self.assertTrue(cast_file.exists())
                wv = _json.loads(wv_file.read_text(encoding="utf-8"))
                assert wv["preset"] == "sci-fi-hard"
                cast = _json.loads(cast_file.read_text(encoding="utf-8"))
                assert cast[0]["persona"]["pearson_primary"] == "seeker"
            finally:
                self._restore(backend, orig_dir)
                backend.deps.PROJECTS_ROOT = saved_root
                c.post("/api/project/init",
                       json={"genre": orig_genre, "culture": orig_culture})
