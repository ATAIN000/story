"""Module 5.3 humanize — 规则化人类感注入（蓝图 5.3，Phase 5 计划决策5，零 LLM）

- `_filter_ai_isms(text, language)`：AI 味黑名单替换表（中文 12 条 + 英文 9 条），
  处理 = 直接删除或替换为更朴素表达（替换表 {ism: replacement or ""}），
  删改而非重写——不做二次 LLM
- `_inject_imperfection(text, language)`：`STORY_ENGINE_HUMANIZE_FLAW` env 门控，
  默认 0=关（蓝图 5-10% 瑕疵有损质量）；>0 时按该百分比概率注入 1 处微小瑕疵
- `_inject_burstiness` / `_show_not_tell_rewrite` 按决策5 不在此实现：
  句长波动 / show-not-tell 写进 Realizer 渲染指令（见 realizer.py `_craft_rules`），
  不做二次 LLM 改写
"""
from __future__ import annotations

import os
import random
import re

# ---- AI 味黑名单替换表：删改而非重写 ----
# 选取原则：生成文本中高频出现、一眼可辨的「AI 腔」；替换目标为更朴素表达，
# 删除（""）只用于去掉后句子仍成立的词条。表顺序即替换顺序（dict 保序）。
AI_ISMS_ZH: dict[str, str] = {
    "值得注意的是": "",
    "总而言之": "总之",
    "综上所述": "如此看来",
    "众所周知": "",
    "与此同时": "同时",
    "不得不说": "只好说",
    "不禁": "不由",
    "仿佛": "好似",
    "似乎": "像是",
    "映入眼帘": "",
    "久久不能平静": "难以平复",
    "一抹": "",
}

AI_ISMS_EN: dict[str, str] = {
    "It is worth noting that": "Notably",
    "It goes without saying that": "Clearly",
    "In conclusion": "In the end",
    "In summary": "Overall",
    "Meanwhile,": "Then,",
    "Needless to say": "Of course",
    "a tapestry of": "a web of",
    "a testament to": "a sign of",
    "delve into": "dig into",
}

_AI_ISM_TABLES: dict[str, dict[str, str]] = {"zh": AI_ISMS_ZH, "en": AI_ISMS_EN}


def _filter_ai_isms(text: str, language: str = "zh") -> str:
    """按语言套用 AI 味替换表；未知语言无表 → 原样返回。

    删除类条目（replacement=""）留下的标点残渣做最小清理：
    zh 收拢连用逗号、句首逗号；en 收拢双空格。不做其他重写。
    """
    table = _AI_ISM_TABLES.get(language)
    if not table:
        return text
    for ism, repl in table.items():
        if ism in text:
            text = text.replace(ism, repl)
    if language == "zh":
        text = re.sub(r"，{2,}", "，", text)
        text = re.sub(r"。，", "。", text)
        text = re.sub(r"(^|\n)，", r"\1", text)
    else:
        text = re.sub(r" {2,}", " ", text)
    return text


def _inject_imperfection(text: str, language: str = "zh") -> str:
    """按概率注入 1 处微小瑕疵（env `STORY_ENGINE_HUMANIZE_FLAW`，默认 0=关）。

    >0 时作为百分比概率（蓝图 5-10%）生效。瑕疵形式是刻意简化版
    「有控制的瑕疵」：zh 删一处句末「了」；en 删一处 "very "；
    找不到目标则原文返回。默认关闭是因为蓝图验证 5-10% 瑕疵有损质量。
    """
    try:
        pct = float(os.environ.get("STORY_ENGINE_HUMANIZE_FLAW", "0") or "0")
    except ValueError:
        pct = 0.0
    if pct <= 0 or random.random() * 100 >= pct:
        return text
    if language == "zh":
        return text.replace("了。", "。", 1)
    return text.replace("very ", "", 1)
