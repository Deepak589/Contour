#!/bin/bash
# SessionEnd (matcher "clear"): summarize the ending session with Haiku into
# .claude/session-memory/latest.md. Runs detached because SessionEnd hooks get
# a short timeout; load-session-memory.sh waits on the lock file.
[ -n "$EVALH_SUMMARIZER" ] && exit 0          # don't recurse from the child claude
input=$(cat)
transcript=$(printf '%s' "$input" | jq -r '.transcript_path // empty')
[ -f "$transcript" ] || exit 0

dir="$(cd "$(dirname "$0")/../session-memory" && pwd)"
lock="$dir/.summarizing"
touch "$lock"

(
  trap 'rm -f "$lock"' EXIT
  export EVALH_SUMMARIZER=1
  text=$(python3 "$(dirname "$0")/extract-transcript.py" "$transcript")
  [ -z "$text" ] && exit 0
  prev=$(cat "$dir/latest.md" 2>/dev/null)
  prompt="You maintain a rolling memory file for a project. Below are the PREVIOUS MEMORY and the TRANSCRIPT of the session that just ended.
Write the UPDATED MEMORY in markdown, max ~400 words:
## Current state  (what exists now, files changed, decisions made)
## Open items  (pending questions, next steps the user asked for)
## User preferences  (how the user wants Claude to work)
Merge with previous memory; drop anything superseded. Facts only, no filler. Output only the markdown.

=== PREVIOUS MEMORY ===
${prev:-(none)}

=== TRANSCRIPT ===
$text"
  out=$(cd "${TMPDIR:-/tmp}" && printf '%s' "$prompt" | claude -p --model haiku \
        --setting-sources project --no-session-persistence 2>/dev/null)
  if [ -n "$out" ]; then
    ts=$(date +%Y-%m-%d_%H%M%S)
    mkdir -p "$dir/history"
    printf '<!-- updated %s from session %s -->\n%s\n' "$ts" "$(basename "$transcript" .jsonl)" "$out" > "$dir/latest.md"
    cp "$dir/latest.md" "$dir/history/$ts.md"
  fi
) </dev/null >/dev/null 2>&1 &
disown
exit 0
