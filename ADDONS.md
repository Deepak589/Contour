# Add-ons (deferred improvements)

Improvements to `EVAL_HARNESS_DESIGN.md` that are agreed but not applied yet.

---

## 1. LaTeX rendering for §13 formulas

**Status:** deferred.
**What it does:** display only — the math does not change. GitHub and VS Code markdown preview render `$$…$$` as typeset math (real fractions, subscripts, Σ).
**Do it when:** the doc feeds a paper/report or is shared on GitHub. Until then, plain-text formulas stay easier to read in the raw `.md`.
**Cost:** raw source gets harder to read; some viewers show the raw `$$…$$`.

### Ready-to-paste replacements (§13.2–13.3, synced with the post-review formulas)

**Seed fusion (RRF)**
$$
s_0(v) = \sum_{r \in \{\text{bm25},\,\text{dense},\,\text{exact}\}} \frac{1}{k + \text{rank}_r(v)}, \qquad k = 60
$$

**Edge weights and transition**
$$
w(e) = \tau_{\text{kind}(e)} \cdot c(e), \qquad P(u \to v) = \frac{w(u,v)}{\sum_x w(u,x)}
$$

**Personalized PageRank (fixed α)**
$$
\pi_s = \alpha \, \hat{s}_0 + (1 - \alpha)\, P^{\top} \pi_s, \qquad \alpha = 0.25
$$

**Hub correction (lift), smoothed and normalized per query**
$$
\text{lift}(v) = \frac{\pi_s(v)}{\bigl(\pi_g(v) + \varepsilon\bigr)^{\beta}}, \qquad
\text{rel}(v) = \frac{\text{lift}(v)}{\max_u \text{lift}(u)}, \qquad \varepsilon = \tfrac{1}{N}
$$

**Chunk score**
$$
\text{rel}(c) = \text{rel}\bigl(\text{sym}(c)\bigr) \cdot \bigl(0.5 + 0.5\,\text{bm25}_{\text{norm}}(c)\bigr)
$$

**Marginal value over the held level**
$$
\Delta v(u, \ell) = \text{rel}(u) \cdot \max\bigl(0,\ g(\ell) - g(h_u)\bigr)
$$

**Objective**
$$
\max_{\{\ell_u\}} \sum_u \Bigl[ \Delta v(u, \ell_u) - \lambda \, c(u, \ell_u) \Bigr]
\quad \text{s.t.} \quad \sum_u c(u, \ell_u) \le B
$$

**Greedy solver stop rule**
$$
\text{pick } \arg\max \frac{\Delta v}{\Delta c} \quad \text{until} \quad \max \frac{\Delta v}{\Delta c} < \lambda \ \text{ or } \ \sum c = B
$$

### How to apply
Replace each backtick formula in §13.2–13.3 with the matching block above. Keep the prose around them unchanged.
