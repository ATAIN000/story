"""ConsistencyValidator — 7步硬约束验证管线（Module 1.3）

蓝图核心差异化：现有系统（NovelClaw 等）一致性检查全是 LLM 软判定，
这里是可证明的硬约束。赌注1验证：Z3 判定 10/10 正确，5000 规则 <100ms。

7 步管线（接口规范 3.2）：
  1. temporal   — Temporal KG 时序一致性
  2. physical   — Event Calculus 物理硬约束（位置/物品/生死 fluents）
  3. epistemic  — Epistemic EC 认知验证（"他知道吗？"）
  4. causal     — Pearl 因果 DAG（动机可追溯）
  5. intention  — IPOCL 承诺框架（行动服务于活跃目标）
  6. world_rule — Z3 SMT 世界规则（Sanderson三律 + 类型禁忌）
  7. soft       — LLM 软判定兜底（仅主观维度，硬约束全过后才跑）
"""
from __future__ import annotations

import re
import z3

from .types import WorldEvent, WorldState, Check, Verdict

# 故事内时辰顺序（时序检查用）
PERIOD_ORDER = {"子时": 0, "丑时": 1, "寅时": 2, "卯时": 3, "辰时": 4, "巳时": 5,
                "午时": 6, "未时": 7, "申时": 8, "酉时": 9, "戌时": 10, "亥时": 11,
                "清晨": 3.5, "上午": 4.5, "正午": 6, "午后": 7, "傍晚": 9, "入夜": 10.5, "深夜": 0}

# Step 6 事件事实词汇表：事实名 → Python 类型（bool→z3.Bool，其他→z3.Int）。
# Z3 编码（_check_world_rules_smt）与 P7.4 规则 expr 加载校验
#（check_rule_expr）共用同一份声明，保证「能过加载校验的规则运行时必可编译」。
# P7.4：补充 introduces_new_key_clue（fair-play 包 no_late_clue 规则引用）；
# 对不引用它的既有规则零影响 —— 新事实变量不进任何既有规则的约束。
WORLD_FACT_TYPES = {
    "has_supernatural": bool,
    "is_resolution": bool,
    "narrator_is_killer": bool,
    "case_age_days": int,
    "introduces_new_key_clue": bool,
}


