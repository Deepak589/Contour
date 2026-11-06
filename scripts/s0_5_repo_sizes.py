"""S0-5: size of every pool repo, to check which graphs are largest.

For each repo in the S0-3 pool, counts .py files and bytes at the newest task's base_commit
using the GitHub tree API (one call per repo, gh login). Also measures the 5 repos indexed in
S0-5 at the indexed commits, to compare sizes with measured edge counts.
Writes runs/s0-5/repo_sizes.json.

    uv run python scripts/s0_5_repo_sizes.py
"""

import json
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from s0_3_census import load_tasks

# Indexed in S0-5 (docs/spikes/s0-5.md, PPR table): repo -> (commit, measured edges)
MEASURED = {
    "django/django": ("1860f0a3f4", 194_344),
    "sympy/sympy": ("6452b07714", 399_095),
    "huggingface/transformers": ("cdb75de4ad", 375_558),
    "home-assistant/core": ("376e7e9618", 1_186_571),
    "azure/azure-sdk-for-python": ("81e5d6a351", None),  # index failed
}


def gh(path: str) -> Any:
    res = subprocess.run(["gh", "api", path], capture_output=True, text=True, check=False)
    return json.loads(res.stdout) if res.returncode == 0 else None


def py_size(repo: str, commit: str) -> dict[str, Any]:
    c = gh(f"repos/{repo}/commits/{commit}")
    if c is None:
        return {"error": "commit lookup failed"}
    tree = gh(f"repos/{repo}/git/trees/{c['commit']['tree']['sha']}?recursive=1")
    if tree is None:
        return {"error": "tree lookup failed"}
    py = [e for e in tree["tree"] if e["type"] == "blob" and e["path"].endswith(".py")]
    return {
        "commit": commit,
        "py_files": len(py),
        "py_mb": round(sum(e.get("size", 0) for e in py) / 1e6, 1),
        "truncated": tree["truncated"],
    }


def main() -> int:
    tasks, _ = load_tasks()
    by_repo: dict[str, list[Any]] = defaultdict(list)
    for t in tasks:
        by_repo[t.repo].append(t)
    newest = {r: max(ts, key=lambda t: t.created_at).base_commit for r, ts in by_repo.items()}

    def one(repo: str) -> tuple[str, dict[str, Any]]:
        return repo, {"tasks": len(by_repo[repo]), **py_size(repo, newest[repo])}

    with ThreadPoolExecutor(8) as ex:
        pool = dict(ex.map(one, sorted(by_repo)))
        measured = {
            r: {**py_size(r, commit), "edges": edges} for r, (commit, edges) in MEASURED.items()
        }

    ranked = sorted(pool.items(), key=lambda kv: -kv[1].get("py_mb", -1))
    out = Path("runs/s0-5/repo_sizes.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    result = {"repos": len(pool), "measured": measured, "pool": dict(ranked)}
    out.write_text(json.dumps(result, indent=2))

    print(f"repos: {len(pool)}  errors: {sum('error' in v for v in pool.values())}")
    print("\nmeasured (indexed commit):")
    for r, v in measured.items():
        print(f"  {r:40} {v}")
    print("\ntop 25 by .py MB (newest task's base_commit):")
    for r, v in ranked[:25]:
        print(f"  {r:40} {v}")
    for r, v in pool.items():
        if "error" in v:
            print(f"  ERROR {r}: {v['error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
