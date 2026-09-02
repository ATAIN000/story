"""Profile 分层 patch 测试（借鉴 DSH profile/组合包分层）。

验证项目级 patches.yaml 的 params 覆盖题材默认（项目层 > 题材层），
且不污染全局 registry、不影响其他项目。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from story_engine.engine import StoryEngine, _deep_merge


# ---------- _deep_merge 纯函数 ----------
def test_deep_merge_flat_override():
    base = {"a": 1, "b": 2}
    assert _deep_merge(base, {"a": 9}) == {"a": 9, "b": 2}
    assert base == {"a": 1, "b": 2}          # 不改 base


def test_deep_merge_nested():
    base = {"prompt": {"style": "A", "role": "X"}, "n": 1}
    out = _deep_merge(base, {"prompt": {"style": "B"}})
    assert out["prompt"] == {"style": "B", "role": "X"}   # 嵌套合并
    assert out["n"] == 1


def test_deep_merge_new_key():
    assert _deep_merge({"a": 1}, {"new": {"x": 1}}) == {"a": 1, "new": {"x": 1}}


# ---------- engine 项目 patch 应用 ----------
def _make_engine(tmp: Path) -> StoryEngine:
    import os
    os.environ.setdefault("STORY_ENGINE_EMBED_MODE", "dummy")
    os.environ.setdefault("STORY_ENGINE_SCRIPTED_DEMO", "1")
    return StoryEngine(str(tmp), genre_name="mystery")


def test_project_patch_overrides_genre_params():
    """patches.yaml 的 params 覆盖题材默认（项目层最优先）。"""
    tmp = Path(tempfile.mkdtemp())
    (tmp / "patches.yaml").write_text(
        "params:\n  beats_per_chapter: 99\n  custom_flag: hello\n",
        encoding="utf-8")
    eng = _make_engine(tmp)
    assert eng.bundle.genre_params.get("beats_per_chapter") == 99
    assert eng.bundle.genre_params.get("custom_flag") == "hello"
    eng.kernel.close()


def test_no_patch_file_params_unchanged():
    """无 patches.yaml → 题材默认原样（零影响）。"""
    tmp = Path(tempfile.mkdtemp())
    eng = _make_engine(tmp)
    # mystery 题材的默认 beats_per_chapter 应在（未被覆盖）
    assert "beats_per_chapter" in eng.bundle.genre_params
    assert eng.bundle.genre_params.get("custom_flag") is None
    eng.kernel.close()


def test_patch_does_not_pollute_registry():
    """项目 patch 是 engine 层应用，不动全局 registry（其他项目不受影响）。"""
    tmp = Path(tempfile.mkdtemp())
    (tmp / "patches.yaml").write_text(
        "params:\n  beats_per_chapter: 99\n", encoding="utf-8")
    eng1 = _make_engine(tmp)
    # 同 registry 的另一个项目（无 patch）不受影响
    tmp2 = Path(tempfile.mkdtemp())
    eng2 = StoryEngine(str(tmp2), genre_name="mystery")
    assert eng1.bundle.genre_params.get("beats_per_chapter") == 99
    assert eng2.bundle.genre_params.get("beats_per_chapter") != 99
    eng1.kernel.close()
    eng2.kernel.close()


def test_patch_bad_yaml_ignored():
    """损坏的 patches.yaml → 忽略不崩，题材默认生效。"""
    tmp = Path(tempfile.mkdtemp())
    (tmp / "patches.yaml").write_text("{{{{ 不是合法 yaml: [", encoding="utf-8")
    eng = _make_engine(tmp)
    assert eng.bundle.genre_params.get("beats_per_chapter") is not None
    eng.kernel.close()
