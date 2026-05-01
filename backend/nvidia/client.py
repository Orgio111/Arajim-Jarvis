"""Async NVIDIA NIM client with streaming, retry, and parallel execution.

NIM is OpenAI-API-compatible at https://integrate.api.nvidia.com/v1, so we
use the official `openai` SDK in async mode. This is the *only* LLM
transport in the system — every model call routes through here.
"""
from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Iterable

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from backend.config import settings
from backend.core.events import bus
from backend.core.logger import logger


class NIMError(Exception):
    """Wraps any NIM API failure."""


class NIMClient:
    """Thin async wrapper around the OpenAI-compatible NIM endpoint."""

    def __init__(self) -> None:
        if not settings.nvidia_api_key:
            logger.warning(
                "NVIDIA_API_KEY is not set. NIM calls will fail until you populate .env."
            )
        self._client = AsyncOpenAI(
            base_url=settings.nvidia_base_url,
            api_key=settings.nvidia_api_key or "missing",
            timeout=120.0,
        )
        self._semaphore = asyncio.Semaphore(8)
        self._stats: dict[str, dict[str, float]] = {}

    # ----------------------------------------------------------------- chat
    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.6,
        top_p: float = 0.95,
        max_tokens: int = 4096,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict | None = None,
        guided_json: dict[str, Any] | None = None,
        thinking: bool | None = None,
    ) -> ChatCompletion:
        """One-shot chat completion. Returns the full ChatCompletion."""
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": self._inject_thinking(messages, thinking),
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            if tool_choice is not None:
                kwargs["tool_choice"] = tool_choice
        if guided_json is not None:
            kwargs["extra_body"] = {"nvext": {"guided_json": guided_json}}

        async with self._semaphore:
            try:
                async for attempt in AsyncRetrying(
                    stop=stop_after_attempt(4),
                    wait=wait_exponential_jitter(initial=1, max=30),
                    retry=retry_if_exception_type(Exception),
                    reraise=True,
                ):
                    with attempt:
                        result = await self._client.chat.completions.create(**kwargs)
                        self._record_stats(model, result)
                        return result
            except Exception as exc:  # pragma: no cover
                raise NIMError(f"NIM chat failed for {model}: {exc}") from exc
        raise NIMError(f"NIM chat failed for {model}")  # unreachable

    # ------------------------------------------------------------- streaming
    async def stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.6,
        top_p: float = 0.95,
        max_tokens: int = 4096,
        thinking: bool | None = None,
        publish_channel: str | None = None,
    ) -> AsyncIterator[str]:
        """Token stream. Optionally publishes deltas to the event bus."""
        async with self._semaphore:
            stream = await self._client.chat.completions.create(
                model=model,
                messages=self._inject_thinking(messages, thinking),
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if not delta:
                    continue
                if publish_channel:
                    await bus.publish(
                        publish_channel, {"type": "token", "model": model, "delta": delta}
                    )
                yield delta

    # -------------------------------------------------------------- parallel
    async def parallel(
        self,
        *,
        model: str,
        prompt_groups: Iterable[list[dict[str, Any]]],
        temperature: float = 0.6,
        max_tokens: int = 2048,
    ) -> list[ChatCompletion]:
        """Fan out N prompts to the same model concurrently."""
        return await asyncio.gather(
            *(
                self.chat(
                    model=model, messages=msgs,
                    temperature=temperature, max_tokens=max_tokens,
                )
                for msgs in prompt_groups
            )
        )

    async def race(
        self,
        *,
        models: list[str],
        messages: list[dict[str, Any]],
        max_tokens: int = 2048,
    ) -> ChatCompletion:
        """Send the same prompt to several models, return whichever finishes first."""
        tasks = [
            asyncio.create_task(
                self.chat(model=m, messages=messages, max_tokens=max_tokens)
            )
            for m in models
        ]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for p in pending:
            p.cancel()
        return done.pop().result()

    # --------------------------------------------------------------- catalog
    async def list_models(self) -> list[str]:
        try:
            resp = await self._client.models.list()
            return [m.id for m in resp.data]
        except Exception as exc:
            logger.warning(f"Could not list NIM models: {exc}")
            return []

    # ---------------------------------------------------------------- stats
    @property
    def stats(self) -> dict[str, dict[str, float]]:
        return dict(self._stats)

    def _record_stats(self, model: str, result: ChatCompletion) -> None:
        usage = getattr(result, "usage", None)
        if not usage:
            return
        s = self._stats.setdefault(model, {"calls": 0, "tokens_in": 0, "tokens_out": 0})
        s["calls"] += 1
        s["tokens_in"] += usage.prompt_tokens or 0
        s["tokens_out"] += usage.completion_tokens or 0

    @staticmethod
    def _inject_thinking(
        messages: list[dict[str, Any]], thinking: bool | None
    ) -> list[dict[str, Any]]:
        """Nemotron-specific: prepend `detailed thinking on/off` system msg."""
        if thinking is None:
            return messages
        marker = "detailed thinking on" if thinking else "detailed thinking off"
        return [{"role": "system", "content": marker}, *messages]


_singleton: NIMClient | None = None


def get_client() -> NIMClient:
    global _singleton
    if _singleton is None:
        _singleton = NIMClient()
    return _singleton
