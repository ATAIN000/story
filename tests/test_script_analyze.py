"""剧本反推开局（script_analyze）测试：prompt 构建 / 响应解析 / 端点契约。

全部离线：解析与 prompt 是纯函数；端点走 mock（conftest 强制 dummy embedding +
SCRIPTED_DEMO=1，LLM 响应由 mock_script.respond 的 script_analyze 分支提供）。
"""
from __future__ import annotations

import json

import pytest

from story_engine.meta.script_analyze import (
    build_analyze_prompt, parse_analyze_response, analyze_script,
    SCRIPT_MAX_CHARS)


# ---------- prompt 构建 ----------
def test_prompt_contains_script_note_catalog():
    p = build_analyze_prompt("甲：你杀了人。\n乙：我没有。", "要悬疑感",
                             exclude_genres=["mystery"])
    assert "甲：你杀了人" in p
    assert "要悬疑感" in p
    assert "mystery" in p and "换个方向" in p   # 排除清单
    assert "genre_id" in p                       # 输出契约
    # catalog 全量（315 题材）
    assert p.count("|") > 300


def test_prompt_empty_note_no_section():
    p = build_analyze_prompt("对话内容", "")
    assert "【作者补充】" not in p


# ---------- 响应解析 ----------
def test_parse_normal():
    text = json.dumps({
        "genre_id": "mystery", "reason": "理由", "culture": "confucian_officialdom",
        "preset": "hard_reality",
        "characters": [{"name": "沈砚清", "role": "主角", "traits": "冷静"}],
        "worldview_hints": {"conflict_type": "真相", "tone": "沉静"},
    }, ensure_ascii=False)
    r = parse_analyze_response(text)
    assert r["genre_id"] == "mystery"
    assert r["characters"][0]["name"] == "沈砚清"
    assert r["worldview_hints"]["tone"] == "沉静"


def test_parse_tolerates_surrounding_text():
    text = '好的，分析如下：\n{"genre_id": "wuxia", "characters": []}\n希望对你有帮助'
    r = parse_analyze_response(text)
    assert r is not None and r["genre_id"] == "wuxia"
    assert r["characters"] == []          # 空人物列表合法
    assert r["worldview_hints"] == {}     # 缺字段补空


def test_parse_filters_nameless_characters():
    text = '{"genre_id": "mystery", "characters": [{"name": ""}, {"name": "  "}, "bad", {"name": "包拯"}]}'
    r = parse_analyze_response(text)
    assert len(r["characters"]) == 1
    assert r["characters"][0]["name"] == "包拯"
    assert r["characters"][0]["role"] == "配角"   # 缺 role 补默认


@pytest.mark.parametrize("bad", ["", "没有JSON", "[1,2]", '{"no_genre": 1}', '{"genre_id": ""}'])
def test_parse_rejects_invalid(bad):
    assert parse_analyze_response(bad) is None


# ---------- 主函数（假 llm_call）----------
@pytest.mark.asyncio
async def test_analyze_script_fallback_title_match():
    """LLM 返回 title 而非 id 时，模糊回退到真实题材 id。"""
    class Resp:
        text = '{"genre_id": "末日情缘", "characters": [{"name": "陆离"}]}'

    async def fake_llm(prompt, **kw):
        return Resp()

    r = await analyze_script("对话", "", fake_llm)
    assert r is not None
    assert r["genre_id"] == "apocalypse-romance"   # title → id 回退


@pytest.mark.asyncio
async def test_analyze_script_unknown_genre_returns_none():
    class Resp:
        text = '{"genre_id": "不存在的题材xyz", "characters": []}'

    async def fake_llm(prompt, **kw):
        return Resp()

    assert await analyze_script("对话", "", fake_llm) is None


@pytest.mark.asyncio
async def test_analyze_script_empty_text_none():
    async def fake_llm(prompt, **kw):  # pragma: no cover
        raise AssertionError("空脚本不应调 LLM")
    assert await analyze_script("   ", "", fake_llm) is None


# ---------- 端点（mock 模式）----------
class TestAnalyzeEndpoint:
    def _client(self):
        from fastapi.testclient import TestClient
        from conftest import import_backend_main
        backend = import_backend_main()
        return TestClient(backend.app)

    def test_empty_script_422(self):
        c = self._client()
        r = c.post("/api/gacha/analyze_script", json={"script_text": "  "})
        assert r.status_code == 422
        assert "台词脚本" in r.json()["detail"]

    def test_mock_mode_full_structure(self):
        """mock 模式：mock_script.script_analyze 固定推荐 mystery，结构完整。
        backend 单例按 .env 真实配置为非 mock（见 conftest 注释），
        故临时把 pool.mode 拨回 mock，finally 还原。"""
        from conftest import import_backend_main
        backend = import_backend_main()
        pool = backend.deps.engine.kernel.llm
        saved_mode = pool.mode
        pool.mode = "mock"
        try:
            c = self._client()
            r = c.post("/api/gacha/analyze_script",
                       json={"script_text": "甲：大人，冤枉！\n乙：来人，带下去。"})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["genre"]["id"] == "mystery"
            assert body["genre"]["title"]          # taxon 展开非空
            assert body["genre"]["recommended_presets"]
            assert len(body["characters"]) >= 2
            assert body["characters"][0]["name"] == "沈砚清"
            assert body["reason"]
            assert body["worldview_hints"]["tone"]
        finally:
            pool.mode = saved_mode
