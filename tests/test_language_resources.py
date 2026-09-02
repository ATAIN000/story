"""语言资源消费测试 — realizer 消费语言包非标准键（感官词/隐喻/氛围/对话节奏）

此前语言包的非 LANGUAGE_RESOURCES 键（如 zh-romance 的 感官描写词/情感隐喻/
氛围词/对话节奏模板）被 warning+忽略，题材特色质感素材全部浪费。现收集进
_extra_resources 并由 _resource_block 注入「题材质感素材」段。
"""
import warnings
from pathlib import Path

import pytest

from story_engine.narrative.realizer import ChineseRealizer
from story_engine.narrative.ir import TextureParams


@pytest.fixture(scope="module")
def real_registry():
    from story_engine.kernel.registry import ExtensionRegistry
    r = ExtensionRegistry()
    r.scan_plugins(Path("story_engine/plugins"))
    return r


def _texture():
    return TextureParams(0.2, 0.5, 0.4, 0.3, (18, 9), 0.6, "limited",
                         "chronological")


def test_extra_resources_collected_from_language_packs(real_registry):
    """zh-romance-texture 的非标准键被收集（不再丢弃）"""
    rz = ChineseRealizer(registry=real_registry)
    # romance pack 的特色键应进 _extra_resources
    assert "情感隐喻" in rz._extra_resources
    assert "氛围词" in rz._extra_resources
    assert "对话节奏模板" in rz._extra_resources
    # 感官描写词是 dict（按触觉/视觉/听觉分子键）
    assert isinstance(rz._extra_resources["感官描写词"], dict)
    assert "触觉" in rz._extra_resources["感官描写词"]


def test_resource_block_includes_genre_texture_section(real_registry):
    rz = ChineseRealizer(registry=real_registry)
    block = rz._resource_block(_texture())
    assert "题材质感素材" in block
    assert "情感隐喻" in block


def test_no_warning_for_unknown_resource_keys(real_registry):
    """非标准键不再触发 UserWarning（此前每章生成都有这些 warning）"""
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # 任一 UserWarning → 抛错
        ChineseRealizer(registry=real_registry)  # 不应抛


def test_no_registry_extra_resources_empty():
    """无 registry → _extra_resources 空，_resource_block 无题材质感段（零漂移）"""
    rz = ChineseRealizer(registry=None)
    assert rz._extra_resources == {}
    block = rz._resource_block(_texture())
    assert "题材质感素材" not in block


def test_extra_list_values_deduped_across_packs(real_registry):
    """多 pack 的 list 值去重合并"""
    rz = ChineseRealizer(registry=real_registry)
    # 情感隐喻是 list，去重后无重复
    metaphors = rz._extra_resources["情感隐喻"]
    assert len(metaphors) == len(set(metaphors))


def test_gongan_pack_resources_also_collected(real_registry):
    """zh-gongan-texture 的特色键也被收集（公堂用语/动作描写模板）"""
    rz = ChineseRealizer(registry=real_registry)
    assert "公堂用语" in rz._extra_resources
