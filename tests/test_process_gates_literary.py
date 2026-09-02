"""⑦ ProcessGate.check_l5 文笔维度测试 — 段落超长/句首重复/AI腔残留

这些是规则化（无 LLM）的确定性文笔硬伤检查，在 critic 议会之前拦住，
gate FAIL 驱动下一轮修正。
"""
import asyncio

import pytest

from story_engine.evaluator.process_gates import ProcessGate


def _l5(text):
    """跑 check_l5（async）返回 Gate"""
    return asyncio.run(ProcessGate(style="1000-1500字").check_l5(text))


def _good_chapter():
    """一段正常的章节文本（标题+正文+结尾标点）"""
    return ("标题：测试\n\n"
            "他推开门。冷风灌入。\n\n"
            "屋里漆黑。他点燃灯。\n\n"
            "灯下坐着一个人。")


# ---------- 段落超长 ----------

def test_wall_of_text_flagged_when_paragraph_too_long():
    """单段 >8 句 → wall_of_text FAIL"""
    nine_sents = "。" .join(f"他做了第{i}件事" for i in range(1, 10)) + "。"
    gate = _l5(f"标题：测试\n\n{nine_sents}")
    assert not gate.passed
    assert "wall_of_text" in gate.failures


def test_wall_of_text_not_flagged_for_normal_paragraphs():
    """正常分段（每段 1-2 句）→ 不触发 wall_of_text"""
    gate = _l5(_good_chapter())
    assert "wall_of_text" not in gate.failures


def test_wall_of_text_flagged_when_paragraph_over_600_chars():
    """单段 >600 字（即使句数不多）→ wall_of_text FAIL"""
    long_blob = "长" * 601
    gate = _l5(f"标题：测试\n\n{long_blob}。")
    assert "wall_of_text" in gate.failures


# ---------- 句首重复 ----------

def test_repetitive_opening_flagged():
    """3+ 连续段落同首 2 字 → repetitive_opening FAIL"""
    text = ("标题：测试\n\n"
            "他走过来。\n\n他走到门前。\n\n他走入房间。\n\n他走向窗边。")
    gate = _l5(text)
    assert not gate.passed
    assert "repetitive_opening" in gate.failures


def test_repetitive_opening_not_flagged_for_varied_openings():
    gate = _l5(_good_chapter())
    assert "repetitive_opening" not in gate.failures


def test_repetitive_opening_needs_three_consecutive():
    """仅 2 段同首不触发（需 3+ 连续）"""
    text = "标题：测试\n\n他走了。\n\n他停了。\n\n她来了。"
    gate = _l5(text)
    assert "repetitive_opening" not in gate.failures


# ---------- AI 腔残留 ----------

def test_ai_ism_residue_flagged_when_many():
    """>3 处已知 AI-ism → ai_ism_residue FAIL（安全网，捕过滤漏网）"""
    text = ("标题：测试\n\n"
            "值得注意的是，映入眼帘的是一抹夕阳。"
            "值得注意的是，众所周知，他久久不能平静。")
    gate = _l5(text)
    assert not gate.passed
    assert "ai_ism_residue" in gate.failures


def test_ai_ism_residue_not_flagged_for_clean_text():
    gate = _l5(_good_chapter())
    assert "ai_ism_residue" not in gate.failures


# ---------- 集成：check_l5 整体 ----------

def test_good_chapter_passes_all_literary_checks():
    """正常章节通过全部文笔检查（含原有 title/wordcount/truncated）"""
    gate = _l5(_good_chapter())
    # 字数可能不足（good_chapter 很短），但文笔三项不应触发
    for key in ("wall_of_text", "repetitive_opening", "ai_ism_residue"):
        assert key not in gate.failures
