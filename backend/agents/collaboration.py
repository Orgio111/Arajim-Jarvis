"""Agent debate and cross-review.

For high-stakes tasks (complex code, ambiguous research) the orchestrator
runs a debate loop instead of a single-pass plan:

  1. Coder produces v1
  2. Reviewer scores v1 and emits issues
  3. Optimizer rewrites v1 → v2 addressing issues
  4. Reviewer scores v2; loop ends when score >= MIN_SCORE or rounds exhausted

Final output is the highest-scored version with the merged improvements.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from backend.agents.coder import CoderAgent
from backend.agents.optimizer import OptimizerAgent
from backend.agents.reviewer import ReviewerAgent
from backend.core.events import bus
from backend.core.logger import logger


MIN_SCORE = 8.5
MAX_ROUNDS = 3


@dataclass
class DebateRound:
    n: int
    output: str
    review: dict[str, Any]
    score: float


@dataclass
class DebateResult:
    final: str
    rounds: list[DebateRound] = field(default_factory=list)
    elapsed_s: float = 0.0


class CollaborationEngine:
    def __init__(self) -> None:
        self.coder = CoderAgent()
        self.reviewer = ReviewerAgent()
        self.optimizer = OptimizerAgent()

    async def debate(self, task: str, *, language: str = "python",
                     max_rounds: int = MAX_ROUNDS) -> DebateResult:
        t0 = time.perf_counter()
        rounds: list[DebateRound] = []

        # Initial pass
        first = await self.coder.handle({
            "description": task,
            "input": {"language": language, "instruction": task},
        })
        current = first["data"].get("code") or first["data"].get("output", "")

        for n in range(max_rounds):
            await bus.publish("debate", {"type": "round", "n": n, "phase": "review"})
            review = (await self.reviewer.handle({
                "input": {"target": current},
                "description": "review the proposed work strictly",
            }))["data"]
            score = float(review.get("score", 5))
            rounds.append(DebateRound(n=n, output=current, review=review, score=score))
            if score >= MIN_SCORE or review.get("approve") and score >= 7.5:
                break

            await bus.publish("debate", {"type": "round", "n": n, "phase": "optimize"})
            opt = await self.optimizer.handle({
                "description": task,
                "input": {
                    "target": current,
                    "issues": review.get("issues", []),
                    "suggestions": review.get("suggestions", []),
                    "language": language,
                },
            })
            # Optimizer returns telemetry-style data. Ask the coder to re-implement
            # using the optimizer's analysis as guidance.
            improvement_notes = (opt.get("data") or {}).get("analysis", "")
            re_pass = await self.coder.handle({
                "description": (
                    f"Original task: {task}\n"
                    f"Previous version had issues: {review.get('issues', [])}\n"
                    f"Optimizer notes: {improvement_notes}\n"
                    "Produce an improved version."
                ),
                "input": {"language": language, "context": current,
                          "instruction": task},
            })
            current = re_pass["data"].get("code") or re_pass["data"].get("output", current)

        # Pick best
        best = max(rounds, key=lambda r: r.score, default=None)
        final = best.output if best else current
        return DebateResult(final=final, rounds=rounds,
                            elapsed_s=time.perf_counter() - t0)

    async def cross_review(self, target: str, *, n: int = 2) -> list[dict[str, Any]]:
        """Independent reviews from N reviewer instances in parallel."""
        return await asyncio.gather(*(
            self.reviewer.handle({
                "input": {"target": target},
                "description": "independent review",
            }) for _ in range(n)
        ))


collaboration = CollaborationEngine()
