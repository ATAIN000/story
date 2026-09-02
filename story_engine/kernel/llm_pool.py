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
        # Model-visible-logged：可选记录钩子（kernel 注入 → EventStore.record_llm_call）。
        # 每次 call 完成时回调，携带完整 prompt/response/章节，使任何一章的
        # 生成上下文可从 llm_calls 表精确重建/回放。
        self.on_call = None          # Callable(**record) | None
        self.current_chapter = None  # engine 生成章节时设置/清除

    @property
    def is_mock(self) -> bool:
        return self.mode == "mock" or not self.api_key

    async def call(self, prompt: str, *, purpose: str = "generate",
                   temperature: float = 0.7, max_tokens: int = 16384,
                   no_retry: bool = False,
                   model: str | None = None) -> LLMResponse:
        # 第三波⑥：model 覆盖（None → self.model）。供 critic 用更强模型评估
        # （STORY_ENGINE_CRITIC_MODEL），生成仍用 self.model。向后兼容：不传则同现状。
        eff_model = model or self.model
        tag = "[LLM][MOCK]" if self.is_mock else "[LLM]"
        logger.debug(
            "{} 调用 | purpose={} | model={} | temp={} | max_tokens={} | "
            "prompt:\n{}", tag, purpose, eff_model, temperature, max_tokens,
            prompt)
        try:
            if self.is_mock:
                resp = await self._mock_call(prompt, purpose)
            else:
                resp = await self._openai_call(prompt, temperature, max_tokens,
                                               purpose=purpose, model=model)
                if not resp.text.strip() and purpose != "_retry" \
                        and not no_retry:
                    resp = await self._openai_call(
                        prompt, temperature, max(max_tokens * 2, 16384),
                        force_thinking=True, purpose=purpose, model=model)
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
        # Model-visible-logged：完成时触发记录钩子（完整 prompt/response 落盘）
        if self.on_call is not None:
            try:
                self.on_call(chapter=self.current_chapter, purpose=purpose,
                             model=resp.model, prompt=prompt,
                             response=resp.text, tokens_in=resp.tokens_in,
                             tokens_out=resp.tokens_out,
                             latency_ms=round(resp.latency_ms, 1))
            except Exception:
                logger.debug("on_call 记录钩子异常（已忽略）", exc_info=True)
        return resp

    async def call_stream(
        self, prompt: str, *, purpose: str = "generate",
        temperature: float = 0.7, max_tokens: int = 16384,
        on_thinking=None,
    ) -> AsyncGenerator[str, None]:
        """流式调用 LLM，逐 chunk yield delta text（P20）。

        real 模式：httpx stream POST + SSE 行解析 → yield delta content。
        mock 模式：把 mock_script 的完整响应切成小块 yield + 小延迟。

        on_thinking：可选 async 回调——GLM-5.x thinking 模式下，首次检测到
        reasoning_content（思考流）时调用一次。用途：宏观计划等长 thinking
        场景，前端收到通知后显示「AI 深度构思中」而不是 3-5 分钟黑屏。
        思考流本身不 yield（保持正文纯净，解析方不受影响）。
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
            if self._thinking_disabled(purpose):
                body["thinking"] = {"type": "disabled"}
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
                    delta_obj = (chunk.get("choices", [{}])[0]
                                 .get("delta", {}))
                    # GLM-5.x thinking：reasoning_content 首次出现 → 通知调用方
                    # （思考流不进正文 yield，只发一次信号）
                    if on_thinking is not None and delta_obj.get(
                            "reasoning_content"):
                        hook, on_thinking = on_thinking, None
                        try:
                            await hook()
                        except Exception:
                            logger.debug("on_thinking 回调异常（已忽略）",
                                         exc_info=True)
                    delta = delta_obj.get("content", "")
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

    # 创作型 purpose：creative 模式下保留思考（质量敏感）
    _THINKING_KEEP_PREFIXES = (
        "realize_chapter", "correct_chapter", "macro_plan",
        "rewrite_paragraph", "synth",
    )
    # 任何模式下都关闭 thinking 的 purpose：纯机械输出（JSON 数组/名单），
    # thinking 对质量零帮助、只加延迟（实测 GLM-5.2 起名 32-55s → 关掉后秒级）
    _THINKING_NEVER_PREFIXES = ("cast_naming", "script_analyze", "entity_extract")

    def _thinking_disabled(self, purpose: str) -> bool:
        """GLM-5.x 等非 kimi-code 渠道的思考开关。

        STORY_ENGINE_LLM_THINKING：
        - on（默认）：从不下发 thinking 字段（现状，GLM 默认思考）；
        - off：全部调用关闭思考（最快，质量有损）；
        - creative：仅创作型 purpose 保留思考，propose/critic/reflect 等
          机械性调用关闭（推荐：省时约一半，质量基本无损）。
        _THINKING_NEVER_PREFIXES 中的 purpose 在任何模式下都关闭。
        """
        if self._is_kimi_code:
            return False  # kimi 渠道走 _openai_call 既有分支
        if any(purpose.startswith(p) for p in self._THINKING_NEVER_PREFIXES):
            return True
        mode = os.environ.get("STORY_ENGINE_LLM_THINKING", "on").lower()
        if mode == "off":
            return True
        if mode == "creative":
            return not any(purpose.startswith(p)
                           for p in self._THINKING_KEEP_PREFIXES)
        return False

    async def _openai_call(self, prompt: str, temperature: float,
                           max_tokens: int, force_thinking: bool = False,
                           purpose: str = "generate",
                           model: str | None = None) -> LLMResponse:
        eff_model = model or self.model
        t0 = time.perf_counter()
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if self.user_agent:
            headers["User-Agent"] = self.user_agent

        body: dict = {
            "model": eff_model,
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
            if self._thinking_disabled(purpose):
                body["thinking"] = {"type": "disabled"}

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
            text=content, model=eff_model,
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
