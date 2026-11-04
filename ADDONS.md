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
