"""Embedder — 本地 bge-small-zh-v1.5（Phase 2 / Module 2.2 L0 向量层）

蓝图技术栈：sqlite-vec + bge-small-zh。
使用 FastEmbed（ONNX Runtime）替代 sentence-transformers，
无需 PyTorch，安装体积从 ~2GB 降到 ~30MB，CPU 推理更快。

环境变量：
  STORY_ENGINE_EMBED_MODE=local|dummy          # 默认 local；无模型时自动退到 dummy
  STORY_ENGINE_EMBED_MODEL=BAAI/bge-small-zh-v1.5
  STORY_ENGINE_EMBED_DIMENSIONS=512            # bge-small-zh-v1.5 固有维度
  HF_ENDPOINT=https://hf-mirror.com            # 国内镜像（建议写进 .env）

成本控制：
  - 本地缓存（LRU + 可选落盘）：同一文本不重复 encode
  - embed_batch：fastembed 原生批处理
  - dummy 模式：hash 伪向量，测试无 GPU/无模型也能跑
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import struct
import time
from collections import OrderedDict
from pathlib import Path

# 国内镜像优先：在 import huggingface 相关包前设置
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"
DEFAULT_DIM = 512  # bge-small-zh-v1.5 固有输出维度


class EmbedderError(Exception):
    """Embedding 调用失败"""


class Embedder:
    """本地文本向量客户端 — FastEmbed(bge-small-zh-v1.5, ONNX) + dummy 兜底"""

    def __init__(
        self,
        model: str | None = None,
        dimensions: int | None = None,
        *,
        mode: str | None = None,
        device: str | None = None,
        cache_path: str | Path | None = None,
        lazy_load: bool = True,
    ):
        self.model_name = model or os.environ.get(
            "STORY_ENGINE_EMBED_MODEL", DEFAULT_MODEL)
        dim_env = os.environ.get("STORY_ENGINE_EMBED_DIMENSIONS")
        self.dimensions = int(dimensions or dim_env or DEFAULT_DIM)
        self.mode = (
            mode
            or os.environ.get("STORY_ENGINE_EMBED_MODE", "local")
        ).lower()
        self.device = device or os.environ.get("STORY_ENGINE_EMBED_DEVICE", "auto")

        self._model = None  # SentenceTransformer 实例（懒加载）
        self._load_error: str | None = None

        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_capacity = 4096
        self._cache_path = Path(cache_path) if cache_path else None
        self._load_cache()
        self._lock = asyncio.Lock()
        self.call_log: list[dict] = []

        if not lazy_load and self.mode == "local":
            self._ensure_model()

    # =========================================================
    # 公开属性
    # =========================================================
    @property
    def is_dummy(self) -> bool:
        """dummy 模式：无本地模型 / 显式指定 / 加载失败"""
        if self.mode == "dummy":
            return True
        if self.mode == "local":
            # 尝试一次加载；失败则永久 dummy
            if self._model is None and self._load_error is None:
                try:
                    self._ensure_model()
                except Exception as e:
                    self._load_error = str(e)
                    return True
            return self._model is None
        return True

    # =========================================================
    # 公开 API
    # =========================================================
    async def embed(self, text: str) -> list[float]:
        """单条文本 → 向量（自动命中缓存）"""
        if not text:
            return [0.0] * self.dimensions
        cache_key = self._cache_key(text)
        async with self._lock:
            hit = self._cache_get(cache_key)
        if hit is not None:
            return hit

        vec = await self._raw_embed_one(text)
        async with self._lock:
            self._cache_put(cache_key, vec)
            if self._cache_path:
                self._save_cache()
        return vec

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量文本 → 向量列表"""
        if not texts:
            return []

        results: list[list[float] | None] = [None] * len(texts)
        misses: list[int] = []

        async with self._lock:
            for i, t in enumerate(texts):
                if not t:
                    results[i] = [0.0] * self.dimensions
                    continue
                hit = self._cache_get(self._cache_key(t))
                if hit is not None:
                    results[i] = hit
                else:
                    misses.append(i)

        if misses:
            miss_texts = [texts[i] for i in misses]
            miss_vecs = await self._raw_embed_batch(miss_texts)
            async with self._lock:
                for idx, vec in zip(misses, miss_vecs):
                    results[idx] = vec
                    self._cache_put(self._cache_key(texts[idx]), vec)
                if self._cache_path:
                    self._save_cache()

        return [r if r is not None else [0.0] * self.dimensions for r in results]

    def close(self) -> None:
        self._model = None

    # =========================================================
    # 本地模型加载 / encode
    # =========================================================
    def _ensure_model(self):
        if self._model is not None:
            return
        if self.mode == "dummy":
            return
        # 确保镜像端点
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        try:
            from fastembed import TextEmbedding
        except ImportError as e:
            raise EmbedderError(
                "缺少 fastembed。请 pip install fastembed"
            ) from e

        t0 = time.perf_counter()
        self._model = TextEmbedding(model_name=self.model_name)
        # 校准维度（模型固有维度优先）：fastembed 首次 embed 触发模型下载
        try:
            probe = list(self._model.embed(["ping"]))
            actual = int(probe[0].shape[-1])
            if actual != self.dimensions:
                self.dimensions = actual
        except Exception:
            pass
        self.call_log.append({
            "event": "model_loaded",
            "model": self.model_name,
            "dimensions": self.dimensions,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
        })

    async def _raw_embed_one(self, text: str) -> list[float]:
        vecs = await self._raw_embed_batch([text])
        return vecs[0]

    async def _raw_embed_batch(self, texts: list[str]) -> list[list[float]]:
        if self.is_dummy:
            return [self._hash_vec(t) for t in texts]

        t0 = time.perf_counter()

        def _encode():
            self._ensure_model()
            assert self._model is not None
            arrs = list(self._model.embed(texts))
            return [list(map(float, row)) for row in arrs]

        vecs = await asyncio.to_thread(_encode)
        self.call_log.append({
            "model": self.model_name,
            "n": len(texts),
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            "preview": texts[0][:60],
            "backend": "local",
        })
        self.call_log = self.call_log[-200:]
        return vecs

    # =========================================================
    # Dummy 兜底（hash 伪向量）
    # =========================================================
    def _hash_vec(self, text: str) -> list[float]:
        h = hashlib.sha256(text.encode("utf-8")).digest()
        out: list[float] = []
        i = 0
        while len(out) < self.dimensions:
            chunk = h[i % len(h):(i % len(h)) + 4]
            if len(chunk) < 4:
                chunk = chunk + h[:4 - len(chunk)]
            (val,) = struct.unpack("<f", chunk)
            if not math.isfinite(val):
                val = 0.0
            val = max(-1.0, min(1.0, val / 1e38 if abs(val) > 1e38 else val))
            out.append(val)
            i += 4
        norm = math.sqrt(sum(x * x for x in out))
        if norm < 1e-9:
            out[0] = 1.0
            norm = 1.0
        return [x / norm for x in out[:self.dimensions]]

    # =========================================================
    # 缓存
    # =========================================================
    def _cache_key(self, text: str) -> str:
        return f"{self.model_name}:{self.dimensions}:{hashlib.sha1(text.encode('utf-8')).hexdigest()}"

    def _cache_get(self, key: str) -> list[float] | None:
        v = self._cache.get(key)
        if v is not None:
            self._cache.move_to_end(key)
        return v

    def _cache_put(self, key: str, value: list[float]) -> None:
        self._cache[key] = value
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_capacity:
            self._cache.popitem(last=False)

    def _load_cache(self) -> None:
        if not self._cache_path or not self._cache_path.exists():
            return
        try:
            raw = json.loads(self._cache_path.read_text(encoding="utf-8"))
            for k, v in raw.items():
                self._cache[k] = v
        except (json.JSONDecodeError, OSError):
            pass

    def _save_cache(self) -> None:
        if not self._cache_path:
            return
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(
                json.dumps(self._cache, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
