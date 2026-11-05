"""S0-3 dataset census: pool, gold, tags, post-cutoff supply, split, staleness, licenses.

Writes counts only to runs/s0-3/census.json (gitignored). No issue text, patch or hint is written.

    uv run python scripts/s0_3_census.py                    # offline parts (steps 2-6)
    uv run python scripts/s0_3_census.py --licenses         # + GitHub license per repo (gh login)
    uv run python scripts/s0_3_census.py --stale-sample 10  # + bare clones under EVALH_CACHE
    uv run python scripts/s0_3_census.py --hand-check 10    # print tags of N random tasks
    uv run python scripts/s0_3_census.py --post-cutoff-supply 20  # GitHub search counts
"""

import argparse
import json
import os
import random
import re
import subprocess
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from datasets import load_dataset

# Sonnet 5.5 and Haiku 5.5: training data cutoff "Jun 2026"
# (platform.claude.com/docs/en/models/overview, read 2026-11-05). End of month, to be safe.
CUTOFF = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)

# Load order matters: on a duplicate instance_id the first source wins (czlll rows carry gold).
SOURCES = {
    "swebench_lite": ("czlll/SWE-bench_Lite", "test"),
    "locbench_v1": ("czlll/Loc-Bench_V1", "test"),
    "swebench_live": ("SWE-bench-Live/SWE-bench-Live", "full"),
}

DEV_TARGET, DEV_TOL = 150, 5
DEV_MAX_REPO_TASKS = 25  # no single repo dominates dev150
TEST_BENCHMARK_NEEDED = 500
POST_CUTOFF_NEEDED = 100
STALE_K = 20

HUNK_SYMBOL = re.compile(r"^@@ [^@]* @@\s*(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*)", re.M)


@dataclass
class Task:
    id: str
    source: str
    repo: str  # lower-case owner/name
    base_commit: str
    created_at: datetime
    problem: str
    touched: list[str]
    gold_files: list[str]  # pre-existing .py files the fix modifies
    gold_symbols: list[str]  # identifier names of gold functions/classes
    symbols_exact: bool  # True: from edit_functions; False: from diff hunk headers (approximate)
    edit_function_files: list[str] | None
    tags: dict[str, Any] = field(default_factory=dict)


def to_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)  # Live: naive, assumed UTC
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value / 1000, tz=UTC)  # Loc-Bench: epoch milliseconds
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)


def patch_blocks(patch: str) -> list[tuple[str, bool, str]]:
    """(path, existed_at_base, block text) per file in a unified diff."""
    out = []
    for block in re.split(r"^diff --git ", patch, flags=re.M)[1:]:
        m = re.match(r"a/(\S+) b/(\S+)", block)
        if not m:
            continue
        head = block.split("\n@@", 1)[0]
        new_file = "new file mode" in head or re.search(r"^--- /dev/null$", head, re.M) is not None
        out.append((m.group(1), not new_file, block))
    return out


def symbols_from_edit_functions(entries: list[str]) -> list[str]:
    names: set[str] = set()
    for e in entries:
        qual = e.split(":", 1)[1] if ":" in e else ""
        names.update(n for n in qual.split(".") if n)
    return sorted(names)


def load_tasks() -> tuple[list[Task], dict[str, Any]]:
    stats: dict[str, Any] = {"raw_rows": {}, "duplicates_dropped": 0, "not_python": Counter()}
    stats["strict_python_only"] = Counter()
    tasks: dict[str, Task] = {}
    for source, (name, split) in SOURCES.items():
        ds = load_dataset(name, split=split)
        stats["raw_rows"][source] = ds.num_rows
        for r in ds:
            blocks = patch_blocks(r["patch"])
            touched = [p for p, _, _ in blocks]
            gold = [p for p, existed, _ in blocks if existed and p.endswith(".py")]
            if not gold:
                stats["not_python"][source] += 1
                continue
            if all(p.endswith(".py") for p in touched):
                stats["strict_python_only"][source] += 1
            ef = r.get("edit_functions")
            if ef is not None:
                symbols, exact = symbols_from_edit_functions(ef), True
                ef_files: list[str] | None = sorted({e.split(":", 1)[0] for e in ef})
            else:
                found = {
                    m.group(1)
                    for p, existed, b in blocks
                    if existed and p.endswith(".py")
                    for m in HUNK_SYMBOL.finditer(b)
                }
                symbols, exact, ef_files = sorted(found), False, None
            if r["instance_id"] in tasks:
                stats["duplicates_dropped"] += 1
                continue
            tasks[r["instance_id"]] = Task(
                id=r["instance_id"],
                source=source,
                repo=r["repo"].lower(),
                base_commit=r["base_commit"],
                created_at=to_utc(r["created_at"]),
                problem=r["problem_statement"] or "",
                touched=touched,
                gold_files=sorted(set(gold)),
                gold_symbols=symbols,
                symbols_exact=exact,
                edit_function_files=ef_files,
            )
    return list(tasks.values()), stats


