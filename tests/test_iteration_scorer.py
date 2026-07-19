"""P4.4：迭代控制器（3 轮 best-of-K）+ 展示层打分核心测试（用户指令：限 3 用例）

1. 蓝图验收核心：fake generate_fn 两轮（第 1 轮 leader 出 blocking revision →
   第 2 轮全 PASS）→ 收敛于第 2 轮、generate_fn 收到 must_fix feedback、
   best-of-K 选出正确版本
2. delta 无提升提前停：两轮都 blocking 且 must_fix 数不降 → 提前 break 不跑满
   3 轮（best-of-K 并列取最早，顺带证明 best 不是最后一版）；
   「not blocking 提前停」合并带过（第 1 轮全 PASS → 只跑 1 轮）
3. ScoreReport 聚合数值对拍：2 FAIL 5 PASS + mystery 已知权重 → overall 手算
   对拍；critic_pass_rate 格式；空 reader 曲线 engagement=3.0

全部离线：fake generate_fn + stub parliament/gates（leader 用真 LeaderArbiter，
纯规则无 LLM，顺带验证仲裁接线）。
"""
from __future__ import annotations

import asyncio

import pytest

from story_engine.evaluator import (
    ChapterSpec, Critique, Gate, IterationController, LeaderArbiter,
    PresentationScorer,
)


def run(coro):
    return asyncio.run(coro)


def critique(dim: str, verdict: str, fix: str = "") -> Critique:
    return Critique(dimension=dim, verdict=verdict, evidence=["某引文"],
                    fix_directive=fix, executable="yes")


class FakeParliament:
    """按序返回剧本 critiques 的 stub（不触 LLM）"""

    def __init__(self, script: list[list[Critique]]):
        self._script = list(script)

    async def assess(self, chapter, state=None):
        return self._script.pop(0) if self._script else []


class FakeGates:
    """恒定全 PASS 的 L5 stub（gate 规则本身由 test_process_gates.py 覆盖）"""

    async def check_l5(self, text):
        return Gate(layer="L5", passed=True, failures={})


def make_generate(feedbacks: list, calls: list):
    """fake generate_fn：记录每轮 feedback 与调用次数，返回带轮次标记的章节"""
    async def gen(spec, feedback=None):
        feedbacks.append(feedback)
        calls.append(1)
        return f"标题：第{len(calls)}轮\n\n正文{len(calls)}。"
    return gen


def test_converges_round2_with_feedback_and_best_of_k():
    """第 1 轮 blocking（setting_consistency FAIL）→ 第 2 轮全 PASS：
    收敛于第 2 轮；generate_fn 第 2 次调用收到 must_fix feedback；
    best-of-K 选出第 2 轮版本"""
    feedbacks, calls = [], []
    parliament = FakeParliament([
        [critique("setting_consistency", "FAIL", "改掉明清称谓")],  # 第 1 轮
        [],                                                        # 第 2 轮全 PASS
    ])
    ctrl = IterationController(
        parliament, LeaderArbiter(), FakeGates())
    result = run(ctrl.run(make_generate(feedbacks, calls), ChapterSpec()))

    assert len(result.all_versions) == 2            # 两轮都过 gate，均记版本
    assert len(calls) == 2                          # 第 2 轮收敛，不跑第 3 轮
    assert feedbacks == [None, ["改掉明清称谓"]]     # must_fix 成为下轮 feedback
    assert result.all_versions[0].revision.blocking is True
    assert result.all_versions[1].revision.blocking is False
    # best-of-K 选出第 2 轮（blocking False 优先）
    assert result.best is result.all_versions[1]
    assert result.best.round == 1
    assert "正文2" in result.best.text


def test_no_improvement_breaks_early_and_pass_breaks_round1():
    """两轮都 blocking 且 must_fix 数不降（2→2）→ delta 无提升提前 break，
    不跑满 3 轮；并列时 best-of-K 取最早版本（best 不是最后一版）"""
    feedbacks, calls = [], []
    parliament = FakeParliament([
        [critique("plot_coherence", "FAIL", "补因果链"),
         critique("theme_depth", "FAIL", "补主题")],               # must_fix ×2
        [critique("plot_coherence", "FAIL", "仍补因果链"),
         critique("sensory_detail", "FAIL", "补感官")],            # must_fix ×2 不降
        [critique("plot_coherence", "FAIL", "不该跑到")],           # 不应被消费
    ])
    ctrl = IterationController(parliament, LeaderArbiter(), FakeGates())
    result = run(ctrl.run(make_generate(feedbacks, calls), ChapterSpec()))

    assert len(calls) == 2                          # 提前 break，不跑第 3 轮
    assert len(result.all_versions) == 2
    assert all(v.revision.blocking for v in result.all_versions)
    # blocking/must_fix 并列 → 取最早版本（best-of-K ≠ 最后一版）
    assert result.best is result.all_versions[0]

    # 合并带过：第 1 轮全 PASS（not blocking）→ 只跑 1 轮
    feedbacks2, calls2 = [], []
    ctrl2 = IterationController(FakeParliament([[]]), LeaderArbiter(), FakeGates())
    result2 = run(ctrl2.run(make_generate(feedbacks2, calls2), ChapterSpec()))
    assert len(calls2) == 1 and len(result2.all_versions) == 1
    assert result2.best is result2.all_versions[0]


def test_score_report_aggregation_hand_computed():
    """2 FAIL（setting_consistency/cliche_detection）5 PASS + mystery 权重
    （和恰为 1.0）→ overall = 1 - 0.25 - 0.10 = 0.65 手算对拍；
    critic_pass_rate「5/7」；空 reader 曲线 engagement=3.0"""
    weights = {  # mystery.yaml params.evaluation_weights 逐字（和 = 1.00）
        "情节连贯": 0.20, "角色动机": 0.15, "设定一致性": 0.25,
        "对话真实度": 0.10, "感官细节": 0.10, "套路检测": 0.10, "主题深度": 0.10,
    }
    critiques = [
        critique("plot_coherence", "PASS"),
        critique("character_motivation", "PASS"),
        critique("setting_consistency", "FAIL", "改掉明清称谓"),
        critique("dialogue_authenticity", "PASS"),
        critique("sensory_detail", "PASS"),
        critique("cliche_detection", "FAIL", "删掉套话"),
        critique("theme_depth", "PASS"),
    ]
    report = PresentationScorer({"evaluation_weights": weights}).score(
        critiques, {"engagement": []})

    assert report.overall == pytest.approx(0.65)     # 手算对拍
    assert report.critic_pass_rate == "5/7"
    assert report.dimensions["setting_consistency"] == 0.0
    assert report.dimensions["cliche_detection"] == 0.0
    assert report.dimensions["plot_coherence"] == 1.0
    assert len(report.dimensions) == 7               # 展示分只算蓝图 7 维
    assert report.reader_engagement == 3.0           # 空曲线 → 中性 3.0

    # 权重和不为 1 时归一化（翻倍 → overall 不变）；非空曲线取均值
    report2 = PresentationScorer(
        {"evaluation_weights": {k: v * 2 for k, v in weights.items()}}
    ).score(critiques, {"engagement": [4, 5]})
    assert report2.overall == pytest.approx(0.65)
    assert report2.reader_engagement == pytest.approx(4.5)
