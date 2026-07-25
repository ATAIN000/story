"""ReaderProxy — 读者代理（蓝图 6.4，行为预测非评分）

蓝图 1605-1645 的最小可运行实现（独立层，P4.5 才接线 engine）：

铁律：输出是**行为预测**，不是质量评分——ReaderReaction 的
tension/curiosity/engagement 1-5 是该 persona 读者的反应强度预测，
供曲线形状检查（中段是否塌陷）与 L4 反预期设计使用，critic/Leader
链路从不把它当质量分消费。

- 独立轨道：读者体验必须用独立 agent，非 generator 自评
- prompt 按蓝图原文四问 + 跳过点（章节原文附在问句后，否则读者无文本可反应）
- temperature=0.5（读者反应要有多样性，不同于 critic 的 0.3 低温求稳）
- 解析防御式：LLM 返回空/不可解析 → 中性兜底 ReaderReaction，不抛异常；
  三项强度无论如何钳制在 1-5
- reaction_history 累积；get_reaction_curve() 三条曲线；get_predictions()
  供 L4 反预期设计

LLM 设施与 P4.2 critic_parliament 同款：kernel.llm_call 或直接注入 callable
（async (prompt, *, purpose=, temperature=, max_tokens=) -> 带 .text 的对象）；
两者皆无/异常/空响应 → 中性兜底，不阻塞。
"""
from __future__ import annotations

import logging
import re

from .types_eval import ReaderReaction

logger = logging.getLogger(__name__)

# LLM 调用参数（蓝图 6.4：temperature=0.5）
_TEMPERATURE = 0.5
_MAX_TOKENS = 16384


class ReaderProxy:
    """persona 读者代理——每章一次行为预测（蓝图 6.4）

    persona: 读者人设，如 "30岁喜欢悬疑的读者"
    kernel: Kernel 实例（可选；取其 llm_call 作为 LLM 设施）
    llm_call: 直接注入的 LLM callable（测试 fake 注入点；优先级高于 kernel）
    """

    def __init__(self, persona: str, kernel=None, *, llm_call=None):
        self.persona = persona
        if llm_call is not None:
            self._llm_call = llm_call
        elif kernel is not None:
            self._llm_call = kernel.llm_call
        else:
            self._llm_call = None
        self.reaction_history: list[ReaderReaction] = []

    async def react(self, chapter: str) -> ReaderReaction:
        # prompt 按蓝图原文四问 + 跳过点（章节原文附后供阅读）
        prompt = f"""你是{self.persona}。读完后只回答:
1. 继续读下一章吗? yes/no
2. 最关心哪个角色?
3. 预测接下来发生什么?
4. 紧张度/好奇度/投入度: 各1-5
哪里让你想跳过?

章节原文：
{chapter or ""}"""
        text = await self._call_llm(prompt)
        reaction = self._parse_reaction(text)
        self.reaction_history.append(reaction)
        return reaction

    def get_reaction_curve(self) -> dict[str, list[int]]:
        """紧张/好奇/投入度曲线 — critic评估曲线形状(中段是否塌陷)"""
        return {
            "tension": [r.tension for r in self.reaction_history],
            "curiosity": [r.curiosity for r in self.reaction_history],
            "engagement": [r.engagement for r in self.reaction_history],
        }

    def get_predictions(self) -> list[str]:
        """读者预测→反馈给L4做反预期设计"""
        return [r.prediction for r in self.reaction_history]

    # ---------- 解析（防御式，不抛异常） ----------
    @staticmethod
    def _parse_reaction(text: str) -> ReaderReaction:
        """解析四问 + 跳过点的回答；空/不可解析 → 中性兜底，不抛异常"""
        # 中性兜底：继续意愿默认 True、三项强度取中位 3、其余空串——
        # 行为预测缺省不偏不倚，且评分恒在 1-5 内
        reaction = ReaderReaction()
        if not text or not text.strip():
            return reaction
        answers = _numbered_answers(text)
        # 1. 继续意愿 yes/no（不可解析 → 保持兜底 True）
        q1 = answers.get(1, "")
        if re.search(r"\byes\b", q1, re.I):
            reaction.continue_reading = True
        elif re.search(r"\bno\b", q1, re.I):
            reaction.continue_reading = False
        # 2/3. 最关心角色 / 预测接下来
        reaction.favorite_character = answers.get(2, "").strip()
        reaction.prediction = answers.get(3, "").strip()
        # 4. 三项强度：取该行前三个数字，钳制 1-5；不足三个 → 保持兜底 3
        nums = [int(n) for n in re.findall(r"\d+", answers.get(4, ""))][:3]
        if len(nums) == 3:
            reaction.tension, reaction.curiosity, reaction.engagement = [
                _clamp_1_5(n) for n in nums]
        # 5. 跳过点：编号 5 的回答，或「跳过：xxx」行冒号后内容
        reaction.skip_point = answers.get(5, "").strip() or _find_skip_point(text)
        return reaction

    # ---------- LLM 设施（callable 注入，P4.2 同款模式） ----------
    async def _call_llm(self, prompt: str) -> str:
        """统一 LLM 出口；无设施/异常/空响应 → ""（上层按不可解析兜底，不阻塞）"""
        if self._llm_call is None:
            return ""
        try:
            resp = await self._llm_call(
                prompt, purpose="reader_proxy",
                temperature=_TEMPERATURE, max_tokens=_MAX_TOKENS)
            return (getattr(resp, "text", "") or "").strip()
        except Exception:
            return ""


def _numbered_answers(text: str) -> dict[int, str]:
    """把 `1. xxx` / `1、xxx` / `1: xxx` 形式的回答行收进 {序号: 回答}（只认 1-5）"""
    answers: dict[int, str] = {}
    for line in text.splitlines():
        m = re.match(r"^\s*([1-5])\s*[.、．:：]?\s*(.*?)\s*$", line)
        if m:
            answers[int(m.group(1))] = m.group(2)
    return answers


def _find_skip_point(text: str) -> str:
    """无编号回答时，从含「跳过」且带冒号的行取冒号后内容"""
    for line in text.splitlines():
        if "跳过" in line and ("：" in line or ":" in line):
            return re.split(r"[:：]", line, maxsplit=1)[-1].strip()
    return ""


def _clamp_1_5(n: int) -> int:
    """强度钳制在 1-5（蓝图四问原文：各1-5）"""
    return max(1, min(5, n))
