# Related work (S0-6)

**Owner:** B · **Date:** 2026-11-08 · **Scope:** time-boxed notes on RepoGraph, LocAgent, cAST and Agentless: what each
does, where Variant F differs, and what it means for this study's validity. Numbers are quoted from the papers' arXiv
HTML versions, read 2026-11-08; none are reproduced here.

## Summary

| Work | What it is | Representation given to the model | Reports tokens? | Relation to this study |
|---|---|---|---|---|
| RepoGraph (ICLR 2025) | Line-level code graph, plug-in for agents and pipelines | k-hop ego-graph around one search term, flattened or LLM-summarised | Yes, per instance and per variant | Closest to "more graph context": shows more context can hurt |
| LocAgent (ACL 2025) | Graph-guided localization agent + Loc-Bench | Search / traverse / retrieve tools over a file-class-function graph | Cost and rounds only | Closest prior work; source of one pool dataset and the Acc@k convention |
| cAST (2025) | AST-aware chunking for code RAG | Chunks that split large nodes and merge small siblings | No | Our L2 unit (§13, line 692) |
| Agentless (FSE 2025) | Non-agent pipeline: localize, repair, validate | Hierarchical: files → classes/functions → edit lines | Cost per instance | Defines the hierarchical localization baseline and the Acc@k convention |

## RepoGraph

[Ouyang et al., arXiv 2410.14684](https://arxiv.org/abs/2410.14684), ICLR 2025, code at `ozyyshr/RepoGraph`.

- **Graph:** tree-sitter, one node per *line* (definition or reference), edges `contain` and `invoke`; built-in and
  third-party calls filtered out.
- **Retrieval:** one search term → k-hop ego-graph (k = 1, 2), returned flattened or as an LLM summary. In agent
  frameworks it is an action (`search_repograph`); in Agentless it is prompt context at every step.
- **Results (SWE-bench Lite):** about +2 to +2.7 pp resolve rate across four frameworks (e.g. Agentless/GPT-4o 27.33 →
  29.67). File-level localization: Agentless 68.7 → 74.3%.
- **Token cost:** 1-hop flatten 2,311 tokens per retrieval vs 2-hop flatten 10,505. Agentless with 2-hop flatten
  resolves **26.00% vs 29.67%** with 1-hop: more graph context lowered the score. Per-instance tokens rise 5–30%
  (Agentless 42,376 → 47,323).

**For us:** the 1-hop vs 2-hop result is prior evidence for F's thesis that a budget on delivered context matters, not
only graph coverage. RepoGraph fixes the context size by hop count; F fixes it by a token budget with a relevance stop.
That's the contrast to state in the paper.

## LocAgent

[Chen et al., arXiv 2503.09089](https://arxiv.org/abs/2503.09089), ACL 2025, code at `gersteinlab/LocAgent`.

- **Graph:** directory, file, class, function nodes; `contain`, `import`, `invoke`, `inherit` edges. Almost the same
  as CodeGraph's Python graph (S0-5: `contains`, `imports`, `calls`, `extends`, plus `instantiates`, `references`,
  `decorates`).
- **Tools:** `SearchEntity` (keywords → entities at fold / preview / full detail), `TraverseGraph` (typed BFS from
  given entities, returned as a tree), `RetrieveEntity` (full attributes and code).
- **Results (Claude-3.5):** SWE-bench Lite file Acc@5 94.16, function Acc@5 73.36; Loc-Bench file Acc@5 83.39,
  function Acc@10 59.29. Baselines on Loc-Bench function Acc@10: OpenHands 59.11, SWE-agent 51.96, Agentless 42.68.
- **Cost:** $0.66 per example (7 rounds) with Claude-3.5; fine-tuned Qwen2.5-32B $0.09. No token counts for baselines.
- **Loc-Bench:** 560 tasks (bug 242, feature 150, security 29, performance 139); bug issues created after Oct 2024.
  The text mentions 660 collected; the released set is 560 (matches S0-3).

**For us:**
1. **Acc@k definition differs.** LocAgent and Agentless count a hit only if *all* gold locations are in the top k
   (hit-all). Our primary is **hit-any** (§5 line 146). Our numbers are not comparable to theirs and will look higher.
   We already report hit-all as secondary; the paper should compare to literature on hit-all only.
2. **Loc-Bench is not post-cutoff for our final models.** "After Oct 2024" was post-cutoff for Claude-3.5; it is
   before the Jun 2026 cutoff of Sonnet 5.5 / Haiku 5.5 (S0-3). It is in our pool as ordinary data, not a
   contamination control.
3. **Reviewer question: "why not LocAgent as a baseline?"** Its graph and tools are close to Variant D and F0. Not in
   the matrix today. Either argue F0 covers "graph tools over an index" or add LocAgent's tool surface as an
   exploratory arm. Decision for A and B, not taken here.
4. LocAgent reports dollars and rounds, not tokens-to-localization. `T_loc` is a gap we fill.

## cAST

[Zhang et al., arXiv 2506.15655](https://arxiv.org/abs/2506.15655), CMU and Augment Code, code at `yilinjz/astchunk`.

- **Method:** parse with tree-sitter; recursively split AST nodes larger than a size cap; merge small adjacent
  siblings up to the cap.
- **Results:** +4.3 Recall@5 on RepoEval retrieval and +2.67 Pass@1 on SWE-bench generation vs fixed-size line chunks.
- **Stated limits:** no context from parent AST nodes; code files only.

**For us:** cAST is F's L2 unit as written in §13 (line 692). Its "no parent context" limit is what F's L1 skeletons
supply, so the L1 + L2 pair is the piece to describe as ours, not the chunker. Cite cAST for the chunker and don't
claim chunking as a contribution.

## Agentless

[Xia et al., arXiv 2407.01489](https://arxiv.org/abs/2407.01489), FSE 2025.

- **Pipeline:** localize → repair → validate, no agent loop. Localization is hierarchical: files → classes and
  functions → edit lines, combining LLM ranking with embedding retrieval.
- **Results:** SWE-bench Lite 27.33% at $0.34 (v1); a later version reports 32.00% at $0.70.
- Source of the hit-all Acc@k convention LocAgent follows.

**For us:** Agentless is a fixed pipeline, so it isn't in our matrix, which holds the agent loop constant (validity
rule 6). It shows a non-agent pipeline is a strong, cheap baseline; on Loc-Bench, though, it trails the agents
(function Acc@10 42.68 vs LocAgent 59.29). Mention it as the non-agent reference point; no action needed.

## Actions (proposed, not applied)

1. Paper compares to literature on **hit-all** Acc@k only; say so in §5 (A and B).
2. Decide whether a LocAgent-style tool surface is an exploratory arm or argued away (A and B, before G3).
3. Paper positions F against RepoGraph's hop-count context: budgeted delivery, not more graph.
