"""Embedding 能力 seam（借鉴 DSH 能力三角）。

Service Definition：`EmbedProvider` 接口。默认 Provider 是 `Embedder`
（kernel/embedding.py，fastembed/ONNX 实现，天然满足 Protocol）。
换 embedding 实现（如换模型/换 onnx 之外的运行时）= 换 Provider 注册进 kernel。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbedProvider(Protocol):
    """Embedding 能力接口。Embedder 天然满足。"""
    is_dummy: bool
    dimensions: int
    model_name: str

    async def embed(self, text: str) -> list[float]: ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...
