# Add-ons (deferred improvements)

Improvements to `EVAL_HARNESS_DESIGN.md` that are agreed but not applied yet.

---

## 1. LaTeX rendering for §13 formulas

**Status:** deferred.
**What it does:** display only — the math does not change. GitHub and VS Code markdown preview render `$$…$$` as typeset math (real fractions, subscripts, Σ).
**Do it when:** the doc feeds a paper/report or is shared on GitHub. Until then, plain-text formulas stay easier to read in the raw `.md`.
**Cost:** raw source gets harder to read; some viewers show the raw `$$…$$`.

### Ready-to-paste replacements (§13.2–13.3)

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

**Hub correction (lift)**
$$
\text{rel}(v) = \frac{\pi_s(v)}{\pi_g(v)^{\beta}}, \qquad \beta \in [0, 1]
$$

**Value with ledger term**
$$
v(u, \ell) = \text{rel}(u) \cdot g(\ell) \cdot \bigl(1 - \sigma(u, \ell)\bigr)
$$

**Objective**
$$
\max_{\{\ell_u\}} \sum_u \Bigl[ v(u, \ell_u) - \lambda \, c(u, \ell_u) \Bigr]
\quad \text{s.t.} \quad \sum_u c(u, \ell_u) \le B
$$

**Greedy solver stop rule**
$$
\text{pick } \arg\max \frac{\Delta v}{\Delta c} \quad \text{until} \quad \max \frac{\Delta v}{\Delta c} < \lambda \ \text{ or } \ \sum c = B
$$

### How to apply
Replace each backtick formula in §13.2–13.3 with the matching block above. Keep the prose around them unchanged.
