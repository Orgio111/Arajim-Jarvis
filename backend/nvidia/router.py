"""Smart model router.

Picks the best NIM model for a given task based on tier, prompt size, recent
benchmark scores, and runtime availability. Every agent goes through this —
no model IDs are hardcoded outside `models.py` and `.env`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.config import settings
from backend.core.logger import logger
from backend.nvidia.models import MODEL_REGISTRY, ModelInfo, ModelTier, models_for


@dataclass
class RouteContext:
    """Hints the router uses to pick a model."""
    tier: ModelTier = ModelTier.GENERAL
    estimated_input_tokens: int = 0
    needs_tools: bool = False
    prefer_speed: bool = False
    prefer_quality: bool = False


class ModelRouter:
    def __init__(self) -> None:
        # tier -> default model id from .env
        self._defaults: dict[ModelTier, str] = {
            ModelTier.REASONING: settings.nim_model_reasoning,
            ModelTier.GENERAL: settings.nim_model_general,
            ModelTier.CODE: settings.nim_model_code,
            ModelTier.FAST: settings.nim_model_fast,
            ModelTier.LONG_CONTEXT: settings.nim_model_long_context,
        }
        # model_id -> rolling avg latency / quality score
        self._scores: dict[str, dict[str, float]] = {}
        # disabled models (rate-limited or failing)
        self._disabled: set[str] = set()

    # ------------------------------------------------------------- selection
    def pick(self, ctx: RouteContext) -> str:
        """Return the model id that best fits the context."""
        # 1. Long context override
        if ctx.estimated_input_tokens > 200_000:
            ctx = RouteContext(
                tier=ModelTier.LONG_CONTEXT,
                estimated_input_tokens=ctx.estimated_input_tokens,
                needs_tools=ctx.needs_tools,
            )

        # 2. Fast override when speed > quality
        if ctx.prefer_speed and ctx.tier != ModelTier.LONG_CONTEXT:
            ctx = RouteContext(
                tier=ModelTier.FAST,
                estimated_input_tokens=ctx.estimated_input_tokens,
                needs_tools=ctx.needs_tools,
            )

        candidates = self._candidates(ctx.tier, ctx)
        if not candidates:
            logger.warning(f"No candidates for tier {ctx.tier}; falling back.")
            return self._defaults[ModelTier.GENERAL]

        chosen = self._rank(candidates, ctx)[0]
        logger.debug(f"router.pick tier={ctx.tier} -> {chosen.id}")
        return chosen.id

    def pick_for(self, agent_role: str, **overrides: Any) -> str:
        """Convenience wrapper: pick by agent role name."""
        role_to_tier = {
            "planner": ModelTier.REASONING,
            "executor": ModelTier.GENERAL,
            "coder": ModelTier.CODE,
            "reviewer": ModelTier.REASONING,
            "optimizer": ModelTier.REASONING,
            "router": ModelTier.FAST,
            "voice": ModelTier.FAST,
            "memory": ModelTier.LONG_CONTEXT,
        }
        ctx = RouteContext(tier=role_to_tier.get(agent_role, ModelTier.GENERAL))
        for k, v in overrides.items():
            setattr(ctx, k, v)
        return self.pick(ctx)

    # --------------------------------------------------------------- ranking
    def _candidates(self, tier: ModelTier, ctx: RouteContext) -> list[ModelInfo]:
        pool = models_for(tier) or list(MODEL_REGISTRY.values())
        out: list[ModelInfo] = []
        for m in pool:
            if m.id in self._disabled:
                continue
            if ctx.needs_tools and not m.supports_tools:
                continue
            if ctx.estimated_input_tokens >= m.context_window * 0.8:
                continue
            out.append(m)
        return out

    def _rank(self, models: list[ModelInfo], ctx: RouteContext) -> list[ModelInfo]:
        default_id = self._defaults.get(ctx.tier)

        def score(m: ModelInfo) -> float:
            s = 0.0
            if m.id == default_id:
                s += 10.0  # configured default wins ties
            recent = self._scores.get(m.id, {})
            s += recent.get("quality", 0.0) * 5
            s -= recent.get("latency_s", 0.0)  # lower latency is better
            if ctx.prefer_quality and m.tier == ModelTier.REASONING:
                s += 3
            if ctx.prefer_speed and m.tier == ModelTier.FAST:
                s += 3
            return s

        return sorted(models, key=score, reverse=True)

    # --------------------------------------------------------------- runtime
    def report(
        self,
        model_id: str,
        *,
        latency_s: float | None = None,
        quality: float | None = None,
    ) -> None:
        """Feed back observations from benchmark or live calls."""
        s = self._scores.setdefault(model_id, {"latency_s": 0.0, "quality": 0.0, "n": 0})
        n = s["n"]
        if latency_s is not None:
            s["latency_s"] = (s["latency_s"] * n + latency_s) / (n + 1)
        if quality is not None:
            s["quality"] = (s["quality"] * n + quality) / (n + 1)
        s["n"] = n + 1

    def disable(self, model_id: str) -> None:
        self._disabled.add(model_id)
        logger.warning(f"Router disabled model: {model_id}")

    def enable(self, model_id: str) -> None:
        self._disabled.discard(model_id)

    @property
    def scores(self) -> dict[str, dict[str, float]]:
        return dict(self._scores)


router = ModelRouter()
