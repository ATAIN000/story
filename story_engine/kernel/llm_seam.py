"""LLM 能力 seam（借鉴 DSH 能力三角：Service Definition / Provider / Consumer）。

本文件定义 **Service Definition**（能力接口）。`LLMPool` 是默认 Provider
（天然满足 Protocol，无需改其实现）；Consumer 是 engine/critic 等调用方。

换模型/换 provider = 换 Provider（写一个满足 LLMProvider 的类注册进 kernel），
不改核心。critic 用更强模型：Consumer 调用时传 model=STORY_ENGINE_CRITIC_MODEL。
"""
from __future__ import annotations

from typing import Any, AsyncGenerator, Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """LLM 能力接口（Service Definition）。

    LLMPool 现状天然满足（call/call_stream/is_mock/model/base_url/call_log）。
    新 Provider（如直连 Anthropic/本地 vLLM）实现同签名即可注册。
    """
    is_mock: bool
    model: str
    base_url: str

    async def call(self, prompt: str, *, purpose: str = "generate",
                   temperature: float = 0.7, max_tokens: int = 16384,
                   no_retry: bool = False,
                   model: str | None = None) -> Any: ...

    async def call_stream(self, prompt: str, *, purpose: str = "generate",
                          temperature: float = 0.7, max_tokens: int = 16384,
                          on_thinking=None) -> AsyncGenerator[str, None]: ...


def critic_model(default: str | None = None) -> str | None:
    """critic 评估用的模型覆盖：STORY_ENGINE_CRITIC_MODEL（蓝图要求 critic ≥
    generator）。返回 None 表示用 generator 同模型（现状兜底）。"""
    import os
    return os.environ.get("STORY_ENGINE_CRITIC_MODEL") or default
