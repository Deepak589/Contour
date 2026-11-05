# Add-ons (deferred improvements)

Improvements to `EVAL_HARNESS_DESIGN.md` that are agreed but not applied yet.

---

## 1. LaTeX rendering for §13 formulas

**Status:** deferred.
**What it does:** display only — the math does not change. GitHub and VS Code markdown preview render `$$…$$` as typeset math (real fractions, subscripts, Σ).
**Do it when:** the doc feeds a paper/report or is shared on GitHub. Until then, plain-text formulas stay easier to read in the raw `.md`.
**Cost:** raw source gets harder to read; some viewers show the raw `$$…$$`.

### Ready-to-paste replacements (§13.2–13.3, synced with the merged plan)

**Seed fusion (RRF)**
$$
s_0(v) = \sum_{r \in \{\text{bm25},\,\text{dense},\,\text{exact}\}} \frac{1}{k + \text{rank}_r(v)}, \qquad k = 60
$$

**Edge weights and transition**
$$
w(u \to v) = \tau_{\text{kind}(e)} \cdot c(e), \qquad w(v \to u) = \rho \cdot \tau_{\text{kind}(e)} \cdot c(e), \qquad P(u \to v) = \frac{w(u,v)}{\sum_x w(u,x)}
$$

**Personalized PageRank (fixed α)**
$$
\pi_s = \alpha \, \hat{s}_0 + (1 - \alpha)\, P^{\top} \pi_s, \qquad \alpha = 0.25
$$

**Hub correction, normalized per query**
$$
h(v) = \max\bigl(N \cdot \pi_g(v),\ 1\bigr), \qquad
\text{lift}(v) = \frac{\pi_s(v)}{h(v)^{\beta}}, \qquad
\text{rel}(v) = \frac{\text{lift}(v)}{\max_u \text{lift}(u)}
$$

**Value of each step up the ladder**
$$
v(u, \text{handle}) = \text{rel}(u) \cdot g_h, \qquad
v(u, L_1) = \text{rel}(u) \cdot \max\bigl(g_1 - g_{\text{held}}(u),\ 0\bigr)
$$
$$
v(\text{chunk}) = \text{rel}(u) \cdot \bigl(1 - \max(g_1, g_{\text{held}}(u))\bigr) \cdot \text{share}(\text{chunk}), \qquad
\text{share}(\text{chunk}) = \frac{1 + q}{\sum (1 + q)}
$$

**Objective (heuristic)**
$$
\max \sum \bigl[ v - \lambda \, c \bigr]
\quad \text{s.t.} \quad \sum c \le B
$$

**Greedy solver stop rule**
$$
\text{take items in descending } \frac{\Delta v}{\Delta c}, \text{ stop at the first with } \frac{\Delta v}{\Delta c} < \lambda, \text{ skip any that would exceed } B
$$

### How to apply
Replace each backtick formula in §13.2–13.3 with the matching block above. Keep the prose around them unchanged.

---

## 2. S0-4 results: frozen-index route, Node version, F0 tool surface

**Status:** proposed by B, needs A's sign-off. Evidence: `docs/spikes/s0-4.md`.
**Why:** S0-4 showed three places in the design doc are now wrong, and one decision is missing.

### Edits

1. **§4 Frozen index (line 232).** Replace the "one-line patch / `src/mcp/index.ts:146-149` fallback" text with:
   > **Frozen index:** mount the checkout `:ro`, put a tmpfs over `.codegraph/`, and bind-mount `codegraph.db` `:ro` on top.
   > Catch-up `sync()` fails harmlessly (`attempt to write a readonly database`) and the server keeps serving the frozen index.
   > No upstream patch. A plain `:ro` mount fails: upstream writes `.codegraph/writer.pid.*.tmp` first (EROFS), so the
   > `index.ts:146-149` fallback is never reached. **Acceptance test:** the DB's SHA-256 is unchanged after a run (passed in S0-4).
2. **§16 G0 (line 932).** "If frozen F0 fails: apply the patch route or drop F0 from the stale arm" → frozen F0 passed
   without a patch. Keep the patch only as a contingency.
