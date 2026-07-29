"""P5.11：Phase 5 验收 — IR-first 集成链路核心测试（用户指令：限 3 用例）

1. chapter≥2 Actor 路径：fake LLM 下连生成第 1/2 章，第 2 章断言
   - narrative_ir 摘要非 None 且 events == 本章实际提交的 actor 事件数
     （_ChapterClosingKernelView 虚拟闭合让章切片覆盖进行中本章——不生效则
     切出空区间 events=0；合成闭合 beat 已过滤——泄漏则 events 多 1，
     传导 1/3/5 闭环）
   - Realizer prompt 不含 act:narrative_beat（合成闭合 beat 不进 prompt）
   - IR-first 产出首行「标题：」（engine 侧补行）且过真实 L5 门（genre
     style 字数区间），L5 不再恒 FAIL（传导 1 闭环）
2. structural 经 API 重生成（P5.10 评审传导）：TestClient 生成第 1 章（剧本
   路径，离线）→ POST /api/intervene(structural remove_event) →
   regenerated=True + 章节被重跑（旧记录 superseded、新记录顶上、
   被删事件 active=False）
3. IR_FIRST=0 回退：env 关闭 → narrative_ir=None + 旧汇总渲染文本 +
   IR 组件零构造（哨兵）零 realize 调用（回归保险）

全部离线：fake LLM 剧本化分发；API 用例走 SCRIPTED_DEMO=1 剧本章。
"""
from __future__ import annotations

import asyncio
import json
import re
from types import SimpleNamespace

import pytest

from story_engine.engine import StoryEngine
from story_engine.evaluator import ProcessGate

# backend.main 导入隔离样板见 conftest.import_backend_main（env 快照/还原 +
# 临时项目目录 + kernel 单例 atexit 收尾）；本文件与 test_hitl_api 共享单例
from conftest import import_backend_main

backend = import_backend_main()

# ---------- fake LLM（签名对齐 LLMPool.call，is_mock=False 过门控） ----------
PROPOSE_JSON = json.dumps(
    [{"action": "暗访赌坊", "summary": "暗访聚宝赌坊查探刘伯行踪"}],
    ensure_ascii=False)


def _ir_chapter_body() -> str:
    """Realizer 产出的正文（故意不产标题行——引擎补行是传导1的验证点）；
    非空白字数落在 genre style「800-1200字」区间内，句末标点收尾"""
    filler = "夜色深沉，更鼓声自远处传来，府衙内外一片肃然。"
    lines = ["展昭潜入聚宝赌坊，暗中记下刘伯出入的时辰。"]
    while len(re.sub(r"\s", "", "\n".join(lines))) < 880:
        lines.append(filler)
    lines.append("包拯听罢沉吟片刻，提笔在卷宗上落下一行小字。")
    return "\n".join(lines)


class ScriptedFakeLLM:
    """按 purpose 分发的可控伪 LLM：propose → 1 条行动 JSON（不带 motivation
    等字段，7 步验证全过、不触发修正回路）；realize → 无标题行的长正文。"""

    is_mock = False
    model = "scripted-fake"

    def __init__(self):
        self.calls: list[tuple[str, str]] = []   # (purpose, prompt)
        self.call_log: list[dict] = []

    async def call(self, prompt: str, *, purpose: str = "generate",
                   temperature: float = 0.7, max_tokens: int = 8192):
        self.calls.append((purpose, prompt))
        self.call_log.append({"purpose": purpose, "model": self.model})
        return SimpleNamespace(text=self._respond(purpose), model=self.model)

    @staticmethod
    def _respond(purpose: str) -> str:
        if purpose.startswith("propose:"):
            return PROPOSE_JSON
        if purpose == "realize_chapter":
            return _ir_chapter_body()
        return ""


async def _gen_chapters(eng: StoryEngine, n: int) -> list[dict]:
    """同一 event loop 内连生成 n 章，最后停掉 Actor 循环（清理）"""
    try:
        return [await eng.generate_chapter() for _ in range(n)]
    finally:
        await eng.kernel.scheduler.stop_all()


def run(coro):
    return asyncio.run(coro)


