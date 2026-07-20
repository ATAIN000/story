"""H7-B5：29 题材统一验收 — 全量加载 / 代表题材产卡 / 无 RAG 路由碰撞

对应 .superpowers/sdd/briefs/task-49-b5-brief.md 的三项验收：
  ① 全量加载：Registry 枚举全部 29 个 genre（mystery/romance/wuxia + 26 新），
     逐个 validate_combo(genre, "confucian_officialdom")（culture_bound 题材按
     其声明断言白名单内过、白名单外拒）；params 必填键存在
     （tracks/beats_per_chapter/payoff_window/prompt 五键/phase_beats 五态）。
     注：wuxia 为 Phase 2 遗留题材，缺 prompt/phase_beats 两段 —— 引擎对此有
     设计内兜底（P3.8 通用 prompt 兜底 / planner DEFAULT_PHASE_BEATS，注释
     明确提及 wuxia），故 prompt/phase_beats 断言覆盖其余 28 个题材，
     wuxia 只断言运行时三键；该遗留见验收报告。
  ② 决策卡可产：5 个代表新题材（cyberpunk-xianxia/fantasy-mystery/
     xianxia-cthulhu/isekai-romance/sequence-pathway）+ 现有 3 题材，
     StoryEngine 直构产决策卡：轨道名读得出（track_names）、
     beats 数 == beats_per_chapter、任意两题材卡结构不同。
  ③ 无 RAG 路由碰撞：26 个新题材进入检索库后，test_meta 定义的经典路由
     契约不变（悬疑→mystery / 江湖→wuxia / 未知→mystery 兜底）。
"""
import asyncio
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_engine.engine import StoryEngine
from story_engine.kernel import Kernel
from story_engine.meta import MetaGenerator, UserIntent
from story_engine.types import StoryEngineError

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "story_engine" / "plugins"

# H7 四批提升的 26 个新题材（300f873/0d1852b/42e5ae3/5bc4476）
NEW_GENRES = {
    "apocalypse-romance", "court-workplace", "cozy-fantasy-mystery",
    "cyberpunk-xianxia", "fantasy-mystery", "fantasy-sports", "folk-cthulhu",
    "game-reality-invasion", "historical-isekai", "historical-system",
    "horror-comedy", "infinite-dungeon", "isekai-detective", "isekai-romance",
    "meta-isekai-dual", "political-cultivation", "reborn-business-era",
    "romance-suspense", "romantasy", "sci-fi-horror", "sequence-pathway",
    "supernatural-management", "system-isekai", "tomb-exploration",
    "wuxia-steampunk", "xianxia-cthulhu",
}
ORIGINAL_GENRES = {"mystery", "romance", "wuxia"}
ALL_GENRES = NEW_GENRES | ORIGINAL_GENRES

# culture_bound 题材的声明白名单（按各 yaml 实际声明值）
CULTURE_BOUND = {
    "folk-cthulhu": ["chinese_folk", "confucian_officialdom"],
    "supernatural-management": ["chinese_folk", "confucian_officialdom"],
    "tomb-exploration": ["chinese_folk", "confucian_officialdom"],
    "wuxia": ["confucian_officialdom", "taoist_chinese"],
}

# 运行时三键（Showrunner/调度直接消费）；prompt 五键 + phase_beats 五态
CORE_KEYS = ("tracks", "beats_per_chapter", "payoff_window")
PROMPT_KEYS = ("role", "setting", "characters", "style", "hard_requirements")
TODOROV_PHASES = ("equilibrium", "disruption", "recognition",
                  "repair", "new_equilibrium")
# wuxia：Phase 2 遗留，缺 prompt/phase_beats，引擎有设计内兜底（见模块 docstring）
PROMPT_SECTION_GENRES = ALL_GENRES - {"wuxia"}

# ② 代表题材：5 新 + 3 旧
REPRESENTATIVE = ["mystery", "romance", "wuxia", "cyberpunk-xianxia",
                  "fantasy-mystery", "xianxia-cthulhu", "isekai-romance",
                  "sequence-pathway"]


