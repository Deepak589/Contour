# Eval Harness — Core Design Plan

> An agent evaluation harness. Primary research question: **for a fixed agent, how do different code-index representations trade off localization accuracy against cost (tokens, tool calls, latency) — and when does structure actually help?**
>
>
> Method contribution: **Variant F — budgeted multi-resolution context delivery (CodeGraph v2)**. Sub-question: *does it reduce tokens-to-localization vs flat retrieval at equal accuracy?* Variants A–E are the baselines (see §13).
>
> Multi-domain support is a design property of the core, not a v1 deliverable.

---

## 1. Goals & Non-Goals

### Goals
- Run **agents × tasks × conditions × seeds** as a reproducible experiment matrix.
- Plug in new **domains, agents, tools, graders** without touching the core engine.
- Capture full **trajectories** (every step, tool call, token, latency) in one schema.
- Report **accuracy + cost + efficiency** with variance (pass@k, mean ± CI).
- First (and only v1) domain: **coding** — issue **localization** as the primary task, with **index variant** (5 levels, see §1a) as the key independent variable.

### Non-Goals (v1)
- Not a feature-rich coding agent.
- Not a UI/dashboard product (CLI + static HTML/CSV reports is enough).
- Not distributed/cluster scheduling (local parallelism first).
- Not a second domain in v1 — tool-calling/SQL moved to Future Work (doesn't serve the research question).
- Not a new indexer product — the contribution is the **controlled comparison**.

---

## 1a. Research Design

### Independent variables
| Axis | Levels |
|---|---|
| **Index variant** | A `grep_read` (baseline) · B `bm25` · C `embeddings` (pgvector + BGE-M3) · D `ast_graph` (tree-sitter: calls / imports / inheritance) · E `graph_summaries` (D + LLM-written module summaries) · **F `multires_v2`** (hybrid seeds → PPR → budgeted L1/L2/L3 selection + session ledger, §13) · **F0 `codegraph_v1`** (unmodified CodeGraph, direct baseline for F) |
| **Token budget** (F only) | 2k · 4k · 8k · 16k per `explore` call |
| **Model** | 1 small/cheap model · 1 frontier model |
| **Index freshness** | `fresh` · `stale_k20` (index built 20 commits before the task commit) |

**Controlled:** identical system prompt, agent loop, step/token budget and tool interface — `search(query) -> [{path, symbol, snippet, score}]` + `read_file`. Only the retrieval backend changes.
**Ablation:** `additive` mode (index tool *plus* grep) run on the dev subset to reflect real-world agent setups.

### Hypotheses
- **H1** Structural indexes (D/E) beat lexical (A/B) mainly on `multi_hop` tasks.
- **H2** On `small` repos, A ≈ best variant — index overhead not worth it.
- **H3** Small models gain more from structure than frontier models.
- **H4** Accuracy degrades with staleness; structural indexes degrade faster than grep.
- **H5** Summaries (E) cut tokens vs D at equal accuracy.
- **H6** F reaches the same file/function Acc@5 as F0 and D with fewer tokens-to-localization.
- **H7** In F, the ledger and multi-resolution selection each contribute measurable savings (ablation, §13.5); expected order: ledger > selection > hybrid seeds — untested.
- **H8** Ledger does not hurt accuracy: re-expansion rate stays low and Acc@k does not drop vs F-without-ledger.

### Datasets
- **Primary:** SWE-bench Lite (localization gold) + Loc-Bench — 150–300 tasks with gold files/functions.
- **Contamination check:** ~30 hand-made tasks on repos/commits after model cutoff (`metadata.created_after_cutoff = true`); results reported separately.
- **Tagging:** every task has `task_type` (single_file | multi_hop), `repo_size` (small | medium | large), `language`.
- **Dev subset:** 50 stratified tasks for iteration; full set only for final runs.

### Outcomes
- **Primary:** file Acc@k, function Acc@k (k = 1, 5, 10), MRR; for F: **tokens-to-localization** and **recall@token-budget**.
- **Secondary:** `tests_pass` — confounded by patch-writing skill, never the headline result.

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
| **YAGNI** | Extract abstractions from 2 real domains; don't pre-design for 10. |
| **Observability by default** | Every step emits a structured event; nothing is "printed". |

---

## 3. Design Patterns (where & why)

| Pattern | Component | Why |
|---|---|---|
| **Strategy** | `Grader`, `AgentAdapter` | Swap scoring method / agent at runtime with same interface. |
| **Adapter** | `AgentAdapter`, `DatasetLoader` | Wrap external agents (Claude Code, OpenHands) and external benchmarks (SWE-bench, τ-bench) into our interfaces. |
| **Registry + Plugin** | `registry.py` | Domains/agents/graders register by name (`@register_grader("tests_pass")`). Config refers by name. Enables Open/Closed. |
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
- **Plugins** — `domains/coding`, `domains/tool_calling`, `agents/*`, `graders/*`. Changes often.
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
# plugins/graders/tests_pass.py
@register("grader", "tests_pass")
class TestsPassGrader:
    name = "tests_pass"
    def score(self, task, traj, state):
        ok = state.data["test_exit_code"] == 0
        return GradeResult(grader=self.name, score=float(ok), passed=ok)
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
    metadata: dict = {}          # task_type (single_file|multi_hop), repo_size, language, created_after_cutoff

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
    stop_reason: Literal["done", "budget", "timeout", "error"]

class RunResult(BaseModel):
    run_id: str
    experiment_id: str
    config_hash: str             # reproducibility
    agent: str
    task_id: str
    condition: str               # grep_read | bm25 | embeddings | ast_graph | graph_summaries
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

class IndexBuildRecord(BaseModel):  # one per (repo, commit, variant) — amortised cost
    repo: str
    commit: str
    variant: str
    build_time_s: float
    build_tokens: int            # > 0 only for graph_summaries
    index_size_mb: float
```

---

## 7. Experiment Config (config-driven, no code changes)

```yaml
# experiments/code_index_variants.yaml
experiment: code_index_variants_v1
dataset:
  loader: swebench_loc
  sources: [czlll/SWE-bench_Lite, czlll/Loc-Bench_V1, datasets/coding/post_cutoff.jsonl]
  subset: dev50              # dev50 | full
agents:
  - name: mini_agent         # primary result
    models: [claude-haiku-5-5, claude-sonnet-5-5]
    temperature: 0.7         # > 0 so seeds give real variance
  - name: claude_code_mcp    # validity check only
conditions:
  grep_read:       { toolset: [grep, read_file] }
  bm25:            { toolset: [search_bm25, read_file] }
  embeddings:      { toolset: [search_embed, read_file] }
  ast_graph:       { toolset: [search_graph, graph_neighbors, read_file] }
  graph_summaries: { toolset: [search_graph, graph_neighbors, module_summary, read_file] }
  codegraph_v1:    { toolset: [codegraph_explore, read_file] }
  multires_v2:     { toolset: [explore_v2, expand, read_file], params: { budget_tokens: 4000, ledger: true } }
index_freshness: [fresh, stale_k20]
budget: { max_steps: 30, max_tokens: 200000, timeout_s: 600 }
graders: [loc_acc_at_k, mrr, process_metrics]
secondary_graders: [tests_pass]
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
│       │   ├── mini_agent.py        # ~150 lines, controlled baseline
│       │   └── claude_code.py       # adapter, index via MCP
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
│       │       ├── codegraph_v1.py  # thin adapter over upstream CodeGraph MCP
│       │       └── multires_v2/     # Variant F — standalone service over CodeGraph SQLite
│       │           ├── levels.py    # L1 skeleton / L2 cAST chunks / L3 line ranges + token counts
│       │           ├── merkle.py    # incremental re-index
│       │           ├── seeds.py     # BM25 + dense, RRF fusion
│       │           ├── spread.py    # personalized PageRank, typed + confidence-weighted edges
│       │           ├── select.py    # greedy multiple-choice knapsack
│       │           ├── ledger.py    # per-session content-hash ledger + handles
│       │           └── server.py    # MCP: explore_v2, expand
│       └── graders/
│           ├── loc_acc_at_k.py      # primary
│           ├── mrr.py               # primary
│           ├── tests_pass.py        # secondary
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
- **Secondary (outcome):** pass@1 via `tests_pass`; judge score kept separate, never averaged with deterministic scores.
- **Efficiency:** tokens/task, cost/task, tool calls/task, steps-to-first-correct-file, wall time.
- **Cost-at-equal-accuracy:** tokens needed to reach a target Acc@5 — the headline Pareto plot (accuracy vs tokens per variant × model).
- **Index cost:** build time, build tokens, index size — reported amortised per task.
- **Variant F specific:** tokens-to-localization (tokens spent before gold file/function first appears), recall@budget curve (2k–16k), handle-expansion rate, ledger hit rate, **ledger re-expansion rate** (agent expands a handle it was told it already had → context loss signal), level mix returned (L1/L2/L3 share).
- **Adoption:** index-call rate per run; runs where the agent never queried the index are flagged and analysed separately.
- **Slices:** every metric broken down by `task_type`, `repo_size`, model, freshness.
- **Reliability:** variance across 5 seeds, 95% bootstrap CI, error/timeout rate.
- **Comparisons:** paired per-task differences vs `grep_read`; Wilcoxon signed-rank for continuous metrics, McNemar for binary Acc@k; Holm correction across the 4 comparisons.

---

## 10. Roadmap (~10 weeks)

| Phase | Deliverable | Exit criteria |
|---|---|---|
| **0. Research (1 wk)** | Read RepoGraph, LocAgent, CodexGraph, SweRank, cAST, LongCodeZip, Agentless; study Inspect AI, mini-swe-agent, CodeGraph SQLite schema | Decide Inspect AI vs own core. Freeze `search()` / `explore_v2` contracts |
| **1. Harness MVP + baselines (2 wks)** | Core, Docker env, mini agent, `loc_acc_at_k`, tokens-to-localization; `grep_read` + `codegraph_v1` on dev50 | Baseline numbers stable across 5 seeds — **v2 work starts only after this** |
| **2. Variants B–E (1–2 wks)** | Implemented behind the same contract; `IndexBuildRecord` logged | Sanity checks pass |
| **3. Variant F core (3 wks)** | Levels L1–L3, hybrid seeds, PPR, greedy selection, ledger with expand handles, Merkle re-index | Runs on dev50; ledger safeguards tests pass |
| **4. Experiments (1 wk)** | Full runs; F ablations (§13.5); budget sweep; staleness; small vs frontier model | H1–H8 each answered with a test result |
| **5. Analysis & write-up (1 wk)** | Pareto plot, recall@budget curves, ablation table, report; release harness + v2 | Reproducible from config hash |
| **Future work** | L0 LLM summaries, learned edge weights from trajectories, embedding fine-tuning, external agent adapters, second domain | Only if time remains |

---

## 11. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Data contamination (model memorised repo) | Use repos/commits after model cutoff; flag in `metadata` |
| Confounded results via external agents' own retrieval | Mini agent is primary result; external agents = validity check |
| Prompt bias between conditions | Identical system prompt across conditions; only toolset differs |
| LLM judge drift / bias | Calibrate on ~50 human-labelled samples; report agreement (Cohen's κ) |
| Cost blow-up | Budgets per run, caching proxy, small dev subset before full runs |
| Over-engineering | Extract abstractions only after 2 concrete domains (YAGNI) |
| Flaky sandboxes | Pinned Docker images, health checks, retries as Commands |
| Cache leaks responses across seeds → fake variance | Seed in cache key; `llm_cache: off` for experiments; seed-isolation test |
| Agent ignores the index tool | Log `index_calls`; report adoption rate; treat as a finding, not a bug |
| Effect undetectable (too few tasks) | 150–300 benchmark tasks × 5 seeds; paired tests; dev50 only for iteration |
| Unfair comparison across variants | Same tool interface + budget; only backend changes; additive mode as ablation |
| Ledger references code the agent no longer has (context compaction, sub-agents share session id) | Every ledger reference carries an `expand` handle; never assume persistence; ledger scoped per agent-context id, not per session; measure re-expansion rate; `ledger: false` ablation |
| Knapsack value function is arbitrary | Define utility explicitly (§13.3); calibrate weights on dev50 only; report sensitivity |
| Name-matched edges are wrong (dynamic languages) | Edge `confidence`: `exact` (SCIP/LSP-resolved) vs `name_match`; PPR down-weights `name_match` |
| Agent ignores handles / never calls `expand` | Tool description iteration on dev subset; log expansion rate; treat non-use as a finding |
| v2 scope creep | Summaries and learned weights are Future Work; v2 = levels + selection + ledger only |

---

## 12. Testing Strategy

- **Unit:** each grader, tool decorator, builder matrix expansion.
- **Contract tests:** every registered plugin must satisfy its Protocol (auto-run over registry).
- **Golden-run test:** a fake deterministic agent on a toy task → asserts the exact `RunResult`.
- **Replay test:** re-run in `replay` mode → identical trajectory hash.
- **Seed-isolation test:** two seeds in `record` mode must never share a cached response.
- **Index contract test:** every variant returns the same `search()` schema on a toy repo.
- **Variant F tests:** selection never exceeds `budget_tokens`; token counts match the tokenizer; Merkle re-index touches only changed files; every ledger reference resolves via `expand`; changed content invalidates its ledger entry.

---

## 13. Variant F — CodeGraph v2: Budgeted Multi-Resolution Context Delivery

Built as a **standalone MCP service reading CodeGraph's existing SQLite index** (MIT-licensed upstream) — no changes to CodeGraph core until savings are proven in the harness.

```
INDEX (offline, incremental)        RETRIEVE (per call)                 DELIVER (per agent context)
L1 file skeletons      ┐ Merkle     hybrid seeds (BM25 + dense, RRF)    ledger of content hashes
L2 AST chunks (cAST)   │ hashes     → personalized PageRank             → unchanged = 1-line ref + handle
L3 line ranges + toks ─┘            → greedy budgeted level selection   → compact text, no JSON wrapping
typed edges + confidence
```

### 13.1 Index levels
| Level | Content | Built from |
|---|---|---|
| L1 | File skeleton: signatures, types, docstrings, no bodies | tree-sitter |
| L2 | Symbol bodies split along the AST (cAST: split large nodes, merge small siblings under a size cap) | tree-sitter |
| L3 | Exact line ranges | source |
| L0 *(future)* | Module/dir summaries, bottom-up | small local LLM, optional |

Every unit stores a precomputed token count. Files and dirs are hashed into a Merkle tree; on change only affected units (and, later, L0 ancestors) are rebuilt. This also produces the `stale_k20` condition cheaply.

### 13.2 Retrieval
1. **Seeds:** BM25 over split identifiers + signatures + docstrings; dense search over signatures (local embedding model to stay offline); fuse with Reciprocal Rank Fusion.
2. **Spread:** personalized PageRank from seeds; edge weight = `w_type × w_conf` (`calls`, `imports`, `inherits`, `references`; `exact` > `name_match`).
3. **Select:** see 13.3.

### 13.3 Selection — multiple-choice knapsack (greedy)
- Each candidate symbol *s* can be emitted at one level ℓ ∈ {handle, L1, L2, L3} or skipped.
- Value: `v(s, ℓ) = rel(s) × g(ℓ)` where `rel(s)` = normalised PPR score and `g(ℓ)` = level gain (initial guess: handle 0.1, L1 0.4, L2 1.0, L3 0.6 — **calibrated on dev50 only**).
- Cost: `c(s, ℓ)` = token count of that unit.
- Greedy: repeatedly take the upgrade with the highest marginal `Δv / Δc` until `budget_tokens` is reached.
- Expected shape: seeds → L2 bodies, 1-hop → L1 signatures, 2-hop → handles.
- **Question-type budget** (optional ablation): "where is X" → 2k, "explain flow" → 8k.

### 13.4 Delivery and ledger
- Ledger keyed by **agent-context id** (not MCP session — sub-agents have separate contexts).
- Unit already sent and unchanged → `[seen] path:L10-42 sym=foo#a1b2  (expand: h_a1b2)`.
- **Safeguards:** every reference is expandable; content hash change invalidates the entry; `reset_ledger` tool exposed for clients that compact; re-expansion rate logged as the health metric.
- Output is plain text: path header + line range + code. Deterministic ordering (for reproducibility, not caching — prefix caching gains from intra-result ordering are negligible).

### 13.5 Ablations (run on full set, 1 model, 5 seeds)
| Config | Levels | Selection | Ledger | Hybrid seeds |
|---|---|---|---|---|
| F0 `codegraph_v1` | — | — | — | — |
| F-full | ✓ | ✓ | ✓ | ✓ |
| F − ledger | ✓ | ✓ | ✗ | ✓ |
| F − selection (all L2, top-k) | ✓ | ✗ | ✓ | ✓ |
| F − levels (L2 only) | ✗ | ✓ | ✓ | ✓ |
| F − hybrid (BM25 only) | ✓ | ✓ | ✓ | ✗ |

Plus budget sweep {2k, 4k, 8k, 16k} on F-full → recall@budget curve.

### 13.6 Benchmarks for F
- SWE-bench Lite / Loc-Bench localization (main, same as A–E).
- RepoQA (code QA, optional).
- CoIR for the seed/search component in isolation (optional).

### 13.7 Out of scope for v2 (Future Work)
L0 LLM summaries · learned edge weights from logged trajectories · embedding fine-tuning on agent usage · question-type classifier.

