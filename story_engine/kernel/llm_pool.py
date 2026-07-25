"""LLMPool — 多 provider LLM 调用池（Module 0.4 / Kernel LLM 维度）

迁移自 story_engine/llm.py。Kernel 通过 llm_call() 统一入口，未来加 provider 路由。

两种模式：
- mock：读 mock_script 的剧本化响应（默认，无 key 时跑通全流程）
- openai_compatible：OpenAI /chat/completions 协议（GLM/DeepSeek/Moonshot 等均兼容）

环境变量（与原 LLMClient 完全一致，保持向后兼容）：
  STORY_ENGINE_LLM_MODE=mock|openai
  STORY_ENGINE_LLM_BASE_URL=https://api.kimi.com/coding/v1
  STORY_ENGINE_LLM_API_KEY=...
  STORY_ENGINE_LLM_MODEL=kimi-for-coding
  STORY_ENGINE_LLM_USER_AGENT=claude-code/0.1.0   # Kimi Code 端点要求 Coding-Agent UA
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import AsyncGenerator

import httpx
from loguru import logger

KIMI_CODE_UA = "claude-code/0.1.0"


@dataclass
class LLMResponse:
    text: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0.0
    mock: bool = False


class LLMPool:
    """LLM 调用池 — Kernel 内部组件"""

    def __init__(self, mode: str | None = None):
        self.mode = mode or os.environ.get("STORY_ENGINE_LLM_MODE", "mock")
        self.base_url = os.environ.get(
            "STORY_ENGINE_LLM_BASE_URL", "https://api.kimi.com/coding/v1")
        self.api_key = os.environ.get("STORY_ENGINE_LLM_API_KEY", "")
        self.model = os.environ.get("STORY_ENGINE_LLM_MODEL", "kimi-for-coding")
        self.user_agent = os.environ.get("STORY_ENGINE_LLM_USER_AGENT", "")
        if not self.user_agent and self.api_key.startswith("sk-kimi-"):
            self.user_agent = KIMI_CODE_UA
        self.call_log: list[dict] = []

    @property
    def is_mock(self) -> bool:
        return self.mode == "mock" or not self.api_key

    async def call(self, prompt: str, *, purpose: str = "generate",
                   temperature: float = 0.7, max_tokens: int = 16384,
                   no_retry: bool = False) -> LLMResponse:
        tag = "[LLM][MOCK]" if self.is_mock else "[LLM]"
        logger.debug(
            "{} 调用 | purpose={} | model={} | temp={} | max_tokens={} | "
            "prompt:\n{}", tag, purpose, self.model, temperature, max_tokens,
            prompt)
        try:
            if self.is_mock:
                resp = await self._mock_call(prompt, purpose)
            else:
                resp = await self._openai_call(prompt, temperature, max_tokens)
                if not resp.text.strip() and purpose != "_retry" \
                        and not no_retry:
                    resp = await self._openai_call(
                        prompt, temperature, max(max_tokens * 2, 16384),
                        force_thinking=True)
        except Exception:
            logger.exception("{} 异常 | purpose={} | model={}", tag, purpose,
                             self.model)
            raise
        logger.debug(
            "{} 响应 | purpose={} | latency={}ms | tokens={}/{} | response:\n{}",
            tag, purpose, round(resp.latency_ms, 1), resp.tokens_in,
            resp.tokens_out, resp.text)
        self.call_log.append({
            "purpose": purpose, "model": resp.model, "mock": resp.mock,
            "latency_ms": round(resp.latency_ms, 1),
            "tokens_in": resp.tokens_in, "tokens_out": resp.tokens_out,
            "prompt_excerpt": prompt[:300],
        })
        self.call_log = self.call_log[-200:]
        return resp

    async def call_stream(
        self, prompt: str, *, purpose: str = "generate",
        temperature: float = 0.7, max_tokens: int = 16384,
    ) -> AsyncGenerator[str, None]:
        """流式调用 LLM，逐 chunk yield delta text（P20）。

        real 模式：httpx stream POST + SSE 行解析 → yield delta content。
        mock 模式：把 mock_script 的完整响应切成小块 yield + 小延迟。
        """
        tag = "[LLM-STREAM][MOCK]" if self.is_mock else "[LLM-STREAM]"
        logger.debug("{} 调用 | purpose={} | model={} | prompt:\n{}", tag,
                     purpose, self.model, prompt)
        if self.is_mock:
            from .. import mock_script
            text = mock_script.respond(purpose, prompt)
            for i in range(0, len(text), 50):
                yield text[i:i + 50]
                await asyncio.sleep(0.05)
            return
        # real mode: SSE stream
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if self.user_agent:
            headers["User-Agent"] = self.user_agent
        body: dict = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "stream": True,
        }
        if self._is_kimi_code:
            body["temperature"] = 0.6
            body["thinking"] = {"type": "disabled"}
        else:
            body["temperature"] = temperature
        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream(
                "POST", f"{self.base_url.rstrip('/')}/chat/completions",
                headers=headers, json=body,
            ) as r:
                if r.status_code != 200:
                    raw = await r.aread()
                    raise LLMError(self._friendly_error(
                        r.status_code, raw.decode("utf-8", "replace")))
                async for line in r.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    delta = (chunk.get("choices", [{}])[0]
                             .get("delta", {}).get("content", ""))
                    if delta:
                        yield delta

    async def _mock_call(self, prompt: str, purpose: str) -> LLMResponse:
        from .. import mock_script
        t0 = time.perf_counter()
        text = mock_script.respond(purpose, prompt)
        return LLMResponse(text=text, model=f"mock:{purpose}", mock=True,
                           latency_ms=(time.perf_counter() - t0) * 1000)

    @property
    def _is_kimi_code(self) -> bool:
        return "kimi.com/coding" in self.base_url

    async def _openai_call(self, prompt: str, temperature: float,
                           max_tokens: int, force_thinking: bool = False) -> LLMResponse:
        t0 = time.perf_counter()
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if self.user_agent:
            headers["User-Agent"] = self.user_agent

        body: dict = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
        }
        if self._is_kimi_code:
            thinking_on = force_thinking or \
                os.environ.get("STORY_ENGINE_LLM_THINKING", "off") == "on"
            if thinking_on:
                body["temperature"] = 1
            else:
                body["temperature"] = 0.6
                body["thinking"] = {"type": "disabled"}
        else:
            body["temperature"] = temperature

        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers=headers, json=body)
            if r.status_code != 200:
                raise LLMError(self._friendly_error(r.status_code, r.text))
            data = r.json()
        msg = data["choices"][0]["message"]
        content = msg.get("content") or ""
        usage = data.get("usage", {})
        return LLMResponse(
            text=content, model=self.model,
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
            latency_ms=(time.perf_counter() - t0) * 1000,
        )

    @staticmethod
    def _friendly_error(status: int, text: str) -> str:
        if "usage limit" in text or "quota" in text.lower():
            return ("LLM 额度已用完（Kimi Code 套餐按周期配额）。"
                    "等下个周期刷新、充值，或换 Moonshot 开放平台 key（platform.moonshot.cn）。")
        if status in (401, 403):
            return f"LLM 认证/权限失败 {status}：{text[:200]}"
        return f"LLM 调用失败 {status}: {text[:300]}"


# 向后兼容别名：旧代码 `from story_engine.llm import LLMClient`
LLMClient = LLMPool


class LLMError(Exception):
    """LLM 调用失败（网络/认证/限流）"""
