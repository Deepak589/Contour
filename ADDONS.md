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
