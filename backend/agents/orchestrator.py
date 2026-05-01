"""Orchestrator — runs the multi-agent loop.

Pipeline:
  0. Memory triggers (remember / forget) handled inline.
  1. Intent prediction (fast NIM model, cached).
  2. Exact + semantic response cache lookup.
  3. Strategy dispatch:
       - direct       → run a single skill
       - deep_search  → multi-step research with citations
       - debate       → coder/reviewer/optimizer iterative loop
       - plan         → classic Planner → parallel Executor steps
  4. Synthesis + cache write + learning record.
  5. Everything streamed to the event bus.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator

from backend.agents.coder import CoderAgent
from backend.agents.collaboration import collaboration
from backend.agents.executor import ExecutorAgent
from backend.agents.optimizer import OptimizerAgent
from backend.agents.planner import PlannerAgent
from backend.agents.reviewer import ReviewerAgent
from backend.cache.manager import cache
from backend.config import settings
from backend.core.events import bus
from backend.core.logger import logger
from backend.intelligence.intent import predict_intent
from backend.learning.passive import learner
from backend.memory.context import build_context, summarize_old_turns
from backend.memory.store import get_store
from backend.nvidia.client import get_client
from backend.nvidia.router import router
from backend.search.deep import deep_search
from backend.skills.registry import registry as skill_registry


CACHE_NS = "chat-reply"


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

    # =============================================================== entry
    async def handle(self, *, session_id: str, user_message: str) -> dict[str, Any]:
        """Top-level entry. Watchdog: never raises — failures are surfaced as
        chat replies and published to the event bus so the UI sees them."""
        try:
            return await self._handle_inner(session_id, user_message)
        except Exception as exc:
            logger.exception("orchestrator.handle crashed; auto-recovery active")
            await bus.publish("error", {"type": "orchestrator", "message": str(exc)})
            reply = f"⚠ Orchestrator error: {exc}. The system has recovered and is ready for the next request."
            try:
                await get_store().append_chat(session_id, "assistant", reply,
                                              metadata={"error": str(exc)})
            except Exception:
                pass
            return {"reply": reply, "error": str(exc), "ok": False}

    async def _handle_inner(self, session_id: str, user_message: str) -> dict[str, Any]:
        store = get_store()
        await store.append_chat(session_id, "user", user_message)
        await bus.publish("chat", {"type": "user", "session_id": session_id,
                                    "content": user_message})

        # 0) memory triggers
        early = await self._handle_memory_triggers(session_id, user_message)
        if early is not None:
            # Memory state changed — drop cached replies that may now be stale
            try:
                await cache.invalidate(CACHE_NS)
            except Exception as exc:
                logger.debug(f"cache invalidate after memory change failed: {exc}")
            return early

        t0 = time.perf_counter()

        # 1) intent
        intent = await predict_intent(user_message)
        await bus.publish("intent", {
            "type": "predicted",
            "intent": intent.intent,
            "confidence": intent.confidence,
            "strategy": intent.strategy,
            "skill": intent.suggested_skill,
        })

        # 2) cache hit?
        cached = await cache.wrap(
            namespace=CACHE_NS,
            key_text=user_message,
            fn=lambda: self._noop(),
            semantic=True,
            ttl=settings.cache_exact_ttl,
        )
        if cached and isinstance(cached, dict) and cached.get("reply"):
            await store.append_chat(session_id, "assistant", cached["reply"],
                                    metadata={"cache_hit": True})
            await bus.publish("chat", {"type": "assistant",
                                       "session_id": session_id,
                                       "content": cached["reply"],
                                       "cache_hit": True})
            return {**cached, "cache_hit": True, "elapsed_s": time.perf_counter() - t0}

        # 3) periodic summarization
        try:
            await summarize_old_turns(session_id)
        except Exception as exc:
            logger.debug(f"summarization skipped: {exc}")

        # 4) strategy dispatch (override with passive learner if confident)
        strategy = intent.strategy or "plan"
        if intent.confidence >= 0.8:
            strategy = learner.best_strategy(intent.intent, default=strategy)

        await bus.publish("strategy", {"type": "dispatch", "strategy": strategy})

        if strategy == "direct" and intent.suggested_skill:
            outcome = await self._dispatch_direct(intent.suggested_skill, user_message)
        elif strategy == "deep_search":
            outcome = await self._dispatch_deep_search(user_message)
        elif strategy == "debate":
            outcome = await self._dispatch_debate(user_message)
        else:
            outcome = await self._dispatch_plan(session_id, user_message)

        reply = outcome["reply"]
        elapsed = time.perf_counter() - t0

        # 5) cache + persist + learn
        await cache.set_exact(CACHE_NS, user_message, {"reply": reply})
        try:
            await cache.set_semantic(CACHE_NS, user_message, {"reply": reply})
        except Exception:
            pass

        await store.append_chat(
            session_id, "assistant", reply,
            metadata={
                "intent": intent.intent, "strategy": strategy,
                "elapsed_s": elapsed,
            },
        )
        await bus.publish("chat", {"type": "assistant",
                                   "session_id": session_id, "content": reply})

        await learner.record(
            intent=intent.intent, strategy=strategy,
            model=outcome.get("model"), skill=outcome.get("skill"),
            latency_s=elapsed, ok=outcome.get("ok", True),
        )

        return {
            "reply": reply,
            "intent": intent.__dict__,
            "strategy": strategy,
            "elapsed_s": elapsed,
            **{k: v for k, v in outcome.items() if k != "reply"},
        }

    # ============================================================ stream API
    async def handle_stream(self, *, session_id: str,
                             user_message: str) -> AsyncIterator[dict[str, Any]]:
        """Token-streaming variant for SSE.

        For most flows we still run the orchestration synchronously and stream
        only the final synthesis tokens. Plain chat intents stream from the
        general model directly for sub-second perceived latency.
        """
        store = get_store()
        await store.append_chat(session_id, "user", user_message)
        yield {"event": "start"}

        early = await self._handle_memory_triggers(session_id, user_message)
        if early is not None:
            yield {"event": "token", "delta": early["reply"]}
            yield {"event": "end", "reply": early["reply"]}
            return

        intent = await predict_intent(user_message)
        yield {"event": "intent", "data": intent.__dict__}

        # Pure chat intents stream directly for perceived speed
        if intent.intent == "chat" and intent.confidence >= 0.7:
            t0 = time.perf_counter()
            client = get_client()
            ctx = await build_context(session_id, user_message)
            messages = ctx + [{"role": "user", "content": user_message}]
            model = router.pick_for("executor")
            chunks: list[str] = []
            async for delta in client.stream(model=model, messages=messages,
                                              max_tokens=1024, thinking=False):
                chunks.append(delta)
                yield {"event": "token", "delta": delta}
            full = "".join(chunks).strip()
            await store.append_chat(session_id, "assistant", full,
                                    metadata={"streamed": True})
            await learner.record(
                intent=intent.intent, strategy="stream", model=model,
                skill=None, latency_s=time.perf_counter() - t0, ok=True,
            )
            yield {"event": "end", "reply": full}
            return

        # Otherwise: full pipeline, then stream the synthesized reply
        outcome = await self.handle(session_id=session_id, user_message=user_message)
        reply = outcome["reply"]
        # Token-by-token re-emit for UI consistency
        for word in reply.split(" "):
            yield {"event": "token", "delta": word + " "}
            await asyncio.sleep(0)
        yield {"event": "end", **outcome}

    # =============================================================== triggers
    async def _handle_memory_triggers(self, session_id: str,
                                      msg: str) -> dict[str, Any] | None:
        store = get_store()
        if (m := store.parse_remember(msg)):
            mid = await store.remember(m)
            reply = f"Saved as memory #{mid}: {m}"
            await store.append_chat(session_id, "assistant", reply,
                                    metadata={"kind": "memory_save"})
            await bus.publish("chat", {"type": "assistant",
                                       "session_id": session_id, "content": reply})
            return {"reply": reply, "plan": None, "results": []}
        if (fid := store.parse_forget(msg)) is not None:
            ok = await store.forget(fid)
            reply = f"Forgot memory #{fid}." if ok else f"No memory #{fid}."
            await store.append_chat(session_id, "assistant", reply,
                                    metadata={"kind": "memory_forget"})
            await bus.publish("chat", {"type": "assistant",
                                       "session_id": session_id, "content": reply})
            return {"reply": reply, "plan": None, "results": []}
        return None

    # ============================================================ strategies
    async def _dispatch_direct(self, skill: str, message: str) -> dict[str, Any]:
        result = await skill_registry.invoke(skill, query=message,
                                             instruction=message,
                                             command=message, path=".")
        if result.ok:
            data = result.data or {}
            text = data.get("answer") or data.get("text") \
                   or data.get("output") or data.get("code") \
                   or str(data)[:1000]
        else:
            text = f"Skill `{skill}` failed: {result.error}"
        return {"reply": text, "skill": skill, "ok": result.ok,
                "model": None, "data": result.data}

    async def _dispatch_deep_search(self, question: str) -> dict[str, Any]:
        r = await deep_search(question)
        cite_lines = "\n".join(f"[{c['n']}] {c['title']} — {c['url']}"
                                for c in r.citations)
        text = f"{r.answer}\n\nSources:\n{cite_lines}" if r.citations else r.answer
        return {"reply": text, "skill": "deep_search", "ok": True,
                "model": None, "citations": r.citations}

    async def _dispatch_debate(self, task: str) -> dict[str, Any]:
        r = await collaboration.debate(task)
        rounds = [{"n": rd.n, "score": rd.score, "issues": rd.review.get("issues", [])}
                  for rd in r.rounds]
        return {"reply": r.final, "skill": "debate", "ok": True,
                "model": None, "rounds": rounds, "elapsed_s": r.elapsed_s}

    async def _dispatch_plan(self, session_id: str, message: str) -> dict[str, Any]:
        plan = await self.planner.handle({"goal": message})
        await bus.publish("plan", {"type": "ready", "session_id": session_id,
                                    "plan": plan})
        results = await self._run_steps(plan.get("steps", []))
        reply = await self._synthesize(message, plan, results)
        return {"reply": reply, "plan": plan, "results": results,
                "ok": all(r.get("ok") for r in results), "model": None,
                "skill": None}

    # --------------------------------------------------------- step runner
    async def _run_steps(self, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not steps:
            return []
        by_id = {int(s["id"]): s for s in steps}
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
                await bus.publish("step", {"type": "end", "step_id": sid, "result": result})
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
        if len(results) == 1 and results[0].get("data", {}).get("text"):
            return results[0]["data"]["text"]
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

    @staticmethod
    async def _noop() -> Any:
        return None


orchestrator = Orchestrator()