def dotted_module(path: str) -> str | None:
    p = path[:-3]
    if p.endswith("/__init__"):
        p = p[: -len("/__init__")]
    for prefix in ("src/", "lib/"):
        if p.startswith(prefix):
            p = p[len(prefix) :]
    return p.replace("/", ".") if "/" in p else None  # single names like "utils" are too generic


def tag(t: Task) -> None:
    text = t.problem
    t.tags["multi_hop"] = len(t.gold_files) >= 2
    path_hits = []
    for f in t.gold_files:
        forms = {f, f.removeprefix("src/").removeprefix("lib/")}
        mod = dotted_module(f)
        if mod:
            forms.add(mod)
        path_hits += [x for x in forms if x in text]
    t.tags["explicit_path"] = bool(path_hits)
    t.tags["path_hits"] = sorted(set(path_hits))
    # Dunders and very short names ("of", "run") match issue text by chance, so they don't count.
    names = [
        s for s in t.gold_symbols if len(s) >= 4 and not (s.startswith("__") and s.endswith("__"))
    ]
    if names:
        hits = [s for s in names if re.search(rf"(?<!\w){re.escape(s)}(?!\w)", text)]
        t.tags["paraphrase"] = not hits
        t.tags["symbol_hits"] = hits
    else:
        t.tags["paraphrase"] = None  # no symbol known (module-level edit, or no hunk header)
        t.tags["symbol_hits"] = []
    t.tags["post_cutoff"] = t.created_at > CUTOFF


def gold_agreement(tasks: list[Task]) -> dict[str, Any]:
    checked = [t for t in tasks if t.edit_function_files is not None]
    agree = [t for t in checked if set(t.edit_function_files or []) == set(t.gold_files)]
    subset = [t for t in checked if set(t.edit_function_files or []) < set(t.gold_files)]
    other = [t for t in checked if t not in agree and t not in subset]
    return {
        "checked": len(checked),
        "equal": len(agree),
        "equal_rate": round(len(agree) / len(checked), 4) if checked else None,
        "edit_functions_strict_subset": len(subset),  # patch also touches .py files w/o functions
        "other_mismatch": len(other),
        "other_mismatch_ids": sorted(t.id for t in other)[:50],
    }


def shares(tasks: list[Task]) -> dict[str, float]:
    n = len(tasks)
    src = Counter(t.source for t in tasks)
    out = {f"source:{s}": round(c / n, 3) for s, c in sorted(src.items())}
    out["multi_hop"] = round(sum(t.tags["multi_hop"] for t in tasks) / n, 3)
    return out


