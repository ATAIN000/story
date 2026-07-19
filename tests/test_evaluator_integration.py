"""P4.6：Phase 4 验收 — evaluator 集成链路核心测试（用户指令：限 3 用例）

1. 蓝图 Module 6 验收链路（标准 2/6）：SCRIPTED_DEMO=0 + 可控 fake（非 mock）
   经公共 API generate_chapter 走 Actor 路径自评迭代：
   生成 → gate(L5) → critic 议会(verdict + quote 命中原文) → leader
   revision_plan(blocking) → 迭代第 2 轮收敛（best-of-K 取第 2 轮）。
   断言 evaluation 七键齐全、critiques 带原文命中 evidence、第 2 轮修正
   prompt 确实携带 leader must_fix、Actor 已提交事件零改写、快照章节记录
   同样携带 evaluation。
   接线说明（已知路由事实，task-15 报告 §5）：公共 API 下非剧本恒走 Actor
   路径（engine.py:159-165），自评经 `_iterate_display_text` 做 text-only
   迭代；直接 LLM 路径 `_generate_chapter_llm_path(scripted=False)` 经公共
   API 暂不可达，其 eval 分支已由 P4.5 私有路径自验覆盖（task-15 §4），
   故本用例验收公共可达的 Actor 路径。
2. mock/剧本路径（标准 5）：generate_chapter 返回 evaluation=None，
   自评组件零构造（哨兵）、零 LLM 调用（计数），快照一致。
3. EVAL_ENABLED=0（标准 5 变体）：非 mock fake + env 关闭 → 跳过自评
   （evaluation=None、零 critic/reader 调用），章节正常生成。

全部离线：fake LLM 剧本化分发，不触网、不调真 LLM/embedding。
"""
from __future__ import annotations

import asyncio
import json
import re
from types import SimpleNamespace

import pytest

from story_engine.engine import StoryEngine

# ---------- 剧本化章节文本（过 L5：首行标题 / 800-1200 非空白字 / 句末标点） ----------
SUSPECT_V1 = "刘伯嘴角勾起一抹冷笑，坚称案发夜未曾离开王府半步。"
EVIDENCE_V1 = "坚称案发夜未曾离开王府半步"          # ⊂ SUSPECT_V1 ⊂ TEXT_V1
SUSPECT_V2 = "展昭将玉佩拓片呈上公堂，包拯细察其上纹路，刘伯伏地战栗。"
FIX_DIRECTIVE = "补一段刘伯从王员外口中得知失窃详情的合法信息渠道"
EVAL_FEEDBACK_MARK = "自评反馈"      # engine 注入「自评反馈（必须逐条处理）」段


def _chapter_text(title: str, marker: str) -> str:
    filler = "夜色深沉，更鼓声自远处传来，府衙内外一片肃然。"
    lines = [f"标题：{title}", "", marker]
    while len(re.sub(r"\s", "", "\n".join(lines))) < 880:
        lines.append(filler)
    lines.append("包拯沉吟片刻，提笔在卷宗上落下一行小字。")
    return "\n".join(lines) + "\n"


TEXT_V1 = _chapter_text("公堂初审", SUSPECT_V1)   # 违规修正版 = 自评第 1 轮底稿
TEXT_V2 = _chapter_text("公堂再审", SUSPECT_V2)   # 自评第 2 轮修正版（收敛）

# ---------- fake LLM 剧本 ----------
# Actor propose：motivation「无端猜疑」不可追溯 → 强制 causal 违规（确定性），
# 使违规修正块先行、自评底稿=可控的 TEXT_V1
PROPOSE_JSON = json.dumps(
    [{"action": "暗访聚宝赌坊", "summary": "暗访聚宝赌坊查探刘伯行踪",
      "motivation": "无端猜疑"}], ensure_ascii=False)

JUDGE_RESP_V1 = f"- quote: {SUSPECT_V1}\n  reason: 刘伯的否认缺乏合法信息渠道铺垫\n"
JUDGE_RESP_V2 = f"- quote: {SUSPECT_V2}\n  reason: 呈堂一段节奏可再打磨\n"

# 第 1 轮：高优先级维 plot_coherence FAIL（blocking），evidence 命中 TEXT_V1 原文
CRITIC_FAIL_PLOT_YAML = (
    "verdict: FAIL\n"
    f"evidence:\n  - {EVIDENCE_V1}\n"
    f"fix_directive: {FIX_DIRECTIVE}\n"
    "executable: yes\n")
# 第 2 轮：全维 PASS，evidence 命中 TEXT_V2 原文（quote 过滤后保留）
CRITIC_PASS_YAML = (
    "verdict: PASS\n"
    f"evidence:\n  - {SUSPECT_V2}\n"
    "fix_directive: 无\n"
    "executable: yes\n")

READER_RESP = "1. yes\n2. 包拯\n3. 刘伯的赌债将被揭开\n4. 4 4 4\n5. 无\n"

EVAL_PURPOSES = ("critic_judge", "reader_proxy")


