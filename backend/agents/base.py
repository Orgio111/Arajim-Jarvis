"""Base Agent class. All agents share this contract."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from backend.core.events import bus
from backend.core.logger import logger
from backend.nvidia.client import get_client
from backend.nvidia.router import router


@dataclass
class AgentMessage:
    role: str       # "user" | "assistant" | "system" | "tool"
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_openai(self) -> dict[str, Any]:
        return {"role": self.role, "content": self.content}


class Agent(ABC):
    role: str = "agent"
    description: str = ""
    system_prompt: str = ""

    def __init__(self) -> None:
        self.client = get_client()
        self.history: list[AgentMessage] = []

    # ------------------------------------------------------------------- model
    def model(self, **overrides: Any) -> str:
        return router.pick_for(self.role, **overrides)

    # ------------------------------------------------------------------ chat
    async def chat(
        self,
        user_message: str,
        *,
        extra_context: list[AgentMessage] | None = None,
        max_tokens: int = 2048,
        thinking: bool | None = None,
        publish: bool = True,
    ) -> str:
        messages: list[dict[str, Any]] = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        for ctx in extra_context or []:
            messages.append(ctx.to_openai())
        for h in self.history[-10:]:
            messages.append(h.to_openai())
        messages.append({"role": "user", "content": user_message})

        model = self.model()
        if publish:
            await bus.publish(
                "agent",
                {"type": "thinking", "agent": self.role, "model": model},
            )

        resp = await self.client.chat(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            thinking=thinking,
        )
        text = resp.choices[0].message.content or ""
        self.history.append(AgentMessage(role="user", content=user_message))
        self.history.append(AgentMessage(role="assistant", content=text))
        if publish:
            await bus.publish(
                "agent",
                {"type": "reply", "agent": self.role, "model": model, "content": text},
            )
        logger.debug(f"[{self.role}] -> {len(text)}c via {model}")
        return text

    # -------------------------------------------------------------- abstract
    @abstractmethod
    async def handle(self, task: dict[str, Any]) -> dict[str, Any]:
        """Process one structured task and return a structured result."""
