"""跨 router 共享的 Pydantic 请求模型。"""
from __future__ import annotations

from pydantic import BaseModel


class DeriveCastReq(BaseModel):
    """POST /api/gacha/{sid}/derive_cast body：worldview 与 language 的分层 profile，
    均可选（容忍空/部分填写）。"""
    worldview: dict[str, dict[str, str]] = {}
    language: dict[str, dict[str, str]] = {}


class CrossCheckReq(BaseModel):
    worldview: dict | None = None
    cast: list | None = None
