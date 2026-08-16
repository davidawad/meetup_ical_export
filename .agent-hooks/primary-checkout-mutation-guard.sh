#!/usr/bin/env bash
# PreToolUse hook — block history-mutating git commands against a repo's
# PRIMARY checkout (dot-5dh). Root cause it kills: the merge step of the
# bead workflow lived nowhere in the toolchain, so agents improvised
# `git merge` by hand in the shared primary checkout — one conflicted,
# nothing aborted it, and the repo sat in MERGING state until a human's
# prompt happened to render it (found live 2026-08-04, dot-dhj).
#
# Two tiers:
#   ALL modes (interactive or headless): git merge / rebase / cherry-pick /
#     am / reset --hard. These wedge or rewrite the shared checkout every
#     session depends on; the sanctioned path is
#     AI/hooks/house-done-bead-hooks/lib/land-bead.sh, which merges with
#     conflict-auto-abort under the repo lock. (Scripts' own internal git
#     calls are child processes this hook never sees — only a raw Bash tool
#     command spelling these out gets blocked.)
#   INTERACTIVE mode only: git commit. Interactive work is worktree-first
#     (interactive-worktree-guard.sh already blocks Write/Edit against the
#     primary checkout); headless automation legitimately commits in some
#     repos' primary checkouts (kb ingest, scheduled skills), so commit
#     stays allowed there.
#
# Recovery commands (--abort/--continue/--quit/--skip) are always allowed —
# they UNWEDGE state, and blocking them would trap an agent that's trying
# to clean up. Linked worktrees are never this hook's concern (git-dir !=
# git-common-dir). Escape hatch: ALLOW_MAIN_CHECKOUT=1, same as
# interactive-branch-switch-guard.sh.

_s="${BASH_SOURCE[0]}"; [ -L "$_s" ] && _s="$(cd "$(dirname "$_s")/$(dirname "$(readlink "$_s")")" && pwd)/$(basename "$_s")"
HOOKS_DIR="$(cd "$(dirname "$_s")/.." && pwd)"

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // ""')
case "$TOOL" in
  Bash|bash|shell|execute_command) ;;
  *) exit 0 ;;
esac

COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""')

# Fast path: no git subcommand of interest anywhere in the string.
echo "$COMMAND" | grep -qE '(^|[;&|]|&&)[[:space:]]*git[[:space:]]' || exit 0

GIT_PREFIX='(^|[;&|]|&&)[[:space:]]*git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?([[:space:]]+-c[[:space:]]+[^[:space:]]+)*'

MATCHED=""
if echo "$COMMAND" | grep -qE "${GIT_PREFIX}[[:space:]]+(merge|rebase|cherry-pick|am)([[:space:]]|\$)"; then
  MATCHED="merge/rebase/cherry-pick/am"
elif echo "$COMMAND" | grep -qE "${GIT_PREFIX}[[:space:]]+reset([[:space:]]+[^[:space:]]+)*[[:space:]]+--hard"; then
  MATCHED="reset --hard"
fi

INTERACTIVE_ONLY=0
if [ -z "$MATCHED" ]; then
  if echo "$COMMAND" | grep -qE "${GIT_PREFIX}[[:space:]]+commit([[:space:]]|\$)"; then
    MATCHED="commit"
    INTERACTIVE_ONLY=1
  else
    exit 0
  fi
fi

# Recovery/cleanup forms are always fine — they resolve wedged state.
echo "$COMMAND" | grep -qE -- '--(abort|continue|quit|skip)\b' && exit 0
# `git merge --is-ancestor`-style plumbing never appears (that's merge-base,
# excluded by the ([[:space:]]|$) boundary above), but --no-commit dry-run
# style merges still block — they create MERGE_HEAD too.

[ "${ALLOW_MAIN_CHECKOUT:-0}" = "1" ] && exit 0

if [ "$INTERACTIVE_ONLY" = "1" ]; then
  CODING_AGENT="${CODING_AGENT:-claude-code}"
  AGENT_DETECT="$HOOKS_DIR/../plugins/interactive-cli/agent-detect/$CODING_AGENT.sh"
  if [ -f "$AGENT_DETECT" ]; then
    source "$AGENT_DETECT"
  else
    # Materialized standalone copy (swe-repo copies this file into a
    # project's .claude/hooks/, where the interactive-cli plugin tree
    # doesn't exist) — fall back to the same signal agent-detect/
    # claude-code.sh reads, so the commit tier still works in every
    # pack-materialized repo instead of silently disabling itself.
    is_interactive_mode() { [ "${CLAUDE_CODE_ENTRYPOINT:-}" = "cli" ]; }
  fi
  is_interactive_mode || exit 0
fi

# Evaluate the repo the command actually targets: an explicit `git -C <path>`
# wins over cwd (an agent sitting in a worktree can still aim at the
# primary checkout with -C — that's exactly the bypass to close). A leading
# `cd <path> &&`/`cd <path>;` wins next, for the same reason (dot-a17):
# `.tool_input.cwd` is the session's registered cwd, which does NOT track a
# `cd` embedded in the command string — a command that `cd`s into a
# completely different repo's worktree (e.g. from a session rooted in repo
# A, `cd ~/repoB/.worktrees/x && git commit ...`) was evaluated against
# repo A's stale cwd instead of the worktree actually being committed in,
# blocking a legitimate commit as if it were hitting repo A's primary
# checkout — same root-cause shape as the finish-worktree-removal.sh bug
# this session was actually there to fix.
TARGET=$(echo "$COMMAND" | sed -nE 's/.*git[[:space:]]+-C[[:space:]]+"?([^"[:space:]]+)"?.*/\1/p' | head -1)
if [ -z "$TARGET" ]; then
  TARGET=$(echo "$COMMAND" | sed -nE 's/^[[:space:]]*cd[[:space:]]+"?([^"[:space:]]+)"?[[:space:]]*(&&|;).*/\1/p')
  TARGET="${TARGET/#\~/$HOME}"
fi
if [ -z "$TARGET" ]; then
  TARGET=$(echo "$INPUT" | jq -r '.cwd // empty')
  [ -z "$TARGET" ] && TARGET="$PWD"
fi

git -C "$TARGET" rev-parse --git-dir >/dev/null 2>&1 || exit 0
git_dir=$(git -C "$TARGET" rev-parse --path-format=absolute --git-dir)
common_dir=$(git -C "$TARGET" rev-parse --path-format=absolute --git-common-dir)
[ "$git_dir" != "$common_dir" ] && exit 0  # linked worktree — not this rule's concern

REPO_ROOT=$(git -C "$TARGET" rev-parse --show-toplevel 2>/dev/null)

if [ "$MATCHED" = "commit" ]; then
  echo "BLOCKED: 'git commit' against the primary checkout ($REPO_ROOT) — interactive tasks work in their own worktree, never by committing on the shared checkout.
  EnterWorktree({name: \"<task-slug>\"}) and commit there instead.
Intentional primary-checkout commit: ALLOW_MAIN_CHECKOUT=1." >&2
  exit 2
fi

echo "BLOCKED: git $MATCHED against the primary checkout ($REPO_ROOT) — this is how the repo ends up abandoned mid-MERGING while every other agent's session depends on it.
  To land a finished bead branch, use the sanctioned script instead (merges under the repo lock, auto-aborts on conflict):
    ~/.dotfiles/AI/hooks/house-done-bead-hooks/lib/land-bead.sh <branch>
  To rework a branch, do it inside that branch's own worktree, not here.
Intentional (you know why): ALLOW_MAIN_CHECKOUT=1." >&2
exit 2