# ---------- 用例 ①：chapter≥2 Actor 路径 IR-first（传导 1/3/5） ----------
def test_actor_path_chapter2_ir_first(monkeypatch, tmp_path):
    monkeypatch.setenv("STORY_ENGINE_SCRIPTED_DEMO", "0")
    monkeypatch.setenv("STORY_ENGINE_IR_FIRST", "1")
    monkeypatch.setenv("STORY_ENGINE_EVAL_ENABLED", "0")   # 隔离自评，聚焦 IR
    monkeypatch.setenv("STORY_ENGINE_ACTOR_MAX_TICKS", "1")
    fake = ScriptedFakeLLM()
    eng = StoryEngine(str(tmp_path), llm_client=fake)
    assert eng._ir_first_enabled() is True

    rec1, rec2 = run(_gen_chapters(eng, 2))
    eng.kernel.close()

    assert rec2["generation_mode"] == "actor"
    assert rec2["chapter"] == 2

    # —— 虚拟闭合生效：第 2 章 IR 事件切片非空，且 == 本章实际提交的 actor
    #    事件数（闭合标记不生效则 0；合成闭合 beat 泄漏则多 1）——
    ir2 = rec2["narrative_ir"]
    assert ir2 is not None
    committed2 = rec2["final"]["committed_events"]
    assert len(committed2) > 0
    assert ir2["events"] == len(committed2)
    for key in ("beats", "events", "dialogue", "language",
                "texture", "pov", "order"):
        assert key in ir2, f"narrative_ir 摘要缺键 {key}"

    # —— 合成闭合 beat 不进 Realizer prompt（world act:narrative_beat 噪声）——
    realize_prompts = [p for purpose, p in fake.calls
                       if purpose == "realize_chapter"]
    assert len(realize_prompts) == 2          # 每章恰好 1 次 Realizer 调用
    assert all("act:narrative_beat" not in p for p in realize_prompts)

    # —— 传导 1：引擎补标题行，IR-first 产出过真实 L5 门（不再恒 FAIL）——
    draft2 = rec2["draft"]["text"]
    assert re.match(r"^标题：\S+", draft2.splitlines()[0])
    gate = run(ProcessGate(
        style=eng._prompt_config()["style"]).check_l5(draft2))
    assert gate.passed, f"L5 仍 FAIL：{gate.failures}"

    # —— 标题解析链路一致：首行标题被剥离、record.title 取到 ——
    assert rec2["title"].startswith("第2章")
    assert not rec2["final"]["text"].startswith("标题：")
    # 第 1 章同样走通 IR-first（摘要非 None）
    assert rec1["narrative_ir"] is not None


# ---------- 用例 ②：structural 经 API 重生成（P5.10 评审传导） ----------
def test_structural_intervene_via_api_regenerates():
    from fastapi.testclient import TestClient

    with TestClient(backend.app) as client:
        # 生成第 1 章（剧本路径 SCRIPTED_DEMO=1：纯离线，不触 LLM）
        r = client.post("/api/project/generate")
        assert r.status_code == 200, r.text
        rec = r.json()
        assert rec["generation_mode"] == "scripted"
        committed = rec["final"]["committed_events"]
        assert committed
        target_id = committed[0]["event_id"]

        # structural remove_event → rolled_back + 章级重生成
        r = client.post("/api/intervene", json={
            "type": "structural", "reason": "删掉开场多余情节",
            "payload": {"action": "remove_event", "event_id": target_id}})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["regenerated"] is True

        # 章节被重跑：旧记录 superseded、新第 1 章记录顶上
        chapters = backend.deps.engine._read_chapters()
        ch1 = [c for c in chapters if c["chapter"] == 1]
        assert len(ch1) == 2
        assert ch1[0]["superseded"] is True
        assert not ch1[1].get("superseded")

        # 被删事件（及其下游）active=False；重生成的章节重新提交了事件
        by_id = {e["event_id"]: e
                 for e in backend.deps.kernel.query_world("all_events")}
        assert by_id[target_id]["active"] is False
        assert ch1[1]["final"]["committed_events"]


# ---------- 用例 ③：IR_FIRST=0 回退（回归保险） ----------
def test_ir_first_disabled_falls_back(monkeypatch, tmp_path):
    monkeypatch.setenv("STORY_ENGINE_SCRIPTED_DEMO", "0")
    monkeypatch.setenv("STORY_ENGINE_IR_FIRST", "0")
    monkeypatch.setenv("STORY_ENGINE_EVAL_ENABLED", "0")
    monkeypatch.setenv("STORY_ENGINE_ACTOR_MAX_TICKS", "1")
    fake = ScriptedFakeLLM()
    eng = StoryEngine(str(tmp_path), llm_client=fake)
    assert eng._ir_first_enabled() is False

    # 哨兵：IR 组件一旦被构造即测试失败（零 IR 组件调用）
    import story_engine.engine as engine_mod

    def _boom(*_args, **_kwargs):
        raise AssertionError("IR_FIRST=0 时不得构造 IR 组件")
    for name in ("IRBuilder", "FabulaBuilder", "SjuzhetSelector", "Narrativizer"):
        monkeypatch.setattr(engine_mod, name, _boom)

    rec = run(_gen_chapters(eng, 1))[0]
    eng.kernel.close()

    assert rec["generation_mode"] == "actor"
    assert rec["narrative_ir"] is None                # 回退：无 IR 摘要
    assert rec["final"]["text"].strip()               # 旧路径正常产文本
    # 旧汇总渲染：文本由 actor 行动汇总而来（含行动 summary）
    assert "暗访聚宝赌坊查探刘伯行踪" in rec["final"]["text"]
    # 零 Realizer 调用（IR-first 唯一 LLM 入口未触达）
    assert all(purpose != "realize_chapter" for purpose, _ in fake.calls)


