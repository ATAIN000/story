"""ExtensionRegistry — 扩展点注册表（Module 0.2）

核心只定义契约，实现由插件提供。绝不在核心写题材特化逻辑。
静态声明优先（YAML manifest），懒加载实例化。

迁移自 story_engine/registry.py（Phase 1 收尾，搬到 kernel 子包）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..types import PluginNotFoundError, StoryEngineError

logger = logging.getLogger(__name__)

# pack manifest 必备三键：缺一即跳过 + warning（P7.1 宽松加载）
PACK_REQUIRED_KEYS = ("manifest_version", "name", "extension_point")

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
    def from_dict(cls, data: dict) -> "PluginManifest":
        return cls(
            name=data["name"],
            extension_point=data["extension_point"],
            activation_events=data.get("activation_events", []),
            params=data.get("params", {}),
            manifest_version=data.get("manifest_version", 1),
            culture_bound=data.get("culture_bound", False),
            allowed_cultures=data.get("allowed_cultures", ["*"]),
        )

    @classmethod
    def load(cls, path: str | Path) -> "PluginManifest":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data)


@dataclass
class _PluginEntry:
    manifest: PluginManifest
    instance: Any = None


class ExtensionRegistry:
    """扩展点注册表 — 懒加载"""

    def __init__(self):
        self._plugins: dict[str, dict[str, _PluginEntry]] = {}
        # 素材包分桶（P7.1）：extension_point → name → entry。
        # 与 _plugins 分离：pack 桶（如 world.rule）不受 EXTENSION_POINTS 契约约束，
        # 经 packs()/pack_manifests() 查询；list_plugins 合并展示。
        self._packs: dict[str, dict[str, _PluginEntry]] = {}
        # 已挂载的插件目录（scan_plugins 记录），供 reload() 运行时重扫
        self._plugin_dir: Path | None = None

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
        # P7.1：packs 合并进列表（前端插件视图据此显示素材包）；
        # 同名去重（L2 接线的 story.skill 包同时存在于 _plugins 与 _packs）
        if extension_point:
            return {extension_point: self._merged_names(extension_point)}
        result = {ep: self._merged_names(ep) for ep in self._plugins}
        for ep in self._packs:
            if ep not in result:
                result[ep] = self._merged_names(ep)
        return result

    def _merged_names(self, extension_point: str) -> list[str]:
        names = list(self._plugins.get(extension_point, {}))
        names.extend(n for n in self._packs.get(extension_point, {})
                     if n not in names)
        return names

    def display_map(self) -> dict[str, str]:
        """{name: params.title or name} 合并表（P9.1 显示名中文化，纯展示层）。

        覆盖全部已注册 manifest（_plugins）与素材包（_packs）；
        无 title 的包回落 id 本身，前端可无条件查表。"""
        result: dict[str, str] = {}
        for bucket in (self._packs, self._plugins):
            for entries in bucket.values():
                for name, entry in entries.items():
                    title = entry.manifest.params.get("title")
                    result[name] = str(title) if title else name
        return result

    # =========================================================
    # 素材包（P7.1 L1）：plugins/packs/ 宽松扫描 + 分桶查询
    # =========================================================
    def load_packs(self, packs_dir: str | Path) -> None:
        """扫描素材包目录，按 extension_point 分桶。

        语义（docs/素材包体系与hermes采集计划.md）：
        - _index.yaml 维护 status：draft → 跳过；active / 未列入索引 → 尝试加载
        - manifest 缺 PACK_REQUIRED_KEYS 之一 / 非映射 / YAML 解析失败
          → warning + 跳过（不崩，其余包照常加载）
        - extension_point 与所在目录名不一致 → warning，按 manifest 内值归桶
        """
        packs_dir = Path(packs_dir)
        if not packs_dir.is_dir():
            return
        status_by_name = self._load_pack_index(packs_dir / "_index.yaml")
        for path in sorted(packs_dir.glob("*/*.yaml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError as e:
                logger.warning("pack 解析失败，跳过: %s (%s)", path, e)
                continue
            if not isinstance(data, dict):
                logger.warning("pack manifest 非映射，跳过: %s", path)
                continue
            missing = [k for k in PACK_REQUIRED_KEYS if k not in data]
            if missing:
                logger.warning("pack manifest 缺键 %s，跳过: %s", missing, path)
                continue
            if status_by_name.get(str(data["name"])) == "draft":
                continue  # 草稿不加载（正常状态，静默跳过）
            dir_point = path.parent.name
            if data["extension_point"] != dir_point:
                logger.warning(
                    "pack %s extension_point=%s 与目录 %s 不一致，按 manifest 归类",
                    data["name"], data["extension_point"], dir_point)
            manifest = PluginManifest.from_dict(data)
            self._packs.setdefault(manifest.extension_point, {})[manifest.name] = \
                _PluginEntry(manifest=manifest)

    @staticmethod
    def _load_pack_index(index_path: Path) -> dict[str, str]:
        """读 _index.yaml → {pack 名: status}；文件缺失/形态异常按无索引处理"""
        if not index_path.exists():
            return {}
        try:
            data = yaml.safe_load(index_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            logger.warning("pack _index.yaml 解析失败，按无索引处理: %s (%s)",
                           index_path, e)
            return {}
        if not isinstance(data, list):
            return {}
        status = {}
        for entry in data:
            if isinstance(entry, dict) and "pack" in entry:
                status[str(entry["pack"])] = str(entry.get("status", "active"))
        return status

    # =========================================================
    # 目录扫描 + 运行时重扫（P8.2）
    # =========================================================
    def scan_plugins(self, plugin_dir: str | Path) -> None:
        """递归扫描插件目录并注册（Kernel._load_plugins 的唯一入口）。

        - packs/ 子目录跳过 rglob 注册，改由 load_packs 宽松加载
          （其 _index.yaml 是清单而非 manifest，且 world.rule 等桶不在
          EXTENSION_POINTS 契约内，不能走 register）
        - P7.1 L2：active story.skill 包复用同一注册路径，
          与训练管线结晶同源可见
        - 记录 plugin_dir 供 reload() 复用
        """
        plugin_dir = Path(plugin_dir)
        self._plugin_dir = plugin_dir
        for path in plugin_dir.rglob("*.yaml"):
            if "packs" in path.relative_to(plugin_dir).parts:
                continue
            self.register(PluginManifest.load(path))
        # P7.1 L1：素材包分桶加载（draft 跳过、坏包 warning 不崩）
        self.load_packs(plugin_dir / "packs")
        for manifest in self.pack_manifests("story.skill"):
            self.register(manifest)

    def reload(self) -> None:
        """运行时重扫已挂载插件目录（清索引 → 重扫，幂等替换）。

        抽卡 confirm 落盘新 genre 后调用；懒实例化的 entry 随索引一并
        重建，下次 get/packs 按新 manifest 实例化。未挂载过目录时无操作。
        """
        if self._plugin_dir is None:
            return
        self._plugins = {}
        self._packs = {}
        self.scan_plugins(self._plugin_dir)

    def packs(self, extension_point: str) -> list["PluginInstance"]:
        """按扩展点查素材包实例（懒实例化，与 get 同一包装）"""
        instances = []
        for entry in self._packs.get(extension_point, {}).values():
            if entry.instance is None:
                entry.instance = self._instantiate(entry.manifest)
            instances.append(entry.instance)
        return instances

    def pack_manifests(self, extension_point: str) -> list[PluginManifest]:
        """按扩展点查素材包 manifest（L2 接线用）"""
        return [e.manifest
                for e in self._packs.get(extension_point, {}).values()]

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