def split_feasibility(tasks: list[Task], seeds: int = 500) -> dict[str, Any]:
    pool = [t for t in tasks if not t.tags["post_cutoff"]]
    by_repo: dict[str, list[Task]] = defaultdict(list)
    for t in pool:
        by_repo[t.repo].append(t)
    target = shares(pool)
    best: tuple[float, int, list[str]] | None = None
    for seed in range(seeds):
        rng = random.Random(seed)
        repos = sorted(r for r, ts in by_repo.items() if len(ts) <= DEV_MAX_REPO_TASKS)
        rng.shuffle(repos)
        chosen: list[str] = []
        n = 0
        for r in repos:
            k = len(by_repo[r])
            if n + k > DEV_TARGET + DEV_TOL:
                continue
            chosen.append(r)
            n += k
            if n >= DEV_TARGET - DEV_TOL:
                break
        if not DEV_TARGET - DEV_TOL <= n <= DEV_TARGET + DEV_TOL:
            continue
        got = shares([t for r in chosen for t in by_repo[r]])
        dist = sum(abs(got.get(k, 0.0) - target[k]) for k in target)
        if best is None or dist < best[0]:
            best = (dist, seed, chosen)
    if best is None:
        return {"feasible": False}
    dist, seed, chosen = best
    dev = [t for r in chosen for t in by_repo[r]]
    test = [t for t in pool if t.repo not in set(chosen)]
    test_repo_counts = Counter(t.repo for t in test)
    top = test_repo_counts.most_common(5)
    return {
        "feasible": len(test) >= TEST_BENCHMARK_NEEDED,
        "seed": seed,
        "dev_tasks": len(dev),
        "dev_repos": len(chosen),
        "dev_shares": shares(dev),
        "pool_shares": target,
        "share_distance": round(dist, 3),
        "test_pool_tasks": len(test),
        "test_pool_repos": len(test_repo_counts),
        "test_top_repos": [(r, c, round(c / len(test), 3)) for r, c in top],
        "test_ids": sorted(t.id for t in test),
    }


def git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def stale_sample(tasks: list[Task], test_ids: set[str], n_repos: int) -> dict[str, Any]:
    cache = Path(os.environ.get("EVALH_CACHE", Path.home() / "evalh-cache")) / "repos"
    cache.mkdir(parents=True, exist_ok=True)
    test = [t for t in tasks if t.id in test_ids]
    counts = Counter(t.repo for t in test)
    ranked = [r for r, _ in counts.most_common()]
    rng = random.Random(0)
    rest = [r for r in ranked[3:] if counts[r] >= 5]
    sample = ranked[:3] + rng.sample(rest, min(n_repos - 3, len(rest)))
    per_repo: dict[str, dict[str, int]] = {}
    for repo in sample:
        bare = cache / (repo.replace("/", "__") + ".git")
        if not bare.exists():
            url = f"https://github.com/{repo}.git"
            res = git("clone", "--bare", "--filter=blob:none", "--quiet", url, str(bare))
            if res.returncode != 0:
                per_repo[repo] = {"clone_failed": 1}
                continue
        c: Counter[str] = Counter()
        for t in (t for t in test if t.repo == repo):
            if git("cat-file", "-e", f"{t.base_commit}^{{commit}}", cwd=bare).returncode != 0:
                c["base_missing"] += 1
                continue
            diff = git("diff", "--name-only", f"{t.base_commit}~{STALE_K}", t.base_commit, cwd=bare)
            if diff.returncode != 0:
                c["history_too_short"] += 1
                continue
            changed = set(diff.stdout.split())
            c["eligible" if changed & set(t.gold_files) else "not_eligible"] += 1
        per_repo[repo] = dict(c)
    tot: Counter[str] = Counter()
    for v in per_repo.values():
        tot.update(v)
    checked = tot["eligible"] + tot["not_eligible"]
    rate = tot["eligible"] / checked if checked else 0.0
    return {
        "k": STALE_K,
        "repos": per_repo,
        "totals": dict(tot),
        "eligible_rate": round(rate, 3),
        "extrapolated_eligible_in_test_pool": round(rate * len(test)),
    }


def repo_licenses(repos: list[str]) -> dict[str, Any]:
    def one(repo: str) -> tuple[str, str]:
        res = subprocess.run(
            ["gh", "api", f"repos/{repo}", "--jq", '.license.spdx_id // "NONE"'],
            capture_output=True,
            text=True,
            check=False,
        )
        return repo, res.stdout.strip() if res.returncode == 0 else "LOOKUP_FAILED"

    with ThreadPoolExecutor(max_workers=8) as ex:
        found = dict(ex.map(one, repos))
    return {"by_spdx": dict(Counter(found.values()).most_common()), "per_repo": found}


