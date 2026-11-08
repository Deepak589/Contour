# CLAUDE.md — Eval Harness (Contour)

Agent eval harness: does code-index representation (A–F, F0) change localization accuracy vs token cost?
Full design: `EVAL_HARNESS_DESIGN.md` (source of truth). Agreed-but-unapplied edits: `ADDONS.md`.

## Team & branches
- 2 devs. Roles per §16: **A** = harness + experiments, **B** = indexes + Variant F.
- Don't work on `main` directly. **Both devs work on `dev-D`**; merge to `main` via PR.
- `git pull` before starting and again before every push (`pull.rebase true`, so no merge commits).
  Conflict → fix, `git add`, `git rebase --continue` (or `--abort`). `uv sync` after `uv.lock` changes.
- Run `just check` before every push. Flag edits to shared files (`interfaces.py`, `schemas.py`, design doc).
- Second local worktree needs its own short-lived branch (git won't check out `dev-D` twice); merge it back.
- Sprint 0 runs 2026-11-02 → 11-06. Check the gate (G0…G5) before starting the next sprint's work.

## How I work (style)
1. **Analysis first, edits second.** Answer "what does X do?" plainly before touching anything. Ask when unclear.
2. **Plan before building.** For 3+ step tasks write `tasks/todo.md` with `step → verify: check` items; check in before coding.
3. **Simplest thing that works.** No speculative features, no single-use abstractions, no config nobody asked for.
4. **Surgical diffs.** Touch only what the task needs. Match existing style. Mention unrelated dead code, don't delete it.
5. **Keep docs consistent.** Editing one section of the design doc → update every section that references it.
6. **Verify before done.** Run tests / show output. Never claim "works" without evidence. Report failures as-is.
7. **Honest critique.** Flag validity problems (contamination, power, leakage, unfair comparison) even when not asked.
8. **Check claims against source.** Cite `file:line` at the pinned commit; mark anything unverified as unverified.
9. **Commit only when asked.** Never push or merge without being asked.
10. **Config changes:** back up the file first and give undo steps.
11. **Corrections → `tasks/lessons.md`.** One rule per mistake so it isn't repeated.

## Python conventions
- Python 3.12, `uv` + `uv.lock`. Add deps with `uv add`, never pip.
- Pydantic v2; `Task`, `RunConfig`, `RunResult` are `frozen=True`. Trajectories append-only.
- Small `Protocol`s in `evalh/core/interfaces.py`; plugins register by name in `registry.py`.
- Core depends on nothing concrete. Plugins → core interfaces. Infra → core interfaces.
- `asyncio` + semaphores for concurrency. No Celery/Ray/LangGraph.
- Type hints everywhere; `mypy` clean. `ruff` for lint + format.
- Structured JSONL records, not prints.
- Tests: `pytest`, `pytest-asyncio`, Hypothesis for Variant F selector properties.
- No test in CI calls the live API. Live checks are run by hand (`just smoke`).

## Commands
```bash
uv sync                      # install (after every pull that changes uv.lock)
just check                   # ruff + ruff format --check + mypy strict + pytest — must pass before commit
just fmt                     # auto-format + auto-fix
just test                    # pytest only
```
Ruff skips `.claude/` and `*.md`. CI runs the same checks with no API key.

## Claude API rules (every Claude request)
- **Never send** `temperature`, `top_p`, `top_k` — 400 on Sonnet 5.5 / Haiku 5.5.
- Always set `output_config={"effort": "medium"}`; defaults differ per model.
- `tool_choice` stays `auto`. No server-side fallbacks.
- Pin `api_version` and SDK version (see `experiments/*.yaml`).
- Token counts via `count_tokens`, never `tiktoken`.
- Check `stop_reason` for `refusal` / `max_tokens` before reading content.
- `seed` is a replicate label only; the API has no seed param.
- Models: `claude-sonnet-5-5` (primary), `claude-haiku-5-5` (small). Claims limited to these.

## LLM providers (D19–D21)
- All model calls go through the `LLMClient` protocol (`evalh/infra/llm/`). Agent, graders and store see only neutral types.
- **Dev backend: Mistral** `mistral-small-2603`, `mistralai` 3.7.0 (pinned in `uv.lock`). Use it on `dev50` to build and debug. Mistral runs are never reported as results.
- **Final runs:** the pinned Claude models above. One results set never mixes providers.
- Delivered tokens and `T_loc` use one reference tokenizer for every provider: `count_tokens` on `claude-sonnet-5-5`. Provider usage is for billing only. No Anthropic key → `T_loc` is null.
- Provider, model ID and SDK version are part of `config_hash`.

## CodeGraph (F0 baseline)
- Pinned at **`f72c9d2`** (v1.6.2). Line refs in the design doc assume this commit.
- Requires Node `>=20 <25`. Local Node is 26 → **run CodeGraph only in the Node 22 container.**
- Never modify upstream CodeGraph for F0. F is a separate MCP service reading CodeGraph's SQLite.
- Launch: `codegraph serve --mcp --no-watch --no-telemetry`. `--no-watch` does NOT stop catch-up `sync()`
  (`src/mcp/project-lifecycle.ts:176`).
- With `CODEGRAPH_NO_DAEMON=1`, a held writer lock → `process.exit(1)` (`src/mcp/index.ts` `startDirect`),
  not read-only. Read-only fallback lives only on the daemon/proxy path. S0-4 decides the freeze route.
- Frozen-index acceptance: SHA-256 of `.codegraph/codegraph.db` (+ `-wal`) unchanged after a run.

## Study validity rules (never break)
1. No Variant F agent runs before gate G1.
2. Live agent runs during development use `dev50` only. **`test_core` is untouched until G3.**
3. After G3 (`prereg-v1` tag): no change to F, tools, prompts, graders or analysis except documented bug fixes;
   a result-affecting fix voids and reruns the affected runs.
4. Every reported number traces to a config hash.
5. `llm_cache: off` for experiments. Cache key includes replicate + run ID.
6. Same system prompt, loop, budget, `read_file` and `submit_locations` across variants.
7. `hints_text` never shown to the agent; `.git` never mounted in tool containers.
8. Fit F's parameters on `dev150` only (repo-disjoint from `test_core`).

## Environment
- Dev machine: macOS (Apple Silicon). Images must build for arm64 as well as amd64.
- Cache outside repo: `EVALH_CACHE` (default `~/evalh-cache`) — bare clones, worktrees, indexes, embeddings.
- Tool containers: `--network none`, read-only checkout + index mounts, tmpfs scratch.
- `runs/` and `.env` are gitignored. Never commit API keys or task text before licensing is checked (S0-3).

## Don't
- Don't add Postgres, pgvector, FAISS, Inspect AI, LangGraph — rejected in §14.
- Don't add EventBus / CompositeGrader / Null Object until a real second use exists.
- Don't run the experiment matrix or spend API budget without being asked.
