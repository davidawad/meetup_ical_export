#!/usr/bin/env bash
# PreToolUse hook — blocks Write/Edit/NotebookEdit calls that target the
# PRIMARY checkout while it's sitting on a protected branch (main/master/
# develop), instead of a linked worktree.
#
# Root cause this closes: pre-write-worktree-escape-guard.sh only stops a
# write from ESCAPING a worktree back to the primary checkout — it exits
# immediately when the session is already sitting in the primary checkout
# (there's nothing to "escape" from). That leaves the primary checkout wide
# open: any session opened directly against it, or any agent-isolated
# process whose cwd never got switched to a worktree, can freely dirty
# main/master with no guard until (if ever) `check-branch-worktree.sh` catches
# it at commit time. Confirmed live: uncommitted edits accumulated directly on
# dotfiles' master, one of them written by the `swe` agent-isolation user
# rather than through EnterWorktree.
#
# Companion to, not a replacement for, check-branch-worktree.sh (which blocks
# the *commit*, not the write) — this catches the mistake at edit time,
# before there's anything to commit.

PROTECTED_BRANCH_RE='^(main|master|develop)$'

INPUT=$(cat)

TOOL=$(echo "$INPUT" | jq -r '.tool_name // ""')
case "$TOOL" in
  Write|Edit|NotebookEdit) ;;
  *) exit 0 ;;
esac

FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.notebook_path // empty')
[ -z "$FILE_PATH" ] && exit 0

CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
[ -z "$CWD" ] && CWD="$PWD"

cd "$CWD" 2>/dev/null || exit 0
git rev-parse --git-dir >/dev/null 2>&1 || exit 0

[ "${ALLOW_MAIN_WRITE:-0}" = "1" ] && exit 0

# See pre-write-worktree-escape-guard.sh for why `pwd -P` (physical) here:
# git resolves --show-toplevel physically, so a symlinked ancestor dir would
# otherwise make every literal-prefix comparison below unreliable.
CURRENT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
GIT_COMMON_DIR=$(git rev-parse --git-common-dir 2>/dev/null) || exit 0
MAIN_ROOT=$(cd "$(dirname "$GIT_COMMON_DIR")" 2>/dev/null && pwd -P) || exit 0

# Sitting in a linked worktree, not the primary checkout — the sanctioned
# flow. Nothing to guard against.
[ "$CURRENT_ROOT" != "$MAIN_ROOT" ] && exit 0

BRANCH=$(git symbolic-ref --quiet --short HEAD 2>/dev/null || echo HEAD)
echo "$BRANCH" | grep -qE "$PROTECTED_BRANCH_RE" || exit 0

# Relative paths resolve against CWD, which we've just proven is under
# MAIN_ROOT — always in scope. Absolute paths outside MAIN_ROOT (e.g. a
# /tmp scratch file) aren't our business even though the session happens to
# be sitting in the primary checkout.
case "$FILE_PATH" in
  /*)
    case "$FILE_PATH" in
      "$MAIN_ROOT"/*|"$MAIN_ROOT") ;;
      *) exit 0 ;;
    esac
    ;;
esac

echo "BLOCKED: this session is in the PRIMARY checkout on protected branch '$BRANCH' — $TOOL would write there directly instead of through a worktree. Use a worktree: Claude Code: EnterWorktree({name: \"<task>\"}); Manual: git worktree add ../\$(basename \"$MAIN_ROOT\")-worktrees/<branch> -b <branch>. Intentional direct write (rare): ALLOW_MAIN_WRITE=1." >&2
exit 2
