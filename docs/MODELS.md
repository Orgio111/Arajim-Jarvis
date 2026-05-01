# NVIDIA NIM Model Catalog

The router (`backend/nvidia/router.py`) picks dynamically from this catalog. Any model not in the registry is still usable — pass its id directly to `NIMClient.chat(model=...)`.

| Model | Tier | Context | Strengths | Default Role |
|-------|------|---------|-----------|--------------|
| `nvidia/llama-3.3-nemotron-ultra-253b` | reasoning | 128K | reasoning, planning, math, tool-use | Planner, Reviewer, Optimizer |
| `nvidia/llama-3.3-nemotron-super-49b` | general | 128K | general, tool-use, throughput | Executor |
| `nvidia/llama-3.3-nemotron-nano-8b` | fast | 128K | speed, classification, routing | Skill router, voice classification |
| `deepseek-ai/deepseek-v4-flash` | code | 1M | coding, agentic, long-context | Coder |
| `deepseek-ai/deepseek-v4-pro` | reasoning | 200K | reasoning, coding, general | (alt) Planner |
| `moonshotai/kimi-k2.5` | long_context | 2M | long-context, agentic | Memory recall, large docs |
| `qwen/qwen2.5-coder-32b-instruct` | code | 128K | coding | (alt) Coder |
| `meta/llama-3.1-405b-instruct` | general | 128K | stable | Fallback |
| `minimaxai/minimax-m2.7` | general | 200K | balanced cost | (alt) general |

## Selection logic

1. If estimated input >200K tokens → force `long_context` tier.
2. Else if `prefer_speed` → force `fast` tier.
3. Else use the agent's tier.
4. Within a tier, score by:
   - +10 if it equals the configured default (`NIM_MODEL_<TIER>` env var)
   - +5 × runtime quality score (from `router.report()`)
   - −1 × runtime average latency in seconds
   - +3 if `prefer_quality` and tier is reasoning, etc.

The benchmark endpoint (`POST /api/benchmark`) feeds quality + latency back into the router.

## Nemotron-specific features

Pass `thinking=True` (or `False`) to `NIMClient.chat()` / `Agent.chat()` to inject the `detailed thinking on/off` system marker required by Llama-Nemotron models.

## Function calling / tool use

`Skill.to_tool_schema()` produces OpenAI-compatible tool definitions. Pass `tools=registry.tool_schemas()` to `NIMClient.chat()` for native tool-use. The Executor agent currently runs skills directly — switch to native tool-use by setting `tool_choice="auto"`.

## Guided JSON

For strict structured outputs, pass `guided_json={"type": "object", ...}`. The client wraps it as `extra_body={"nvext": {"guided_json": ...}}` per NIM's extension.
