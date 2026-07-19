"""HITL 介入路由（Module 7.1，P5.7 前 3 类 + P5.8 structural/textual）

蓝图 7.1：介入即事件，可回放。作者介入统一走 InterventionRouter.route 分流：
  - intent      改目标/约束 → author_intervention 事件，下章决策卡生效
  - structural  Fabula 层重写 → rolled_back + 可选章级重生成（P5.8）
  - character   改角色信念/关系/记忆 → 事件（learn/relations 复用现有 effects 协议）
  - textual     Sjuzhet 层改写 → 只记事件，不重生成（P5.8，蓝图：最贵，最小化）
  - evaluation  质量标注 → 事件 + TrainingPipeline 偏好数据（P5.9，依赖注入预留）

全部规则化，零 LLM（重生成调用注入的 regenerate_fn 除外——那是 engine 的事）。

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
    """介入结果。regenerated：structural 触发章级重生成成功时为 True"""
    ok: bool
    event_id: str | None
    message: str
    regenerated: bool = False


class InterventionRouter:
    """按介入类型分流处理（P5.7：intent/character/evaluation；P5.8：structural/textual）"""

    def __init__(self, kernel, pipeline=None, regenerate_fn=None):
        """
        kernel:        Kernel 实例（commit_event / query_world / rollback syscall）
        pipeline:      TrainingPipeline（P5.9）可选依赖注入；有则 evaluation 介入
                       额外调 pipeline.process_intervention(event)，无则跳过不崩。
        regenerate_fn: P5.8 structural 的章级重生成入口（engine 侧可调用对象，
                       无参同步调用；engine 生成系为 async，由调用方包同步包装，
                       接线留 P5.10）。None 时 structural 只标 rolled_back 不重生成。
                       LLM 只存在于该注入 callable 内部，router 自身零 LLM。
        """
        self.kernel = kernel
        self.pipeline = pipeline
        self.regenerate_fn = regenerate_fn

    def route(self, intervention: HumanInput) -> InterventionResult:
        handler = {
            "intent": self._route_intent,
            "structural": self._route_structural,
            "character": self._route_character,
            "textual": self._route_textual,
            "evaluation": self._route_evaluation,
        }.get(intervention.type)
        if handler is None:
            return InterventionResult(
                ok=False, event_id=None,
                message=f"未知介入类型「{intervention.type}」"
                        "（支持 intent/structural/character/textual/evaluation）")
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

    # ---------- structural：Fabula 层改写（remove/edit/insert） ----------
    def _route_structural(self, intervention: HumanInput) -> InterventionResult:
        # payload: {action: "remove_event"|"edit_event"|"insert_event",
        #           event_id?, before?, after?, event?}
        #   remove/edit → event_id 定位目标；edit 的 after = 新内容
        #   insert      → after = 插入点 event_id（之后全部受影响），event = 新事件
        #
        # rolled_back 机制（P5.8 调查结论，以代码实际为准）：
        # EventStore 没有事件级 rolled_back 标记 API；既有机制是 tick 级 head
        # 指针回滚（kernel.rollback(int) → store.rollback：head 回移 + timeline
        # 递增），world_tick > head 的事件在 all_events 里 active=False、不进
        # projection（章节级 superseded 标记在 engine 侧，仅用于 chapters.json
        # 展示）。因此「标 rolled_back」= 回滚到受影响事件之前一格，改动点及其
        # 下游一并失效——正好契合蓝图「从改动点重生成下游」的语义。
        p = intervention.payload
        action = p.get("action")

        # 1. 定位受影响位置 → 回滚目标 tick
        if action in ("remove_event", "edit_event"):
            target = self._find_active_event(p.get("event_id"))
            if target is None:
                return InterventionResult(
                    ok=False, event_id=None,
                    message=f"structural {action} 找不到 active 事件 "
                            f"「{p.get('event_id')}」（不存在或已 rolled_back）")
            rollback_to: int | None = target["world_tick"] - 1
        elif action == "insert_event":
            anchor = p.get("after")
            if anchor is None:
                rollback_to = None  # 末尾插入：无下游受影响，无需回滚
            else:
                point = self._find_active_event(anchor)
                if point is None:
                    return InterventionResult(
                        ok=False, event_id=None,
                        message=f"structural insert 插入点事件「{anchor}」"
                                "不存在或已 rolled_back")
                rollback_to = point["world_tick"]
        else:
            return InterventionResult(
                ok=False, event_id=None,
                message=f"未知 structural action「{action}」"
                        "（支持 remove_event/edit_event/insert_event）")

        # 2. 标 rolled_back（必须先回滚再记事件，否则审计事件自身也被回滚）
        if rollback_to is not None:
            self.kernel.rollback(rollback_to)
        mark = (f"rolled_back 到 tick {rollback_to}"
                if rollback_to is not None else "末尾插入无需回滚")

        # 3. 审计事件（介入即事件，可回放）
        audit = self._commit_intervention(intervention, {
            "action": action,
            "event_id": p.get("event_id"),
            "before": p.get("before"),
            "after": p.get("after"),
            "rolled_back_to_tick": rollback_to,
        })

        # 4. edit/insert 的新内容事件进流（edit 语义 = 旧事件 rolled_back +
        #    新内容事件 commit；顺序：审计在前、效果在后，同 character）
        if action == "edit_event":
            new_type, new_payload = self._edited_event_content(
                target, p.get("after"))
            self._commit(new_type, {
                **new_payload,
                "source": "author_intervention",
                "intervention_event": audit.event_id,
                "replaces": target["event_id"],
            })
        elif action == "insert_event":
            spec = p.get("event") or {}
            self._commit(spec.get("event_type", "character_action"), {
                **spec.get("payload", {}),
                "source": "author_intervention",
                "intervention_event": audit.event_id,
            })

        # 5. 重生成（本期简化 = 重跑当前章，见 regenerate_fn docstring；
        #    与蓝图「从改动点精准重放下游」的差：不跨章连锁重放）
        if self.regenerate_fn is None:
            return InterventionResult(
                ok=True, event_id=audit.event_id, regenerated=False,
                message=f"structural {action} 已记录并标记（{mark}）；"
                        "未注入 regenerate_fn：已标记，待重生成")
        try:
            self.regenerate_fn()
        except Exception as exc:
            return InterventionResult(
                ok=True, event_id=audit.event_id, regenerated=False,
                message=f"structural {action} 已记录并标记（{mark}），"
                        f"但重生成异常：{exc}")
        return InterventionResult(
            ok=True, event_id=audit.event_id, regenerated=True,
            message=f"structural {action} 已生效（{mark}），本章已重生成")

    def _find_active_event(self, event_id: str | None) -> dict | None:
        """在 all_events（含 active 标记）里找指定 active 事件"""
        if not event_id:
            return None
        for e in self.kernel.query_world("all_events"):
            if e["event_id"] == event_id and e.get("active", True):
                return e
        return None

    @staticmethod
    def _edited_event_content(old_event: dict, after) -> tuple[str, dict]:
        """edit 语义的新事件内容：after 为含 event_type/payload 键的 dict 时
        按覆盖解释（缺省沿用旧 event_type）；其余形态整体作为新 payload。"""
        event_type = old_event["event_type"]
        if isinstance(after, dict) and ("event_type" in after or "payload" in after):
            return after.get("event_type", event_type), dict(after.get("payload") or {})
        return event_type, dict(after) if isinstance(after, dict) else {"text": after}

    # ---------- textual：Sjuzhet 文本编辑（只记录，不重生成） ----------
    def _route_textual(self, intervention: HumanInput) -> InterventionResult:
        # payload: {chapter, before: str, after: str}
        # 蓝图 7.1：textual 最贵、最小化——只记事件（before/after/reason，
        # 可回放），不触发重生成（regenerated 恒 False）。
        # 落盘调查（P5.8）：engine 侧章节持久化只有整文件读写的
        # _read_chapters/_write_chapters，无干净的单章文本更新公开口子
        # → 本期只在事件中记录；展示层正文更新留 P5.10 API/前端阶段
        # （届时可从事件回放应用 before→after）。
        p = intervention.payload
        if p.get("chapter") is None or "after" not in p:
            return InterventionResult(
                ok=False, event_id=None,
                message="textual 介入缺少 payload.chapter 或 payload.after")
        event = self._commit_intervention(intervention, {
            "chapter": p.get("chapter"),
            "before": p.get("before"),
            "after": p.get("after"),
        })
        return InterventionResult(
            ok=True, event_id=event.event_id, regenerated=False,
            message=f"第{p['chapter']}章文本编辑已记录（可回放），不重生成")
