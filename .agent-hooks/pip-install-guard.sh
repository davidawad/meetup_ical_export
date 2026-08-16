#!/usr/bin/env bash
# PreToolUse hook — in a repo managed by poetry/uv (pyproject.toml present),
# a bare `pip install <pkg>` doesn't touch the lockfile — the dependency
# silently isn't declared anywhere, and the next `uv sync`/`poetry install`
# on another machine won't have it. Nudge the project's real dependency
# manager instead. `pip install -e .` and `pip install -r requirements.txt`
# are unaffected (installing the project itself / a pinned requirements
# file, not adding an undeclared package).
#
# Escape hatch: PIP_INSTALL_SKIP=1 pip install ...

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
[ -z "$CWD" ] && CWD="$PWD"

echo "$COMMAND" | grep -qE '(^|[;&|]|&&)[[:space:]]*pip[0-9.]*[[:space:]]+install\b' || exit 0
echo "$COMMAND" | grep -q 'PIP_INSTALL_SKIP=1' && exit 0
echo "$COMMAND" | grep -qE -- '-e[[:space:]]|--editable\b|-r[[:space:]]|--requirement\b' && exit 0

[ -f "$CWD/pyproject.toml" ] || exit 0

if [ -f "$CWD/uv.lock" ]; then
  MGR="uv add"
elif [ -f "$CWD/poetry.lock" ]; then
  MGR="poetry add"
else
  exit 0  # pyproject.toml with no recognized lockfile — don't guess
fi

echo "BLOCKED: this repo is managed by $MGR (pyproject.toml + lockfile present). A bare 'pip install' won't update the lockfile — use '$MGR <package>' instead so the dependency is actually declared. If this genuinely needs to bypass the manager: PIP_INSTALL_SKIP=1." >&2
exit 2