3. **Node version (§4 CodeGraph notes, Compute, CLAUDE.md).** "Node 22" → **Node ≥ 22.13, < 25**. On 22.12, `node:sqlite`
   is still flag-gated and `init` fails. The image pins `node:22.23-bookworm-slim`.
4. **S1-5 container lifecycle.** Give each tool container a `--name` and `docker rm -f` it on exit. Killing the
   `docker run` client leaves the container running, and in S0-4 a leftover one wrote into the next run's index.

### New decision (needed before G1)

**F0 tool surface.** At `f72c9d2`, `tools/list` shows only `codegraph_explore` (`src/mcp/tools.ts:2034`, `DEFAULT_MCP_TOOLS`).
The other tools still work when called and can be listed with `CODEGRAPH_MCP_TOOLS`. Each explore call returns about 21–25K characters
(roughly 6K tokens). Options:
- **Upstream default (explore only):** F0 as users actually get it.
- **Full set:** a stronger baseline, but a configuration upstream doesn't ship.
Pick one, add a row to the §0 decision table, and record `CODEGRAPH_MCP_TOOLS` in the run config hash.

### How to apply
Edit the lines above in `EVAL_HARNESS_DESIGN.md`. Check that every section mentioning the patch route or "Node 22" still agrees.

---

## 3. S0-3 results: post-cutoff source, dataset facts, gold

**Status:** proposed by A, signed off by B 2026-11-05 (with a note for S2-2, below). Evidence: `docs/spikes/s0-3.md`, `scripts/s0_3_census.py`.
**Why:** the census showed the post-cutoff plan can't work as written, and a few dataset facts in §1a are wrong.

### Edits

1. **§1a Datasets, SWE-bench-Live row.** "1,319 tasks / 93 repos in the initial paper" → `full` split: 1,888 tasks, 223 repos,
   MIT. Its Python tasks end on **2025-09-02**, so it is a benchmark pool, **not** a post-cutoff source.
   `SWE-bench-Live/MultiLang` has 2026 tasks but no Python, so it is out of v1.
2. **§1a post-cutoff slice.** Both models' training data cutoff is **Jun 2026** (models overview, read 2026-11-05), so
   no public dataset has post-cutoff Python tasks. Replace the source with **self-collected tasks**: Python issue → merged PR pairs
   from pool repos, merged on or after 2026-07-01, gold from the patch. Localization needs no test harness, so this is cheap.
   GitHub search shows 1,364 merged PRs linked to issues in the 20 largest pool repos since 2026-07-01 (upper bound;
   language, source-only and linked-issue quality filters still apply). Add as an S1/S2 task, about 2 pd, owner A.
3. **§1a Datasets, Loc-Bench row.** All 560 tasks edit at least one pre-existing `.py` file; 467 touch only `.py` files.
   The earlier "about 85 non-Python" note was wrong.
4. **§1a Tags / stratification.** SWE-bench Lite has **no** `multi_hop` tasks (it is single-file by construction).
   `multi_hop` comes from Loc-Bench and SWE-bench-Live; about 30% of the pool overall.
5. **§16 S2-1 gold.** Patch-derived gold files equal `edit_functions` files on 95.4% of the 834 czlll tasks; the other 4.6%
   are patches that also touch `.py` files outside any function. Rule: **gold files come from the patch**; function gold
   comes from `edit_functions` where present and from base-commit parsing (S2-1) for SWE-bench-Live.
6. **§0 / §14 API rules.** The models overview lists default effort as Sonnet 5.5 `high`, Haiku 5.5 `medium`. This
   confirms D1 (defaults differ, so effort is set explicitly).

### How to apply
Edit §1a, §16 S2 and the readiness facts in §17. Update `CLAUDE.md` rule 8 only if the split rule changes.

### B's note for S2-2 (not a blocker for these edits)
The S0-3 feasibility split only lets repos with ≤ 25 tasks into `dev150` (`DEV_MAX_REPO_TASKS`), so every repo with many tasks
(conan, django, matplotlib, …, also big codebases) lands in `test_core`. F's parameters are fitted on `dev150`, and graph features such as
PageRank scale with repo size, so F would be fitted on small graphs and tested on large ones. When S2-2 freezes the real
split, stratify `dev150` by repo size (e.g. node-count bands from S2-4) instead of excluding large repos, or report a
`repo_size` slice so a size mismatch is visible.