class ConsistencyValidator:
    """生成任何新剧情前必经的 7 步验证管线"""

    def __init__(self, world_rules: list[dict] | None = None):
        # 世界规则声明（来自 Genre/Culture 插件），默认悬疑+公案规则
        self.world_rules = world_rules or [
            {"id": "sanderson_1", "kind": "bool", "desc": "Sanderson第一律：鬼神介入不解决剧情",
             "expr": "not(has_supernatural and is_resolution)"},
            {"id": "fair_play", "kind": "bool", "desc": "Fair Play：叙述者不可为凶手",
             "expr": "not(narrator_is_killer)"},
            {"id": "case_aging", "kind": "arith", "desc": "案件时效：结案不超过365天",
             "expr": "case_age_days <= 365"},
        ]

    # ============ 主入口 ============
    def validate(self, event: WorldEvent, state: WorldState) -> Verdict:
        checks = [
            self._check_temporal_tkg(event, state),
            self._check_physical_ec(event, state),
            self._check_epistemic_ec(event, state),
            self._check_causal_dag(event, state),
            self._check_intention_ipocl(event, state),
            self._check_world_rules_smt(event, state),
            self._check_soft(event, state),
        ]
        return Verdict(passed=all(c.passed for c in checks), checks=checks)

    # ---------- Step 1: Temporal KG ----------
    def _check_temporal_tkg(self, event: WorldEvent, state: WorldState) -> Check:
        label = "时序 (Temporal KG)"
        st = event.payload.get("story_time")
        if not st or not state.narrative.last_story_time:
            return Check("temporal", label, True)
        last = self._parse_story_time(state.narrative.last_story_time)
        cur = self._parse_story_time(st)
        if last and cur and cur < last and not event.payload.get("is_flashback"):
            return Check("temporal", label, False,
                         f"时序矛盾：事件时间「{st}」早于已确立的「{state.narrative.last_story_time}」（非闪回）")
        return Check("temporal", label, True)

    @staticmethod
    def _parse_story_time(st: str) -> tuple[float, float] | None:
        m = re.match(r"第(\d+)日[·\s]?(.+)", st)
        if not m:
            return None
        return (float(m.group(1)), PERIOD_ORDER.get(m.group(2), 99))

    # ---------- Step 2: Event Calculus 物理 ----------
    def _check_physical_ec(self, event: WorldEvent, state: WorldState) -> Check:
        label = "物理 (Event Calculus)"
        for precond in event.payload.get("physical_preconditions", []):
            if precond.startswith("!"):
                if state.physical.get(precond[1:], False):
                    return Check("physical", label, False,
                                 f"物理约束失败：{precond[1:]} 不成立（要求否定成立）")
            elif not state.physical.get(precond, False):
                hint = self._fluent_hint(precond, state)
                return Check("physical", label, False,
                             f"物理约束失败：「{precond}」不成立{hint}")
        return Check("physical", label, True)

    @staticmethod
    def _fluent_hint(precond: str, state: WorldState) -> str:
        m = re.match(r"at\(([^,]+),[^)]+\)", precond)
        if m:
            who = m.group(1)
            for f, v in state.physical.items():
                if v and f.startswith(f"at({who},"):
                    return f"（当前 {f}）"
        return ""

    # ---------- Step 3: Epistemic EC 认知 ----------
    def _check_epistemic_ec(self, event: WorldEvent, state: WorldState) -> Check:
        label = "认知 (Epistemic EC)"
        agent = event.payload.get("agent")
        if not agent:
            return Check("epistemic", label, True)
        mind = state.minds.get(agent)
        for fact in event.payload.get("requires_knowing", []):
            known = mind.beliefs.get(fact, False) if mind else False
            if not known:
                return Check("epistemic", label, False,
                             f"「{agent}」此时不知道「{fact}」（无合法获知渠道）")
        return Check("epistemic", label, True)

    # ---------- Step 4: 因果 DAG ----------
    def _check_causal_dag(self, event: WorldEvent, state: WorldState) -> Check:
        label = "因果 (Pearl DAG)"
        motivation = event.payload.get("motivation")
        if not motivation:
            return Check("causal", label, True)
        for link in state.narrative.causal_links:
            if motivation in link:
                return Check("causal", label, True)
        return Check("causal", label, False,
                     f"因果链断裂：动机「{motivation}」无已确立的前因（不可追溯）")

    # ---------- Step 5: IPOCL 意图 ----------
    def _check_intention_ipocl(self, event: WorldEvent, state: WorldState) -> Check:
        label = "意图 (IPOCL)"
        agent = event.payload.get("agent")
        serves = event.payload.get("serves_goal")
        if not agent or not serves:
            return Check("intention", label, True)
        mind = state.minds.get(agent)
        goals = mind.goals if mind else []
        if serves in goals:
            return Check("intention", label, True)
        return Check("intention", label, False,
                     f"「{agent}」的行动不服务于任何活跃目标（声明 {serves}，活跃目标 {goals}）")

    # ---------- Step 6: Z3 SMT 世界规则 ----------
    def _check_world_rules_smt(self, event: WorldEvent, state: WorldState) -> Check:
        """把事件事实断言 + 世界规则约束一起交给 Z3 做可满足性判定。

        赌注1验证结论：Z3 能完美表达"鬼神介入不解决剧情"这类文学约束——
        关键是分解为布尔变量（has_supernatural ∧ is_resolution → ⊥）。
        """
        label = "世界规则 (Z3 SMT)"
        # 1. 从事件 payload 提取事实（布尔/算术，词汇表见 WORLD_FACT_TYPES）
        facts = {
            k: (bool(event.payload.get(k, False)) if t is bool
                else int(event.payload.get(k, 0)))
            for k, t in WORLD_FACT_TYPES.items()
        }
        # 2. 符号化编码进 Z3：符号变量 + 事实断言 + 全部规则约束
        sym = {k: (z3.Bool(k) if isinstance(v, bool) else z3.Int(k))
               for k, v in facts.items()}
        solver = z3.Solver()
        for k, v in facts.items():
            solver.add(sym[k] == v)
        for rule in self.world_rules:
            solver.add(self._compile_rule(rule["expr"], sym))
        sat = solver.check() == z3.sat

        # 3. 逐条定位违规规则（具体值回代，用于报告）
        violated = []
        if not sat:
            for rule in self.world_rules:
                try:
                    ok = eval(rule["expr"], {"__builtins__": {}}, dict(facts))
                except Exception:
                    ok = True
                if not ok:
                    violated.append(rule["desc"])
        if violated:
            return Check("world_rule", label, False, "；".join(violated))
        return Check("world_rule", label, True)

    @staticmethod
    def _compile_rule(expr: str, sym: dict) -> z3.BoolRef:
        """把声明式规则编译为 Z3 符号表达式（and/or/not → z3.And/Or/Not）"""
        env = dict(sym)
        env["and_"] = lambda *a: z3.And(*a)
        env["or_"] = lambda *a: z3.Or(*a)
        # 把 Python 语法糖转换为 z3 调用形式
        z3_expr = (expr.replace("not(", "Not(")
                       .replace(" and ", ", ")
                       .replace(" or ", ", "))
        # "not(A, B)" 形式不合法，特判：Not(And(A,B)) / Not(Or(A,B))
        # 简单规则集下 expr 只有三种形态：not(A and B) / not(X) / 算术比较
        if expr.startswith("not(") and " and " in expr:
            inner = expr[4:-1]
            parts = [p.strip() for p in inner.split(" and ")]
            return z3.Not(z3.And(*[sym[p] for p in parts]))
        if expr.startswith("not("):
            return z3.Not(sym[expr[4:-1].strip()])
        return eval(expr, {"__builtins__": {}}, env)

    @staticmethod
    def check_rule_expr(expr) -> bool:
        """P7.4 L5：规则 expr 加载期语法校验（rule_packs 合并入口用）。

        复用 _compile_rule 的 Z3 解析路径：按 Step 6 同一事实词汇表
        （WORLD_FACT_TYPES）声明符号后试编译，并要求结果是布尔约束。
        语法错误 / 引用未声明事实 / 非字符串 / 非布尔结果 → False。
        只做加载校验，不做可满足性判定。
        """
        if not isinstance(expr, str):
            return False
        sym = {k: (z3.Bool(k) if t is bool else z3.Int(k))
               for k, t in WORLD_FACT_TYPES.items()}
        try:
            compiled = ConsistencyValidator._compile_rule(expr, sym)
        except Exception:
            return False
        return isinstance(compiled, z3.BoolRef)

    # ---------- Step 7: LLM 软判定兜底 ----------
    def _check_soft(self, event: WorldEvent, state: WorldState) -> Check:
        # 仅处理前 6 步无法覆盖的主观维度；demo 默认通过
        return Check("soft", "软判定 (LLM 兜底)", True)