class ScriptedFakeLLM:
    """按 purpose/prompt 内容分发剧本响应的可控伪 LLM（签名对齐 LLMPool.call）。

    is_mock=False（类属性，对齐 LLMPool.is_mock 的属性访问方式）以通过自评
    门控第二条件；全部响应离线剧本化。call_log/model 供 project_snapshot 读取。
    """

    is_mock = False
    model = "scripted-fake"

    def __init__(self):
        self.calls: list[tuple[str, str]] = []   # (purpose, prompt)
        self.call_log: list[dict] = []

    async def call(self, prompt: str, *, purpose: str = "generate",
                   temperature: float = 0.7, max_tokens: int = 8192):
        self.calls.append((purpose, prompt))
        self.call_log.append({"purpose": purpose, "model": self.model})
        return SimpleNamespace(text=self._respond(purpose, prompt),
                               model=self.model)

    @staticmethod
    def _respond(purpose: str, prompt: str) -> str:
        if purpose.startswith("propose:"):
            return PROPOSE_JSON
        if purpose.startswith("reflect:"):
            return ""
        if purpose == "correct_chapter":
            # 违规修正块（无自评反馈段）→ V1；自评迭代轮（带 leader must_fix）→ V2
            return TEXT_V2 if EVAL_FEEDBACK_MARK in prompt else TEXT_V1
        if purpose in ("extract_events", "extract_corrected_events"):
            return "[]"
        if purpose == "critic_judge":
            return JUDGE_RESP_V2 if SUSPECT_V2 in prompt else JUDGE_RESP_V1
        if purpose.startswith("critic_"):
            if SUSPECT_V2 in prompt:            # 第 2 轮：全维 PASS
                return CRITIC_PASS_YAML
            if purpose == "critic_plot_coherence":   # 第 1 轮：blocking FAIL
                return CRITIC_FAIL_PLOT_YAML
            return ""        # 其余维度第 1 轮不可解析 → 该 critique 丢弃
        if purpose == "reader_proxy":
            return READER_RESP
        return ""


def _eval_purpose_calls(fake: ScriptedFakeLLM) -> list[str]:
    return [p for p, _ in fake.calls
            if p in EVAL_PURPOSES or p.startswith("critic_")]


async def _generate_and_stop(eng: StoryEngine):
    """生成一章并在同一 event loop 内停掉 Actor 循环（清理）"""
    try:
        return await eng.generate_chapter()
    finally:
        await eng.kernel.scheduler.stop_all()


def run(coro):
    return asyncio.run(coro)


# ---------- 用例 ①：蓝图 Module 6 验收链路（标准 2/6） ----------
def test_blueprint_acceptance_chain_actor_path(monkeypatch, tmp_path):
    """可控 fake 下完整链路：生成→gate→critic(quote 命中原文)→leader blocking
    →第 2 轮收敛；evaluation 七键齐全；事件历史零改写；快照携带 evaluation"""
    monkeypatch.setenv("STORY_ENGINE_SCRIPTED_DEMO", "0")
    monkeypatch.setenv("STORY_ENGINE_EVAL_ENABLED", "1")
    monkeypatch.setenv("STORY_ENGINE_ACTOR_MAX_TICKS", "1")
    fake = ScriptedFakeLLM()
    eng = StoryEngine(str(tmp_path), llm_client=fake)
    # 门控三条件齐备（SCRIPTED_DEMO=0 + 非 mock + EVAL_ENABLED!=0）
    assert eng._eval_enabled() is True

    rec = run(_generate_and_stop(eng))
    snap = eng.project_snapshot()
    eng.kernel.close()

    # —— 章节正常产出；违规修正块先行（motivation 剧本强制 causal 违规）——
    assert rec["generation_mode"] == "actor"
    assert rec["draft"]["violation_count"] >= 1
    assert rec["correction"] is not None
    assert rec["final"]["text"].strip()
    # 返回体原字段齐全（决策6 只增不改）：抽验既有键 + 新增 evaluation
    for key in ("chapter", "title", "decision_card", "draft", "correction",
                "final", "foreshadow_updates", "snapshot_id", "tick_range"):
        assert key in rec, f"返回体缺既有键 {key}"

    # —— 事件历史零改写：5 角色 × 1 tick 的行动事件，迭代不增改事件 ——
    committed = rec["final"]["committed_events"]
    assert len(rec["actor_actions"]) == 5
    assert len(committed) == 5
    assert all(e["event_type"] == "character_action" for e in committed)

    # —— 决策6：evaluation 七键齐全 ——
    ev = rec["evaluation"]
    assert ev is not None
    for key in ("rounds", "best_round", "gates", "critiques",
                "revision", "reader", "score"):
        assert key in ev, f"evaluation 缺键 {key}"

    # —— 迭代收敛：第 1 轮 leader blocking → 第 2 轮收敛，best-of-K 取第 2 轮 ——
    assert ev["rounds"] == 2
    assert ev["best_round"] == 1
    assert ev["gates"] == [{"layer": "L5", "passed": True, "failures": {}}]
    assert ev["revision"]["blocking"] is False

    # leader 的 blocking must_fix 确实作为 feedback 进入第 2 轮修正 prompt
    fb_prompts = [p for purpose, p in fake.calls
                  if purpose == "correct_chapter" and EVAL_FEEDBACK_MARK in p]
    assert len(fb_prompts) == 1
    assert FIX_DIRECTIVE in fb_prompts[0]

    # best 版本 = 第 2 轮文本（首行标题已被引擎剥离）；第 1 轮句子不在其中
    final_text = rec["final"]["text"]
    assert SUSPECT_V2 in final_text
    assert SUSPECT_V1 not in final_text

    # —— critiques 带原文命中的 evidence（quote 过滤在接线层真实生效）——
    assert len(ev["critiques"]) == 4      # mystery active_critics 4 维全 PASS
    assert {c["dimension"] for c in ev["critiques"]} == {
        "plot_coherence", "character_motivation",
        "setting_consistency", "cliche_detection"}
    for c in ev["critiques"]:
        assert c["verdict"] == "PASS"
        assert c["evidence"]
        for q in c["evidence"]:
            assert q in final_text

    # —— reader / score（展示层聚合随返回体给出）——
    assert ev["reader"]["engagement"] == 4
    assert ev["score"]["critic_pass_rate"] == "4/4"
    assert ev["score"]["overall"] == pytest.approx(1.0)
    assert ev["score"]["reader_engagement"] == pytest.approx(4.0)
    assert len(ev["reader_predictions"]) == 2

    # —— LLM 调用账目：2 轮 × (judge + 4 critic + reader) ——
    purposes = [p for p, _ in fake.calls]
    assert purposes.count("critic_judge") == 2
    assert purposes.count("reader_proxy") == 2
    assert purposes.count("critic_plot_coherence") == 2

    # —— 快照章节记录同样携带 evaluation（标准 6）——
    assert snap["chapters"][0]["evaluation"]["rounds"] == 2
    assert snap["chapters"][0]["evaluation"]["best_round"] == 1