# ---------- 用例 ④：P24.6 行动数达标提前退出（性能） ----------
def test_actor_ticks_early_exit(monkeypatch, tmp_path):
    """max_ticks=5 但行动数达标即停：5 角色 2 轮收工（10 次 propose），
    未提前退出则需 25 次。"""
    monkeypatch.setenv("STORY_ENGINE_SCRIPTED_DEMO", "0")
    monkeypatch.setenv("STORY_ENGINE_IR_FIRST", "1")
    monkeypatch.setenv("STORY_ENGINE_EVAL_ENABLED", "0")
    monkeypatch.setenv("STORY_ENGINE_ACTOR_MAX_TICKS", "5")
    monkeypatch.delenv("STORY_ENGINE_ACTOR_TARGET_ACTIONS", raising=False)
    fake = ScriptedFakeLLM()
    eng = StoryEngine(str(tmp_path), llm_client=fake)
    rec = run(_gen_chapters(eng, 1))[0]
    eng.kernel.close()

    assert rec["generation_mode"] == "actor"
    proposes = [purpose for purpose, _ in fake.calls
                if purpose.startswith("propose:")]
    n_actors = len({p.split(":", 1)[1] for p in proposes})
    assert n_actors >= 2, "应至少 2 个角色 Actor"
    # 提前退出：≤2 轮（2×actors 次 propose）；跑满 5 轮则是 5×actors
    assert len(proposes) <= 2 * n_actors, \
        f"未提前退出？propose 次数={len(proposes)}（{n_actors} 角色）"


def test_actor_ticks_target_zero_runs_full(monkeypatch, tmp_path):
    """STORY_ENGINE_ACTOR_TARGET_ACTIONS=0 → 关闭提前退出，跑满 max_ticks。"""
    monkeypatch.setenv("STORY_ENGINE_SCRIPTED_DEMO", "0")
    monkeypatch.setenv("STORY_ENGINE_IR_FIRST", "1")
    monkeypatch.setenv("STORY_ENGINE_EVAL_ENABLED", "0")
    monkeypatch.setenv("STORY_ENGINE_ACTOR_MAX_TICKS", "3")
    monkeypatch.setenv("STORY_ENGINE_ACTOR_TARGET_ACTIONS", "0")
    fake = ScriptedFakeLLM()
    eng = StoryEngine(str(tmp_path), llm_client=fake)
    rec = run(_gen_chapters(eng, 1))[0]
    eng.kernel.close()

    assert rec["generation_mode"] == "actor"
    proposes = [purpose for purpose, _ in fake.calls
                if purpose.startswith("propose:")]
    n_actors = len({p.split(":", 1)[1] for p in proposes})
    assert len(proposes) == 3 * n_actors, \
        f"应跑满 3 轮：propose={len(proposes)}（{n_actors} 角色）"


# ---------- 用例 ⑤：markdown 标题行归一化（P25 修复） ----------
def test_markdown_title_line_normalized(monkeypatch, tmp_path):
    """LLM 产「# 标题：X」→ 归一化为约定格式：record.title 取到 X，
    正文不残留 markdown 标题行（此前被当成无标题补兜底，md 行残留+真标题丢失）。"""
    monkeypatch.setenv("STORY_ENGINE_SCRIPTED_DEMO", "0")
    monkeypatch.setenv("STORY_ENGINE_IR_FIRST", "1")
    monkeypatch.setenv("STORY_ENGINE_EVAL_ENABLED", "0")
    monkeypatch.setenv("STORY_ENGINE_ACTOR_MAX_TICKS", "1")

    class MdTitleFakeLLM(ScriptedFakeLLM):
        @staticmethod
        def _respond(purpose: str) -> str:
            if purpose == "realize_chapter":
                return "# 标题：矿底寒霜\n\n" + _ir_chapter_body()
            return ScriptedFakeLLM._respond(purpose)

    fake = MdTitleFakeLLM()
    eng = StoryEngine(str(tmp_path), llm_client=fake)
    rec = run(_gen_chapters(eng, 1))[0]
    eng.kernel.close()

    assert rec["title"] == "矿底寒霜", f"标题未取到：{rec['title']}"
    assert not rec["final"]["text"].startswith("#")
    assert "标题：腹中" not in rec["final"]["text"]
