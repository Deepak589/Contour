# S0-5 Schema spike (owner B, due G0 2026-11-06)

Goal (§16 S0-5): read CodeGraph's DB from Python; edge metadata; PPR latency on the largest graph; confirm or drop
the §13.0 open items. G0 needs "PPR latency acceptable" (target p95 < 500 ms per query). Decides option A (Python service).

Output: `scripts/s0_5_schema.py` (stdlib sqlite3 + numpy) + `docs/spikes/s0-5.md`. Proposed design edits → `ADDONS.md` §4.

## Early probe (Django `1860f0a3f4`)
- Open read-only needs `file:...?immutable=1` (plain `-readonly` fails on the pristine copy: no `-shm`).
- Python graph has **7** edge kinds (contains, calls, instantiates, imports, references, extends, decorates), not 13.
- `metadata.confidence` present on 135,334 / 194,344 edges; values 0.4–0.95 (not 0.6–0.95); absent → 1.

## Progress (2026-11-05)
Steps 1–7 done; results in `docs/spikes/s0-5.md`, proposed edits in `ADDONS.md` §4. Largest graph measured:
home-assistant/core, PPR p95 351 ms (PASS). azure-sdk-for-python index failed (likely memory); proposed size cap.

## Steps
1. Read DB from Python via `sqlite3` URI `mode=ro&immutable=1` → verify: node/edge counts match S0-4 (62,854 / 194,344); DB SHA-256 unchanged after.
2. Schema notes: nodes/edges/files columns F needs (id, kind, file, line range, qualified name, signature, docstring); FTS table coverage → verify: table in `s0-5.md` with `schema.sql:line` at `f72c9d2`.
3. Edge metadata: kinds, confidence distribution per kind, other metadata keys; check where confidence is set in source → verify: per-kind table + `file:line` refs.
4. Pick largest graphs: list pool repos (HF `repo` column only), index the 3 likely-largest (e.g. sympy, scikit-learn, matplotlib; adjust after listing) in the Node 22 container → verify: node/edge counts per repo; largest named.
5. PPR timing: numpy power iteration (bincount matvec), α = 0.25, τ/ρ/confidence weights, tol 1e-6; global PageRank once; 100 random seed sets of 50 nodes → verify: p50/p95/max ms and iterations on the largest graph; π sums to 1.
6. §13.0 open items: dedup "8-call memory" (`explore-dedup.ts`), confidence range, Linux-kernel index time → verify: each confirmed with `file:line` or dropped.
7. Write `docs/spikes/s0-5.md` + `ADDONS.md` §4 (proposed, needs A's sign-off) → verify: `just check` passes; numbers reproducible by the script.

## Decisions to confirm
- Add `numpy` as direct dep (`uv add numpy`; already installed via `datasets`). No scipy — bincount matvec is enough.
- Local `~/codegraph` clone is checked out at `a0174cee`; read source at `f72c9d2` via `git show`, don't change the checkout.

---

# S0-3 Dataset census (owner A, due G0 2026-11-06)

Goal (§16 S0-3): show whether the pool supports a repo-disjoint `dev150` + `test_core` (750 Python tasks, 100 post-cutoff), or switch to the `holdout_repos` fallback at G0.

Output: `scripts/s0_3_census.py` (counts only) + `docs/spikes/s0-3.md`. No task text, patches or issue bodies are committed (licensing, CLAUDE.md). Raw data stays in the Hugging Face cache.

## Probe results so far (2026-11-04, metadata only)

| Source | Rows | Python-only patches | Repos | `created_at` range | License on card |
|---|---|---|---|---|---|
| `czlll/SWE-bench_Lite` | 274 | 274 | 12 (django 102, sympy 66) | 2012-09 .. 2023-07 | none listed |
| `czlll/Loc-Bench_V1` | 560 | 475 | 165 | 2015-11 .. 2025-02 (epoch ms) | none listed |
| `SWE-bench-Live/SWE-bench-Live` `full` | 1,888 | 1,291 | 223 | 2021-07 .. **2025-09-02** | MIT |
| `SWE-bench-Live/MultiLang` | 1,077 | 0 (8 other languages) | | up to 2026-07 | |

- Instance-ID overlap: Lite∩Loc 0, Lite∩Live 0, Loc∩Live 5. Union 2,716 rows.
- Python pool before filters: about 2,035 tasks. **Size is not the problem.**
- **Risk: post-cutoff.** The newest public Python task is 2025-09-02. The Sonnet 5.5 and Haiku 5.5 training cutoffs aren't in the local API docs. If either is later, no public dataset has post-cutoff Python tasks.

## Progress (2026-11-05)

All 9 steps done. Results in `docs/spikes/s0-3.md`. Post-cutoff came back 0, so option (a) was
sized (1,364 candidate PRs in the 20 largest repos) and proposed in `ADDONS.md` §3. Collecting the tasks is not started.

## Steps

1. Model cutoffs → verify: Sonnet 5.5 and Haiku 5.5 cutoffs taken from Anthropic's models overview page, with URL and date, in `s0-3.md`.
2. Loader + normaliser for the 3 sources (one row schema; `created_at` to UTC; Python-only filter; dedupe the 5 shared IDs) → verify: row counts match the table above.
3. Gold from `edit_functions` / `added_functions` (czlll) and from the patch (Live) → verify: on Lite + Loc, patch-derived gold files equal the `edit_functions` files for ≥ 95% of tasks; differences listed by ID.
4. Mechanical tags: `multi_hop`, `paraphrase`, `explicit_path`, `repo_size` (needs node counts from the S2-4 index build, so marked pending) → verify: tag counts per source; 10 random tasks checked by hand.
5. Post-cutoff supply: count Python tasks after each model's cutoff → verify: number per model. If < 100, write up option (a) below with an effort estimate.
6. Repo-disjoint split feasibility: greedy assignment of whole repos to `dev150` with stratification on `multi_hop` and source; remainder is the test pool → verify: dev150 = 150 ± 5, test pool ≥ 500 benchmark tasks, no repo in both.
7. Stale eligibility (gold file changed in the 20 first-parent commits before `base_commit`) on a sample of 10 repos, via bare clones under `EVALH_CACHE` → verify: eligible share per repo; extrapolated count; full count deferred to S2-4.
8. Licenses: record what each dataset card and each sampled repo license says → verify: table in `s0-3.md`; anything unclear is marked "do not redistribute".
9. Write `docs/spikes/s0-3.md` with the census table, the G0 recommendation and any design-doc edits proposed (in `ADDONS.md`, not applied) → verify: `just check` passes; every number is reproducible by `uv run python scripts/s0_3_census.py`.

## Post-cutoff options if step 5 comes back < 100

- **(a) Mine our own (recommended):** localization needs only issue text, base commit and the merged patch, not a test harness. Collect Python issue → PR pairs merged after the cutoff from the repos already in the pool, using the GitHub API. Estimate: about 2 pd extra, a GitHub token, and a filter for linked issues and source-only patches.
- **(b) Hand-made only:** the planned ~30 tasks. Too few for a slice (< 30 is descriptive only).
- **(c) Drop the post-cutoff slice:** rely on the memory-probe gate alone. Weakest; contamination becomes a stated limitation.
