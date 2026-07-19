"""Genre 插件测试 — P3.1：romance.yaml 加载 / 组合校验 / 关键词路由"""
import tempfile
import unittest
from pathlib import Path

from story_engine.kernel import Kernel
from story_engine.meta import UserIntent
from story_engine.meta.rule_configurator import RuleConfigurator


class TestRomancePluginLoading(unittest.TestCase):
    """① romance.yaml 能被插件加载：Registry 加载不报错、字段可读"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        plugin_dir = Path(__file__).resolve().parent.parent / "story_engine" / "plugins"
        self.kernel = Kernel(self.tmp, plugin_dir=plugin_dir)

    def tearDown(self):
        try:
            self.kernel.close()
        except Exception:
            pass

    def test_romance_manifest_loads(self):
        m = self.kernel.registry.get_manifest("story.genre", "romance")
        self.assertEqual(m.name, "romance")
        self.assertEqual(m.extension_point, "story.genre")
        self.assertFalse(m.culture_bound)
        self.assertEqual(m.allowed_cultures, ["*"])

    def test_romance_core_params_readable(self):
        p = self.kernel.registry.get_params("story.genre", "romance")
        # 与 mystery 结构差：payoff_window=3 / beats_per_chapter=5
        self.assertEqual(p["payoff_window"], 3)
        self.assertEqual(p["beats_per_chapter"], 5)
        # 蓝图 3.1：romance 4 轨道（追求/障碍/情敌/成长）
        self.assertEqual(len(p["tracks"]), 4)
        self.assertIn("rags_to_riches", p["emotion_arcs"])
        # 对齐 mystery.yaml 的存量键
        for key in ("pacing_curve", "resolution_pattern", "main_track",
                    "theme_track", "world_rules", "foreshadow_templates",
                    "taboo_list", "evaluation_weights", "active_critics"):
            self.assertIn(key, p, f"缺少与 mystery 对齐的键: {key}")

    def test_romance_new_sections(self):
        """P3 新增段：prompt / phase_beats / blend_domains / pacing_targets"""
        p = self.kernel.registry.get_params("story.genre", "romance")

        # prompt 段：决策8 五键齐全，且不出现公案题材字样
        prompt = p["prompt"]
        for key in ("role", "setting", "characters", "style", "hard_requirements"):
            self.assertIn(key, prompt, f"prompt 缺键: {key}")
        prompt_text = str(prompt)
        self.assertNotIn("包拯", prompt_text)
        self.assertNotIn("开封府", prompt_text)

        # phase_beats 段：Todorov 5 态齐全，beat 带 primitive 提示键
        phases = p["phase_beats"]
        for phase in ("equilibrium", "disruption", "recognition",
                      "repair", "new_equilibrium"):
            self.assertIn(phase, phases, f"phase_beats 缺 phase: {phase}")
            self.assertGreater(len(phases[phase]), 0)
        valid_primitives = {
            "Conflict", "Suspense", "TurningPoint", "Revelation",
            "Sacrifice", "Betrayal", "Recognition", "GoalFormation",
        }
        for phase, beats in phases.items():
            for beat in beats:
                self.assertIn(beat["primitive"], valid_primitives,
                              f"{phase} 中 beat 的 primitive 非法: {beat}")

        # blend_domains / pacing_targets 段
        self.assertGreater(len(p["blend_domains"]), 0)
        pacing = p["pacing_targets"]
        for key in ("reversal_density", "avg_reversal_magnitude",
                    "pacing_consistency", "cliffhanger_strength"):
            self.assertIn(key, pacing, f"pacing_targets 缺键: {key}")
            lo, hi = pacing[key]
            self.assertLessEqual(lo, hi)

    def test_romance_instance_accessible(self):
        """插件实例化（懒加载）后 params 可以属性方式读取"""
        inst = self.kernel.registry.get("story.genre", "romance")
        self.assertEqual(inst.name, "romance")
        self.assertEqual(inst.payoff_window, 3)


class TestRomanceComboValidation(unittest.TestCase):
    """② validate_combo(romance + confucian_officialdom) 通过"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        plugin_dir = Path(__file__).resolve().parent.parent / "story_engine" / "plugins"
        self.kernel = Kernel(self.tmp, plugin_dir=plugin_dir)

    def tearDown(self):
        try:
            self.kernel.close()
        except Exception:
            pass

    def test_romance_with_confucian_officialdom_allowed(self):
        # culture_bound=false → 任意组合合法；不抛异常即通过
        self.kernel.registry.validate_combo("romance", "confucian_officialdom")

    def test_romance_allows_any_culture(self):
        self.kernel.registry.validate_combo("romance", "anything")


class TestRomanceKeywordRouting(unittest.TestCase):
    """③ UserIntent 含言情关键词 → RuleConfigurator 路由出 genre="romance\""""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        plugin_dir = Path(__file__).resolve().parent.parent / "story_engine" / "plugins"
        self.kernel = Kernel(self.tmp, plugin_dir=plugin_dir)
        self.configurator = RuleConfigurator(self.kernel)

    def tearDown(self):
        try:
            self.kernel.close()
        except Exception:
            pass

    def test_caizi_jiaren_keyword_routes_romance(self):
        cfg = self.configurator.configure(
            UserIntent(theme="才子佳人的古代情缘", culture_hint="中国古风"))
        self.assertEqual(cfg.genre, "romance")
        self.assertEqual(cfg.culture, "confucian_officialdom")
        self.assertEqual(cfg.source, "rule")

    def test_each_romance_keyword_routes(self):
        for kw in ("言情", "爱情", "恋爱", "romance", "才子佳人"):
            with self.subTest(keyword=kw):
                cfg = self.configurator.configure(
                    UserIntent(theme=f"想看一段{kw}故事", culture_hint="中国古风"))
                self.assertEqual(cfg.genre, "romance")

    def test_english_keyword_case_insensitive(self):
        """英文关键词大小写不敏感（中文无大小写，行为不变）"""
        cfg = self.configurator.configure(
            UserIntent(theme="古装 ROMANCE 大戏", culture_hint="中国古风"))
        self.assertEqual(cfg.genre, "romance")

    def test_romance_config_inherits_plugin_weights_and_critics(self):
        cfg = self.configurator.configure(
            UserIntent(theme="才子佳人", culture_hint="中国古风"))
        self.assertGreater(cfg.evaluation_weights.get("情节连贯", 0), 0)
        self.assertGreater(len(cfg.active_critics), 0)


if __name__ == "__main__":
    unittest.main()