class TestAllGenresLoadAndValidate(unittest.TestCase):
    """① 全量加载：29 题材枚举 / 组合校验 / 必填键"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kernel = Kernel(self.tmp, plugin_dir=PLUGIN_DIR)

    def tearDown(self):
        try:
            self.kernel.close()
        except Exception:
            pass

    def test_registry_enumerates_all_29_genres(self):
        genres = self.kernel.registry.list_plugins("story.genre")["story.genre"]
        self.assertEqual(len(genres), 29)
        self.assertEqual(set(genres), ALL_GENRES)

    def test_validate_combo_with_confucian_officialdom(self):
        for genre in sorted(ALL_GENRES):
            with self.subTest(genre=genre):
                m = self.kernel.registry.get_manifest("story.genre", genre)
                if genre in CULTURE_BOUND:
                    # 按声明断言：白名单含 confucian_officialdom → 组合合法
                    self.assertTrue(m.culture_bound)
                    self.assertEqual(m.allowed_cultures, CULTURE_BOUND[genre])
                    self.kernel.registry.validate_combo(
                        genre, "confucian_officialdom")
                    # 白名单外文化必须拒绝
                    with self.assertRaises(StoryEngineError):
                        self.kernel.registry.validate_combo(
                            genre, "scandinavian_protestant")
                else:
                    # culture_bound=false → 任意组合合法
                    self.assertFalse(m.culture_bound)
                    self.assertEqual(m.allowed_cultures, ["*"])
                    self.kernel.registry.validate_combo(
                        genre, "confucian_officialdom")
                    self.kernel.registry.validate_combo(genre, "anything")

    def test_required_keys_present(self):
        for genre in sorted(ALL_GENRES):
            with self.subTest(genre=genre):
                p = self.kernel.registry.get_params("story.genre", genre)
                for key in CORE_KEYS:
                    self.assertIn(key, p, f"{genre} 缺运行时键: {key}")
                self.assertGreater(len(p["tracks"]), 0)
                if genre not in PROMPT_SECTION_GENRES:
                    continue  # wuxia 遗留缺口，见模块 docstring
                prompt = p.get("prompt", {})
                for key in PROMPT_KEYS:
                    self.assertIn(key, prompt, f"{genre} prompt 缺键: {key}")
                phases = p.get("phase_beats", {})
                for phase in TODOROV_PHASES:
                    self.assertIn(phase, phases,
                                  f"{genre} phase_beats 缺 phase: {phase}")
                    self.assertGreater(len(phases[phase]), 0)


class TestRepresentativeDecisionCards(unittest.TestCase):
    """② 决策卡可产：5 代表新题材 + 3 旧题材，StoryEngine 直构产卡"""

    def setUp(self):
        self.dirs = []
        self.engines = {}
        for genre in REPRESENTATIVE:
            tmp = tempfile.mkdtemp()
            with mock.patch.dict(os.environ, {"STORY_ENGINE_GENRE": genre}):
                eng = StoryEngine(tmp)
            self.dirs.append(tmp)
            self.engines[genre] = eng

    def tearDown(self):
        for eng in self.engines.values():
            try:
                eng.kernel.close()
            except Exception:
                pass
        for d in self.dirs:
            shutil.rmtree(d, ignore_errors=True)

    def _card(self, genre: str, episode: int = 1):
        eng = self.engines[genre]
        state = eng.kernel.query_world("current_state")
        return eng.showrunner.generate_decision_card(episode, state)

    def test_card_track_names_readable_and_beats_count(self):
        for genre in REPRESENTATIVE:
            with self.subTest(genre=genre):
                eng = self.engines[genre]
                card = self._card(genre)
                # beats 数 == 题材声明的 beats_per_chapter
                self.assertEqual(
                    len(card.beats),
                    eng.bundle.genre_params["beats_per_chapter"])
                # 轨道名读得出：卡上出现的每个轨道都有非空中文名
                scheduled = set(card.advance + card.seed
                                + card.mid_touch + card.dormant)
                self.assertTrue(scheduled)
                for tid in scheduled:
                    self.assertTrue(card.track_names.get(tid),
                                    f"{genre} 轨道 {tid} 无名")

    def test_any_two_genres_card_structure_differs(self):
        sigs = {g: tuple(sorted(self._card(g).track_names.items()))
                for g in REPRESENTATIVE}
        for i, a in enumerate(REPRESENTATIVE):
            for b in REPRESENTATIVE[i + 1:]:
                self.assertNotEqual(sigs[a], sigs[b],
                                    f"{a} 与 {b} 决策卡轨道结构相同")


class TestNoRAGRoutingCollision(unittest.TestCase):
    """③ 无 RAG 路由碰撞：26 新题材入库后经典路由契约不变（test_meta 口径）"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kernel = Kernel(self.tmp, plugin_dir=PLUGIN_DIR)
        self.meta = MetaGenerator(self.kernel)

    def tearDown(self):
        try:
            self.kernel.close()
        except Exception:
            pass

    def test_classic_routes_unchanged(self):
        cases = [
            ("悬疑破案", "mystery"),          # 路径 A+B 均命中 mystery
            ("江湖武林侠客", "wuxia"),
            ("完全未知的新题材", "mystery"),   # 未知主题兜底 mystery
        ]
        for theme, expected in cases:
            with self.subTest(theme=theme):
                cfg = asyncio.run(self.meta.generate_config(
                    UserIntent(theme=theme, culture_hint="中国古风")))
                self.assertEqual(cfg.genre, expected)
                self.assertEqual(cfg.culture, "confucian_officialdom")


if __name__ == "__main__":
    unittest.main()
