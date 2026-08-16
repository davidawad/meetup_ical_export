#!/usr/bin/env bash
# check-branch-worktree.sh — mechanical enforcement of the "Git Worktree
# Workflow" standard in swe-engineering-standards.md.
#
# 1. Blocks a commit made directly on a protected branch (main/master/develop)
#    — every PR-producing change gets a branch named after its issue-tracker
#    ref (e.g. ENGIN-123), never a commit straight on the trunk.
# 2. Warns (non-blocking) when committing from the repo's primary checkout
#    instead of a linked git worktree — worktrees are how concurrent
#    tasks/agents avoid colliding in one working directory.
#
# Wired in as a husky pre-commit step (TS/JS) or a `local` pre-commit hook
# (Python) — see swe-repo/rules.py's hooks.has_branch_worktree_guard.
set -euo pipefail

# symbolic-ref (not rev-parse --abbrev-ref) so this also works on a repo's
# very first commit, before HEAD resolves to any commit object.
branch="$(git symbolic-ref --quiet --short HEAD || echo HEAD)"

if [[ "$branch" =~ ^(main|master|develop)$ ]] && [ "${ALLOW_MAIN_COMMIT:-0}" != "1" ]; then
  echo "error: direct commits to '$branch' are blocked (swe-engineering-standards)." >&2
  echo "  create a branch named after its issue-tracker ref instead, e.g. ENGIN-123." >&2
  echo "  intentional direct commit: ALLOW_MAIN_COMMIT=1 git commit ..." >&2
  exit 1
fi

git_dir="$(cd "$(git rev-parse --git-dir)" && pwd)"
common_dir="$(cd "$(git rev-parse --git-common-dir)" && pwd)"
if [ "$git_dir" = "$common_dir" ] && [ "${ALLOW_MAIN_CHECKOUT:-0}" != "1" ]; then
  echo "warning: committing from the primary checkout, not a git worktree." >&2
  echo "  swe-engineering-standards: PR work should happen in its own worktree —" >&2
  echo "  Claude Code: EnterWorktree({name: \"$branch\"})" >&2
  echo "  Manual: git worktree add .worktrees/$branch -b $branch" >&2
fi

exit 0
