"""P9.1 测试：显示名中文化 —— registry.display_map()

核心用例（用户指令：≤2 核心）：
1. 真实插件目录扫描后，display_map 含已知词表映射
   （mystery→公案悬疑、apocalypse-romance→末日情缘；pack 侧 fair-play→公平竞争）
2. 无 title 的包回落 id 本身（合成 manifest，纯展示层语义）
"""
import unittest
from pathlib import Path

from story_engine.kernel.registry import ExtensionRegistry, PluginManifest

PLUGIN_DIR = (Path(__file__).resolve().parent.parent
              / "story_engine" / "plugins")


class TestDisplayMap(unittest.TestCase):
    def test_1_known_glossary_mappings(self):
        reg = ExtensionRegistry()
        reg.scan_plugins(PLUGIN_DIR)
        m = reg.display_map()
        self.assertEqual(m["mystery"], "公案悬疑")
        self.assertEqual(m["apocalypse-romance"], "末日情缘")
        # pack 桶（world.rule 不经 register，亦须入表）
        self.assertEqual(m["fair-play"], "公平竞争")

    def test_2_missing_title_falls_back_to_id(self):
        reg = ExtensionRegistry()
        reg.register(PluginManifest.from_dict({
            "manifest_version": 1,
            "name": "bare-genre",
            "extension_point": "story.genre",
            "params": {"pacing_curve": "slow_burn"},
        }))
        self.assertEqual(reg.display_map()["bare-genre"], "bare-genre")


if __name__ == "__main__":
    unittest.main()
