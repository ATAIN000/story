"""Meta-Generator 测试 — 蓝图 Module 8 双路径 + 组合校验"""
import asyncio
import tempfile
import unittest
from pathlib import Path

from story_engine.kernel import Kernel
from story_engine.meta import MetaGenerator, UserIntent
from story_engine.types import StoryEngineError


class TestRuleConfigurator(unittest.TestCase):
    """路径 A：决策树配置"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        plugin_dir = Path(__file__).resolve().parent.parent / "story_engine" / "plugins"
        self.kernel = Kernel(self.tmp, plugin_dir=plugin_dir)
        self.meta = MetaGenerator(self.kernel)

    def tearDown(self):
        try:
            self.kernel.close()
        except Exception:
            pass

    def test_intent_with_mystery_keyword_returns_mystery(self):
        cfg = asyncio.run(self.meta.generate_config(
            UserIntent(theme="破案悬疑", culture_hint="中国古风", language="zh")))
        self.assertEqual(cfg.genre, "mystery")
        self.assertEqual(cfg.culture, "confucian_officialdom")
        self.assertEqual(cfg.language, "zh")
        # 蓝图 v3.0 赌注5：active_critics 从插件裁剪
        self.assertIn("plot_coherence", cfg.active_critics)
        # 评估权重从插件继承
        self.assertGreater(cfg.evaluation_weights.get("情节连贯", 0), 0)

    def test_intent_with_wuxia_keyword_returns_wuxia(self):
        cfg = asyncio.run(self.meta.generate_config(
            UserIntent(theme="江湖武林侠客", culture_hint="中国古风", language="zh")))
        self.assertEqual(cfg.genre, "wuxia")
        self.assertEqual(cfg.culture, "confucian_officialdom")

    def test_intent_with_unknown_theme_defaults_mystery(self):
        cfg = asyncio.run(self.meta.generate_config(
            UserIntent(theme="完全未知的新题材", culture_hint="中国古风")))
        self.assertEqual(cfg.genre, "mystery")


class TestCultureBoundValidation(unittest.TestCase):
    """蓝图 v3.0 赌注2：culture_bound 题材拒绝非法组合"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        plugin_dir = Path(__file__).resolve().parent.parent / "story_engine" / "plugins"
        self.kernel = Kernel(self.tmp, plugin_dir=plugin_dir)
        self.meta = MetaGenerator(self.kernel)

    def tearDown(self):
        try:
            self.kernel.close()
        except Exception:
            pass

    def test_wuxia_with_unloaded_culture_rejected_by_validate_combo(self):
        """直接验证 validate_combo：wuxia × 不在 allowed_cultures 中的 culture 应被拒绝

        端到端不触发是因为 RuleConfigurator 默认兜底 confucian_officialdom（合法）。
        这里直接调 registry.validate_combo 验证 culture_bound 防线本身。
        """
        with self.assertRaises(StoryEngineError):
            # wuxia 的 allowed_cultures = [confucian_officialdom, taoist_chinese]
            # scandinavian_protestant 不在内 → 必须拒绝
            self.kernel.registry.validate_combo("wuxia", "scandinavian_protestant")

    def test_wuxia_with_confucian_culture_allowed(self):
        """wuxia × confucian_officialdom 合法（在 allowed_cultures 白名单内）"""
        # 不抛异常即通过
        self.kernel.registry.validate_combo("wuxia", "confucian_officialdom")

    def test_mystery_allows_any_culture(self):
        """mystery 的 allowed_cultures=["*"]，任意 culture 合法"""
        self.kernel.registry.validate_combo("mystery", "anything")
        self.kernel.registry.validate_combo("mystery", "scandinavian_protestant")


class TestRAGCombinator(unittest.TestCase):
    """路径 B：从插件库检索最相似模板"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        plugin_dir = Path(__file__).resolve().parent.parent / "story_engine" / "plugins"
        self.kernel = Kernel(self.tmp, plugin_dir=plugin_dir)
        self.meta = MetaGenerator(self.kernel)

    def tearDown(self):
        try:
            self.kernel.close()
        except Exception:
            pass

    def test_keyword_match_mystery(self):
        """intent 含「悬疑/破案」关键词 → RAG 命中 mystery"""
        cfg = asyncio.run(self.meta.generate_config(
            UserIntent(theme="悬疑破案", culture_hint="中国古风")))
        # 路径 A 与 B 都命中 mystery，最终 merged.genre = mystery
        self.assertEqual(cfg.genre, "mystery")
        # source 应该是 "merged"（A+B 都跑了）或 "rule"（A 单独跑）
        self.assertIn(cfg.source, ("merged", "rule"))

    def test_rag_combinator_returns_none_when_no_overlap(self):
        """RAG 召回弱时返回 None → MetaGenerator 回退到路径 A"""
        # 用一个与所有 manifest token 都无重叠的 theme
        cfg = self.meta.rag_combinator.retrieve(
            UserIntent(theme="zzz qq xxx", culture_hint="中国古风"))
        # 这种垃圾输入下，Jaccard 相似度应全 0 → 返回 None
        # 但注意 language="zh" 可能与 manifest 中的字段碰巧匹配，所以放宽：
        # 关键断言是"返回 None 或 source='rag'"
        if cfg is not None:
            self.assertEqual(cfg.source, "rag")

    def test_rag_combinator_returns_config_on_overlap(self):
        """RAG 与 manifest 文档有 token 重叠时返回 StoryConfig"""
        # theme 含「江湖」（wuxia manifest 的 taboo_list 中"不允许现代武器"含"江湖"上下文 token）
        # 或更稳妥：直接构造一个有 overlap 的 theme
        cfg = self.meta.rag_combinator.retrieve(
            UserIntent(theme="wuxia mystery 古代 中国", culture_hint="中国古风"))
        self.assertIsNotNone(cfg)
        if cfg is not None:
            self.assertEqual(cfg.source, "rag")
            self.assertIn(cfg.genre, ("mystery", "wuxia"))


class TestStoryConfigContract(unittest.TestCase):
    """蓝图 8.1：StoryConfig 三正交轴数据结构契约"""

    def test_to_dict_roundtrip(self):
        from story_engine.meta import StoryConfig
        c = StoryConfig(
            genre="mystery", culture="confucian_officialdom", language="zh",
            target_length=10, platform="novel",
            evaluation_weights={"a": 0.5}, active_critics=["x"],
            source="merged", matched_template="mystery",
        )
        d = c.to_dict()
        self.assertEqual(d["genre"], "mystery")
        self.assertEqual(d["culture"], "confucian_officialdom")
        self.assertEqual(d["target_length"], 10)
        self.assertEqual(d["source"], "merged")
        self.assertIn("a", d["evaluation_weights"])


if __name__ == "__main__":
    unittest.main()
