#!/usr/bin/env bash
# PreToolUse hook — file-length ceiling for Python, mirroring
# shell-line-count-guard.sh (swe-project-plugin-pack-shell). This repo's own
# config/programming-languages/python/README.md names a 600-line ceiling
# ("Ruff PLR0904 family; or custom check") but ruff has no rule that
# actually counts raw file lines — this is that custom check.
#
# Escape hatch: PYTHON_LINE_LIMIT_SKIP_REASON="..." git commit ...
# Override the ceiling per-repo: PYTHON_MAX_LINES=800

MAX_LINES="${PYTHON_MAX_LINES:-600}"

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
[ -z "$CWD" ] && CWD="$PWD"

echo "$COMMAND" | grep -qE '(^|[;&|]|&&)[[:space:]]*git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?[[:space:]]+commit\b' || exit 0

SKIP_REASON=$(echo "$COMMAND" | grep -oE "PYTHON_LINE_LIMIT_SKIP_REASON=('[^']*'|\"[^\"]*\"|[^ ]*)" | head -1 | sed -E "s/PYTHON_LINE_LIMIT_SKIP_REASON=//; s/^['\"]//; s/['\"]\$//")
if [ -n "$SKIP_REASON" ]; then
  echo "WARNING: skipping python line-count gate (PYTHON_LINE_LIMIT_SKIP_REASON=\"$SKIP_REASON\")." >&2
  exit 0
fi

cd "$CWD" 2>/dev/null || exit 0
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

mapfile -t FILES < <(git diff --cached --name-only --diff-filter=ACM -- '*.py' 2>/dev/null)
[ "${#FILES[@]}" -eq 0 ] && exit 0

OVER=""
for f in "${FILES[@]}"; do
  [ -f "$f" ] || continue
  lines=$(wc -l <"$f" | tr -d ' ')
  if [ "$lines" -gt "$MAX_LINES" ]; then
    OVER="${OVER}  $f: $lines lines\n"
  fi
done

[ -z "$OVER" ] && exit 0

printf '%b' "$OVER" >&2
echo "BLOCKED: staged Python file(s) above are over the ${MAX_LINES}-line ceiling. Split the module — see config/programming-languages/python/README.md. To bypass: PYTHON_LINE_LIMIT_SKIP_REASON=\"...\"" >&2
exit 2
