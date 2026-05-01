"""Intent prediction.

A fast NIM model classifies the incoming message into one of:
  chat | command | code | research | system | memory | upgrade | search

The orchestrator uses this to decide:
  - skip planning entirely for trivial chat (faster)
  - use deep_search for research
  - use the debate collaboration for complex code
  - dispatch directly to a single skill when the intent is unambiguous
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from backend.cache.manager import cache
from backend.core.logger import logger
from backend.nvidia.client import get_client
from backend.nvidia.router import router


INTENTS = ["chat", "command", "code", "research", "system", "memory", "upgrade", "search"]


SYSTEM = (
    "You are a fast intent classifier. Given the user's message, output strict JSON: "
    "{\"intent\": \"chat|command|code|research|system|memory|upgrade|search\", "
    "\"confidence\": 0..1, "
    "\"strategy\": \"direct|plan|debate|deep_search\", "
    "\"reasoning\": \"...\", "
    "\"suggested_skill\": \"<skill_name or null>\"}"
)


@dataclass
class IntentPrediction:
    intent: str
    confidence: float
    strategy: str  # direct | plan | debate | deep_search
    reasoning: str
    suggested_skill: str | None = None


def _extract_json(text: str) -> dict | None:
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        try: return json.loads(fence.group(1))
        except json.JSONDecodeError: pass
    brace = re.search(r"(\{.*\})", text, re.DOTALL)
    if brace:
        try: return json.loads(brace.group(1))
        except json.JSONDecodeError: return None
    return None


async def predict_intent(message: str) -> IntentPrediction:
    """Cached, fast intent prediction (sub-second)."""
    async def _predict() -> dict:
        client = get_client()
        model = router.pick_for("router", prefer_speed=True)
        resp = await client.chat(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": message},
            ],
            max_tokens=200, temperature=0.0,
        )
        text = resp.choices[0].message.content or ""
        data = _extract_json(text) or {"intent": "chat", "confidence": 0.5,
                                       "strategy": "plan", "reasoning": "fallback"}
        return data

    try:
        data = await cache.wrap(
            namespace="intent",
            key_text=message,
            fn=_predict,
            semantic=True,
            ttl=300,
        )
    except Exception as exc:
        logger.warning(f"intent predict failed: {exc}")
        data = {"intent": "chat", "confidence": 0.4, "strategy": "plan",
                "reasoning": "fallback on error"}

    return IntentPrediction(
        intent=data.get("intent", "chat"),
        confidence=float(data.get("confidence", 0.5)),
        strategy=data.get("strategy", "plan"),
        reasoning=data.get("reasoning", ""),
        suggested_skill=data.get("suggested_skill"),
    )
