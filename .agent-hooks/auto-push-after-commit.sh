#!/usr/bin/env bash
# PostToolUse hook — mirrors the "push is part of the commit action, not a
# later step" standard (swe-engineering-standards) at the Claude Code layer,
# so it fires even in repos without the native post-commit git hook the
# swe-repo skill scaffolds separately (e.g. before that scaffold has run, or
# in a repo swe-repo doesn't own). Re-derives ground truth from git state
# rather than trusting tool_response — robust to a failed/no-op commit.
#
# Escape hatch for an intentional local-only commit: SKIP_AUTO_PUSH=1 git commit ...

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
[ -z "$CWD" ] && CWD="$PWD"

# Only act on a real `git commit` invocation, not `git log --grep=commit` etc.
echo "$COMMAND" | grep -qE '(^|[;&|]|&&)[[:space:]]*git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?[[:space:]]+commit\b' || exit 0
echo "$COMMAND" | grep -q 'SKIP_AUTO_PUSH=1' && exit 0

cd "$CWD" 2>/dev/null || exit 0
git rev-parse --git-dir >/dev/null 2>&1 || exit 0

BRANCH=$(git symbolic-ref --quiet --short HEAD 2>/dev/null)
[ -z "$BRANCH" ] && exit 0  # detached HEAD — nothing to push

REMOTE=$(git config --get "branch.${BRANCH}.remote" 2>/dev/null)
if [ -z "$REMOTE" ]; then
  git remote | grep -q . || exit 0  # no remote configured at all
  echo "BLOCKED: commit made on '$BRANCH' with no upstream tracking branch. Push now: git push -u origin $BRANCH (or the appropriate remote) — don't leave it local-only." >&2
  exit 2
fi

AHEAD=$(git rev-list --count "@{u}..HEAD" 2>/dev/null || echo 0)
[ "$AHEAD" -eq 0 ] 2>/dev/null && exit 0  # already pushed, or commit didn't happen

echo "BLOCKED: $AHEAD unpushed commit(s) on '$BRANCH'. Push now: git push — commits sitting local-only are one lost worktree away from vanishing." >&2
exit 2
