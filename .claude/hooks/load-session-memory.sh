#!/bin/bash
# SessionStart: inject .claude/session-memory/latest.md into context.
# After /clear the summarizer may still be running; wait up to 90s for it.
[ -n "$EVALH_SUMMARIZER" ] && exit 0
dir="$(cd "$(dirname "$0")/../session-memory" && pwd)"
for _ in $(seq 90); do [ -f "$dir/.summarizing" ] || break; sleep 1; done
[ -s "$dir/latest.md" ] || exit 0
echo "Memory from previous sessions in this project (.claude/session-memory/latest.md):"
cat "$dir/latest.md"
