"""HITL 介入路由（Module 7.1，P5.7 实现前 3 类）

蓝图 7.1：介入即事件，可回放。作者介入统一走 InterventionRouter.route 分流：
  - intent      改目标/约束 → author_intervention 事件，下章决策卡生效
  - structural  Fabula 层重写（P5.8）
  - character   改角色信念/关系/记忆 → 事件（learn/relations 复用现有 effects 协议）
  - textual     Sjuzhet 层改写（P5.8）
  - evaluation  质量标注 → 事件 + TrainingPipeline 偏好数据（P5.9，依赖注入预留）

全部规则化，零 LLM。

commit 容忍度结论（P5.7 调查，以代码实际为准）：
  kernel.commit_event 是 EventStore.append 的薄包装，commit 路径不经过
  ConsistencyValidator（7 步验证只在引擎生成路径显式调用）；且
  author_intervention 已在 types.EVENT_HANDLERS 注册（no-op fold）。
  因此 author_intervention 事件可直接 commit，无需任何"内部通道"。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from ..types import WorldEvent


@dataclass(frozen=True)
class HumanInput:
    """作者介入输入（蓝图 7.1 引用，本任务按任务卡最小定义）"""
    type: str                 # intent / structural / character / textual / evaluation
    payload: dict[str, Any]
    reason: str = ""


@dataclass(frozen=True)
class InterventionResult:
    """介入结果。regenerated 给 P5.8 structural/textual 用，本任务恒 False"""
    ok: bool
    event_id: str | None
    message: str
    regenerated: bool = False


class InterventionRouter:
    """按介入类型分流处理（P5.7：intent / character / evaluation）"""

    def __init__(self, kernel, pipeline=None):
        """
        kernel:   Kernel 实例（commit_event / query_world syscall）
        pipeline: TrainingPipeline（P5.9）可选依赖注入；有则 evaluation 介入
                  额外调 pipeline.process_intervention(event)，无则跳过不崩。
        """
        self.kernel = kernel
        self.pipeline = pipeline

    def route(self, intervention: HumanInput) -> InterventionResult:
        handler = {
            "intent": self._route_intent,
            "character": self._route_character,
            "evaluation": self._route_evaluation,
        }.get(intervention.type)
        if handler is None:
            # structural / textual（P5.8）及未知类型：不记事件，明确返回未实现
            return InterventionResult(
                ok=False, event_id=None,
                message=f"介入类型「{intervention.type}」尚未实现（structural/textual 留 P5.8）")
        return handler(intervention)

    # ---------- 事件提交 ----------
    def _commit(self, event_type: str, payload: dict) -> WorldEvent:
        event = WorldEvent(
            event_id=str(uuid4())[:8],
            event_type=event_type,
            timestamp=datetime.now().isoformat(timespec="seconds"),
            world_tick=self.kernel.query_world("next_tick"),
            branch_id="main",
            payload=payload)
        self.kernel.commit_event(event)
        return event

    def _commit_intervention(self, intervention: HumanInput,
                             extra: dict | None = None) -> WorldEvent:
        """author_intervention 审计事件（介入即事件，可回放）。

        fold 为 no-op（types._h_author_intervention），对 projection 无影响；
        实际状态变更由具体类型的效果事件承担（见 character）。
        """
        return self._commit("author_intervention", {
            "type": intervention.type,
            "reason": intervention.reason,
            **(extra or {}),
        })

    # ---------- intent：改目标/约束 ----------
    def _route_intent(self, intervention: HumanInput) -> InterventionResult:
        # payload: {goal_update?: str, constraint?: str}
        # 现状：决策卡（showrunner/decision.py）没有读取外部 intent 覆盖的消费口子
        # （章级 AuthorIntent 由 advance 轨道构造），本任务只保证「记录可回放」
        # （query_world("all_events") 可查）；消费接线留 P5.11 / 后续任务。
        event = self._commit_intervention(intervention, {
            "goal_update": intervention.payload.get("goal_update"),
            "constraint": intervention.payload.get("constraint"),
        })
        return InterventionResult(
            ok=True, event_id=event.event_id,
            message="intent 已记入事件流（可回放；决策卡消费接线留 P5.11）")

    # ---------- character：改信念/关系/记忆 ----------
    def _route_character(self, intervention: HumanInput) -> InterventionResult:
        # payload: {character, belief?: str,
        #           relation?: {target, type, intensity}, forget?: str}
        p = intervention.payload
        cid = p.get("character")
        if not cid:
            return InterventionResult(
                ok=False, event_id=None,
                message="character 介入缺少 payload.character")

        # 翻译成现有 effects 协议（types._h_character_action 的 learn/relations）
        effects: dict[str, Any] = {}
        if p.get("belief"):
            effects["learn"] = {cid: [p["belief"]]}
        rel = p.get("relation")
        if rel:
            r = {"type": rel["type"], "intensity": rel["intensity"]}
            if intervention.reason:
                r["note"] = f"作者介入: {intervention.reason}"
            effects["relations"] = {f"{cid}|{rel['target']}": r}

        # 审计事件（含 forget 等无法 fold 的内容：现有 learn 协议只增不删，
        # 信念遗忘不进 projection，仅在审计事件中可回放）
        audit = self._commit_intervention(intervention, {
            "character": cid,
            "belief": p.get("belief"),
            "relation": rel,
            "forget": p.get("forget"),
        })
        if not effects:
            return InterventionResult(
                ok=True, event_id=audit.event_id,
                message="character 介入已记录（无 belief/relation 变更，仅审计）")

        # 效果事件：复用 character_action fold，projection 里 knows/relation 可见
        eff = self._commit("character_action", {
            "agent": cid,
            "action": "author_override",
            "source": "author_intervention",
            "intervention_event": audit.event_id,
            "effects": effects,
        })
        return InterventionResult(
            ok=True, event_id=audit.event_id,
            message=f"character 变更已生效（效果事件 {eff.event_id}）")

    # ---------- evaluation：质量标注 → 训练信号 ----------
    def _route_evaluation(self, intervention: HumanInput) -> InterventionResult:
        # payload: {chapter, quality: "high"|"low"|int, note?}
        p = intervention.payload
        event = self._commit_intervention(intervention, {
            "chapter": p.get("chapter"),
            "quality": p.get("quality"),
            "note": p.get("note"),
        })
        fed = False
        if self.pipeline is not None:
            # TrainingPipeline（P5.9）偏好数据通道：依赖注入预留
            self.pipeline.process_intervention(event)
            fed = True
        return InterventionResult(
            ok=True, event_id=event.event_id,
            message="evaluation 已记录" + ("，已送入 TrainingPipeline" if fed else ""))
