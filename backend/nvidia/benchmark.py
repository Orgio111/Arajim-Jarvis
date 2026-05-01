"""Benchmark NIM models head-to-head and feed results into the router."""
from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass

from backend.core.logger import logger
from backend.nvidia.client import get_client
from backend.nvidia.models import MODEL_REGISTRY
from backend.nvidia.router import router

DEFAULT_PROMPT = (
    "You are testing your reasoning. Answer in one sentence: "
    "What is the smallest number that is divisible by every integer from 1 to 10?"
)
EXPECTED_TOKEN = "2520"


@dataclass
class BenchmarkResult:
    model: str
    latency_s: float
    tokens_out: int
    correct: bool
    sample: str


async def benchmark_model(model_id: str, prompt: str = DEFAULT_PROMPT) -> BenchmarkResult:
    client = get_client()
    t0 = time.perf_counter()
    resp = await client.chat(
        model=model_id,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200,
        temperature=0.2,
    )
    dt = time.perf_counter() - t0
    text = (resp.choices[0].message.content or "").strip()
    tokens_out = (resp.usage.completion_tokens if resp.usage else 0) or 0
    correct = EXPECTED_TOKEN in text

    quality = 1.0 if correct else 0.3
    router.report(model_id, latency_s=dt, quality=quality)
    return BenchmarkResult(
        model=model_id, latency_s=dt, tokens_out=tokens_out,
        correct=correct, sample=text[:200],
    )


async def benchmark_all(prompt: str = DEFAULT_PROMPT) -> list[dict]:
    """Run benchmark across the curated catalog in parallel, return JSON-able results."""
    coros = [benchmark_model(mid, prompt) for mid in MODEL_REGISTRY]
    results: list[BenchmarkResult] = []
    for fut in asyncio.as_completed(coros):
        try:
            results.append(await fut)
        except Exception as exc:
            logger.warning(f"Benchmark failed: {exc}")
    results.sort(key=lambda r: (not r.correct, r.latency_s))
    return [asdict(r) for r in results]
