"""[向后兼容 shim] registry 已迁移到 story_engine.kernel.registry"""
from .kernel.registry import (
    EXTENSION_POINTS,
    ExtensionRegistry,
    PluginManifest,
    PluginInstance,
)

__all__ = ["EXTENSION_POINTS", "ExtensionRegistry", "PluginManifest", "PluginInstance"]
