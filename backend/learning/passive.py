"""Passive learning: improve without bumping the version.

Every completed turn produces an outcome record:
  { intent, strategy, model, skill, latency_s, ok, score? }

The learner aggregates these with exponential decay and feeds them into:
  - the model router's quality/latency scores
  - per-skill success weights (boosting auto_select)
  - per-intent strategy preferences (e.g., "research" → deep_search wins)

Active upgrades (`upgrade myself`) read this telemetry too and propose
structural changes; passive learning just tunes the in-memory dials.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from backend.config import settings
from backend.core.events import bus
from backend.core.logger import logger
from backend.nvidia.router import router


STATE_PATH = Path("./data/learning.json")


class PassiveLearner:
    def __init__(self) -> None:
        self.enabled = settings.passive_learning
        self.decay = settings.learning_decay
        self.recent: deque[dict[str, Any]] = deque(maxlen=500)
        # intent -> strategy -> score
        self.strategy_scores: dict[str, dict[str, float]] = defaultdict(dict)
        # skill -> weight (0..)
        self.skill_weights: dict[str, float] = defaultdict(lambda: 1.0)
        self._lock = asyncio.Lock()
        self._load()

    # --------------------------------------------------------------- record
    async def record(
        self,
        *,
        intent: str,
        strategy: str,
        model: str | None,
        skill: str | None,
        latency_s: float,
        ok: bool,
        score: float | None = None,
    ) -> None:
        if not self.enabled:
            return
        outcome = {
            "ts": time.time(), "intent": intent, "strategy": strategy,
            "model": model, "skill": skill,
            "latency_s": latency_s, "ok": ok, "score": score,
        }
        async with self._lock:
            self.recent.append(outcome)

        # Update router
        if model:
            quality = (score / 10.0) if score is not None else (1.0 if ok else 0.3)
            router.report(model, latency_s=latency_s, quality=quality)

        # Update strategy scores
        if intent and strategy:
            d = self.strategy_scores[intent]
            prev = d.get(strategy, 0.0)
            obs = (1.0 if ok else 0.0)
            d[strategy] = self.decay * prev + (1 - self.decay) * obs

        # Update skill weights
        if skill:
            prev = self.skill_weights[skill]
            obs = 1.2 if ok else 0.7
            self.skill_weights[skill] = max(0.1, min(3.0, self.decay * prev + (1 - self.decay) * obs))

        await bus.publish("learning", {"type": "record", **outcome})
        if len(self.recent) % 10 == 0:
            self._save()

    # ----------------------------------------------------------- decisions
    def best_strategy(self, intent: str, default: str = "plan") -> str:
        scores = self.strategy_scores.get(intent)
        if not scores:
            return default
        return max(scores.items(), key=lambda kv: kv[1])[0]

    def skill_weight(self, name: str) -> float:
        return self.skill_weights.get(name, 1.0)

    # --------------------------------------------------------------- snapshot
    def snapshot(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "samples": len(self.recent),
            "strategy_scores": {k: dict(v) for k, v in self.strategy_scores.items()},
            "skill_weights": dict(self.skill_weights),
            "router_scores": router.scores,
        }

    def _save(self) -> None:
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            STATE_PATH.write_text(json.dumps({
                "strategy_scores": {k: dict(v) for k, v in self.strategy_scores.items()},
                "skill_weights": dict(self.skill_weights),
            }, indent=2))
        except Exception as exc:
            logger.debug(f"learning save skipped: {exc}")

    def _load(self) -> None:
        if not STATE_PATH.exists():
            return
        try:
            data = json.loads(STATE_PATH.read_text())
            for k, v in (data.get("strategy_scores") or {}).items():
                self.strategy_scores[k] = dict(v)
            for k, v in (data.get("skill_weights") or {}).items():
                self.skill_weights[k] = float(v)
            logger.info(f"Passive learner restored: {len(self.skill_weights)} skill weights")
        except Exception as exc:
            logger.debug(f"learning load skipped: {exc}")


learner = PassiveLearner()