# ---------- 用例 ②：mock/剧本路径零自评（标准 5） ----------
def test_mock_scripted_path_zero_evaluation(monkeypatch, tmp_path):
    """mock 剧本路径：evaluation=None、自评组件零构造（哨兵）、零 LLM 调用"""
    monkeypatch.setenv("STORY_ENGINE_SCRIPTED_DEMO", "1")
    monkeypatch.setenv("STORY_ENGINE_LLM_MODE", "mock")  # 防真实环境 key 泄漏
    eng = StoryEngine(str(tmp_path))

    # 哨兵：自评组件一旦被构造即测试失败
    def _boom(*_args, **_kwargs):
        raise AssertionError("mock/剧本路径不得构建自评组件")
    monkeypatch.setattr(StoryEngine, "_build_eval_controller", _boom)
    # 计数：任何 LLM 调用（含自评）都会被记录
    llm_calls: list[str] = []
    orig_call = eng.llm.call

    async def _counting(prompt, **kwargs):
        llm_calls.append(kwargs.get("purpose", "generate"))
        return await orig_call(prompt, **kwargs)
    monkeypatch.setattr(eng.llm, "call", _counting)

    assert eng._eval_enabled() is False
    rec = run(eng.generate_chapter())
    snap = eng.project_snapshot()
    eng.kernel.close()

    assert rec["generation_mode"] == "scripted"
    assert rec["final"]["text"].strip()          # 章节正常产出
    assert rec["evaluation"] is None             # 标准 5：evaluation=None
    assert llm_calls == []                       # 零 LLM 调用（剧本直连 mock_script）
    assert snap["chapters"][0]["evaluation"] is None   # 快照一致


# ---------- 用例 ③：EVAL_ENABLED=0 跳过自评（标准 5 变体） ----------
def test_eval_disabled_env_skips_evaluation(monkeypatch, tmp_path):
    """非 mock fake + EVAL_ENABLED=0：跳过自评（evaluation=None、零
    critic/reader 调用），章节经 Actor 路径正常生成"""
    monkeypatch.setenv("STORY_ENGINE_SCRIPTED_DEMO", "0")
    monkeypatch.setenv("STORY_ENGINE_EVAL_ENABLED", "0")
    monkeypatch.setenv("STORY_ENGINE_ACTOR_MAX_TICKS", "1")
    fake = ScriptedFakeLLM()
    eng = StoryEngine(str(tmp_path), llm_client=fake)
    assert eng._eval_enabled() is False          # env 关闭 → 门控不通过

    rec = run(_generate_and_stop(eng))
    eng.kernel.close()

    assert rec["generation_mode"] == "actor"
    assert rec["evaluation"] is None             # 无迭代痕迹
    assert rec["final"]["text"].strip()          # 章节正常生成
    assert len(rec["final"]["committed_events"]) == 5
    assert _eval_purpose_calls(fake) == []       # 零自评 LLM 调用
    # 生成通道本身确实跑过（非 mock 全链路，不是空转）
    assert any(p.startswith("propose:") for p, _ in fake.calls)
