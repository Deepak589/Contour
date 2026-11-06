"""S0-5 schema spike: read CodeGraph's codegraph.db from Python, edge metadata, PPR latency.

Read-only (sqlite URI mode=ro&immutable=1); checks the DB SHA-256 is unchanged afterwards.
Writes counts and timings only to runs/s0-5/<name>.json (gitignored).

    uv run python scripts/s0_5_schema.py <tree>/.codegraph/codegraph.db [--queries 100]
"""

import argparse
import hashlib
import json
import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

ALPHA = 0.25  # design §13.2, fixed
TOL = 1e-6  # L1 change between iterations
MAX_ITER = 200
SEEDS_PER_QUERY = 50  # RRF top 50 (design §13.2)
RRF_K = 60
# Timing uses neutral weights: every τ = 1, ρ = 0.5, β = 0.5.
# Fitted values change iteration counts only slightly.
RHO, BETA, TOP_K = 0.5, 0.5, 200


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def connect(db: Path) -> sqlite3.Connection:
    # immutable=1: no -shm/-wal/lock files, so it works on a read-only bind mount
    # (S0-4 frozen route).
    return sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)


def edge_report(con: sqlite3.Connection) -> dict[str, Any]:
    rows = con.execute(
        "SELECT kind, json_extract(metadata, '$.confidence'), "
        "json_extract(metadata, '$.resolvedBy'), count(*) FROM edges GROUP BY 1, 2, 3"
    ).fetchall()
    by_kind: dict[str, Counter[str]] = {}
    by_resolver: Counter[str] = Counter()
    for kind, conf, resolver, n in rows:
        by_kind.setdefault(kind, Counter())["absent" if conf is None else str(conf)] += n
        by_resolver[resolver or "none"] += n
    keys = [
        k
        for (k,) in con.execute(
            "SELECT DISTINCT j.key FROM edges, json_each(edges.metadata) j "
            "WHERE edges.metadata IS NOT NULL"
        )
    ]
    return {
        "confidence_by_kind": {k: dict(v.most_common()) for k, v in sorted(by_kind.items())},
        "resolved_by": dict(by_resolver.most_common()),
        "metadata_keys": sorted(keys),
    }


def load_graph(con: sqlite3.Connection) -> tuple[int, np.ndarray, np.ndarray, np.ndarray]:
    """Node count and the transition as (src, dst, prob) arrays, forward + ρ-weighted reverse."""
    ids = [r[0] for r in con.execute("SELECT id FROM nodes")]
    index = {nid: i for i, nid in enumerate(ids)}
    rows = con.execute(
        "SELECT source, target, COALESCE(json_extract(metadata, '$.confidence'), 1) FROM edges"
    ).fetchall()
    keep = [(index[s], index[t], c) for s, t, c in rows if s in index and t in index]
    src = np.fromiter((k[0] for k in keep), dtype=np.int32, count=len(keep))
    dst = np.fromiter((k[1] for k in keep), dtype=np.int32, count=len(keep))
    w = np.fromiter((k[2] for k in keep), dtype=np.float64, count=len(keep))  # τ = 1 for every kind
    src, dst = np.concatenate([src, dst]), np.concatenate([dst, src])
    w = np.concatenate([w, RHO * w])
    n = len(ids)
    out = np.bincount(src, weights=w, minlength=n)
    return n, src, dst, w / out[src]


def ppr(
    n: int, src: np.ndarray, dst: np.ndarray, p: np.ndarray, s: np.ndarray, dangling: np.ndarray
) -> tuple[np.ndarray, int]:
    """π = α·s + (1−α)·Pᵀπ; mass on nodes with no out-weight returns to s, so π sums to 1."""
    pi = s.copy()
    for it in range(1, MAX_ITER + 1):
        nxt = np.bincount(dst, weights=p * pi[src], minlength=n)
        nxt = ALPHA * s + (1 - ALPHA) * (nxt + pi[dangling].sum() * s)
        if np.abs(nxt - pi).sum() < TOL:
            return nxt, it
        pi = nxt
    return pi, MAX_ITER


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("db", type=Path)
    ap.add_argument("--queries", type=int, default=100)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    parent = args.db.parent
    name = parent.parent.name if parent.name == ".codegraph" else parent.name
    before = sha256(args.db)

    t0 = time.perf_counter()
    con = connect(args.db)
    nodes = con.execute("SELECT count(*) FROM nodes").fetchone()[0]
    edges = con.execute("SELECT count(*) FROM edges").fetchone()[0]
    report = edge_report(con)
    t1 = time.perf_counter()
    n, src, dst, p = load_graph(con)
    dangling = np.setdiff1d(np.arange(n), np.unique(src))
    t2 = time.perf_counter()
    pi_g, g_iters = ppr(n, src, dst, p, np.full(n, 1 / n), dangling)  # global PageRank
    hub = np.maximum(n * pi_g, 1.0) ** BETA
    t3 = time.perf_counter()
    con.close()

    rng = np.random.default_rng(0)
    times, iters, sums = [], [], []
    for _ in range(args.queries):
        q0 = time.perf_counter()
        seeds = rng.choice(n, SEEDS_PER_QUERY, replace=False)
        s = np.zeros(n)
        s[seeds] = 1 / (RRF_K + np.arange(1, SEEDS_PER_QUERY + 1))
        s /= s.sum()
        pi, it = ppr(n, src, dst, p, s, dangling)
        lift = pi / hub
        top = np.argpartition(lift, -TOP_K)[-TOP_K:]
        _ = top[np.argsort(lift[top])[::-1]]
        times.append((time.perf_counter() - q0) * 1000)
        iters.append(it)
        sums.append(float(pi.sum()))

    after = sha256(args.db)
    ms = np.array(times)
    result: dict[str, Any] = {
        "name": name,
        "nodes": nodes,
        "edges": edges,
        "transition_entries": int(len(p)),
        "dangling_nodes": int(len(dangling)),
        "db_mb": round(args.db.stat().st_size / 1e6, 1),
        "db_sha256_unchanged": before == after,
        "load_s": {"counts_and_metadata": round(t1 - t0, 2), "graph_arrays": round(t2 - t1, 2)},
        "global_pagerank": {"s": round(t3 - t2, 3), "iterations": g_iters},
        "ppr_query_ms": {
            "n": len(ms),
            "p50": round(float(np.percentile(ms, 50)), 1),
            "p95": round(float(np.percentile(ms, 95)), 1),
            "max": round(float(ms.max()), 1),
        },
        "ppr_iterations": {"min": min(iters), "max": max(iters)},
        "pi_sum_max_error": float(max(abs(x - 1) for x in sums)),
        "params": {"alpha": ALPHA, "tol": TOL, "rho": RHO, "beta": BETA, "tau": "all 1"},
        **report,
    }
    out = args.out or Path("runs/s0-5") / f"{name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    brief = {k: v for k, v in result.items() if k not in ("confidence_by_kind", "resolved_by")}
    print(json.dumps(brief, indent=2))
    return 0 if before == after else 1


if __name__ == "__main__":
    raise SystemExit(main())
