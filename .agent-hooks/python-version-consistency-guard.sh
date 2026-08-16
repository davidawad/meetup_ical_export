#!/usr/bin/env bash
# PreToolUse hook — .python-version (the pinned interpreter) and
# pyproject.toml's requires-python (the declared floor) silently drift
# apart over time; a pinned version below the declared floor means
# `uv run`/CI could resolve to an interpreter the code doesn't actually
# support. Pure textual/numeric comparison, no interpreter needed.
#
# Escape hatch: PYVER_CHECK_SKIP=1 git commit ...

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
[ -z "$CWD" ] && CWD="$PWD"

echo "$COMMAND" | grep -qE '(^|[;&|]|&&)[[:space:]]*git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?[[:space:]]+commit\b' || exit 0
echo "$COMMAND" | grep -q 'PYVER_CHECK_SKIP=1' && exit 0

cd "$CWD" 2>/dev/null || exit 0
[ -f "pyproject.toml" ] || exit 0
[ -f ".python-version" ] || exit 0  # only checkable when both files exist

PINNED=$(head -1 .python-version | tr -d '[:space:]')
FLOOR=$(grep -oE 'requires-python[[:space:]]*=[[:space:]]*"[^"]+"' pyproject.toml | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?' | head -1)

[ -z "$PINNED" ] && exit 0
[ -z "$FLOOR" ] && exit 0

LOWER=$(printf '%s\n%s\n' "$PINNED" "$FLOOR" | sort -t. -k1,1n -k2,2n -k3,3n | head -1)
[ "$LOWER" = "$FLOOR" ] && exit 0  # PINNED >= FLOOR — fine

echo "BLOCKED: .python-version pins $PINNED, but pyproject.toml's requires-python floor is $FLOOR — the pinned interpreter is below what the project declares it supports. Fix one of them. To bypass: PYVER_CHECK_SKIP=1." >&2
exit 2