def post_cutoff_supply(tasks: list[Task], n_repos: int) -> dict[str, Any]:
    """Upper bound for option (a): merged PRs linked to an issue, merged after the cutoff.

    Search API counts only; no PR content is fetched. Language and source-only filters are not
    applied, so the usable share is lower (estimate it on a sample before committing to (a)).
    """
    since = (CUTOFF + timedelta(seconds=1)).date().isoformat()
    repos = [r for r, _ in Counter(t.repo for t in tasks).most_common(n_repos)]
    found: dict[str, int | None] = {}
    for repo in repos:
        q = f"repo:{repo} is:pr is:merged merged:>={since} linked:issue"
        res = subprocess.run(
            ["gh", "api", "-X", "GET", "search/issues", "-f", f"q={q}", "--jq", ".total_count"],
            capture_output=True,
            text=True,
            check=False,
        )
        found[repo] = int(res.stdout.strip()) if res.returncode == 0 else None
        time.sleep(2.5)  # search API: 30 requests per minute
    known = [v for v in found.values() if v is not None]
    return {
        "merged_since": since,
        "per_repo": found,
        "total": sum(known),
        "repos_checked": len(known),
    }


def hand_check(tasks: list[Task], n: int) -> None:
    for t in random.Random(1).sample(tasks, n):
        print(f"{t.id} [{t.source}] gold_files={t.gold_files}")
        print(f"   symbols({'exact' if t.symbols_exact else 'hunk'})={t.gold_symbols[:8]}")
        keys = ("multi_hop", "explicit_path", "path_hits", "paraphrase", "symbol_hits")
        print("  ", {k: t.tags[k] for k in keys})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--licenses", action="store_true")
    ap.add_argument("--stale-sample", type=int, default=0)
    ap.add_argument("--hand-check", type=int, default=0)
    ap.add_argument("--post-cutoff-supply", type=int, default=0, metavar="N_REPOS")
    ap.add_argument("--out", type=Path, default=Path("runs/s0-3/census.json"))
    args = ap.parse_args()

    tasks, stats = load_tasks()
    for t in tasks:
        tag(t)

    per_source: dict[str, dict[str, Any]] = {}
    for s in SOURCES:
        ts = [t for t in tasks if t.source == s]
        dates = sorted(t.created_at for t in ts)
        per_source[s] = {
            "raw_rows": stats["raw_rows"][s],
            "python_tasks": len(ts),
            "not_python": stats["not_python"][s],
            "strict_python_only_patch": stats["strict_python_only"][s],
            "repos": len({t.repo for t in ts}),
            "created_min": dates[0].date().isoformat(),
            "created_max": dates[-1].date().isoformat(),
            "multi_hop": sum(t.tags["multi_hop"] for t in ts),
            "explicit_path": sum(t.tags["explicit_path"] for t in ts),
            "paraphrase": sum(t.tags["paraphrase"] is True for t in ts),
            "paraphrase_unknown": sum(t.tags["paraphrase"] is None for t in ts),
            "post_cutoff": sum(t.tags["post_cutoff"] for t in ts),
            "symbols_exact": all(t.symbols_exact for t in ts),
        }

    split = split_feasibility(tasks)
    result: dict[str, Any] = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "cutoff": CUTOFF.isoformat(),
        "duplicates_dropped": stats["duplicates_dropped"],
        "python_tasks_total": len(tasks),
        "repos_total": len({t.repo for t in tasks}),
        "post_cutoff_total": sum(t.tags["post_cutoff"] for t in tasks),
        "post_cutoff_needed": POST_CUTOFF_NEEDED,
        "per_source": per_source,
        "gold_agreement": gold_agreement(tasks),
        "split": {k: v for k, v in split.items() if k != "test_ids"},
    }
    if args.stale_sample and split.get("test_ids"):
        result["stale"] = stale_sample(tasks, set(split["test_ids"]), args.stale_sample)
    if args.licenses:
        result["licenses"] = repo_licenses(sorted({t.repo for t in tasks}))
    if args.post_cutoff_supply:
        result["post_cutoff_supply"] = post_cutoff_supply(tasks, args.post_cutoff_supply)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    summary = {k: v for k, v in result.items() if k != "licenses"}
    if "licenses" in result:
        summary["licenses"] = result["licenses"]["by_spdx"]
    print(json.dumps(summary, indent=2, default=str))
    if args.hand_check:
        hand_check(tasks, args.hand_check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
