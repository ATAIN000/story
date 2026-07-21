# tests/test_gacha.py
import unittest, yaml
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
