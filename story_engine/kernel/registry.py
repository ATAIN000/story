"""ExtensionRegistry — 扩展点注册表（Module 0.2）

核心只定义契约，实现由插件提供。绝不在核心写题材特化逻辑。
静态声明优先（YAML manifest），懒加载实例化。

迁移自 story_engine/registry.py（Phase 1 收尾，搬到 kernel 子包）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..types import PluginNotFoundError, StoryEngineError

EXTENSION_POINTS = {
    "story.genre": "题材包：节奏/情感弧/原型/冲突/评估权重",
    "story.culture": "文化包：Hofstede 6维 + 叙事维度 + 原型映射",
    "story.language": "语言 realizer：IR→目标语言文本",
    "story.skill": "叙事技能：触发条件+prompt模板+后处理",
    "story.character.archetype": "角色原型",
    "story.evaluator": "评估 critic",
    "story.world.rule": "世界规则",
    "narrator.style": "叙事风格",
}


@dataclass
class PluginManifest:
    """插件清单 — VS Code 式静态声明（v3.0: 支持 culture_bound 标记）"""
    name: str
    extension_point: str
    activation_events: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    manifest_version: int = 1
    culture_bound: bool = False
    allowed_cultures: list[str] = field(default_factory=lambda: ["*"])

    @classmethod
    def load(cls, path: str | Path) -> "PluginManifest":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls(
            name=data["name"],
            extension_point=data["extension_point"],
            activation_events=data.get("activation_events", []),
            params=data.get("params", {}),
            manifest_version=data.get("manifest_version", 1),
            culture_bound=data.get("culture_bound", False),
            allowed_cultures=data.get("allowed_cultures", ["*"]),
        )


@dataclass
class _PluginEntry:
    manifest: PluginManifest
    instance: Any = None


class ExtensionRegistry:
    """扩展点注册表 — 懒加载"""

    def __init__(self):
        self._plugins: dict[str, dict[str, _PluginEntry]] = {}

    def register(self, manifest: PluginManifest) -> None:
        if manifest.extension_point not in EXTENSION_POINTS:
            raise StoryEngineError(f"未知扩展点: {manifest.extension_point}")
        self._plugins.setdefault(manifest.extension_point, {})[manifest.name] = \
            _PluginEntry(manifest=manifest)

    def get(self, extension_point: str, name: str, context: dict | None = None) -> Any:
        entry = self._plugins.get(extension_point, {}).get(name)
        if entry is None:
            raise PluginNotFoundError(extension_point, name)
        if entry.instance is None:
            entry.instance = self._instantiate(entry.manifest)
        return entry.instance

    def get_params(self, extension_point: str, name: str) -> dict:
        entry = self._plugins.get(extension_point, {}).get(name)
        if entry is None:
            raise PluginNotFoundError(extension_point, name)
        return entry.manifest.params

    def get_manifest(self, extension_point: str, name: str) -> PluginManifest:
        entry = self._plugins.get(extension_point, {}).get(name)
        if entry is None:
            raise PluginNotFoundError(extension_point, name)
        return entry.manifest

    def list_plugins(self, extension_point: str | None = None) -> dict[str, list[str]]:
        if extension_point:
            return {extension_point: list(self._plugins.get(extension_point, {}))}
        return {ep: list(plugins) for ep, plugins in self._plugins.items()}

    def validate_combo(self, genre: str, culture: str) -> None:
        """【v3.0 赌注2】Genre×Culture 组合校验：culture_bound 题材只许白名单组合"""
        entry = self._plugins.get("story.genre", {}).get(genre)
        if entry is None:
            raise PluginNotFoundError("story.genre", genre)
        m = entry.manifest
        if m.culture_bound and "*" not in m.allowed_cultures \
                and culture not in m.allowed_cultures:
            raise StoryEngineError(
                f"题材 {genre} 为 culture_bound，仅允许 {m.allowed_cultures}，"
                f"拒绝组合 {genre} × {culture}")

    @staticmethod
    def _instantiate(manifest: PluginManifest) -> Any:
        """demo 级：插件即数据（YAML params），实例 = params 的轻量包装"""
        return PluginInstance(manifest.name, manifest.extension_point, manifest.params)


class PluginInstance:
    """插件实例 — 把 YAML params 包装成属性访问"""
    def __init__(self, name: str, extension_point: str, params: dict):
        self.name = name
        self.extension_point = extension_point
        self.params = params

    def __getattr__(self, item: str) -> Any:
        try:
            return self.params[item]
        except KeyError:
            raise AttributeError(item)

    def get(self, key: str, default: Any = None) -> Any:
        return self.params.get(key, default)
