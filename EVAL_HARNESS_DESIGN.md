# Eval Harness — Core Design Plan

> A multi-domain, multi-agent evaluation harness. First target: **does a code index make coding agents more accurate and cheaper than plain grep/read?**

---

## 1. Goals & Non-Goals

### Goals
- Run **agents × tasks × conditions × seeds** as a reproducible experiment matrix.
- Plug in new **domains, agents, tools, graders** without touching the core engine.
- Capture full **trajectories** (every step, tool call, token, latency) in one schema.
- Report **accuracy + cost + efficiency** with variance (pass@k, mean ± CI).
- First domain: **coding** (repo navigation / bug fixing) with index on/off as the key variable.

### Non-Goals (v1)
- Not a feature-rich coding agent.
- Not a UI/dashboard product (CLI + static HTML/CSV reports is enough).
- Not distributed/cluster scheduling (local parallelism first).

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
| **Proxy (caching)** | `CachedLLMClient` | Same prompt+params → cached response; cuts cost on re-runs and makes runs replayable. |
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
    metadata: dict = {}          # difficulty, tags, created_after_cutoff

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
    condition: str               # "index_on" / "index_off"
    seed: int
    grades: list[GradeResult]
    cost_usd: float
    total_tokens: int
    n_steps: int
    wall_time_s: float
```

---

## 7. Experiment Config (config-driven, no code changes)

```yaml
# experiments/code_index_ab.yaml
experiment: code_index_ab_v1
dataset:
  loader: jsonl
  source: datasets/coding/v1.jsonl
agents:
  - name: mini_agent
    model: claude-sonnet-5-5
    temperature: 0.0
  - name: claude_code_mcp
conditions:
  index_off: { toolset: [grep, read_file, run_tests] }
  index_on:  { toolset: [grep, read_file, run_tests, code_index] }
graders: [tests_pass, gold_file_found, process_metrics, llm_judge]
seeds: [0, 1, 2]
runner:
  workers: 4
  retry: 2
  cache_llm: true
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
│       │   ├── coding/              # env, tools, dataset loader
│       │   └── tool_calling/        # 2nd domain (phase 3)
│       ├── tools/
│       │   ├── decorators.py        # timing, budget, logging
│       │   └── code_index_mcp.py
│       └── graders/
│           ├── tests_pass.py
│           ├── gold_file_found.py
│           ├── process_metrics.py
│           ├── llm_judge.py
│           └── composite.py
├── datasets/coding/v1.jsonl
├── experiments/*.yaml
├── runs/                    # JSONL trajectories (gitignored)
└── tests/                   # unit tests per component + golden-run tests
```

---

## 9. Metrics

- **Outcome:** pass@1, pass@k, gold-file recall, judge score (separate, never averaged with deterministic scores).
- **Efficiency:** tokens/task, cost/task, steps/task, time-to-first-correct-file, wall time.
- **Reliability:** variance across seeds, 95% bootstrap CI, error/timeout rate.
- **A/B:** paired difference per task (index_on − index_off), with a paired significance test.
- **Normalisation:** report per domain; never mix domain scores into one number.

---

## 10. Roadmap

| Phase | Deliverable | Exit criteria |
|---|---|---|
| **0. Research (1 wk)** | Study SWE-bench harness, Inspect AI, Terminal-Bench, τ-bench, mini-swe-agent | Decide: build on Inspect AI vs own core |
| **1. Core MVP (2 wks)** | Schemas, registry, runner, Docker env, mini agent, JSONL logs, `tests_pass` grader | 1 task runs end-to-end reproducibly |
| **2. Coding domain (2 wks)** | 20–30 hand-made tasks on 2–3 repos, baseline vs index A/B, report | Stable numbers across 3 seeds |
| **3. Second domain (1–2 wks)** | Tool-calling or SQL domain | No core code changed to add it (Open/Closed check) |
| **4. External agents (1 wk)** | Claude Code / OpenHands adapters, index via MCP | Same experiment YAML runs all agents |
| **5. Hardening** | LLM cache, resume/retry, judge calibration vs human labels, CI | Re-run = identical results from cache |

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

---

## 12. Testing Strategy

- **Unit:** each grader, tool decorator, builder matrix expansion.
- **Contract tests:** every registered plugin must satisfy its Protocol (auto-run over registry).
- **Golden-run test:** a fake deterministic agent on a toy task → asserts the exact `RunResult`.
- **Replay test:** re-run from LLM cache → identical trajectory hash.
