"""S0-4 spike: drive CodeGraph's stdio MCP server in Docker and check the index stays frozen.

Prints one JSON record: which calls answered, stderr tail, SHA-256 of .codegraph/codegraph.db*
before and after. Stdlib only so it runs the same on macOS and WSL2.

    uv run python scripts/mcp_smoke.py ~/evalh-cache/trees/django-<sha> [--ro | --frozen] [--direct]
"""

import argparse
import hashlib
import json
import queue
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

IMAGE = "evalh/codegraph:f72c9d2"


def index_hashes(tree: Path) -> dict[str, str]:
    files = sorted((tree / ".codegraph").glob("codegraph.db*"))
    return {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in files}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("tree", type=Path, help="checkout with .codegraph/ inside, no .git")
    p.add_argument("--ro", action="store_true", help="mount the tree read-only")
    p.add_argument(
        "--frozen",
        action="store_true",
        help="tree ro + tmpfs over .codegraph/ + codegraph.db bind-mounted ro (no upstream patch)",
    )
    p.add_argument("--direct", action="store_true", help="CODEGRAPH_NO_DAEMON=1 (direct mode)")
    p.add_argument("--query", default="QuerySet", help="codegraph_search / codegraph_explore query")
    p.add_argument("--timeout", type=float, default=60.0, help="seconds per response")
    p.add_argument("--image", default=IMAGE)
    a = p.parse_args()

    tree = a.tree.expanduser().resolve()
    before = index_hashes(tree)
    # Named so it can be force-removed: killing the docker CLI leaves the container running.
    container = f"evalh-smoke-{uuid.uuid4().hex[:8]}"
    cmd = ["docker", "run", "-i", "--rm", "--name", container, "--network", "none"]
    cmd += ["-v", f"{tree}:/repo" + (":ro" if a.ro or a.frozen else "")]
    if a.frozen:
        cmd += ["--tmpfs", "/repo/.codegraph"]
        cmd += ["-v", f"{tree / '.codegraph' / 'codegraph.db'}:/repo/.codegraph/codegraph.db:ro"]
    if a.direct:
        cmd += ["-e", "CODEGRAPH_NO_DAEMON=1"]
    cmd += [a.image, "serve", "--mcp", "--no-watch", "--no-telemetry", "--path", "/repo"]

    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    stdout, stderr = proc.stdout, proc.stderr
    assert proc.stdin and stdout and stderr
    out: queue.Queue[str] = queue.Queue()
    err: list[str] = []

    def pump() -> None:
        for line in stdout:
            out.put(line)

    threading.Thread(target=pump, daemon=True).start()
    threading.Thread(target=lambda: err.extend(stderr), daemon=True).start()

    def send(msg: dict[str, Any]) -> None:
        assert proc.stdin
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", **msg}) + "\n")
        proc.stdin.flush()

    def call(id_: int, method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        send({"id": id_, "method": method, "params": params})
        deadline = time.monotonic() + a.timeout
        while (left := deadline - time.monotonic()) > 0:
            try:
                msg: dict[str, Any] = json.loads(out.get(timeout=left))
            except queue.Empty:
                break
            except json.JSONDecodeError:
                continue  # stdout must be protocol-only; non-JSON is a finding, keep reading
            if msg.get("id") == id_:
                return msg
        return None

    steps: dict[str, Any] = {}
    t0 = time.monotonic()
    init = call(
        1,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "evalh-smoke", "version": "0"},
        },
    )
    steps["initialize"] = init is not None and "result" in init
    if init:
        send({"method": "notifications/initialized"})
        tools = call(2, "tools/list", {})
        steps["tools"] = [t["name"] for t in (tools or {}).get("result", {}).get("tools", [])]
        for id_, name, args in [
            (3, "codegraph_status", {}),
            (4, "codegraph_search", {"query": a.query}),
            (5, "codegraph_explore", {"query": a.query}),
        ]:
            t = time.monotonic()
            r = call(id_, "tools/call", {"name": name, "arguments": args})
            content = (r or {}).get("result", {}).get("content", [])
            text = "".join(c.get("text", "") for c in content)
            steps[name] = {
                "ok": r is not None and "result" in r and not r["result"].get("isError"),
                "error": (r or {}).get("error"),
                "chars": len(text),
                "secs": round(time.monotonic() - t, 2),
                "head": text[:300],
            }

    proc.stdin.close()
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    subprocess.run(["docker", "rm", "-f", container], capture_output=True)
    time.sleep(0.5)  # let the stderr thread drain
    after = index_hashes(tree)

    record = {
        "cmd": " ".join(cmd),
        "exit": proc.returncode,
        "secs": round(time.monotonic() - t0, 2),
        "steps": steps,
        "stderr_tail": "".join(err)[-2000:],
        "sha_before": before,
        "sha_after": after,
        "index_unchanged": before == after,
    }
    print(json.dumps(record, indent=2))
    return 0 if steps.get("initialize") and before == after else 1


if __name__ == "__main__":
    sys.exit(main())
