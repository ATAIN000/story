"""tests/test_macro.py — P17.1 + P17.2 核心测试（≤6 用例）

P17.1: compute_acts 映射 / MacroPlan round-trip / 全 7 模板合法
P17.2: mock 兜底产出合法 MacroPlan / prompt 含世界观+人物上下文 / 解析失败→兜底
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from story_engine.macro import (
    TEMPLATES, MacroPlan, compute_acts, generate_macro_plan,
    macro_plan_to_dict,
)
from story_engine.types import GenreBundle

from conftest import import_backend_main


def run(coro):
    return asyncio.run(coro)


# ============================================================
# P17.1: 数据层 + 模板
# ============================================================

def test_compute_acts_maps_beats_correctly():
    """save_the_cat_15 × 60 集：midpoint 在 ep 30、首 beat ep=1、末幕 end=60"""
    struct = compute_acts("save_the_cat_15", 60)
    assert struct.template == "save_the_cat_15"
    assert len(struct.acts) == 4

    # 首幕首 beat
    first_beat = struct.acts[0].beats[0]
    assert first_beat.name == "opening_image"
    assert int(first_beat.ep) == 1

    # midpoint ≈ ep 30（50% × 60）
    act2a = struct.acts[1]  # act_2a_rising
    midpoint = [b for b in act2a.beats if b.name == "midpoint"][0]
    assert int(midpoint.ep) == 30

    # 末幕 end 恒等于 total_episodes
    assert struct.acts[-1].episode_range[1] == 60


def test_macro_plan_round_trip():
    """MacroPlan dataclass → dict → 检查全部六大组件字段在"""
    plan = MacroPlan()
    plan.blueprint.logline = "测试故事"
    plan.blueprint.thematic_argument.lie = "谎言"
    plan.blueprint.thematic_argument.truth = "真相"
    plan.episode_outlines  # default empty list

    d = macro_plan_to_dict(plan)
    assert d["blueprint"]["logline"] == "测试故事"
    assert d["blueprint"]["thematic_argument"]["lie"] == "谎言"
    assert "act_structure" in d
    assert "episode_outlines" in d
    assert "arc_schedule" in d
    assert "foreshadow_blueprint" in d
    assert "pacing_curve" in d
    assert "revision_log" in d


def test_all_seven_templates_produce_valid_structures():
    """全部 7 模板 × 不同总集数 → act/beats 非空、episode_range 连续、beat 在 act 范围内"""
    for name in TEMPLATES:
        struct = compute_acts(name, 24)
        assert struct.template == name
        assert len(struct.acts) >= 2, f"{name} acts 为空"
        for act in struct.acts:
            assert len(act.beats) >= 1, f"{name} {act.id} beats 为空"
            s, e = act.episode_range
            assert 1 <= s <= e <= 24
            for beat in act.beats:
                ep = int(beat.ep)
                assert s <= ep <= e, f"{name} beat {beat.name} ep={ep} 超出 [{s},{e}]"


# ============================================================
# P17.2: 生成器
# ============================================================

def _mock_kernel(is_mock: bool = True):
    """构造伪 kernel：is_mock 控制 LLM 路由"""
    llm = SimpleNamespace(is_mock=is_mock)
    return SimpleNamespace(llm=llm)


def _bundle():
    return GenreBundle(
        genre="mystery", culture="confucian_officialdom", target_length=10,
        genre_params={"title": "悬疑", "resolution_pattern": "推理破案",
                      "main_track": "A"},
    )


def _cast():
    return [{"name": "陆明", "role": "主角", "persona": {
        "arc_lie": "信任等于软弱", "arc_truth": "连接才是力量",
        "arc_want": "破案", "arc_need": "学会信任", "arc_type": "positive_change"}}]


def test_mock_fallback_produces_valid_plan():
    """mock 模式（kernel.llm.is_mock=True）→ 规则化骨架，含 10 集大纲 + 1 角色 + 2 伏笔"""
    kernel = _mock_kernel(is_mock=True)
    plan = run(generate_macro_plan(kernel, _bundle(), None, _cast(),
                                   "save_the_cat_15"))
    assert isinstance(plan, MacroPlan)
    assert plan.blueprint.total_episodes == 10
    assert len(plan.episode_outlines) == 10
    assert len(plan.arc_schedule.characters) == 1
    assert plan.arc_schedule.characters[0].name == "陆明"
    assert len(plan.foreshadow_blueprint.threads) >= 2  # P1-2: 骨架现在生成5条多样化伏笔
    assert len(plan.act_structure.acts) == 4


class _RecordingLLM:
    """非 mock 伪 LLM：记录 prompt，返回指定 text"""
    def __init__(self, text: str):
        self._text = text
        self.prompt = ""

    async def __call__(self, prompt, **kw):
        self.prompt = prompt
        return SimpleNamespace(text=self._text)


def test_prompt_contains_worldview_and_cast_context():
    """非 mock 模式：LLM prompt 含题材、人物弧光、模板 beat 信息"""
    llm_call = _RecordingLLM("invalid: not yaml")
    kernel = SimpleNamespace(
        llm=SimpleNamespace(is_mock=False), llm_call=llm_call)
    run(generate_macro_plan(kernel, _bundle(), None, _cast(),
                            "save_the_cat_15"))
    prompt = llm_call.prompt
    assert "悬疑" in prompt or "mystery" in prompt  # P18: prompt 用中文 title
    assert "陆明" in prompt
    assert "信任等于软弱" in prompt  # arc_lie
    assert "save_the_cat_15" in prompt
    assert "midpoint" in prompt


def test_parse_failure_falls_back_to_skeleton():
    """非 mock 模式但 LLM 产出非法 YAML → 回退规则化骨架"""
    llm_call = _RecordingLLM("这完全不是 YAML [[[")
    kernel = SimpleNamespace(
        llm=SimpleNamespace(is_mock=False), llm_call=llm_call)
    plan = run(generate_macro_plan(kernel, _bundle(), None, _cast(),
                                   "three_act_classic"))
    assert isinstance(plan, MacroPlan)
    # 兜底骨架一定有 10 集大纲（total_episodes 来自 bundle）
    assert len(plan.episode_outlines) == 10
    assert len(plan.act_structure.acts) == 3  # three_act_classic


# ============================================================
# P17.3: 端点 + 落盘
# ============================================================

def test_macro_templates_endpoint():
    """GET /api/macro/templates → 7 模板，每项含 name + beat_count"""
    backend = import_backend_main()
    from fastapi.testclient import TestClient
    with TestClient(backend.app) as c:
        resp = c.get("/api/macro/templates")
    assert resp.status_code == 200
    items = resp.json()["templates"]
    assert len(items) == 7
    names = {t["name"] for t in items}
    assert "save_the_cat_15" in names
    for t in items:
        assert t["beat_count"] >= 1


def test_macro_plan_generate_endpoint():
    """POST /api/macro/plan → P20 起已废弃（410）；WebSocket 替代。
    改测 session-based begin → WebSocket 不走 TestClient（需 ws），
    故此处验证旧端点返回 410。"""
    backend = import_backend_main()
    from fastapi.testclient import TestClient
    with TestClient(backend.app) as c:
        resp = c.post("/api/macro/plan", json={
            "template_name": "save_the_cat_15",
        })
    assert resp.status_code == 410


def test_as_episode_list_coerces_llm_shapes():
    """LLM 把 plant_episodes 写成标量/字符串时需规范成 list[int]。"""
    from story_engine.macro.generator import _as_episode_list, _as_episode_int, _build_plan

    assert _as_episode_list(None) == []
    assert _as_episode_list(3) == [3]
    assert _as_episode_list("1, 3，5") == [1, 3, 5]
    assert _as_episode_list({"x": 2, "y": 8}) == [2, 8]
    assert _as_episode_int("第12集") == 12

    parsed = {
        "story_blueprint": {
            "logline": "x", "thematic_argument": {}, "central_conflict": {},
            "total_episodes": 12,
        },
        "act_structure": {"acts": []},
        "episode_outlines": [{"episode": 1, "title": "t"}],
        "arc_schedule": {"characters": []},
        "foreshadow_blueprint": {
            "threads": [{
                "id": "f1", "name": "伏",
                "plant_episodes": "2,4",
                "harvest_episode": "10",
                "salience_ladder": "not-a-list",
            }],
        },
        "pacing_curve": {"key_tension_points": []},
    }
    plan = _build_plan(parsed, "save_the_cat_15", 12)
    t = plan.foreshadow_blueprint.threads[0]
    assert t.plant_episodes == [2, 4]
    assert t.harvest_episode == 10
    assert t.salience_ladder == []


def test_cast_summary_accepts_none_and_id_field():
    """P20 修复：cast=None 不崩；前端 id 字段可当人名。"""
    from story_engine.macro.generator import _cast_summary, _build_prompt
    from story_engine.types import GenreBundle

    assert _cast_summary(None) == ""
    assert _cast_summary([]) == ""
    text = _cast_summary([{"id": "沈昭", "role": "主角", "persona": {}}])
    assert "沈昭" in text

    bundle = GenreBundle(
        genre="mystery", culture="test",
        genre_params={"title": "测试"}, culture_params={},
    )
    prompt = _build_prompt(bundle, None, None, "save_the_cat_15", 12, None)
    assert isinstance(prompt, str) and len(prompt) > 50


def test_macro_stream_ws_without_cast_completes():
    """WS macro/stream 无 cast 字段时不应 TypeError 断连，应收到 complete。"""
    backend = import_backend_main()
    from fastapi.testclient import TestClient
    with TestClient(backend.app) as c:
        r = c.post("/api/gacha/begin", json={"genre_name": "mystery"})
        assert r.status_code == 200
        sid = r.json()["session_id"]
        with c.websocket_connect(f"/api/gacha/{sid}/macro/stream") as ws:
            ws.send_json({"template_name": "save_the_cat_15"})
            saw_complete = False
            # mock 骨架 JSON 按 80 字切片，可能数百帧 delta
            for _ in range(500):
                msg = ws.receive_json()
                if msg.get("type") == "complete":
                    assert isinstance(msg.get("plan"), dict)
                    saw_complete = True
                    break
            assert saw_complete, "未收到 complete（可能仍因 cast=None 崩溃）"


def test_llm_call_stream_mock_mode():
    """P20: LLMPool.call_stream mock 模式 → 逐 chunk yield delta text。"""
    import asyncio
    from story_engine.kernel.llm_pool import LLMPool
    pool = LLMPool(mode="mock")
    assert pool.is_mock

    async def collect():
        chunks = []
        async for chunk in pool.call_stream(
                "【CHAPTER=1】test", purpose="generate_chapter"):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(collect())
    assert len(chunks) > 0
    full = "".join(chunks)
    assert len(full) > 0  # mock 产出了非空文本


def test_macro_plan_get_404_without_file():
    """GET /api/macro/plan → 临时项目无 macro_plan.json → 404"""
    backend = import_backend_main()
    from fastapi.testclient import TestClient
    with TestClient(backend.app) as c:
        resp = c.get("/api/macro/plan")
    assert resp.status_code == 404


# ============================================================
# P17.4: macro_context 构建 + 无计划时 None
# ============================================================

def test_build_macro_context_for_chapter():
    """engine._build_macro_context(N) 从 macro_plan.json 提取正确 beat/synopsis/arc"""
    import json
    import tempfile
    from pathlib import Path
    from story_engine.engine import StoryEngine

    plan = macro_plan_to_dict(run(generate_macro_plan(
        _mock_kernel(True), _bundle(), None, _cast(), "save_the_cat_15")))
    # 确保第 5 集有 outline
    assert any(e["episode"] == 5 for e in plan["episode_outlines"])

    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "macro_plan.json").write_text(
            json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        kernel = SimpleNamespace(
            llm=SimpleNamespace(is_mock=True),
            project_dir=Path(td))
        # 最小化构造：只需 project_dir 即可测试 _build_macro_context
        engine = StoryEngine.__new__(StoryEngine)
        engine.project_dir = Path(td)
        ctx = engine._build_macro_context(5)
    assert ctx is not None
    assert ctx["episode_synopsis"]  # 第 5 集有梗概
    assert ctx["act"]  # 落在某个 act 内


def test_build_macro_context_none_without_plan():
    """无 macro_plan.json → _build_macro_context 返回 None（零行为变化）"""
    import tempfile
    from pathlib import Path
    from story_engine.engine import StoryEngine

    with tempfile.TemporaryDirectory() as td:
        engine = StoryEngine.__new__(StoryEngine)
        engine.project_dir = Path(td)
        ctx = engine._build_macro_context(1)
    assert ctx is None
