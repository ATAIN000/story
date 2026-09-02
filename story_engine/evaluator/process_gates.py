"""ProcessGate — 过程检查点 L1/L2/L3/L5（蓝图 6.1，P4 决策4：全部规则化，不调 LLM）

每层 binary pass/fail：PASS 继续 / FAIL 回滚该层（方向19 PRM>ORM，
过程评估 > 结果评估 Lightman 2023）。蓝图 6.1 原文只有 L1/L2/L3/L5
四层（L4 原文空缺），不臆造 L4。

与蓝图 6.1 签名的差异（均已确认，P4.5 接线时对齐）：
- 蓝图 check_l1 内每次 new ConsistencyValidator()；此处改为构造期注入
  （复用同一实例与世界规则配置），行为等价。
- 蓝图 check_l5(text, ir: NarrativeIR)；NarrativeIR 是 Module 5 类型，
  本阶段规则化实现（标题/字数/截断）用不到 ir，故省略该参数；
  字数区间改由构造参数 style（genre params.prompt.style 原文）解析。
- 蓝图 check_l2 的 CharacterAction 在本仓库对应 ActionCandidate /
  事件 payload dict，本层按 duck-typing 兼容两者。
"""
from __future__ import annotations

import re
from typing import Any

from ..showrunner import TODOROV_PHASES
from ..types import WorldEvent, WorldState
from ..validator import ConsistencyValidator
from ..narrative.humanize import AI_ISMS_ZH
from .types_eval import Gate

# L5：字数区间解析失败时的宽默认（不阻塞正常篇幅）
DEFAULT_WORD_RANGE = (100, 20000)
# L5：句末标点（末字符不在其中 = 半截句）
SENTENCE_ENDINGS = "。！？…”」』.!?"
# L2：persona dict 中视为禁词清单的键（无这些键 = 无角色卡信息，记 passed）
PERSONA_FORBIDDEN_KEYS = ("forbidden", "taboos", "never")
# L3：原语最早可出现的 Todorov 相（决策4 示例：Revelation 在 recognition 相之前不出现）
PRIMITIVE_MIN_PHASE = {"Revelation": "recognition"}


