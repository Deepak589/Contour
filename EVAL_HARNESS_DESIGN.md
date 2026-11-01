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
| **Index variant** | A `grep_read` (baseline) · B `bm25` · C `embeddings` (pgvector + BGE-M3; same model as F's dense seeds) · D `ast_graph` (tree-sitter: calls / imports / inheritance) · E `graph_summaries` (D + LLM-written module summaries) · **F `multires_v2`** (hybrid seeds → whole-graph PPR with hub lift → token-budgeted level selection with λ early stop; ledger inside the objective, §13) · **F0 `codegraph_v1`** (unmodified CodeGraph, direct baseline for F) |
| **Token budget** (F only) | 2k · 4k · 8k · 16k per `explore` call |
| **Model** | 1 small/cheap model · 1 frontier model |
| **Index freshness** | `fresh` · `stale_k20` (index built 20 commits before the task commit; F's incremental re-index disabled in this condition) |

**Controlled:** identical system prompt, agent loop, step/token budget, `read_file`, and final-answer format. Retrieval tools **differ by variant by design** (§7) — graph and handle tools cannot hide behind one `search()`. To limit the confound: all tool descriptions follow one template with similar length, and the number of retrieval tools is reported per variant.
**Ablation:** `additive` mode (index tool *plus* grep) run on the dev subset to reflect real-world agent setups.

### Run matrix (pruned)
| Block | Variants | Models | Freshness | Seeds |
|---|---|---|---|---|
| Core | A, D, F0, F0+dedup, F | small + frontier | fresh + stale_k20 | 5 |
| Breadth | B, C, E | frontier only | fresh | 3 |
| F ablations + budget sweep | §13.5 | frontier only | fresh | 5 |

The full cross-product (~50k runs) is not affordable; every hypothesis below is answerable from these blocks.

### Hypotheses
- **H1** Structural indexes (D/E) beat lexical (A/B) mainly on `multi_hop` tasks.
- **H2** On `small` repos, A ≈ best variant — index overhead not worth it. *(SWE-bench Lite is mostly large Python repos — check slice size first; < 30 tasks → descriptive only.)*
- **H3** Small models gain more from structure than frontier models.
- **H4** Index-based variants lose accuracy when stale; structural (D, F0, F) degrade faster than lexical (B). A reads live files and is the staleness-free reference.
- **H5** Summaries (E) cut tokens vs D at equal accuracy.
- **H6** F is **non-inferior** to F0 and D on file/function Acc@5 (one-sided, margin −2 pp) **and** uses fewer tokens-to-localization.
- **H7** In F, each component contributes measurable token savings (ablation, §13.5). Expected order: λ early stop > ledger > selection > hub lift > hybrid seeds — untested. The ledger must also beat F0+dedup, not only F0.
- **H8** Ledger does not hurt accuracy under context loss: with forced compaction, re-expansion rate stays low and Acc@k is non-inferior to F − ledger.
- **H9** F's advantage over F0 is largest on the `paraphrase` slice (issue text shares no identifiers with gold symbols), because dense seeds still find a start point.

### Datasets
- **Primary:** SWE-bench Lite (localization gold) + Loc-Bench — 150–300 tasks with gold files/functions.
- **Contamination check:** ≥ 100 tasks on repos/commits after model cutoff (SWE-bench-Live / SWE-rebench + ~30 hand-made; `metadata.created_after_cutoff = true`); results reported separately. Plus a **memory-probe gate**: each model answers every task with no tools; tasks it localizes from memory are flagged `memorized` and reported as a separate slice.
- **Tagging:** every task has `task_type`, `repo_size` (small | medium | large), `language`, `identifier_overlap` (any | none → `paraphrase` slice).
  - `multi_hop` = gold locations span ≥ 2 files; otherwise `single_file`. Defined mechanically from the gold patch, never by hand.
- **Dev subset:** 50 stratified tasks for iteration and for fitting F's parameters. **dev50 is excluded from all final runs** (`test` = full − dev50).

### Outcomes
- **Agent output:** every run ends with a ranked list of up to 10 locations (`path` or `path::symbol`) in a fixed JSON block. The agent stops by emitting it or when the budget runs out (then the last emitted list, or empty).
- **Primary:** file Acc@k, function Acc@k (k = 1, 5, 10), MRR, computed on that ranked list.
- **Tokens-to-localization:** total tokens (in + out) up to the step whose tool output first contains a gold location — counted **only if** that location is in the final top-5; otherwise the run is "not localized". Gold appearing in a verbose tool output that the agent then ignores does not count.
- **recall@token-budget** (F only): gold recall of a single `explore_v2` call at B ∈ {2k, 4k, 8k, 16k}.
- **Dropped from v1:** `tests_pass` — localization runs produce no patch. A separate repair step is Future Work.

---

## 2. Software Principles Applied

| Principle | How it shows up in this harness |
|---|---|
| **Single Responsibility (S)** | Runner only schedules. Environment only manages state. Grader only scores. Logger only records. No component does two jobs. |
| **Open/Closed (O)** | New domain = new plugin package registered in the registry. Core engine code never changes. |
| **Liskov Substitution (L)** | Any `AgentAdapter` (mini agent, Claude Code, LangGraph) is swappable; runner never type-checks concrete classes. |
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
| **Adapter** | `AgentAdapter`, `DatasetLoader` | Wrap external agents (Claude Code, OpenHands) and external benchmarks (SWE-bench, τ-bench) into our interfaces. |
| **Registry + Plugin** | `registry.py` | Domains/agents/graders register by name (`@register("grader", "loc_acc_at_k")`). Config refers by name. Enables Open/Closed. |
| **Factory** | `ComponentFactory` | Builds concrete objects from YAML config + registry. Single place for wiring (DI root). |
| **Builder** | `ExperimentBuilder` | Expands config into the run matrix (agents × tasks × conditions × seeds). |
| **Template Method** | `BaseEnvironment.run_lifecycle()` | Fixed lifecycle `setup → run → snapshot → teardown`; domains override only the steps. |
| **Decorator** | `ToolSet` wrappers | Add logging, budget-checking, latency timing, fault injection around any tool without changing it. |
| **Observer / Event Bus** | `EventBus` → Logger, Metrics, Live progress | Components emit events (`StepStarted`, `ToolCalled`, `RunFinished`); subscribers react. Decouples logging from logic. |
| **Command** | `RunJob` | Each (agent, task, condition, seed) is a serializable job → retry, resume, parallelize, distribute later. |
| **Repository** | `ResultStore` | Abstract storage (SQLite now, Postgres later) behind one interface. |
| **Proxy (caching)** | `CachedLLMClient` | Cache key = prompt + params + **seed + run_id**. Modes: `off` (default for experiment runs), `record`, `replay` (dev/debug, regression tests). One seed's response is never served to another seed — otherwise variance/CIs are fake. |
| **Composite** | `CompositeGrader` | Combine graders (tests pass + judge + process metrics) into one result with weighted/separate scores. |
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
        ENV[Environment<br/>Docker repo / SQL / API mock]
        TOOLS[ToolSet + Decorators<br/>logging, budget, timing]
        AGT[AgentAdapter<br/>mini-agent / Claude Code / LangGraph]
        AGT <--> TOOLS
        TOOLS <--> ENV
    end

    RUN --> RunScope
    RunScope --> TRJ[Trajectory]
    TRJ --> GRD[CompositeGrader<br/>deterministic + LLM judge + process]
    GRD --> RES[(ResultStore<br/>SQLite/Postgres)]

    BUS((EventBus)) -.-> LOG[Trajectory Logger JSONL]
    BUS -.-> MET[Metrics / Progress]
    RunScope -.emits.-> BUS

    RES --> REP[Reporter<br/>pass@k, cost, steps, CI, A/B diff]
    LLM[CachedLLMClient - Proxy] --- AGT
    LLM --- GRD
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
        hit = bool(set(traj.final_locations[:k]) & set(task.gold["files"]))
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
    tokens_in: int
    tokens_out: int
    latency_s: float

class Trajectory(BaseModel):
    run_id: str
    steps: list[Step]
    final_answer: str | None
    final_locations: list[str]   # ranked, max 10: "path" or "path::symbol"
    stop_reason: Literal["done", "budget", "timeout", "error"]

class RunResult(BaseModel):
    run_id: str
    experiment_id: str
    config_hash: str             # reproducibility
    agent: str
    task_id: str
    condition: str               # grep_read | bm25 | embeddings | ast_graph | graph_summaries | codegraph_v1 | codegraph_v1_dedup | multires_v2[-ablation]
    model: str
    index_fresh: bool            # False = staleness experiment
    seed: int
    grades: list[GradeResult]
    cost_usd: float
    total_tokens: int
    n_steps: int
    wall_time_s: float
    index_calls: int             # adoption: how often the agent actually used the index
    first_correct_file_step: int | None
    tokens_to_localization: int | None   # None = not localized (see §1a Outcomes)
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
    models: [claude-haiku-5-5, claude-sonnet-5-5]
    temperature: 0.7         # > 0 so seeds give real variance
conditions:
  grep_read:       { toolset: [grep, read_file] }
  bm25:            { toolset: [search_bm25, read_file] }
  embeddings:      { toolset: [search_embed, read_file], params: { model: bge-m3 } }
  ast_graph:       { toolset: [search_graph, graph_neighbors, read_file] }
  graph_summaries: { toolset: [search_graph, graph_neighbors, module_summary, read_file] }
  codegraph_v1:       { toolset: [codegraph_explore, read_file], params: { version: pinned } }
  codegraph_v1_dedup: { toolset: [codegraph_explore, read_file], params: { version: pinned, env: { CODEGRAPH_EXPLORE_DEDUP: "1" } } }
  multires_v2:
    toolset: [explore_v2, expand, read_file]
    params:
      budget_tokens: 4000        # ceiling B
      lambda: fitted             # early-stop threshold (fitted on dev50)
      beta: fitted               # hub-lift exponent; 0 = plain PPR
      tau: fitted                # per-edge-kind weights
      level_gain: { handle: 0.1, L1: 0.4, L2: 1.0, L3: 0.6 }   # initial, fitted
      rrf_k: 60
      alpha: 0.25                # PPR restart prob; fixed = CodeGraph's value
      dense_model: bge-m3        # same as `embeddings`
      ledger: true
index_freshness: [fresh, stale_k20]
budget: { max_steps: 30, max_tokens: 200000, timeout_s: 600 }
graders: [loc_acc_at_k, mrr, tokens_to_localization, process_metrics]
seeds: [0, 1, 2, 3, 4]
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
│       │   └── indexes/             # one module per variant, same search() contract
│       │       ├── grep_read.py
│       │       ├── bm25.py
│       │       ├── embeddings.py    # pgvector + BGE-M3
│       │       ├── ast_graph.py     # tree-sitter
│       │       ├── graph_summaries.py
│       │       ├── codegraph_v1.py  # thin adapter over pinned upstream CodeGraph MCP (dedup on/off)
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
│           ├── llm_judge.py
│           └── composite.py
├── datasets/coding/post_cutoff.jsonl   # hand-made contamination-check tasks
├── experiments/*.yaml
├── runs/                    # JSONL trajectories (gitignored)
└── tests/                   # unit tests per component + golden-run tests
```

---

## 9. Metrics

- **Primary (localization):** file Acc@k, function Acc@k (k = 1, 5, 10), MRR.
- **Efficiency:** tokens/task, cost/task, tool calls/task, steps-to-first-correct-file, wall time.
- **Cost-at-equal-accuracy:** tokens needed to reach a target Acc@5 — the headline Pareto plot (accuracy vs tokens per variant × model).
- **Index cost:** build time, build tokens, index size — reported amortised per task.
- **Variant F specific:** tokens-to-localization (definition in §1a), recall@budget curve (2k–16k), **early-stop rate** and mean tokens used ÷ B (how often λ stops before the ceiling), handle-expansion rate, ledger hit rate, **ledger re-expansion rate** (agent expands a handle it was told it already had → context loss signal), level mix returned (L1/L2/L3 share).
- **Adoption:** index-call rate per run; runs where the agent never queried the index are flagged and analysed separately.
- **Slices:** every metric broken down by `task_type`, `repo_size`, model, freshness, `paraphrase`, `memorized`, post-cutoff. Slices with < 30 tasks are descriptive only.
- **Reliability:** variance across 5 seeds, 95% bootstrap CI, error/timeout rate.
- **Comparisons:** paired per-task differences (seed-averaged per task); Wilcoxon signed-rank for continuous metrics, McNemar for binary Acc@k.
- **Non-inferiority (H6, H8):** one-sided test on paired Acc@5 difference with margin −2 pp, fixed before any final run.
- **Confirmatory family (Holm-corrected):** H6 vs F0, H6 vs D, H1, H4, H9. Everything else (H2, H3, H5, H7 ablations, slices) is exploratory and labelled as such.

---

## 10. Roadmap (~10 weeks)

| Phase | Deliverable | Exit criteria |
|---|---|---|
| **0. Research (1 wk)** | Read RepoGraph, LocAgent, CodexGraph, SweRank, cAST, LongCodeZip, Agentless; study Inspect AI, mini-swe-agent, CodeGraph SQLite schema | Decide Inspect AI vs own core. Freeze `search()` / `explore_v2` contracts |
| **1. Harness MVP + baselines (2 wks)** | Core, Docker env, mini agent (ranked-answer format), `loc_acc_at_k`, tokens-to-localization, memory-probe gate; `grep_read` + `codegraph_v1` (dedup off/on) on dev50 | Baseline numbers stable across 5 seeds — **v2 work starts only after this** |
| **2. Variants B–E (1–2 wks)** | Implemented behind the same contract; `IndexBuildRecord` logged | Sanity checks pass |
| **3. Variant F core (3 wks)** | Stable IDs + body hashes, levels + token counts, global PageRank, hybrid seeds, whole-graph PPR + hub lift, MCKP with ledger term and λ stop, expand handles, Merkle re-index; fit τ, β, g, λ on dev50 | Runs on dev50; F tests (§12) pass; parameters frozen before Phase 4 |
| **4. Experiments (1 wk)** | Pruned run matrix (§1a) on `test`; F ablations (§13.5); budget sweep; staleness; small vs frontier model | H1–H9 each answered with a test result |
| **5. Analysis & write-up (1 wk)** | Pareto plot, recall@budget curves, ablation table, report; release harness + v2 | Reproducible from config hash |
| **Future work** | L0 LLM summaries, learned edge weights from trajectories, embedding fine-tuning, external agent adapters (Claude Code), repair step + `tests_pass`, lazy reference resolution, second domain | Only if time remains |

---

## 11. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Data contamination (model memorised repo) | ≥ 100 post-cutoff tasks; memory-probe gate flags `memorized` tasks; both reported as slices |
| Prompt bias between conditions | Identical system prompt across conditions; tool descriptions from one template |
| LLM judge drift / bias | Calibrate on ~50 human-labelled samples; report agreement (Cohen's κ) |
| Cost blow-up | Pruned run matrix (§1a), budgets per run, dev50 before full runs |
| Over-engineering | One domain in v1; abstractions only when a second concrete use exists |
| Flaky sandboxes | Pinned Docker images, health checks, retries as Commands |
| Cache leaks responses across seeds → fake variance | Seed in cache key; `llm_cache: off` for experiments; seed-isolation test |
| Agent ignores the index tool | Log `index_calls`; report adoption rate; treat as a finding, not a bug |
| Effect undetectable (too few tasks) | 150–300 benchmark tasks + ≥ 100 post-cutoff × 5 seeds; paired tests; dev50 only for iteration |
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
- **Index contract test:** every variant returns the same `search()` schema on a toy repo.
- **Variant F tests:** selection never exceeds `budget_tokens`; token counts match the tokenizer; raising λ never increases selected tokens; a ledger hit (σ = 1) is emitted as a handle, not content; stable IDs survive a line-shifting edit; global PageRank sums to 1; Merkle re-index touches only changed files; every ledger reference resolves via `expand`; changed content invalidates its ledger entry.

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

### 13.0 Baseline gaps this targets (from source analysis of CodeGraph, Nov 2026)
| CodeGraph today | Where | Variant F |
|---|---|---|
| Budget in **characters**, fixed tiers 13k/18k/24k | `src/mcp/tools.ts:317` | Caller-set **token** budget; a cap, not a target (λ) |
| Budget split **per file first**, ~20 magic constants | `tools.ts:802, 5055` | One global selection over all symbols across files |
| Cross-call dedup **off by default** (`CODEGRAPH_EXPLORE_DEDUP=1`), line-range based, ≥8 lines, 8-call memory | `src/mcp/explore-dedup.ts` | Content-hash ledger, on by default, part of the objective |
| Lexical seeds only (FTS5 prefix + LIKE + fuzzy); paraphrased queries return empty | `src/db/queries.ts:1798`, `tools.ts:4598` | BM25 + dense + exact, RRF-fused |
| RWR only over the lexically gathered subgraph; BFS ignores edge kinds | `tools.ts:4327`, `src/graph/traversal.ts:126` | PPR over the whole graph with `τ_kind × confidence` weights |
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
- **Token count** per unit per level (same tokenizer as the evaluated model).
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

   `τ` per edge kind (calls, extends/implements, imports, references, …); `c(e)` = CodeGraph's stored resolution confidence (0.6–0.95, from edge `metadata`).

   `π_s = α · s0_norm + (1 − α) · Pᵀ π_s`  (iterate to convergence), **α = 0.25 fixed**

   α = restart probability: high α stays near the seeds (precise, misses distant code); low α spreads further (better multi-hop, noisier). Fixed at CodeGraph's value so F vs F0 differences come from whole-graph spread, edge weights and hub lift — not from α. `s0_norm` = seed scores normalised to sum to 1.
3. **Hub correction (lift)** —

   `rel(v) = π_s(v) / π_g(v)^β`, β ∈ [0, 1]

   π_s = personalized PR, π_g = global PR. Demotes symbols that are central to everything (logging, utils, base classes) rather than to this query. β = 0 recovers plain PPR.

### 13.3 Selection — one objective, ledger included
Each unit *u* is skipped or emitted at exactly one level ℓ ∈ {handle, L1, L2, L3}.

**Value:** `v(u, ℓ) = rel(u) × g(ℓ) × (1 − σ(u, ℓ))`
- `g(ℓ)` = level gain (initial guess: handle 0.1, L1 0.4, L2 1.0, L3 0.6).
- `σ(u, ℓ)` = 1 if the agent context already holds this exact content at ≥ ℓ (ledger hit, matched by body hash), else 0. A ledger hit has zero value, so the optimizer emits a handle instead. Changed hash → σ = 0 → re-sent.

**Cost:** `c(u, ℓ)` = precomputed tokens of that unit at that level + one-time file-header tokens for the first unit selected in each file.

**Objective:**

`max Σ_u [ v(u, ℓ_u) − λ · c(u, ℓ_u) ]`  s.t.  `Σ_u c(u, ℓ_u) ≤ B`, one level per unit, containment consistency (a class at L2 already covers its methods; children are not emitted again).

**Solver:** greedy on marginal `Δv / Δc` over level upgrades; **stop when the best ratio < λ or B is reached**. Return the better of the greedy set and the single best item (½-approximation for multiple-choice knapsack).

- **λ is the key new parameter:** B is a ceiling, not a target. Easy queries stop early and spend fewer tokens; CodeGraph always fills its tier.
- Expected shape: seeds → L2 bodies, 1-hop → L1 signatures, 2-hop → handles.
- **Fitted parameters (dev50 only, dev50 excluded from final evaluation):** τ, β, g(ℓ), λ. Report sensitivity for each. α is **fixed** at 0.25 (not fitted), see 13.2.
- **Question-type budget** (optional ablation): "where is X" → 2k, "explain flow" → 8k.

### 13.4 Delivery and ledger safeguards
- Ledger keyed by **agent-context id** (not MCP session — sub-agents have separate contexts).
- Ledger hit → `[seen] path:L10-42 sym=foo#a1b2  (expand: h_a1b2)`.
- **Safeguards:** every reference is expandable via `expand`; body-hash change invalidates the entry; `reset_ledger` tool for clients that compact; re-expansion rate logged as the health metric.
- **Testing H8 needs context loss:** the mini agent never compacts, so the ledger is also evaluated with forced compaction (drop tool outputs older than N steps) to exercise re-expansion.
- Output is plain text: path header + line range + code. Deterministic ordering (for reproducibility, not caching).

### 13.5 Ablations (full set minus dev50, 1 model, 5 seeds)
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
| Global PR goes stale after edits | Incremental recompute on sync; staleness condition covers it |

### 13.8 Out of scope for v2 (Future Work)
L0 LLM summaries · learned edge weights / τ from logged trajectories · embedding fine-tuning on agent usage · question-type classifier · lazy (query-time) reference resolution to cut CodeGraph's resolution-dominated index time (~12 of ~15 min on the Linux kernel) · SCIP-resolved `exact` edges.
