"""IterationController — 3 轮 best-of-K 迭代控制器（蓝图 6.5）

蓝图 1647-1697 的最小可运行实现（独立层，P4.5 才接线 engine）：

- Self-Refine 不是单调提升，3 轮是经验甜区；MAX_ROUNDS 类常量 3，
  构造参数可覆盖（env 接线在 P4.5）
- 保留所有版本，best-of-K 选择（不是最后一版！）
- 依赖注入：parliament（P4.2 CriticParliament）/ leader（P4.3 LeaderArbiter）
  / gates（P4.1 ProcessGate）/ reader（P4.3 ReaderProxy，可选）——
  controller 只依赖 duck-typing 接口，测试注入 fake/stub，不触网
- generate_fn 签名 (chapter_spec, feedback: list[str] | None) -> str，
  async/sync 均可（可 await 的返回值会被 await）

与蓝图原文的差异（均已确认，注释在对应代码处）：
- gate FAIL 的轮次不记 Version（蓝图原文如此：continue 前没 append）——
  3 轮全 gate FAIL 时 versions 为空，_select_best 兜底返回 None，
  engine 接线侧 P4.5 处理 None = 保留初版
- reader 反应无法入 Version（types_eval.Version 无 reader 字段，types 不改），
  故在 controller 内维护与 versions 对齐的平行表 _reactions；
  只对记录了版本的轮次 react（gate FAIL 轮不记版本，也不浪费 reader 调用）
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable

from .types_eval import Gate, IterationResult, ReaderReaction, Version


@dataclass
class ChapterSpec:
    """章节规格载体（蓝图 chapter_spec 的本 repo 默认实现）。

    controller 只 duck-typing 读属性，任何带同名属性的对象（如
    SimpleNamespace）均可替代。state 供 parliament.assess 与 L1 使用；
    其余为对应过程 Gate 的可选输入，缺失则该层跳过。
    """
    state: Any = None      # 世界状态（parliament.assess / L1）
    event: Any = None      # L1：事件（可选，缺则 L1 跳过）
    action: Any = None     # L2：角色行动（可选，缺则 L2 跳过）
    character: Any = None  # L2：角色卡（可选，缺则 L2 跳过）
    beat: Any = None       # L3：beat 规格（可选，缺则 L3 跳过）
    decision: Any = None   # L3：决策卡（可选，缺则 L3 跳过）


class IterationController:
    """3 轮 best-of-K 迭代控制器（蓝图 6.5）

    parliament: CriticParliament（async assess(chapter, state) -> list[Critique]）
    leader: LeaderArbiter（arbitrate(critiques) -> RevisionPlan）
    gates: ProcessGate（async check_l1/l2/l3/l5）；None → 跳过整个 gate 阶段
    reader: ReaderProxy（可选；有则每个记录版本 react() 一次，反应存 controller
            内平行表，供 _has_improvement / _select_best 的 engagement 维度用）
    max_rounds: 覆盖类常量 MAX_ROUNDS（P4.5 env 接线入口）
    """

    MAX_ROUNDS = 3

    def __init__(self, parliament, leader, gates, reader=None,
                 max_rounds: int | None = None):
        self.parliament = parliament
        self.leader = leader
        self.gates = gates
        self.reader = reader
        self.max_rounds = int(max_rounds) if max_rounds else self.MAX_ROUNDS
        self._last_feedback: list[str] | None = None
        # 与 versions 对齐的 reader 反应平行表（Version 无 reader 字段，types 不改）
        self._reactions: list[ReaderReaction] = []

    async def run(self, generate_fn: Callable, chapter_spec) -> IterationResult:
        versions: list[Version] = []
        self._last_feedback = None
        self._reactions = []

        for round_num in range(self.max_rounds):
            # 生成（generate_fn async/sync 均可）
            result = generate_fn(chapter_spec, feedback=self._last_feedback)
            chapter = await result if inspect.isawaitable(result) else result

            # 过程 gate（能跑的层）
            gates = await self._run_process_gates(chapter, chapter_spec)
            if not all(g.passed for g in gates):
                # gate FAIL 轮次不记 Version（蓝图原文如此）——
                # 可能导致 versions 为空，兜底见 _select_best
                self._last_feedback = self._gate_feedback(gates)
                continue

            # critic 议会 + leader 仲裁
            critiques = await self.parliament.assess(
                chapter, getattr(chapter_spec, "state", None))
            revision = self.leader.arbitrate(critiques)

            # 读者代理（可选）：只对记录版本的轮次 react 一次，
            # 反应入平行表（与 versions 同序对齐）
            if self.reader is not None:
                self._reactions.append(await self.reader.react(chapter))

            # 记录版本
            versions.append(Version(
                round=round_num, text=chapter,
                critiques=critiques, revision=revision, gates=gates,
            ))

            # delta check：新轮无提升 → 停止
            # （蓝图原文判 round_num > 0；gate FAIL 轮不记版本，versions 长度
            #   可能落后 round_num，故按可比较的两个版本存在与否判断）
            if len(versions) >= 2 and not self._has_improvement(versions):
                break

            # 全 PASS（not blocking）→ 提前停止
            if not revision.blocking:
                break

            self._last_feedback = revision.must_fix

        # best-of-K：从所有版本选最优（不是最后一版！）
        best = self._select_best(versions)
        return IterationResult(best=best, all_versions=versions)

    # ---------- 过程 gate：跑 L1/L2/L3/L5 中能跑的 ----------
    async def _run_process_gates(self, chapter: str, chapter_spec) -> list[Gate]:
        """输入缺失的层跳过（如 L2 无 actor 上下文时）；L5 只需章节文本，恒可跑"""
        if self.gates is None:
            return []  # 无 gate 设施 → all([]) 为 True，不阻塞
        gates: list[Gate] = [await self.gates.check_l5(chapter)]
        # L1 需要 event + state（章节级迭代通常无事件上下文 → 跳过）
        event = getattr(chapter_spec, "event", None)
        state = getattr(chapter_spec, "state", None)
        if event is not None and state is not None:
            gates.append(await self.gates.check_l1(event, state))
        # L2 需要 action + character（无 actor 上下文时跳过）
        action = getattr(chapter_spec, "action", None)
        character = getattr(chapter_spec, "character", None)
        if action is not None and character is not None:
            gates.append(await self.gates.check_l2(action, character))
        # L3 需要 beat + decision
        beat = getattr(chapter_spec, "beat", None)
        decision = getattr(chapter_spec, "decision", None)
        if beat is not None and decision is not None:
            gates.append(await self.gates.check_l3(beat, decision))
        return gates

    @staticmethod
    def _gate_feedback(gates: list[Gate]) -> list[str]:
        """把各层 failures 拼成修正指令列表，作为下一轮 generate_fn 的 feedback"""
        return [f"[{g.layer}/{check}] {reason}"
                for g in gates if not g.passed
                for check, reason in g.failures.items()]

    # ---------- delta check：最近两版是否有提升 ----------
    def _has_improvement(self, versions: list[Version]) -> bool:
        """blocking 变 False / must_fix 数量下降 / 读者 engagement 上升，
        任一即提升；无 reader 时只看前两项"""
        prev, curr = versions[-2], versions[-1]
        if prev.revision.blocking and not curr.revision.blocking:
            return True
        if len(curr.revision.must_fix) < len(prev.revision.must_fix):
            return True
        if self.reader is not None and len(self._reactions) >= 2:
            if self._reactions[-1].engagement > self._reactions[-2].engagement:
                return True
        return False

    # ---------- best-of-K（不是最后一版！） ----------
    def _select_best(self, versions: list[Version]) -> Version | None:
        """排序键：blocking 最少（False 优先）> must_fix 最少 >
        读者 engagement 最高（有 reader 时）；并列取最早版本。

        versions 为空（3 轮全 gate FAIL）→ 返回 None 兜底：
        engine 接线侧 P4.5 处理 None = 保留初版。
        """
        if not versions:
            return None

        def key(indexed: tuple[int, Version]):
            i, v = indexed
            engagement = (self._reactions[i].engagement
                          if self.reader is not None and i < len(self._reactions)
                          else 0)
            return (v.revision.blocking, len(v.revision.must_fix), -engagement)

        return min(enumerate(versions), key=key)[1]
