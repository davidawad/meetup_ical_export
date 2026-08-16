#!/usr/bin/env bash
# PostToolUse hook — the merge-triggered counterpart to lifecycle/worktree-sweep.sh
# (which only cleans up at the START of the *next* session). Fires immediately
# after `gh pr merge` succeeds, while this session still remembers which
# worktree/branch it was working from, instead of leaving it for the sweep.
#
# Never tries to `git worktree remove` the worktree Claude is currently
# sitting inside (git refuses that anyway, and rm'ing your own cwd out from
# under a running process is a bad idea) — instead surfaces the exact
# cleanup commands to run from the primary checkout.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
[ -z "$CWD" ] && CWD="$PWD"

echo "$COMMAND" | grep -qE '(^|[;&|]|&&)[[:space:]]*gh[[:space:]]+pr[[:space:]]+merge\b' || exit 0

cd "$CWD" 2>/dev/null || exit 0
git rev-parse --git-dir >/dev/null 2>&1 || exit 0

BRANCH=$(git symbolic-ref --quiet --short HEAD 2>/dev/null)
[ -z "$BRANCH" ] && exit 0

GIT_COMMON_DIR=$(git rev-parse --git-common-dir 2>/dev/null)
GIT_DIR=$(git rev-parse --git-dir 2>/dev/null)
PRIMARY_ROOT=$(git worktree list 2>/dev/null | head -1 | awk '{print $1}')
CURRENT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)

REMOTE=$(git config --get "branch.${BRANCH}.remote" 2>/dev/null)
REMOTE="${REMOTE:-origin}"

if [ "$GIT_COMMON_DIR" != "$GIT_DIR" ] && [ -n "$PRIMARY_ROOT" ] && [ "$CURRENT_ROOT" != "$PRIMARY_ROOT" ]; then
  echo "BLOCKED: PR merged from worktree '$CURRENT_ROOT' (branch '$BRANCH'). Clean it up now — from the primary checkout ($PRIMARY_ROOT), run:
  git -C \"$PRIMARY_ROOT\" worktree remove \"$CURRENT_ROOT\"
  git -C \"$PRIMARY_ROOT\" branch -d \"$BRANCH\"
  git -C \"$PRIMARY_ROOT\" push $REMOTE --delete \"$BRANCH\"
Don't leave it for worktree-sweep.sh to catch next session — do it now." >&2
  exit 2
else
  echo "BLOCKED: PR merged (branch '$BRANCH'). Delete the merged branch now:
  git branch -d \"$BRANCH\"
  git push $REMOTE --delete \"$BRANCH\"" >&2
  exit 2
fi
