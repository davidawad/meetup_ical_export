#!/usr/bin/env bash
# PreToolUse hook — the classic "added a dependency, forgot to re-lock"
# mistake: pyproject.toml is staged for commit but uv.lock/poetry.lock
# isn't, which breaks `uv sync`/`poetry install` on every other machine.
# Purely mechanical (git-staged-file check), no real dependency resolution
# needed.
#
# Escape hatch: LOCKFILE_DRIFT_SKIP=1 git commit ...

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
[ -z "$CWD" ] && CWD="$PWD"

echo "$COMMAND" | grep -qE '(^|[;&|]|&&)[[:space:]]*git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?[[:space:]]+commit\b' || exit 0
echo "$COMMAND" | grep -q 'LOCKFILE_DRIFT_SKIP=1' && exit 0

cd "$CWD" 2>/dev/null || exit 0
git rev-parse --git-dir >/dev/null 2>&1 || exit 0
[ -f "pyproject.toml" ] || exit 0

if [ -f "uv.lock" ]; then
  LOCKFILE="uv.lock"
elif [ -f "poetry.lock" ]; then
  LOCKFILE="poetry.lock"
else
  exit 0  # no recognized lockfile — nothing to check drift against
fi

STAGED=$(git diff --cached --name-only 2>/dev/null)
echo "$STAGED" | grep -qx "pyproject.toml" || exit 0
echo "$STAGED" | grep -qx "$LOCKFILE" && exit 0

echo "BLOCKED: pyproject.toml is staged but $LOCKFILE isn't — run the lock command (uv lock / poetry lock) and stage it, or this commit ships a dependency change no other machine can reproduce. To bypass: LOCKFILE_DRIFT_SKIP=1." >&2
exit 2
