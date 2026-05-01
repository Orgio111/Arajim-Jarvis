"""Orchestrator — runs the multi-agent loop.

Flow:
  1. User message arrives.
  2. Memory triggers (remember / forget) handled inline.
  3. Planner produces a plan (JSON).
  4. Each step is dispatched to its agent (executor / coder / reviewer / optimizer).
  5. Steps with no inter-dependencies run in parallel; dependent steps wait.
  6. Final synthesis produced by the Executor.
  7. Everything streamed to the event bus for the UI.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from backend.agents.coder import CoderAgent
from backend.agents.executor import ExecutorAgent
from backend.agents.optimizer import OptimizerAgent
from backend.agents.planner import PlannerAgent
from backend.agents.reviewer import ReviewerAgent
from backend.config import settings
from backend.core.events import bus
from backend.core.logger import logger
from backend.memory.store import get_store


class Orchestrator:
    def __init__(self) -> None:
        self.planner = PlannerAgent()
        self.executor = ExecutorAgent()
        self.coder = CoderAgent()
        self.reviewer = ReviewerAgent()
        self.optimizer = OptimizerAgent()
        self._agents = {
            "planner": self.planner,
            "executor": self.executor,
            "coder": self.coder,
            "reviewer": self.reviewer,
            "optimizer": self.optimizer,
        }

    # ------------------------------------------------------------- entry
    async def handle(self, *, session_id: str, user_message: str) -> dict[str, Any]:
        store = get_store()
        await store.append_chat(session_id, "user", user_message)
        await bus.publish("chat", {"type": "user", "session_id": session_id, "content": user_message})

        # 0) trigger phrases
        if (memory := store.parse_remember(user_message)):
            mid = await store.remember(memory)
            reply = f"Saved as memory #{mid}: {memory}"
            await store.append_chat(session_id, "assistant", reply, metadata={"kind": "memory_save"})
            await bus.publish("chat", {"type": "assistant", "session_id": session_id, "content": reply})
            return {"reply": reply, "plan": None, "results": []}

        if (fid := store.parse_forget(user_message)) is not None:
            ok = await store.forget(fid)
            reply = f"Forgot memory #{fid}." if ok else f"No memory #{fid}."
            await store.append_chat(session_id, "assistant", reply, metadata={"kind": "memory_forget"})
            await bus.publish("chat", {"type": "assistant", "session_id": session_id, "content": reply})
            return {"reply": reply, "plan": None, "results": []}

        # 1) plan
        t0 = time.perf_counter()
        plan = await self.planner.handle({"goal": user_message})
        await bus.publish("plan", {"type": "ready", "session_id": session_id, "plan": plan})

        # 2) execute steps respecting dependencies
        results = await self._run_steps(plan.get("steps", []))

        # 3) synthesize a final reply
        reply = await self._synthesize(user_message, plan, results)
        elapsed = time.perf_counter() - t0
        await store.append_chat(
            session_id, "assistant", reply,
            metadata={"plan": plan, "results": results, "elapsed_s": elapsed},
        )
        await bus.publish("chat", {"type": "assistant", "session_id": session_id, "content": reply})
        return {"reply": reply, "plan": plan, "results": results, "elapsed_s": elapsed}

    # --------------------------------------------------------- step runner
    async def _run_steps(self, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not steps:
            return []
        by_id: dict[int, dict[str, Any]] = {int(s["id"]): s for s in steps}
        results: dict[int, dict[str, Any]] = {}
        pending = set(by_id.keys())

        while pending:
            ready = [
                sid for sid in pending
                if all(int(d) in results for d in by_id[sid].get("depends_on", []))
            ]
            if not ready:
                logger.warning("Dependency cycle in plan; running remaining sequentially")
                ready = list(pending)

            async def run_one(sid: int) -> tuple[int, dict[str, Any]]:
                step = by_id[sid]
                agent_name = step.get("agent", "executor")
                agent = self._agents.get(agent_name, self.executor)
                await bus.publish(
                    "step",
                    {"type": "start", "step_id": sid, "agent": agent_name,
                     "description": step.get("description", "")},
                )
                try:
                    result = await agent.handle(step)
                except Exception as exc:
                    logger.exception(f"Step {sid} failed")
                    result = {"agent": agent_name, "ok": False, "error": str(exc)}
                await bus.publish(
                    "step", {"type": "end", "step_id": sid, "result": result},
                )
                return sid, result

            done = await asyncio.gather(*(run_one(sid) for sid in ready))
            for sid, res in done:
                results[sid] = res
                pending.discard(sid)

        return [results[sid] for sid in sorted(results)]

    # ----------------------------------------------------------- synthesis
    async def _synthesize(
        self,
        user_message: str,
        plan: dict[str, Any],
        results: list[dict[str, Any]],
    ) -> str:
        if not results:
            return "I have nothing to do."
        # If single step + executor + non-trivial output, return its text
        if len(results) == 1 and results[0].get("data", {}).get("text"):
            return results[0]["data"]["text"]

        # Otherwise let the executor compose a final answer
        summary_input = (
            f"User asked: {user_message}\n\n"
            f"Plan intent: {plan.get('intent', '')}\n\n"
            "Results:\n"
            + "\n".join(
                f"- step {i+1} ({r.get('agent')}): "
                f"{'ok' if r.get('ok') else 'fail'} -> {str(r.get('data') or r.get('error'))[:400]}"
                for i, r in enumerate(results)
            )
            + "\n\nWrite the final answer for the user, in their language."
        )
        return await self.executor.chat(summary_input, max_tokens=1024)


orchestrator = Orchestrator()
