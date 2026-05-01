"""Deep search: search → analyze → refine → repeat.

Uses the reasoning model to:
  1. Generate an initial query.
  2. Search and read the top hits.
  3. Identify gaps; emit follow-up queries.
  4. Stop when confidence is high or max steps reached.
  5. Synthesize a cited answer.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from backend.config import settings
from backend.core.events import bus
from backend.core.logger import logger
from backend.nvidia.client import get_client
from backend.nvidia.router import router
from backend.search.web import fetch_clean, web_search


PLAN_PROMPT = (
    "You are a research planner. Given the user's question, output strict JSON:\n"
    '{"queries": ["q1", "q2", ...]}  (1-3 search queries)\n'
    "Pick queries that are likely to surface authoritative, recent sources."
)

REFINE_PROMPT = (
    "You have evidence so far. If the user's question is fully answered, set "
    '"done": true. Otherwise emit 1-2 new queries that fill the remaining gaps. '
    "Strict JSON: {\"done\": bool, \"queries\": [...], \"missing\": \"...\"}"
)

SYNTH_PROMPT = (
    "You are a research synthesizer. Using ONLY the evidence below, produce a concise, "
    "well-structured answer with inline citations like [1], [2] referring to the source URLs. "
    "If evidence is insufficient, say so explicitly."
)


@dataclass
class DeepSearchResult:
    answer: str
    citations: list[dict[str, str]] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    elapsed_s: float = 0.0


def _extract_json(text: str) -> dict[str, Any] | None:
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass
    brace = re.search(r"(\{.*\})", text, re.DOTALL)
    if brace:
        try:
            return json.loads(brace.group(1))
        except json.JSONDecodeError:
            return None
    return None


async def deep_search(question: str, *, max_steps: int | None = None) -> DeepSearchResult:
    t0 = time.perf_counter()
    max_steps = max_steps or settings.deep_search_max_steps
    client = get_client()
    plan_model = router.pick_for("planner", prefer_quality=True)
    fast_model = router.pick_for("router", prefer_speed=True)

    # 1. initial plan
    plan_resp = await client.chat(
        model=plan_model,
        messages=[
            {"role": "system", "content": PLAN_PROMPT},
            {"role": "user", "content": question},
        ],
        max_tokens=300, temperature=0.3, thinking=True,
    )
    plan = _extract_json(plan_resp.choices[0].message.content or "") or {"queries": [question]}
    queries: list[str] = plan.get("queries") or [question]
    await bus.publish("search", {"type": "plan", "queries": queries})

    evidence: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    steps: list[dict[str, Any]] = []

    for step in range(max_steps):
        step_evidence: list[dict[str, str]] = []
        for q in queries:
            await bus.publish("search", {"type": "query", "step": step, "q": q})
            results = await web_search(q, k=4)
            for r in results:
                if r.url in seen_urls or not r.url:
                    continue
                seen_urls.add(r.url)
                body = await fetch_clean(r.url, max_chars=4_000)
                step_evidence.append({
                    "url": r.url, "title": r.title, "snippet": r.snippet, "body": body,
                })
        evidence.extend(step_evidence)
        steps.append({"step": step, "queries": queries, "added": len(step_evidence)})

        if step + 1 >= max_steps or len(evidence) >= 12:
            break

        # Refine
        evidence_text = "\n\n".join(
            f"[{i+1}] {e['title']}\n{e['snippet']}\n{e['body'][:1500]}"
            for i, e in enumerate(evidence[-12:])
        )
        ref_resp = await client.chat(
            model=fast_model,
            messages=[
                {"role": "system", "content": REFINE_PROMPT},
                {"role": "user",
                 "content": f"Question: {question}\n\nEvidence:\n{evidence_text}"},
            ],
            max_tokens=300, temperature=0.2,
        )
        refine = _extract_json(ref_resp.choices[0].message.content or "") or {"done": True, "queries": []}
        if refine.get("done") or not refine.get("queries"):
            break
        queries = refine["queries"][:2]

    # 2. synthesize
    cite_block = "\n".join(
        f"[{i+1}] {e['title']} — {e['url']}\n{e['snippet']}\n{e['body'][:1800]}"
        for i, e in enumerate(evidence[:12])
    )
    synth_resp = await client.chat(
        model=plan_model,
        messages=[
            {"role": "system", "content": SYNTH_PROMPT},
            {"role": "user",
             "content": f"Question: {question}\n\nEvidence:\n{cite_block}"},
        ],
        max_tokens=1500, temperature=0.3, thinking=True,
    )
    answer = (synth_resp.choices[0].message.content or "").strip()

    citations = [{"n": str(i + 1), "title": e["title"], "url": e["url"]}
                 for i, e in enumerate(evidence[:12])]
    return DeepSearchResult(
        answer=answer, citations=citations, steps=steps,
        elapsed_s=time.perf_counter() - t0,
    )
