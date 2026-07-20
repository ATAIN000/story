"""P7.1 测试：L1 素材包扫描（draft 跳过 / 宽松校验）+ L2 story.skill 接线

核心用例（用户指令：只保留核心）：
1. packs 扫描：packs("story.skill") 含 3 个样例；draft 的 judge-official 不在任何桶
2. 容错：缺 name 键的坏 pack → warning + 跳过不崩，其余正常加载
3. skill 接线：StoryEngine 启动后 story.skill 注册可见（registry 最短真实路径）
"""
import shutil
import tempfile
import unittest
from pathlib import Path

from story_engine.engine import StoryEngine
from story_engine.kernel.registry import ExtensionRegistry

PACKS_DIR = (Path(__file__).resolve().parent.parent
             / "story_engine" / "plugins" / "packs")
ALL_BUCKETS = ["story.skill", "story.language", "story.evaluator",
               "world.rule", "story.character.archetype"]


class TestPacksScan(unittest.TestCase):
    def test_1_scan_buckets_and_draft_skipped(self):
        reg = ExtensionRegistry()
        reg.load_packs(PACKS_DIR)
        skills = {p.name for p in reg.packs("story.skill")}
        self.assertEqual(skills, {"courtroom-interrogation",
                                  "deliberate-slip", "foreshadow-echo"})
        # draft 的 judge-official 不出现在任何桶
        for point in ALL_BUCKETS:
            self.assertNotIn("judge-official",
                             {p.name for p in reg.packs(point)})

    def test_2_bad_manifest_warns_and_skips(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            pack_dir = tmp / "packs" / "story.skill"
            pack_dir.mkdir(parents=True)
            (pack_dir / "good-pack.yaml").write_text(
                "manifest_version: 1\nname: good-pack\n"
                "extension_point: story.skill\nparams: {}\n",
                encoding="utf-8")
            (pack_dir / "bad-pack.yaml").write_text(
                "manifest_version: 1\nextension_point: story.skill\n",
                encoding="utf-8")  # 缺 name 键
            reg = ExtensionRegistry()
            with self.assertLogs("story_engine.kernel.registry",
                                 level="WARNING") as cm:
                reg.load_packs(tmp / "packs")
            self.assertTrue(any("缺键" in line for line in cm.output))
            # 坏包跳过，好包照常加载
            self.assertEqual([p.name for p in reg.packs("story.skill")],
                             ["good-pack"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestSkillWiring(unittest.TestCase):
    def test_3_story_engine_registers_skill_packs(self):
        tmp = tempfile.mkdtemp()
        try:
            eng = StoryEngine(tmp)
            try:
                skills = eng.registry.list_plugins(
                    "story.skill")["story.skill"]
                for name in ("courtroom-interrogation", "deliberate-slip",
                             "foreshadow-echo"):
                    self.assertIn(name, skills)
                # 与 P5.9 训练管线同路径：register → get 懒实例化可取
                inst = eng.registry.get("story.skill",
                                        "courtroom-interrogation")
                self.assertEqual(inst.extension_point, "story.skill")
            finally:
                eng.kernel.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
