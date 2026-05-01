# Self-Upgrade System

## The Contract

> **The system MUST NOT modify itself automatically.**
> Self-improvement runs ONLY when the user explicitly types `upgrade myself` (or the configured `UPGRADE_CONFIRM_PHRASE`).

This is a hard rule encoded in `backend/upgrade/manager.py:UpgradeManager.is_trigger`. The orchestrator checks every incoming message against this trigger; nothing else can call `upgrade()`.

## Pipeline

When triggered, the manager runs:

1. **Snapshot** — full copy of `backend/` to `versions/v<N>/snapshot/`. This is what rollback restores.
2. **Propose** — the reasoning model (Nemotron-Ultra by default) reads a compact summary of the codebase (`upgrade/analyzer.py`) and outputs strict JSON: `{summary, patches: [{path, intent, rationale}]}`. Limited to 1–3 patches per upgrade.
3. **Rewrite** — for each patch, the coder model (DeepSeek-V4-Flash by default) emits a full file rewrite as JSON `{path, content}`.
4. **Review** — the reviewer model validates each rewrite. Reject criteria: removed public symbols, changed signatures, suspicious diff. Python `compile()` is also run as a hard gate.
5. **Apply** — only validated patches are written to disk.
6. **Smoke test** — reload key modules to confirm imports still work.
7. **Finalize** — manifest set to `applied`, changelog written.
8. **On any failure** — automatic rollback to the previous version, manifest marked `failed`, error captured.

## Versioning

Each upgrade produces:

```
versions/
├── v1/
│   ├── snapshot/         # full backend/ copy
│   ├── manifest.json     # {version, parent_version, status, timestamp, files_changed, summary, model_used, notes}
│   └── changelog.md
├── v2/
│   ├── snapshot/
│   ├── manifest.json
│   └── changelog.md
└── ...
```

`v1` is auto-created on first boot as the baseline so you can always roll back to a known-good state.

## Rollback

UI: click the ↩ button next to any applied version.
API: `POST /api/upgrade/rollback {"version": <N>}`.

Rollback wipes `backend/` and copies `versions/v<N>/snapshot/` over it. The current version's manifest is marked `rolled_back`.

## Protected Files

These are never touched by the upgrade pipeline (modifying them mid-upgrade would corrupt the upgrade itself):

- `backend/upgrade/manager.py`
- `backend/upgrade/versioning.py`
- `backend/upgrade/__init__.py`
- `backend/config.py`
- `backend/main.py`

To upgrade these, do it manually with git in the normal way.

## Safety Properties

| Property | How |
|----------|-----|
| Cannot self-trigger | `is_trigger()` only returns true on exact user-supplied phrase. Endpoints require the same phrase. |
| Cannot break existing features | Snapshot before write. Auto-rollback on failure. Reviewer + Python compile gate every patch. |
| Cannot remove public API | Reviewer model is prompted to reject; manual review of changelog confirms. |
| Cannot lose history | Every version retained until manually deleted. Manifest tracks parent → child. |

## Safe Customization

Tune in `.env`:

```env
UPGRADE_CONFIRM_PHRASE=upgrade myself      # change this for stricter control
UPGRADE_DIR=./versions
```

To make the upgrade flow stricter, set `DEFAULT_MODE=manual` so even read-only steps inside the upgrade pipeline require confirmation. (Not recommended for normal use; the upgrade itself already has multiple gates.)

## What does it actually improve?

The proposal system prompt biases toward:

- Performance (e.g., better caching, parallelism)
- Architecture (smaller modules, clearer boundaries)
- Agent logic (better prompts, scoring)
- Model selection (router heuristics)

It will **not** propose new dependencies, new endpoints, or changes to public agent contracts — those require a human commit.
