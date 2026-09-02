"""critic 驱动叙事修订测试 — _llm_correct 的 feedback+无违规分支

第二波②延伸：critic 发现文学性问题（角色动机断裂等）但 draft 无世界状态违规时，
_llm_correct 原用「修正违规」框架（规则全是认知/物理/世界规则），对文学反馈误导
模型、导致 best_round 恒 0。现改为「叙事修订」框架。本测试固化该分支与原违规
修正路径的区分。
"""
import asyncio

from story_engine.engine import StoryEngine


class _Resp:
    def __init__(self, text):
        self.text = text


class _CapLLM:
    """捕获 correct_chapter purpose 的 prompt"""

    def __init__(self):
        self.correct_prompt = None

    async def call(self, prompt, *, purpose, temperature, **kw):
        if purpose == "correct_chapter":
            self.correct_prompt = prompt
        return _Resp("修订后正文\n标题：测试")


class _StubEngine:
    """轻量 self：只暴露 _llm_correct 依赖（绕过剧本/世界状态真实设施）"""

    def __init__(self, llm):
        self.llm = llm

    def _world_state_digest(self, state):
        return "世界状态摘要"

    def _world_rule_correction_hint(self):
        return "超自然规则提示"

    def _scripted(self, chapter_no):
        return False   # 强制走 LLM 修正，不进 mock 剧本分支


def _run(coro):
    return asyncio.run(coro)


def test_feedback_without_violations_uses_narrative_revision_prompt():
    """critic 反馈 + 无违规 → 叙事修订框架（评审反馈/修订纪律），非违规修正框架"""
    llm = _CapLLM()
    _run(StoryEngine._llm_correct(
        _StubEngine(llm), 5, "正文草稿内容", [], None,
        feedback=["百晓生抛弃同伴的动机断裂，需补足心理依据"],
        with_events=False))
    p = llm.correct_prompt
    assert p is not None
    assert "评审反馈" in p
    assert "修订纪律" in p
    # 不应出现违规修正框架的标志
    assert "检查发现的违规" not in p
    assert "自评反馈" not in p
    assert "认知违规" not in p


def test_violations_plus_feedback_keeps_violation_path():
    """违规 + 反馈 → 保留原违规修正路径（自评反馈 + 检查发现的违规）"""
    llm = _CapLLM()
    viols = [{"event": "百晓生凭空获知密道", "reason": "认知违规"}]
    _run(StoryEngine._llm_correct(
        _StubEngine(llm), 5, "正文草稿", viols, None,
        feedback=["某修正项"], with_events=False))
    p = llm.correct_prompt
    assert "自评反馈" in p
    assert "检查发现的违规" in p


def test_violations_only_no_feedback_uses_pure_violation_path():
    """仅违规无反馈 → 纯违规修正（检查发现的违规，无自评反馈段）"""
    llm = _CapLLM()
    viols = [{"event": "X", "reason": "物理违规"}]
    _run(StoryEngine._llm_correct(
        _StubEngine(llm), 5, "正文", viols, None, with_events=False))
    p = llm.correct_prompt
    assert "检查发现的违规" in p
    assert "自评反馈" not in p


def test_narrative_revision_returns_llm_text():
    """叙事修订分支返回 LLM 文本（with_events=False 不做事件抽取）"""
    llm = _CapLLM()
    out = _run(StoryEngine._llm_correct(
        _StubEngine(llm), 5, "正文", [], None,
        feedback=["动机补足"], with_events=False))
    assert out["text"] == "修订后正文\n标题：测试"
