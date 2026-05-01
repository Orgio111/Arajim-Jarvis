"""Optimizer — looks at agent telemetry, model scores, skill stats and proposes tweaks."""
from __future__ import annotations

import json
from typing import Any

from backend.agents.base import Agent
from backend.memory.store import get_store
from backend.nvidia.client import get_client
from backend.nvidia.router import router


class OptimizerAgent(Agent):
    role = "optimizer"
    description = "Reviews system telemetry and proposes performance / routing tweaks."
    system_prompt = (
        "You are JARVIS-Optimizer. Given telemetry, propose concrete improvements: "
        "model swaps, skill prioritization, retry strategy. Return JSON: "
        "{\"observations\": [..], \"actions\": [..]}."
    )

    async def handle(self, task: dict[str, Any]) -> dict[str, Any]:
        telemetry = await self._collect_telemetry()
        text = await self.chat(
            "System telemetry:\n" + json.dumps(telemetry, indent=2)[:4000],
            thinking=True,
            max_tokens=1024,
        )
        return {"agent": self.role, "ok": True, "data": {"telemetry": telemetry, "analysis": text}}

    @staticmethod
    async def _collect_telemetry() -> dict[str, Any]:
        client = get_client()
        return {
            "client_stats": client.stats,
            "router_scores": router.scores,
            "memory_sessions": await get_store().list_sessions(),
        }
