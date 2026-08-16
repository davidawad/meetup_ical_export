#!/usr/bin/env bash
# push-after-commit.sh — mechanical enforcement of the "push immediately
# after every commit" standard in swe-engineering-standards.md.
#
# Runs as a post-commit hook. Pushes the branch that was just committed to
# its remote right away — no "push before you walk away" window where a
# commit sits local-only (and, for a worktree checkout, is one
# `ExitWorktree`/disk-loss away from vanishing unpushed).
#
# Never blocks or fails the commit itself — post-commit hooks can't undo a
# commit anyway, so this fails LOUD (stderr) instead of failing silent.
#
# Escape hatch for an intentional local-only commit (rare — e.g. mid-rebase,
# a commit you're about to amend/squash): SKIP_AUTO_PUSH=1 git commit ...
set -uo pipefail

if [ "${SKIP_AUTO_PUSH:-0}" = "1" ]; then
  exit 0
fi

branch="$(git symbolic-ref --quiet --short HEAD || true)"
if [ -z "$branch" ]; then
  # Detached HEAD (rebase -i, cherry-pick in progress, etc.) — nothing to push.
  exit 0
fi

log="$(mktemp)"
trap 'rm -f "$log"' EXIT

remote="$(git config --get "branch.${branch}.remote" || true)"
if [ -z "$remote" ]; then
  # New branch, no upstream yet. Pick a default remote: pushDefault, else
  # 'origin' if present, else the first configured remote.
  remote="$(git config --get remote.pushDefault || true)"
  if [ -z "$remote" ]; then
    if git remote | grep -qx origin; then
      remote=origin
    else
      remote="$(git remote | head -1)"
    fi
  fi
  if [ -z "$remote" ]; then
    echo "push-after-commit: no remote configured, skipping auto-push." >&2
    exit 0
  fi
  if ! git push --quiet -u "$remote" "$branch" 2>"$log"; then
    echo "push-after-commit: FAILED to push new branch '$branch' to '$remote'." >&2
    cat "$log" >&2
    echo "push-after-commit: commit is LOCAL ONLY — push manually: git push -u $remote $branch" >&2
  fi
  exit 0
fi

if ! git push --quiet 2>"$log"; then
  echo "push-after-commit: FAILED to push '$branch' to '$remote'." >&2
  cat "$log" >&2
  echo "push-after-commit: commit is LOCAL ONLY — resolve (pull --rebase?) and push manually." >&2
fi
exit 0
