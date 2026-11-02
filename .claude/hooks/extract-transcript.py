"""Print user/assistant text from a Claude Code JSONL transcript (tool calls skipped)."""
import json, sys

MAX_CHARS = 200_000  # ponytail: keep the tail only; chunked summarization if sessions get longer

out = []
for line in open(sys.argv[1], encoding="utf-8"):
    try:
        e = json.loads(line)
    except ValueError:
        continue
    if e.get("type") not in ("user", "assistant") or e.get("isMeta"):
        continue
    c = e.get("message", {}).get("content")
    if isinstance(c, list):
        c = "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    if isinstance(c, str) and c.strip() and "<system-reminder>" not in c[:20]:
        out.append(f"[{e['type'].upper()}] {c.strip()}")

print("\n\n".join(out)[-MAX_CHARS:])
