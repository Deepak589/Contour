# Eval Harness — Core Design Plan

> An agent evaluation harness. Primary research question: **for a fixed agent, how do different code-index representations trade off localization accuracy against cost (tokens, tool calls, latency) — and when does structure actually help?**
>
>
> Method contribution: **Variant F — budgeted multi-resolution context delivery (CodeGraph v2)**. Sub-question: *does it reduce tokens-to-localization vs CodeGraph and flat retrieval without losing accuracy?* Variants A–E and F0 (unmodified CodeGraph) are the baselines (see §13).
>
> Multi-domain support is a design property of the core, not a v1 deliverable.

---

## 1. Goals & Non-Goals

### Goals
- Run **agents × tasks × conditions × seeds** as a reproducible experiment matrix.
- Plug in new **domains, agents, tools, graders** without touching the core engine.
- Capture full **trajectories** (every step, tool call, token, latency) in one schema.
- Report **accuracy + cost + efficiency** with variance (pass@k, mean ± CI).
- First (and only v1) domain: **coding** — issue **localization** as the primary task, with **index variant** (7 levels: A–F + F0, see §1a) as the key independent variable.

### Non-Goals (v1)
- Not a feature-rich coding agent.
- Not a UI/dashboard product (CLI + static HTML/CSV reports is enough).
- Not distributed/cluster scheduling (local parallelism first).
- Not a second domain in v1 — tool-calling/SQL moved to Future Work (doesn't serve the research question).
- Not a new graph extractor — F reuses CodeGraph's graph (parsing, resolution, framework linkers). Contributions are the **controlled comparison** and F's **retrieval + delivery method** (§13).

---

## 1a. Research Design

### Independent variables
| Axis | Levels |
|---|---|
| **Index variant** | A `grep_read` (baseline) · B `bm25` · C `embeddings` (pgvector + BGE-M3; same model as F's dense seeds) · D `ast_graph` (search + neighbour tools over **CodeGraph's SQLite graph** — same extractor as F0/F, so D isolates representation, not extraction quality) · E `graph_summaries` (D + LLM-written module summaries) · **F `multires_v2`** (hybrid seeds → whole-graph PPR with hub lift → token-budgeted level selection with λ early stop; ledger inside the objective, §13) · **F0 `codegraph_v1`** (CodeGraph at a pinned commit with its **original tool descriptions**; only change: catch-up sync disabled in the stale condition, see below) |
| **Token budget** (F only) | 2k · 4k · 8k · 16k per `explore` call |
| **Model** | `claude-sonnet-5-5` (main) · `claude-haiku-5-5` (small). Opus 5.5 / Fable 5.1 sit above Sonnet and are **not** tested — claims are limited to these two models. |
| **Index freshness** | `fresh` · `stale_k20` (index built 20 commits before the task commit). Re-indexing must be off for **every** indexed variant: F's incremental re-index is disabled, and F0's catch-up `sync()` on writer open (`src/mcp/project-lifecycle.ts:176`) plus its file watcher are disabled by a one-line patch to the pinned build (reported as a deviation). A freeze test checks the index is unchanged after a run (§12). |

**Controlled:** identical system prompt, agent loop, step/token budget, `read_file`, and final-answer format. Retrieval tools **differ by variant by design** (§7) — graph and handle tools cannot hide behind one `search()`. To limit the confound: our own variants' tool descriptions follow one template with similar length; F0 keeps CodeGraph's original descriptions (rewriting them would remove tuning it relies on); the number of retrieval tools is reported per variant.
**API settings (fixed for every run):**
- `temperature` / `top_p` / `top_k` are **not sent** — non-default values return a 400 on Sonnet 5.5 and Haiku 5.5, and any value does from API version `2026-10-21`. The API has no seed parameter, so `seed` is a **run label**; dev runs confirm that repeat runs actually vary.
- `output_config.effort` set **explicitly and identically** for both models (`medium`) — defaults differ (Haiku 5.5 `medium`, Sonnet 5.5 `high`), which would confound H3.
- Server-side refusal `fallbacks` **off**, so the model under test never changes; refusals are logged as `stop_reason = refusal`.
**Additive mode** (index tool *plus* grep) — the realistic agent setup — runs on **test** (block below), not only on dev50, which F's parameters were fitted on. It matters because neither F's search nor CodeGraph's FTS table covers string literals, so issues quoting an error message favour grep.

### Run matrix
More tasks buy more power than more seeds, so every block uses 3 seeds and spends the budget on tasks.

| Block | Variants | Model | Tasks (test) | Seeds | Runs |
|---|---|---|---|---|---|
| Core | A, D, F0, F0+dedup, F | Sonnet 5.5, fresh | 350 | 3 | 5,250 |
| Small model | same 5 | Haiku 5.5, fresh | 100 | 3 | 1,500 |
| Staleness | A, D, F0, F | Sonnet 5.5, stale_k20 | 100 (gold files changed within the 20-commit window) | 3 | 1,200 |
| F ablations | 6 configs (§13.5) | Sonnet 5.5 | 150 | 3 | 2,700 |
| Budget sweep | F at 2k / 8k / 16k (4k is in Core) | Sonnet 5.5 | 150 | 3 | 1,350 |
| Breadth | B, C, E | Sonnet 5.5 | 150 | 3 | 1,350 |
| Additive | F + grep, F0 + grep | Sonnet 5.5 | 150 | 3 | 900 |
| **Total** | | | | | **≈ 14,250** |

≈ 5 days at ~2 min/run with 4 workers. **Index builds are a separate budget:** one build per (repo, commit, variant), embeddings included — precompute and cache them in Phase 2–3, before the Phase 4 clock starts. The earlier "pruned" grid (≈ 38–54k runs) did not fit the schedule.

### Hypotheses
- **H1** Structural indexes (D/E) beat lexical (A/B) mainly on `multi_hop` tasks.
- **H2** On `small` repos, A ≈ best variant — index overhead not worth it. *(SWE-bench Lite is mostly large Python repos — check slice size first; < 30 tasks → descriptive only.)*
- **H3** *(exploratory)* Haiku 5.5 gains more from structure than Sonnet 5.5.
- **H4** *(exploratory)* Indexed variants lose accuracy when stale; structural (D, F0, F) degrade faster. A reads live files and is the staleness-free reference.
- **H5** Summaries (E) cut tokens vs D at equal accuracy.
- **H6** F is **non-inferior** to F0 and D on file/function Acc@5 (one-sided, margin δ) **and** uses fewer tokens-to-localization. δ is **not** fixed at 2 pp: at 250–400 tasks a 2 pp margin has only ~5–56 % power (it would need ~770–3,100 tasks). δ is set from the paired disagreement rate measured on dev50 so that power ≥ 80 % at 350 tasks (expected ≈ 3.5–7 pp), and pre-registered before any test run. *(These power numbers are estimates; recompute with the measured rate.)*
- **H7** In F, each component contributes measurable token savings (ablation, §13.5). Expected order: λ early stop > ledger > selection > hub lift > hybrid seeds — untested. The ledger must also beat F0+dedup, not only F0.
- **H8** Ledger does not hurt accuracy under context loss: with old tool results cleared by the API's context editing (`clear_tool_uses`), re-expansion rate stays low and Acc@k is non-inferior to F − ledger.
- **H9** F's advantage over F0 is largest on the `paraphrase` slice (issue text shares no identifiers with gold symbols), because dense seeds still find a start point.

### Datasets
- **Primary:** SWE-bench Lite (localization gold) + Loc-Bench — 150–300 tasks with gold files/functions.
- **Contamination check:** ≥ 100 tasks on repos/commits after model cutoff (SWE-bench-Live / SWE-rebench + ~30 hand-made; `metadata.created_after_cutoff = true`); results reported separately. Plus a **memory-probe gate**: each model answers every task with no tools; tasks it localizes from memory are flagged `memorized` and reported as a separate slice.
- **Tagging:** every task has `task_type`, `repo_size` (small | medium | large), `language`, `identifier_overlap` (any | none → `paraphrase` slice).
  - `multi_hop` = gold locations span ≥ 2 files; otherwise `single_file`. Defined mechanically from the gold patch, never by hand.
- **Dev subset (dev50):** 50 stratified tasks from **repos held out of the test set** (repo-disjoint, so fitted parameters can't learn test repos), used for iteration, fitting F's parameters, and measuring the disagreement rate for δ. Never used in final runs.

### Outcomes
- **Agent output:** every run ends with a ranked list of up to 10 locations (`path` or `path::symbol`) in a fixed JSON block. The agent stops by emitting it or when the budget runs out (then the last emitted list, or empty).
- **Primary:** file Acc@k, function Acc@k (k = 1, 5, 10), MRR, computed on that ranked list. For file-level scoring `path::symbol` answers are reduced to `path`. For `multi_hop` tasks Acc@k = **hit-any** gold location in the top k; **all-gold recall@k** is reported alongside.
- **Tokens-to-localization**, two variants:
  - *to-reference*: tokens until a tool output first **names** a gold location (a one-line handle counts);
  - *to-code*: tokens until the gold **code itself** is shown (L2/L3 or `read_file`) — handles do not count.
  Both count only if that location ends in the final top-5. Runs that never get there are **censored** at their total tokens, not dropped — otherwise a variant that only solves easy tasks looks cheap. Report Kaplan–Meier curves and censoring-aware medians.
- **Token accounting:** report **billed** tokens (input, output, cache-read, cache-write separately) as the cost metric, and **unique content** tokens delivered by retrieval tools as the context metric.
- **Scope of claims:** localization only. Finding a location needs no function bodies, but fixing a bug does, so results say nothing about repair; a small repair pilot is Future Work.
- **recall@token-budget** (F only): gold recall of a single `explore_v2` call at B ∈ {2k, 4k, 8k, 16k}.
- **Dropped from v1:** `tests_pass` — localization runs produce no patch. A separate repair step is Future Work.

---

## 2. Software Principles Applied

| Principle | How it shows up in this harness |
|---|---|
| **Single Responsibility (S)** | Runner only schedules. Environment only manages state. Grader only scores. Logger only records. No component does two jobs. |
| **Open/Closed (O)** | New domain = new plugin package registered in the registry. Core engine code never changes. |
| **Liskov Substitution (L)** | Any `AgentAdapter` is swappable; runner never type-checks concrete classes. |
| **Interface Segregation (I)** | Small interfaces: `Environment`, `ToolSet`, `Grader`, `AgentAdapter`, `DatasetLoader`. No god-interface. |
| **Dependency Inversion (D)** | Runner depends on abstract protocols; concrete implementations injected via config + registry. |
| **Separation of Concerns** | Three layers: **Core** (orchestration), **Plugins** (domain logic), **Infra** (storage, cache, sandbox, LLM clients). |
| **Composition over Inheritance** | A task run = composition of env + tools + agent + graders. No deep class trees. |
| **Immutability** | `Task`, `RunConfig`, `Result` are frozen dataclasses / Pydantic models. Trajectories are append-only. |
| **Reproducibility as a first-class concern** | Pinned repo commits, pinned model IDs, seeds, config hash stored with every result. |
| **Fail-safe / Isolation** | One task crash never kills the experiment. Each run in its own sandbox with timeouts and budgets. |
| **YAGNI** | v1 has one domain; extract abstractions only when a second concrete use exists. |
| **Observability by default** | Every step emits a structured event; nothing is "printed". |

---

## 3. Design Patterns (where & why)

| Pattern | Component | Why |
|---|---|---|
| **Strategy** | `Grader`, `AgentAdapter` | Swap scoring method / agent at runtime with same interface. |
| **Adapter** | `AgentAdapter`, `DatasetLoader` | Wrap external agents and benchmarks (SWE-bench, Loc-Bench) into our interfaces. |
| **Registry + Plugin** | `registry.py` | Domains/agents/graders register by name (`@register("grader", "loc_acc_at_k")`). Config refers by name. Enables Open/Closed. |
| **Factory** | `ComponentFactory` | Builds concrete objects from YAML config + registry. Single place for wiring (DI root). |
| **Builder** | `ExperimentBuilder` | Expands config into the run matrix (agents × tasks × conditions × seeds). |
| **Template Method** | `BaseEnvironment.run_lifecycle()` | Fixed lifecycle `setup → run → snapshot → teardown`; domains override only the steps. |
| **Decorator** | `ToolSet` wrappers | Add logging, budget-checking, latency timing, fault injection around any tool without changing it. |
| **Observer / Event Bus** | `EventBus` → Logger, Metrics, Live progress | Components emit events (`StepStarted`, `ToolCalled`, `RunFinished`); subscribers react. Decouples logging from logic. |
| **Command** | `RunJob` | Each (agent, task, condition, seed) is a serializable job → retry, resume, parallelize, distribute later. |
| **Repository** | `ResultStore` | Abstract storage (SQLite now, Postgres later) behind one interface. |
| **Proxy (caching)** | `CachedLLMClient` | Cache key = prompt + params + **seed + run_id**. Modes: `off` (default for experiment runs), `record`, `replay` (dev/debug, regression tests). One seed's response is never served to another seed — otherwise variance/CIs are fake. |
| **Composite** | `CompositeGrader` | Combine graders (localization + process metrics) into one result, scores kept separate. |
| **Null Object** | `NullToolSet`, `NullGrader` | Clean baselines ("no index" condition) without `if` checks everywhere. |

---

## 4. Architecture

```mermaid
flowchart TB
    CFG[Experiment YAML] --> FAC[ComponentFactory + Registry]
    FAC --> BLD[ExperimentBuilder<br/>agents x tasks x conditions x seeds]
    BLD --> Q[Job Queue - RunJob commands]
    Q --> RUN[Runner / Worker Pool]

    subgraph RunScope[Single Run - isolated sandbox]
        ENV[Environment<br/>Docker repo at task commit]
        TOOLS[ToolSet + Decorators<br/>logging, budget, timing]
        AGT[AgentAdapter<br/>mini-agent]
        AGT <--> TOOLS
        TOOLS <--> ENV
    end

    RUN --> RunScope
    RunScope --> TRJ[Trajectory]
    TRJ --> GRD[CompositeGrader<br/>localization + process]
    GRD --> RES[(ResultStore<br/>SQLite/Postgres)]

    BUS((EventBus)) -.-> LOG[Trajectory Logger JSONL]
    BUS -.-> MET[Metrics / Progress]
    RunScope -.emits.-> BUS

    RES --> REP[Reporter<br/>pass@k, cost, steps, CI, A/B diff]
    LLM[CachedLLMClient - Proxy] --- AGT
```

### Layers
- **Core** — `runner`, `builder`, `factory`, `registry`, `events`, `schemas`. Domain-agnostic. Changes rarely.
- **Plugins** — `domains/coding`, `agents/*`, `graders/*`. Changes often.
- **Infra** — `sandbox` (Docker), `storage`, `llm` (clients + cache), `reporting`.

**Dependency rule:** Plugins → Core interfaces. Infra → Core interfaces. Core depends on nothing concrete.

---

## 5. Core Interfaces (Python Protocols)

```python
# core/interfaces.py
from typing import Protocol, Any
from core.schemas import Task, Trajectory, GradeResult, EnvState, ToolSpec

class Environment(Protocol):
    def setup(self, task: Task) -> None: ...
    def execute(self, action: dict[str, Any]) -> dict[str, Any]: ...
    def snapshot(self) -> EnvState: ...          # final state for graders
    def teardown(self) -> None: ...

class ToolSet(Protocol):
    def specs(self) -> list[ToolSpec]: ...        # JSON schemas for the LLM / MCP
    def call(self, name: str, args: dict) -> dict: ...

class AgentAdapter(Protocol):
    name: str
    def run(self, task: Task, tools: ToolSet, budget: "Budget") -> Trajectory: ...

class Grader(Protocol):
    name: str
    def score(self, task: Task, traj: Trajectory, state: EnvState) -> GradeResult: ...

class DatasetLoader(Protocol):
    def load(self, source: str) -> list[Task]: ...

class ResultStore(Protocol):
    def save(self, result: "RunResult") -> None: ...
    def query(self, **filters) -> list["RunResult"]: ...
```

### Registry (Plugin pattern)
```python
# core/registry.py
_REGISTRY: dict[str, dict[str, type]] = {
    "agent": {}, "grader": {}, "env": {}, "toolset": {}, "dataset": {}
}

def register(kind: str, name: str):
    def deco(cls):
        _REGISTRY[kind][name] = cls
        return cls
    return deco

def resolve(kind: str, name: str) -> type:
    return _REGISTRY[kind][name]
```

```python
# plugins/graders/loc_acc_at_k.py
@register("grader", "loc_acc_at_k")
class LocAccAtK:
    name = "loc_acc_at_k"
    def score(self, task, traj, state, k=5):
        top = {loc.split("::")[0] for loc in traj.final_locations[:k]}  # path::symbol -> path
        hit = bool(top & set(task.gold["files"]))                       # hit-any (multi_hop too)
        return GradeResult(grader=self.name, score=float(hit), passed=hit)
```

### Template Method (environment lifecycle)
```python
class BaseEnvironment:
    def run_lifecycle(self, task, agent, tools, budget):
        self.setup(task)
        try:
            traj = agent.run(task, tools, budget)
            return traj, self.snapshot()
        finally:
            self.teardown()          # always cleans up
```

### Decorator (tool instrumentation)
```python
class TimedTool:
    def __init__(self, inner: ToolSet, bus: EventBus):
        self.inner, self.bus = inner, bus
    def specs(self): return self.inner.specs()
    def call(self, name, args):
        t0 = time.perf_counter()
        out = self.inner.call(name, args)
        self.bus.emit(ToolCalled(name, args, out, time.perf_counter() - t0))
        return out

# composition: BudgetGuard(TimedTool(IndexToolSet(env), bus), budget)
```

---

## 6. Data Schemas

```python
class Task(BaseModel, frozen=True):
    id: str
    domain: str                  # "coding", "tool_calling", ...
    prompt: str
    env_spec: dict               # repo url + commit, docker image, fixtures
    budget: Budget               # max_steps, max_tokens, timeout_s
    gold: dict                   # expected files/functions/tests
    metadata: dict = {}          # task_type (single_file|multi_hop), repo_size, language, identifier_overlap, created_after_cutoff, memorized

class Step(BaseModel):
    idx: int
    role: Literal["assistant", "tool"]
    content: str
    tool_name: str | None
    tool_args: dict | None
    tokens_in: int               # uncached input
    tokens_out: int
    cache_read_tokens: int
    cache_write_tokens: int
    latency_s: float

class Trajectory(BaseModel):
    run_id: str
    steps: list[Step]
    final_answer: str | None
    final_locations: list[str]   # ranked, max 10: "path" or "path::symbol"
    stop_reason: Literal["done", "budget", "timeout", "error", "refusal"]

class RunResult(BaseModel):
    run_id: str
    experiment_id: str
    config_hash: str             # reproducibility
    agent: str
    task_id: str
    condition: str               # grep_read | bm25 | embeddings | ast_graph | graph_summaries | codegraph_v1 | codegraph_v1_dedup | multires_v2[-ablation]
    model: str
    effort: str                  # set explicitly, same for all models
    budget_tokens: int | None    # F's explore budget B (None for other variants)
    index_fresh: bool            # False = staleness experiment
    seed: int
    grades: list[GradeResult]
    cost_usd: float
    total_tokens: int
    n_steps: int
    wall_time_s: float
    index_calls: int             # adoption: how often the agent actually used the index
    first_correct_file_step: int | None
    tokens_to_reference: int     # see §1a Outcomes; = total tokens if censored
    tokens_to_code: int
    localized: bool              # False → both token metrics are censored
    reads_after_index: int       # read_file calls made after an index call (did the index replace reads?)
    retrieval_tools: int         # number of retrieval tools exposed (confound covariate)

class IndexBuildRecord(BaseModel):  # one per (repo, commit, variant) — amortised cost
    repo: str
    commit: str
    variant: str
    build_time_s: float
    build_tokens: int            # LLM tokens; > 0 only for graph_summaries
    embed_time_s: float          # embeddings + F dense seeds
    index_size_mb: float
```

---

## 7. Experiment Config (config-driven, no code changes)

```yaml
# experiments/code_index_variants.yaml
experiment: code_index_variants_v1
dataset:
  loader: swebench_loc
  sources: [czlll/SWE-bench_Lite, czlll/Loc-Bench_V1, swe-bench-live, datasets/coding/post_cutoff.jsonl]
  subset: dev50              # dev50 | test (= full minus dev50; final runs only)
agents:
  - name: mini_agent         # primary result
    models: [claude-sonnet-5-5, claude-haiku-5-5]
    effort: medium           # explicit: defaults differ per model
    fallbacks: off           # model under test never changes
    # no temperature/top_p/top_k: 400 on these models
conditions:
  grep_read:       { toolset: [grep, read_file] }
  bm25:            { toolset: [search_bm25, read_file] }
  embeddings:      { toolset: [search_embed, read_file], params: { model: bge-m3 } }
  ast_graph:       { toolset: [search_graph, graph_neighbors, read_file] }
  graph_summaries: { toolset: [search_graph, graph_neighbors, module_summary, read_file] }
  codegraph_v1:       { toolset: [codegraph_explore, read_file], params: { version: pinned, tool_descriptions: upstream } }
  codegraph_v1_dedup: { toolset: [codegraph_explore, read_file], params: { version: pinned, tool_descriptions: upstream, env: { CODEGRAPH_EXPLORE_DEDUP: "1" } } }
  multires_v2:
    toolset: [explore_v2, expand, read_file]
    params:
      budget_tokens: 4000        # ceiling B
      lambda: fitted             # early-stop threshold on per-query-normalized rel
      beta: fitted               # hub-lift exponent; 0 = plain PPR
      tau: fitted                # 3 edge groups: structural / import / reference
      level_gain: { handle: 0.1, L1: fitted, L2: 1.0, L3: fitted }
      reverse_edge_weight: 1.0   # ρ, fixed: undirected like CodeGraph's walk
      rrf_k: 60
      alpha: 0.25                # PPR restart prob; fixed = CodeGraph's value
      dense_model: bge-m3        # same as `embeddings`
      ledger: true
index_freshness: [fresh, stale_k20]
budget: { max_steps: 30, max_tokens: 200000, timeout_s: 600 }
graders: [loc_acc_at_k, mrr, tokens_to_localization, process_metrics]
seeds: [0, 1, 2]             # run labels only — the API has no seed parameter
runner:
  workers: 4
  retry: 2
  llm_cache: off             # off | record | replay — never on for experiment runs
```

---

## 8. Folder Structure

```
Eval_harness/
├── EVAL_HARNESS_DESIGN.md
├── pyproject.toml
├── evalh/
│   ├── core/                # domain-agnostic engine
│   │   ├── interfaces.py
│   │   ├── schemas.py
│   │   ├── registry.py
│   │   ├── factory.py
│   │   ├── builder.py
│   │   ├── runner.py
│   │   └── events.py
│   ├── infra/
│   │   ├── sandbox/docker_env.py
│   │   ├── storage/sqlite_store.py
│   │   ├── llm/client.py
│   │   ├── llm/cache.py
│   │   └── reporting/report.py
│   └── plugins/
│       ├── agents/
│       │   └── mini_agent.py        # ~150 lines, controlled baseline (+ forced-compaction mode for H8)
│       ├── domains/
│       │   └── coding/              # env, tools, dataset loader (swebench_loc)
│       ├── tools/
│       │   ├── decorators.py        # timing, budget, logging, index-call counter
│       │   ├── code_index_mcp.py    # exposes any index variant via MCP
│       │   └── indexes/             # one module per variant (tool sets differ by design, §1a)
│       │       ├── grep_read.py
│       │       ├── bm25.py
│       │       ├── embeddings.py    # pgvector + BGE-M3
│       │       ├── ast_graph.py     # search + neighbours over CodeGraph's SQLite graph
│       │       ├── graph_summaries.py
│       │       ├── codegraph_v1.py  # pinned upstream CodeGraph MCP (dedup on/off; sync-off patch for stale)
│       │       └── multires_v2/     # Variant F — standalone service over CodeGraph SQLite + side DB
│       │           ├── ids.py       # stable symbol IDs (no line numbers) + per-symbol body hashes
│       │           ├── levels.py    # handle / L1 skeleton / L2 cAST chunks / L3 line ranges + token counts
│       │           ├── merkle.py    # incremental re-index
│       │           ├── centrality.py# global PageRank π_g, incremental after sync
│       │           ├── seeds.py     # BM25 (split identifiers) + dense + exact, RRF fusion
│       │           ├── spread.py    # whole-graph PPR, τ_kind × confidence weights, hub lift
│       │           ├── select.py    # greedy MCKP: ledger term σ, λ early stop, containment
│       │           ├── ledger.py    # per-agent-context hash ledger + expand handles
│       │           └── server.py    # MCP: explore_v2, expand, reset_ledger
│       └── graders/
│           ├── loc_acc_at_k.py      # primary
│           ├── mrr.py               # primary
│           ├── tokens_to_localization.py
│           ├── gold_file_found.py
│           ├── process_metrics.py
│           └── composite.py
├── datasets/coding/post_cutoff.jsonl   # hand-made contamination-check tasks
├── experiments/*.yaml
├── runs/                    # JSONL trajectories (gitignored)
└── tests/                   # unit tests per component + golden-run tests
```

---

## 9. Metrics

- **Primary (localization):** file Acc@k, function Acc@k (k = 1, 5, 10), MRR.
- **Efficiency:** billed tokens/task (input, output, cache-read, cache-write), cost/task, tool calls/task, `read_file` calls after index calls, steps-to-first-correct-file, wall time.
- **Cost-at-equal-accuracy:** tokens needed to reach a target Acc@5 — the headline Pareto plot (accuracy vs tokens per variant × model).
- **Index cost:** build time, build tokens, index size — reported amortised per task.
- **Variant F specific:** tokens-to-reference and tokens-to-code (censored, §1a), recall@budget curve (2k–16k), **early-stop rate** and mean tokens used ÷ B (how often λ stops before the ceiling), handle-expansion rate, ledger hit rate, **ledger re-expansion rate** (agent expands a handle it was told it already had → context loss signal), level mix returned (L1/L2/L3 share).
- **Adoption:** index-call rate per run; runs where the agent never queried the index are flagged and analysed separately.
- **Slices:** every metric broken down by `task_type`, `repo_size`, model, freshness, `paraphrase`, `memorized`, post-cutoff. Slices with < 30 tasks are descriptive only.
- **Reliability:** variance across 3 seeds, 95% CIs, error/timeout/refusal rate.
- **Comparisons:** per-task scores are seed-averaged (so not binary — McNemar does not apply); differences are tested with a **paired bootstrap clustered by repo** (tasks from one repo are not independent). Censored token metrics use log-rank tests / bootstrap on KM medians.
- **Non-inferiority (H6, H8):** one-sided paired-bootstrap test on the Acc@5 difference with margin δ, set from the dev50 disagreement rate and pre-registered (§1a H6).
- **Confirmatory family (Holm-corrected):** H6 vs F0, H6 vs D, H1, H9. Everything else (H2–H5, H7 ablations, additive mode, slices) is exploratory and labelled as such.

---

## 10. Roadmap (~10 weeks)

| Phase | Deliverable | Exit criteria |
|---|---|---|
| **0. Research (1 wk)** | Read RepoGraph, LocAgent, CodexGraph, SweRank, cAST, LongCodeZip, Agentless; study Inspect AI, mini-swe-agent, CodeGraph SQLite schema | Decide Inspect AI vs own core. Freeze the per-variant tool contracts and `explore_v2` |
| **1. Harness MVP + baselines (2 wks)** | Core, Docker env, mini agent (ranked-answer format), `loc_acc_at_k`, tokens-to-localization, memory-probe gate; `grep_read` + `codegraph_v1` (dedup off/on, sync-off patch + freeze test) on dev50; measure run-to-run variation and the disagreement rate → set δ | Baseline numbers stable across 3 seeds — **v2 work starts only after this** |
| **2. Variants B–E (1–2 wks)** | D and E as views over CodeGraph's SQLite graph; B, C standalone; start prebuilding indexes per (repo, commit, variant); `IndexBuildRecord` logged | Sanity checks pass |
| **3. Variant F core (3 wks)** | Stable IDs + body hashes, levels + token counts, global PageRank, hybrid seeds, whole-graph PPR + hub lift, MCKP with ledger term and λ stop, expand handles, Merkle re-index; fit τ, β, g, λ on dev50 | Runs on dev50; F tests (§12) pass; parameters frozen before Phase 4 |
| **4. Experiments (1 wk)** | ≈ 14,250 runs (§1a matrix, ≈ 5 days) on `test` with all indexes prebuilt; F ablations (§13.5); budget sweep; staleness; Sonnet vs Haiku; additive mode | H1, H6, H9 tested (confirmatory); H2–H5, H7, H8 reported (exploratory) |
| **5. Analysis & write-up (1 wk)** | Pareto plot, recall@budget curves, ablation table, report; release harness + v2 | Reproducible from config hash |
| **Future work** | L0 LLM summaries, learned edge weights from trajectories, embedding fine-tuning, external agent adapters (Claude Code), repair step + `tests_pass`, lazy reference resolution, second domain | Only if time remains |

---

## 11. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Data contamination (model memorised repo) | ≥ 100 post-cutoff tasks; memory-probe gate flags `memorized` tasks; both reported as slices |
| Prompt bias between conditions | Identical system prompt across conditions; tool descriptions from one template |
| Cost blow-up | Pruned run matrix (§1a), budgets per run, dev50 before full runs |
| Over-engineering | One domain in v1; abstractions only when a second concrete use exists |
| Flaky sandboxes | Pinned Docker images, health checks, retries as Commands |
| Cache leaks responses across seeds → fake variance | Seed in cache key; `llm_cache: off` for experiments; seed-isolation test |
| Agent ignores the index tool | Log `index_calls`; report adoption rate; treat as a finding, not a bug |
| Effect undetectable (too few tasks) | 350 test tasks in Core; δ chosen for ≥ 80 % power from the measured disagreement rate; tasks over seeds |
| API rejects run settings | No sampling params; explicit effort; fallbacks off; context editing (not history rewriting) for H8 — append-only history, since Sonnet 5.5 rejects edited earlier turns on accounts created from 2026-08-31 |
| F0 stale index repairs itself | Catch-up `sync()` and watcher disabled by a minimal patch; freeze test (§12) |
| Unfair comparison across variants | Same prompt, loop, budget and answer format; tool count reported as covariate; additive mode as ablation; F0 also run with its dedup on |
| Parameters tuned on test data | τ, β, g, λ fitted on dev50 only; dev50 excluded from final runs; parameters frozen before Phase 4 |
| Ledger references code the agent no longer has (context compaction, sub-agents share session id) | Every ledger reference carries an `expand` handle; never assume persistence; ledger scoped per agent-context id, not per session; measure re-expansion rate; `ledger: false` ablation |
| Knapsack value function is arbitrary | Define utility explicitly (§13.3); calibrate weights on dev50 only; report sensitivity |
| Name-matched edges are wrong (dynamic languages) | Use CodeGraph's stored per-edge confidence (0.6–0.95 by resolver strategy) in `w(e)`; SCIP-resolved edges are Future Work |
| Agent ignores handles / never calls `expand` | Tool description iteration on dev subset; log expansion rate; treat non-use as a finding |
| v2 scope creep | v2 = levels + seeds + PPR/hub lift + MCKP/λ + ledger only; summaries, learned weights, lazy resolution are Future Work |

---

## 12. Testing Strategy

- **Unit:** each grader, tool decorator, builder matrix expansion.
- **Contract tests:** every registered plugin must satisfy its Protocol (auto-run over registry).
- **Golden-run test:** a fake deterministic agent on a toy task → asserts the exact `RunResult`.
- **Replay test:** re-run in `replay` mode → identical trajectory hash.
- **Seed-isolation test:** two seeds in `record` mode must never share a cached response.
- **Index contract test:** every variant's tools return their declared schema on a toy repo.
- **Grader test:** `path::symbol` answers match file gold; hit-any vs all-gold on a multi-hop toy task.
- **Freeze test (stale condition):** for each indexed variant incl. F0, index file hashes / node counts are identical before and after a run.
- **Variant F tests:** selection never exceeds `budget_tokens` (local token estimates calibrated against `count_tokens` on a sample, with a safety margin so the bound holds); every held unit that would have been selected appears as a `[seen]` handle; raising λ never increases selected tokens; a ledger hit (σ = 1) is emitted as a handle, not content; stable IDs survive a line-shifting edit; global PageRank sums to 1; Merkle re-index touches only changed files; every ledger reference resolves via `expand`; changed content invalidates its ledger entry.

---

## 13. Variant F — CodeGraph v2: Budgeted Multi-Resolution Context Delivery

Built as a **standalone MCP service reading CodeGraph's existing SQLite index** (MIT-licensed upstream, version pinned) — no changes to CodeGraph core until savings are proven in the harness.

**Positioning:** we do **not** compete on graph construction (CodeGraph's Rust kernel, ~40 framework linkers and resolver are reused as-is). The contribution is **retrieval + delivery**: one budgeted objective that replaces CodeGraph's per-file allocation and ~20 hand-tuned constants with 4 fitted parameters (τ, β, g, λ).

```
INDEX (offline, incremental)          RETRIEVE (per call)                    DELIVER (per agent context)
CodeGraph SQLite (nodes, edges, conf) hybrid seeds (BM25 + dense + exact,    ledger folded into the objective:
+ L1 skeletons / L2 cAST chunks /       RRF)                                 already-held content has value 0
  L3 line ranges, token counts        → whole-graph PPR, typed+conf edges    → emitted as 1-line ref + expand handle
+ stable symbol IDs + body hashes     → hub correction (lift over global PR) → compact text, no JSON wrapping
+ global PageRank                     → greedy MCKP with λ early stop
```

### 13.0 Baseline gaps this targets (source analysis of CodeGraph at commit `a0174cee`, Nov 2026; line numbers differ across commits)
| CodeGraph today | Where | Variant F |
|---|---|---|
| Budget in **characters**, fixed tiers 13k/18k/24k; documented as a ceiling (`tools.ts:318`), actual fill rate unmeasured | `src/mcp/tools.ts:317` | Caller-set **token** budget plus an explicit early stop (λ); fill rate measured for both |
| Budget split **per file first**, ~20 magic constants | `tools.ts:802, 5055` | One global selection over all symbols across files |
| Cross-call dedup **off by default** (`CODEGRAPH_EXPLORE_DEDUP=1`), line-range based, ≥8 lines, 8-call memory | `src/mcp/explore-dedup.ts` | Content-hash ledger, on by default, part of the objective |
| Lexical seeds only (FTS5 prefix + LIKE + fuzzy); paraphrased queries return empty | `src/db/queries.ts:1798`, `tools.ts:4598` | BM25 + dense + exact, RRF-fused |
| RWR only over the lexically gathered subgraph; BFS filters and orders edges by kind (contains > calls > other) but has no weights | `tools.ts:4327`, `src/graph/traversal.ts:126` | PPR over the whole graph with `τ_kind × confidence` weights |
| No stored centrality → hub files (utils, logging) rank high | `src/db/schema.sql` | Lift: personalized PR ÷ global PR^β |
| No stored bodies or token counts; partial skeleton/body/pointer only | `schema.sql` | Precomputed L1/L2/L3 units with token counts |
| Node ID includes line number → IDs churn on any line shift | `src/extraction/tree-sitter-helpers.ts:18` | Stable IDs + per-symbol body hash |

### 13.1 Index
| Level | Content | Built from |
|---|---|---|
| handle | One-line reference: `path:Lstart-end sym=name#hash (expand: h_xxxx)` | node row |
| L1 | Skeleton: signatures, types, docstrings, no bodies | tree-sitter |
| L2 | Symbol bodies split along the AST (cAST: split large nodes, merge small siblings under a size cap) | tree-sitter |
| L3 | Exact line window | source |
| L0 *(future)* | Module/dir summaries, bottom-up | small local LLM, optional |

Additions over the CodeGraph schema (stored in a side database keyed to CodeGraph node rows):
- **Token count** per unit per level: a local estimate calibrated against the API's `count_tokens` on a sample per repo, inflated by a safety margin so budget bounds hold.
- **Stable symbol ID** = `hash(file, kind, qualified_name, ordinal)` — no line number, so edits that shift lines don't change IDs.
- **Per-symbol body hash** — drives symbol-level incremental rebuild *and* the ledger key.
- **Global PageRank** π_g over the weighted graph, recomputed incrementally after sync.
- **Split-identifier FTS column** (camelCase / snake_case split) — replaces CodeGraph's separate segment-vocab workaround.
- Files and dirs hashed into a Merkle tree; only changed units are rebuilt. This also produces the `stale_k20` condition cheaply.

### 13.2 Retrieval
1. **Seeds** — Reciprocal Rank Fusion over three rankers:

   `s0(v) = Σ_{r ∈ {bm25, dense, exact}} 1 / (k + rank_r(v))`, k = 60

   BM25 over split identifiers + signatures + docstrings; dense over signatures + docstrings (local model, same as Variant C so the comparison is fair); exact name matches.
2. **Spread** — personalized PageRank from `s0` over the **whole graph** (not a pre-gathered subgraph):

   `w(e) = τ_kind(e) × c(e)`, transition `P(u→v) = w(u,v) / Σ_x w(u,x)`

   `τ` per edge group — structural (calls, extends, implements, overrides, instantiates), import, reference/other; `c(e)` = CodeGraph's stored resolution confidence from edge `metadata`, **1 when missing** (CodeGraph's own default). *(Its range per resolver strategy is unverified.)*
   - **Direction:** every edge is also added in reverse with weight `ρ · w(e)`, ρ = 1, so the walk is undirected like CodeGraph's — a seed reaches its callers, not just its callees. Fixing α alone would not remove this difference.
   - **Dangling nodes** (no out-edges) send their mass back to `s0_norm`, so no probability is lost.

   `π_s = α · s0_norm + (1 − α) · Pᵀ π_s`  (iterate to convergence), **α = 0.25 fixed**

   α = restart probability: high α stays near the seeds (precise, misses distant code); low α spreads further (better multi-hop, noisier). Fixed at CodeGraph's value so F vs F0 differences come from whole-graph spread, edge weights and hub lift — not from α. `s0_norm` = seed scores normalised to sum to 1.
3. **Hub correction (lift)** —

   `lift(v) = π_s(v) / (π_g(v) + ε)^β`, β ∈ [0, 1], ε = 1/N  (N = nodes in the repo)

   `rel(v) = lift(v) / max_u lift(u)`  — **normalized per query** to [0, 1]

   π_s = personalized PR, π_g = global PR. Demotes symbols that are central to everything (logging, utils, base classes) rather than to this query; β = 0 recovers plain PPR. ε smooths the ratio so obscure leaf nodes with tiny π_g aren't inflated. Per-query normalization makes `rel`, and therefore λ, comparable across small and large repos — raw PPR scores shrink as the graph grows.
4. **Chunk scores** — L2 units are AST chunks, not whole symbols. A chunk inherits its symbol's score, weighted by how well it matches the query:

   `rel(c) = rel(sym(c)) × (0.5 + 0.5 · bm25_norm(c))`, with `bm25_norm` ∈ [0, 1] within the symbol.

   This decides which part of a long function is sent.

### 13.3 Selection — one objective, ledger included
Each unit *u* is skipped or emitted at exactly one level ℓ ∈ {handle, L1, L2, L3}.

**Value (marginal over what the agent holds):** `Δv(u, ℓ) = rel(u) × max(0, g(ℓ) − g(h_u))`
- `g(ℓ)` = level gain: handle 0.1, L2 1.0 fixed; L1 and L3 fitted (initial 0.4, 0.6).
- `h_u` = the level of `u` the agent already holds according to the ledger (matched by body hash; `none` → g = 0). Holding L1 and upgrading to L2 is worth only the difference. Changed hash → `h_u = none` → re-sent in full.
- **`[seen]` references:** a held unit gains nothing from being re-sent, so the optimizer never re-sends it. Instead, after selection, every held unit whose *unheld* ratio `rel(u)·g(h_u) / c(u, h_u)` is ≥ the ratio of the last selected item — i.e. it would have been chosen if it weren't held — is emitted as a `[seen]` handle, and its handle cost counts against B.

**Cost:** `c(u, ℓ)` = precomputed tokens of that unit at that level + one-time file-header tokens for the first unit selected in each file.

**Objective:**

`max Σ_u [ v(u, ℓ_u) − λ · c(u, ℓ_u) ]`  s.t.  `Σ_u c(u, ℓ_u) ≤ B`, one level per unit, containment consistency (a class at L2 already covers its methods; children are not emitted again).

**Solver:** greedy on marginal `Δv / Δc` over level upgrades, respecting containment and charging each file's header once; **stop when the best ratio < λ or B is reached**. This is a heuristic: containment, shared headers and L3's lower gain make it something other than plain multiple-choice knapsack, so **no approximation guarantee is claimed**. There is no "best single item" fallback, which keeps the property that raising λ never increases tokens (same greedy order, earlier stop).

- **λ is the key new parameter:** B is a ceiling, and λ stops earlier when the remaining value per token is low. CodeGraph also treats its budget as a ceiling (`tools.ts:318`), so whether F actually sends fewer tokens is measured, not assumed.
- Expected shape: seeds → L2 bodies, 1-hop → L1 signatures, 2-hop → handles.
- **Fitted values (8):** τ (3 groups), g(L1), g(L3), β, λ, plus the fixed g(handle) = 0.1, g(L2) = 1. Fixed, not fitted: α = 0.25, ρ = 1, ε = 1/N, RRF k = 60. That is fewer than CodeGraph's ~20 hand-set constants, but not "4 parameters".
- **Fitting:** coordinate search on dev50 (repo-disjoint from test). Objective: minimize median tokens-to-code, subject to file Acc@5 no more than 1 pp below the untuned default config. Frozen before Phase 4; sensitivity reported per value.
- **Question-type budget** (optional ablation): "where is X" → 2k, "explain flow" → 8k.

### 13.4 Delivery and ledger safeguards
- Ledger keyed by **agent-context id** (not MCP session — sub-agents have separate contexts).
- Ledger hit → `[seen] path:L10-42 sym=foo#a1b2  (expand: h_a1b2)`.
- **Safeguards:** every reference is expandable via `expand`; body-hash change invalidates the entry; `reset_ledger` tool for clients that compact; re-expansion rate logged as the health metric.
- **Testing H8 needs context loss:** the mini agent never compacts, so H8 runs use the API's context editing (`clear_tool_uses_20250919`, beta `context-management-2025-06-27`) to clear old tool results server-side. Rewriting earlier turns client-side is avoided: Sonnet 5.5 rejects edited history on accounts created from 2026-08-31.
- Output is plain text: path header + line range + code. Deterministic ordering (for reproducibility, not caching).

### 13.5 Ablations (150 test tasks, Sonnet 5.5, 3 seeds)
| Config | Levels | Selection (MCKP) | λ early stop | Ledger | Hybrid seeds | Hub lift |
|---|---|---|---|---|---|---|
| F0 `codegraph_v1` (default, dedup off) | — | — | — | — | — | — |
| F0+dedup (`CODEGRAPH_EXPLORE_DEDUP=1`) | — | — | — | (theirs) | — | — |
| F-full | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| F − λ (fill to B) | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ |
| F − hub (β = 0) | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ |
| F − ledger (σ ≡ 0) | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ |
| F − selection (all L2, top-k) | ✓ | ✗ | ✗ | ✓ | ✓ | ✓ |
| F − levels (L2 only) | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ |
| F − hybrid (BM25 only) | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ |

- The ledger is compared against **both** F0 and F0+dedup — beating only a disabled feature is not a result.
- Budget sweep B ∈ {2k, 4k, 8k, 16k} on F-full → recall@budget curve.
- α sensitivity: α ∈ {0.1, 0.25, 0.5} on F-full (dev50 + test, exploratory) — shows whether the fixed α = 0.25 is near-optimal.
- **Paraphrase slice:** tasks whose issue text shares no identifiers with gold symbols, reported separately (expected largest gain from dense seeds).

### 13.6 Benchmarks for F
- SWE-bench Lite / Loc-Bench localization (main, same as A–E) + post-cutoff tasks.
- RepoQA (code QA, optional).
- CoIR for the seed/search component in isolation (optional).

### 13.7 F-specific risks
| Risk | Mitigation |
|---|---|
| CodeGraph optimises tool calls / wall time, not tokens — it may still win there | Report the Pareto front (accuracy vs tokens, plus tool calls and wall time); no single "beats" claim |
| Gains come mostly from λ, not the rest | Ablation table isolates each component |
| Upstream schema changes (`EXTRACTION_VERSION` bumps) | Pin CodeGraph version + commit; adapter tests against the pinned schema |
| Confidence values are fixed per resolver strategy, not calibrated | Treat `c(e)` as a prior; τ fitted on dev50; sensitivity reported |
| F0's index repairs itself in the stale condition | Catch-up sync and watcher disabled by a minimal patch; freeze test |
| Lexical blind spot (string literals not indexed by F or CodeGraph) | Additive mode (F + grep) run on test and reported |
| Global PR goes stale after edits | Incremental recompute on sync; staleness condition covers it |

### 13.8 Out of scope for v2 (Future Work)
L0 LLM summaries · learned edge weights / τ from logged trajectories · embedding fine-tuning on agent usage · question-type classifier · lazy (query-time) reference resolution to cut CodeGraph's resolution-dominated index time (~12 of ~15 min on the Linux kernel) · SCIP-resolved `exact` edges.
