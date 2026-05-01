"""Registry of NVIDIA NIM models with tier metadata.

The router uses this catalog to pick the best model per task. New models are
discovered live via /v1/models when the client first connects, and merged in
without overriding curated metadata.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ModelTier(str, Enum):
    REASONING = "reasoning"        # heavy planning, multi-step thought
    GENERAL = "general"            # everyday chat / agent tool use
    CODE = "code"                  # writing, refactoring, reviewing code
    FAST = "fast"                  # classification, routing, short replies
    LONG_CONTEXT = "long_context"  # large document understanding


@dataclass
class ModelInfo:
    id: str
    tier: ModelTier
    context_window: int
    strengths: tuple[str, ...] = field(default_factory=tuple)
    supports_tools: bool = True
    supports_streaming: bool = True
    nemotron_thinking: bool = False  # supports `detailed thinking on/off`
    notes: str = ""


# Curated catalog (April 2026). The router uses this as its prior; live
# discovery from /v1/models adds anything new at runtime.
MODEL_REGISTRY: dict[str, ModelInfo] = {
    "nvidia/llama-3.3-nemotron-ultra-253b": ModelInfo(
        id="nvidia/llama-3.3-nemotron-ultra-253b",
        tier=ModelTier.REASONING,
        context_window=128_000,
        strengths=("reasoning", "planning", "math", "tool-use"),
        nemotron_thinking=True,
        notes="Top-tier reasoning. Use for the Planner agent and complex decisions.",
    ),
    "nvidia/llama-3.3-nemotron-super-49b": ModelInfo(
        id="nvidia/llama-3.3-nemotron-super-49b",
        tier=ModelTier.GENERAL,
        context_window=128_000,
        strengths=("general", "tool-use", "throughput"),
        nemotron_thinking=True,
        notes="High-throughput general workhorse for the Executor.",
    ),
    "nvidia/llama-3.3-nemotron-nano-8b": ModelInfo(
        id="nvidia/llama-3.3-nemotron-nano-8b",
        tier=ModelTier.FAST,
        context_window=128_000,
        strengths=("speed", "classification", "routing"),
        nemotron_thinking=True,
        notes="Sub-second responses. Used for the Router and quick classifications.",
    ),
    "deepseek-ai/deepseek-v4-flash": ModelInfo(
        id="deepseek-ai/deepseek-v4-flash",
        tier=ModelTier.CODE,
        context_window=1_000_000,
        strengths=("coding", "agentic", "long-context"),
        notes="Best for the Coder agent and long-file refactors.",
    ),
    "deepseek-ai/deepseek-v4-pro": ModelInfo(
        id="deepseek-ai/deepseek-v4-pro",
        tier=ModelTier.REASONING,
        context_window=200_000,
        strengths=("reasoning", "coding", "general"),
        notes="Heaviest DeepSeek; alternative to Nemotron-Ultra.",
    ),
    "moonshotai/kimi-k2.5": ModelInfo(
        id="moonshotai/kimi-k2.5",
        tier=ModelTier.LONG_CONTEXT,
        context_window=2_000_000,
        strengths=("long-context", "reasoning", "agentic"),
        notes="When the prompt is huge. Memory recall over long history.",
    ),
    "qwen/qwen2.5-coder-32b-instruct": ModelInfo(
        id="qwen/qwen2.5-coder-32b-instruct",
        tier=ModelTier.CODE,
        context_window=128_000,
        strengths=("coding",),
        notes="Specialized coder. Backup for the Coder agent.",
    ),
    "meta/llama-3.1-405b-instruct": ModelInfo(
        id="meta/llama-3.1-405b-instruct",
        tier=ModelTier.GENERAL,
        context_window=128_000,
        strengths=("general", "stable"),
        notes="Stable flagship. Fallback when Nemotron is rate-limited.",
    ),
    "minimaxai/minimax-m2.7": ModelInfo(
        id="minimaxai/minimax-m2.7",
        tier=ModelTier.GENERAL,
        context_window=200_000,
        strengths=("general", "cost-efficient"),
        notes="Balanced cost/quality alternative.",
    ),
}


def models_for(tier: ModelTier) -> list[ModelInfo]:
    """Return all models in a tier, ordered by curated preference."""
    return [m for m in MODEL_REGISTRY.values() if m.tier == tier]