class ProcessGate:
    """过程检查点 — 可验证维度的硬门控（规则化，无 LLM 调用）

    style: genre 插件 params.prompt.style 原文（如 "800-1200字，文白相间…"），
           供 L5 解析字数区间；缺省/解析失败走 DEFAULT_WORD_RANGE。
    validator: L1 复用的 7 步验证器实例（缺省自建，等价蓝图行为）。
    """

    def __init__(self, style: str | None = None,
                 validator: ConsistencyValidator | None = None):
        self.style = style or ""
        self._validator = validator or ConsistencyValidator()

    # ---------- L1：事件后状态自洽 ----------
    async def check_l1(self, event: WorldEvent, state: WorldState) -> Gate:
        """复用 ConsistencyValidator.validate（7 步硬约束），failures 原样映射"""
        result = self._validator.validate(event, state)
        return Gate(layer="L1", passed=result.passed,
                    failures=dict(result.failures))

    # ---------- L2：角色决策后一致性（对照角色卡） ----------
    async def check_l2(self, action: Any, character: Any) -> Gate:
        """action 对照角色卡：persona 禁词 / voice 禁词 / goal 对齐。

        无角色卡信息的维度记 passed（不阻塞，决策4）。
        action 兼容 ActionCandidate（.action/.summary/.serves_goal）与
        事件 payload dict；character 取 CharacterActor 可读属性
        （persona: dict / goals: list[str] / voice: VoiceProfile）。
        """
        act, summary, serves_goal = _action_fields(action)
        text = f"{act} {summary}"
        goals = list(getattr(character, "goals", None) or [])
        persona = getattr(character, "persona", None) or {}
        voice = getattr(character, "voice", None)

        failures: dict[str, str] = {}
        # goal 对齐：角色有活跃目标且行动声明了 serves_goal 时必须命中
        if goals and serves_goal and serves_goal not in goals:
            failures["goal_aligned"] = (
                f"行动声明目标「{serves_goal}」不在角色活跃目标 {goals} 中")
        # voice 禁词：VoiceProfile.forbidden_words 不得出现在行动文本
        forbidden = list(getattr(voice, "forbidden_words", None) or [])
        hit = [w for w in forbidden if w and w in text]
        if hit:
            failures["voice_consistent"] = f"行动文本含声音禁词：{'、'.join(hit)}"
        # persona 关键词：persona 中显式禁词清单不得出现在行动文本
        persona_bad = [w for k in PERSONA_FORBIDDEN_KEYS
                       for w in (persona.get(k) or [])
                       if isinstance(w, str) and w and w in text]
        if persona_bad:
            failures["persona_consistent"] = (
                f"行动文本违反角色卡禁忌：{'、'.join(persona_bad)}")
        return Gate(layer="L2", passed=not failures, failures=failures)

    # ---------- L3：beat 选定后节拍-目标对齐 ----------
    async def check_l3(self, beat: dict, decision: Any) -> Gate:
        """beat 的 primitives 与决策卡计划的一致性（规则化）。

        说明：决策卡 plan_goals 是目标轨迹 dict（id/holder/desc/status），
        与原语类名无字段级可比键，故一致性以决策卡 planner 产出的
        原语集合（beats[].primitives 并集）为准；无计划信息记 passed。
        """
        primitives = [str(p) for p in (beat.get("primitives") or [])]
        phase = (beat.get("micro_phase") or beat.get("phase")
                 or beat.get("macro_phase") or "")

        failures: dict[str, str] = {}
        # 相位合法：beat 声明的相必须是已知 Todorov 相
        if phase and phase not in TODOROV_PHASES:
            failures["phase_valid"] = f"未知叙事相「{phase}」"
        # 原语-相位顺序：如 Revelation 在 recognition 相之前不出现
        if phase in TODOROV_PHASES:
            idx = TODOROV_PHASES.index(phase)
            for p in primitives:
                min_phase = PRIMITIVE_MIN_PHASE.get(p)
                if min_phase and idx < TODOROV_PHASES.index(min_phase):
                    failures["primitive_phase_order"] = (
                        f"原语「{p}」不应出现在「{phase}」相"
                        f"（最早「{min_phase}」相）")
        # 计划在轨：beat 原语不得超出决策卡 planner 产出的原语集合
        planned = {str(p) for b in (getattr(decision, "beats", None) or [])
                   for p in (b.get("primitives") or [])}
        if planned:
            extra = [p for p in primitives if p not in planned]
            if extra:
                failures["primitives_in_plan"] = (
                    f"beat 原语超出决策卡计划范围：{'、'.join(extra)}")
        return Gate(layer="L3", passed=not failures, failures=failures)

    # ---------- L5：叙事化后段落级 ----------
    async def check_l5(self, text: str) -> Gate:
        """三规则：首行标题格式 / 字数在 genre style 区间 / 无半截句。

        标题格式接受三种：
        - 「标题：XXXX」（引擎级约定，全角冒号）
        - 「# 第X章…」（markdown 标题，LLM 常见产出）
        - 「第X章…」（纯文本标题）
        字数检查放宽容差 lo×0.4 / hi×2.0（LLM 不精确控制篇幅，且网文章节
        篇幅差异大；1500字题材合法区间 [600, 3000]）。
        """
        failures: dict[str, str] = {}
        stripped = (text or "").strip()
        first_line = stripped.splitlines()[0] if stripped else ""
        # 标题格式：接受三种（全角冒号 / markdown / 纯文本章标题）
        if not (re.match(r"^标题：\S+", first_line)
                or re.match(r"^#\s*.+", first_line)
                or re.match(r"^第.+章", first_line)):
            failures["title_format"] = "首行标题格式不符（要求「标题：XXXX」或 markdown 标题或「第X章」）"
        # 字数检查：收紧容差（大唐01 实测 644/2687 字在旧容差 [600,3000] 下
        # 全部漏过）。收紧到 lo×0.7 / hi×1.3（1500字题材→[1050,1950]），
        # 失控章节（过短纯对话交代 / 超标塞多场戏）进修正回路。
        lo, hi = parse_word_range(self.style)
        margin_lo = max(50, int(lo * 0.3))
        margin_hi = int(hi * 1.3)
        n_chars = len(re.sub(r"\s", "", stripped))
        if not (lo - margin_lo <= n_chars <= margin_hi):
            failures["word_count"] = (
                f"字数 {n_chars} 超出容差区间 [{lo - margin_lo}, {margin_hi}]（genre style {lo}-{hi}，容差 lo×0.7/hi×1.3）")
        if stripped and stripped[-1] not in SENTENCE_ENDINGS:
            failures["truncated"] = f"结尾无句末标点（疑半截句）：…{stripped[-10:]}"
        # ⑦ 文笔维度（规则化，无 LLM，在 critic 之前拦确定性硬伤）：
        # 段落超长 / 句首重复 / AI腔残留。任一命中 → gate FAIL → 驱动下一轮修正
        for finder in (self._check_wall_of_text,
                       self._check_repetitive_opening,
                       self._check_ai_ism_residue):
            found = finder(stripped)
            if found is not None:
                failures[found[0]] = found[1]
        return Gate(layer="L5", passed=not failures, failures=failures)

    # ---------- ⑦ 文笔规则检查（确定性，无 LLM）----------
    @staticmethod
    def _paragraphs(text: str) -> list[str]:
        """按空行切段落（过滤空段）"""
        return [p.strip() for p in (text or "").split("\n\n") if p.strip()]

    def _check_wall_of_text(self, text: str):
        """段落超长：任一段落 >8 句或 >600 字。realizer 要求 2-4 句/段、场景
        转换空行分隔；超长密集块伤可读性，是网文质感杀手。阈值偏宽（>8 句）
        避免误伤合理的密集场景。返回 (key, reason) 或 None。"""
        for i, p in enumerate(self._paragraphs(text)):
            sents = len(re.findall(r"[。！？…」』!?]", p))
            if sents > 8 or len(p) > 600:
                return ("wall_of_text",
                        f"第{i + 1}段过密（{sents}句/{len(p)}字），"
                        "建议 2-4 句/段、场景转换用空行分隔")
        return None

    def _check_repetitive_opening(self, text: str):
        """句首重复：3+ 连续段落以相同 2 字开头（LLM 常见单调 tic，如连续
        「他…」「她…」）。返回 (key, reason) 或 None。"""
        paras = [p for p in self._paragraphs(text) if len(p) >= 2]
        run = 1
        for i in range(1, len(paras)):
            if paras[i][:2] == paras[i - 1][:2]:
                run += 1
                if run >= 3:
                    return ("repetitive_opening",
                            f"连续{run}+段以「{paras[i][:2]}」开头，句首单调重复")
            else:
                run = 1
        return None

    def _check_ai_ism_residue(self, text: str):
        """AI腔残留安全网：realizer 已 _filter_ai_isms，但若过滤被绕过
        （IR-first 回退/未走 Narrativizer 路径）会残留。残留 >3 处已知 AI-ism
        → 标记。阈值偏宽，正常过滤后文本不会触发。"""
        count = sum(text.count(ism) for ism in AI_ISMS_ZH)
        if count > 3:
            return ("ai_ism_residue",
                    f"残留 {count} 处 AI 腔用词（如「值得注意的是」「映入眼帘」"
                    "等），建议改为朴素表达")
        return None


def parse_word_range(style: str) -> tuple[int, int]:
    """从 genre prompt.style 解析字数区间（如 "800-1200字…"）；失败用宽默认"""
    m = re.search(r"(\d+)\s*[-~—–]\s*(\d+)\s*字", style or "")
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if 0 < lo < hi:
            return lo, hi
    return DEFAULT_WORD_RANGE


def _action_fields(action: Any) -> tuple[str, str, str]:
    """从 ActionCandidate 或事件 payload dict 取 (action, summary, serves_goal)"""
    getter = action.get if isinstance(action, dict) else (
        lambda k, d="": getattr(action, k, d))
    return (str(getter("action", "") or ""),
            str(getter("summary", "") or ""),
            str(getter("serves_goal", "") or ""))
