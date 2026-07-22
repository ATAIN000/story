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
        # 端点 synth 模式 + mock 池：恒降级精简卡（硬约束：零 LLM 调用）。
        # 测试进程内 backend 单例按 .env 真实配置为非 mock（见 conftest），
        # 故临时把 pool.mode 拨回 mock 验证短路，finally 还原。
        from fastapi.testclient import TestClient
        from conftest import import_backend_main
        backend = import_backend_main()
        pool = backend.engine.kernel.llm
        saved_mode = pool.mode
        pool.mode = "mock"
        try:
            assert pool.is_mock
            c = TestClient(backend.app)
            r = c.post("/api/gacha/draw", json={"mode": "synth"})
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
        r = c.post("/api/gacha/draw", json={"mode": "library"})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["mode"], "library")
        self.assertIn("genres", body)
        self.assertTrue(body["genres"])
        # 每条题材卡结构完整
        for item in body["genres"]:
            for key in ("name", "title", "desc", "culture_title", "cast_summary"):
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


class TestGachaConfirmInit(unittest.TestCase):
    """P8.5：confirm 落盘 + project init 切换（TestClient 走通）。

    backend 单例全进程共享：每个用例 finally 必须把 engine 切回原题材/文化、
    清掉落盘探针 yaml 并 reload registry，否则波及字母序靠后的 backend 用例。
    """

    GENRES_DIR = Path(__file__).resolve().parent.parent / "story_engine" / "plugins" / "genres"

    def _backend(self):
        from conftest import import_backend_main
        return import_backend_main()

    def _restore(self, backend, orig_genre, orig_culture):
        """经 init 端点切回原题材/文化（兼清项目状态），并确保探针清除。"""
        from fastapi.testclient import TestClient
        for probe in ("test-synth.yaml", "test-synth-2.yaml"):
            p = self.GENRES_DIR / probe
            if p.exists():
                p.unlink()
        backend.kernel.registry.reload()
        TestClient(backend.app).post(
            "/api/project/init",
            json={"genre": orig_genre, "culture": orig_culture})

    @staticmethod
    def _card(yaml_pack, source="synth", name="test-synth",
              culture="confucian_officialdom"):
        return {"mode": source,
                "genre": {"name": name, "source": source, "desc": "d",
                          "yaml": yaml_pack} if source == "synth" else
                         {"name": name, "source": source, "desc": "d"},
                "note": None}

    def test_confirm_synth_persists_and_init_switches(self):
        from fastapi.testclient import TestClient
        backend = self._backend()
        orig = (backend.engine.genre.name, backend.engine.culture.name)
        env_before = {k: os.environ.get(k)
                      for k in ("STORY_ENGINE_GENRE", "STORY_ENGINE_CULTURE")}
        probe = self.GENRES_DIR / "test-synth.yaml"
        probe2 = self.GENRES_DIR / "test-synth-2.yaml"
        c = TestClient(backend.app)
        try:
            r = c.post("/api/gacha/confirm",
                       json=self._card(yaml.safe_load(VALID_YAML)))
            self.assertEqual(r.status_code, 200, r.text)
            body = r.json()
            self.assertTrue(body["ok"])
            self.assertTrue(body["persisted"])
            self.assertEqual(body["genre"], "test-synth")
            self.assertEqual(body["project"]["genre"], "test-synth")
            self.assertEqual(body["project"]["culture"], "anglo-american")  # P18: test-synth 非东方题材→anglo
            self.assertTrue(probe.exists())
            # engine 单例已切换；init 为进程内覆盖，env 不被改写
            self.assertEqual(backend.engine.genre.name, "test-synth")
            self.assertIsNone(backend.engine._pending_plan)
            self.assertEqual({k: os.environ.get(k) for k in env_before},
                             env_before)
            # 重名冲突：同卡二次 confirm → 自动 -2 后缀落盘并切换
            r2 = c.post("/api/gacha/confirm",
                        json=self._card(yaml.safe_load(VALID_YAML)))
            self.assertEqual(r2.status_code, 200, r2.text)
            self.assertEqual(r2.json()["genre"], "test-synth-2")
            self.assertTrue(probe2.exists())
            self.assertEqual(backend.engine.genre.name, "test-synth-2")
        finally:
            self._restore(backend, *orig)

    def test_confirm_invalid_synth_yaml_422(self):
        from fastapi.testclient import TestClient
        backend = self._backend()
        orig = (backend.engine.genre.name, backend.engine.culture.name)
        c = TestClient(backend.app)
        try:
            bad = yaml.safe_load(VALID_YAML)
            bad["params"]["beats_per_chapter"] = 99  # 超 3-6 区间
            r = c.post("/api/gacha/confirm", json=self._card(bad))
            self.assertEqual(r.status_code, 422, r.text)
            # 未过复核：不落盘、不切换
            self.assertFalse((self.GENRES_DIR / "test-synth.yaml").exists())
            self.assertEqual(backend.engine.genre.name, orig[0])
        finally:
            self._restore(backend, *orig)

    def test_confirm_library_skips_persistence_and_switches(self):
        from fastapi.testclient import TestClient
        backend = self._backend()
        orig = (backend.engine.genre.name, backend.engine.culture.name)
        # romance/mystery 均非 culture_bound，与原文化组合必合法
        other = "romance" if orig[0] != "romance" else "mystery"
        c = TestClient(backend.app)
        try:
            r = c.post("/api/gacha/confirm",
                       json=self._card(None, source="library", name=other,
                                       culture=orig[1]))
            self.assertEqual(r.status_code, 200, r.text)
            body = r.json()
            self.assertTrue(body["ok"])
            self.assertFalse(body["persisted"])  # 库内卡不落盘
            self.assertEqual(body["genre"], other)
            self.assertEqual(body["project"]["genre"], other)
            self.assertEqual(backend.engine.genre.name, other)
            # 库内确认不在 genres 目录留临时/新文件
            self.assertFalse((self.GENRES_DIR / f"{other}.tmp").exists())
        finally:
            self._restore(backend, *orig)

    def test_confirm_bad_extension_point_422_not_persisted(self):
        """终审修复1：synth 包缺/错 extension_point → 422，不落盘不切换
        （否则坏包落盘后 registry 加载路径 KeyError，卡死 reload 与重启）。"""
        from fastapi.testclient import TestClient
        backend = self._backend()
        orig = (backend.engine.genre.name, backend.engine.culture.name)
        probe = self.GENRES_DIR / "test-synth.yaml"
        c = TestClient(backend.app)
        try:
            for mutate in (lambda p: p.pop("extension_point"),
                           lambda p: p.update(extension_point="story.culture")):
                bad = yaml.safe_load(VALID_YAML)
                mutate(bad)
                r = c.post("/api/gacha/confirm", json=self._card(bad))
                self.assertEqual(r.status_code, 422, r.text)
                self.assertIn("extension_point", r.json()["detail"])
                self.assertFalse(probe.exists())          # 不落盘
                self.assertEqual(backend.engine.genre.name, orig[0])  # 不切换
        finally:
            self._restore(backend, *orig)

    def test_confirm_culture_bound_mismatch_422_not_persisted(self):
        """P13：allowed_cultures 引用不存在的文化 → 422 且不落盘
        （否则文件已注册、init 却崩，落盘与项目状态不一致）。"""
        from fastapi.testclient import TestClient
        backend = self._backend()
        orig = (backend.engine.genre.name, backend.engine.culture.name)
        probe = self.GENRES_DIR / "test-synth.yaml"
        c = TestClient(backend.app)
        try:
            pack = yaml.safe_load(VALID_YAML)
            pack["culture_bound"] = True
            pack["allowed_cultures"] = ["nordic_saga"]  # 不存在的文化
            r = c.post("/api/gacha/confirm", json=self._card(pack))
            self.assertEqual(r.status_code, 422, r.text)
            self.assertIn("已注册文化", r.json()["detail"])
            self.assertFalse(probe.exists())              # 不落盘
            self.assertEqual(backend.engine.genre.name, orig[0])  # 不切换
        finally:
            self._restore(backend, *orig)
