#!/usr/bin/env bash
# reap-stale-branches.sh — mechanical enforcement of the "Git Worktree
# Workflow" standard in swe-engineering-standards.md: a branch (and its
# linked worktree, if any) that's had no activity in STALE_DAYS is either
# already-safe to delete (merged + clean — just delete it) or needs a
# backup first (unmerged or never confirmed as merged — push it to its
# remote so the commits survive, THEN delete). Wired into `make clean` /
# `just clean` so the command everyone already runs to tidy a repo also
# reaps these, instead of requiring a separate command nobody remembers
# (swe-repo audit rule: hooks.has_stale_branch_reaper).
#
# Never touches a branch checked out in the worktree this process is
# running from (git itself refuses `branch -d/-D` on a checked-out branch,
# but `git worktree remove` on your own cwd is a worse failure mode — rm'ing
# the directory a running process is sitting in — so that's guarded
# explicitly below).
#
# A DIRTY worktree (uncommitted changes) is never auto-deleted regardless
# of age or merge status: a push only backs up committed history, so
# deleting a dirty worktree would silently destroy whatever wasn't
# committed. Dirty + stale worktrees are reported, not touched.
#
# Manual/CI-invoked (via `make clean` / `just clean`), not an automatic
# session hook — unlike a SessionStart sweep that fires on every session
# start from every concurrent agent, this only runs when a human or CI
# deliberately asks for cleanup, so it doesn't need a cross-process repo
# lock the way that kind of hook would.
#
# Env vars:
#   STALE_DAYS=2            days of no commits before a branch is "stale"
#   DRY_RUN=0               1 = log what would happen, change nothing
#   PROTECTED_BRANCHES=""   space-separated extra branch names to never touch
#                           (main/master/develop are always protected)
set -u

STALE_DAYS="${STALE_DAYS:-2}"
STALE_AFTER_S=$(( STALE_DAYS * 86400 ))
DRY_RUN="${DRY_RUN:-0}"
PROTECTED_BRANCHES="${PROTECTED_BRANCHES:-}"

log() {
  local event="$1"; shift
  local args=(--arg event "$event" --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)")
  # single-quoted: this is a jq filter, $ts/$event are jq vars, not bash's.
  # shellcheck disable=SC2016
  local filter='{ts: $ts, event: $event}'
  local kv k v
  for kv in "$@"; do
    k="${kv%%=*}"; v="${kv#*=}"
    args+=(--arg "$k" "$v")
    filter+=" + {\"$k\": \$$k}"
  done
  jq -cn "${args[@]}" "$filter"
}

git rev-parse --git-dir >/dev/null 2>&1 || { log noop reason="not_a_git_repo"; exit 0; }

CWD_REAL=$(pwd -P 2>/dev/null)
CURRENT_BRANCH=$(git symbolic-ref --quiet --short HEAD 2>/dev/null)

# Default branch: prefer the remote's HEAD symref (works for master or main),
# fall back to whichever of main/master exists locally.
default_branch=""
for remote in $(git remote 2>/dev/null); do
  ref=$(git symbolic-ref --quiet "refs/remotes/$remote/HEAD" 2>/dev/null) || continue
  default_branch="${ref#refs/remotes/"$remote"/}"
  break
done
if [ -z "$default_branch" ]; then
  for candidate in main master; do
    git show-ref --verify --quiet "refs/heads/$candidate" && { default_branch="$candidate"; break; }
  done
fi
if [ -z "$default_branch" ]; then
  log noop reason="no_default_branch_found"
  exit 0
fi

is_protected() {
  local b="$1"
  [[ "$b" =~ ^(main|master|develop)$ ]] && return 0
  [ "$b" = "$default_branch" ] && return 0
  [ "$b" = "$CURRENT_BRANCH" ] && return 0
  local p
  for p in $PROTECTED_BRANCHES; do
    [ "$b" = "$p" ] && return 0
  done
  return 1
}

# branch -> worktree path, from `git worktree list --porcelain`:
#   worktree /abs/path
#   HEAD <sha>
#   branch refs/heads/<name>
#   <blank line separates entries; "bare"/"detached" entries have no branch>
declare -A WT_PATH_BY_BRANCH
current_wt=""
while IFS= read -r line; do
  case "$line" in
    worktree\ *) current_wt="${line#worktree }" ;;
    branch\ refs/heads/*) WT_PATH_BY_BRANCH["${line#branch refs/heads/}"]="$current_wt" ;;
    "") current_wt="" ;;
  esac
done < <(git worktree list --porcelain 2>/dev/null)

now_ts=$(date +%s)
evaluated=0 removed_merged=0 reaped_pushed=0 skipped_dirty=0 skipped_no_remote=0 push_failed=0

while IFS=' ' read -r branch committer_ts; do
  [ -z "$branch" ] && continue
  is_protected "$branch" && continue

  age=$(( now_ts - committer_ts ))
  [ "$age" -lt "$STALE_AFTER_S" ] && continue
  evaluated=$((evaluated + 1))

  wt_path="${WT_PATH_BY_BRANCH[$branch]:-}"
  if [ -n "$wt_path" ]; then
    wt_real=$(cd "$wt_path" 2>/dev/null && pwd -P)
    if [ -n "$wt_real" ] && [[ "$CWD_REAL" == "$wt_real"* ]]; then
      log skipped branch="$branch" reason="running_from_this_worktree"
      continue
    fi
    if [ -n "$(git -C "$wt_path" status --porcelain 2>/dev/null)" ]; then
      skipped_dirty=$((skipped_dirty + 1))
      log skipped branch="$branch" worktree="$wt_path" age_days="$(( age / 86400 ))" reason="dirty_worktree_refusing_to_lose_uncommitted_work"
      continue
    fi
  fi

  merged=0
  git merge-base --is-ancestor "$branch" "$default_branch" 2>/dev/null && merged=1

  if [ "$merged" = "1" ]; then
    if [ "$DRY_RUN" = "1" ]; then
      log would_remove branch="$branch" worktree="${wt_path:-none}" age_days="$(( age / 86400 ))" reason="merged_clean"
      continue
    fi
    [ -n "$wt_path" ] && git worktree remove "$wt_path" 2>/dev/null
    if git branch -d "$branch" >/dev/null 2>&1; then
      removed_merged=$((removed_merged + 1))
      log removed branch="$branch" worktree="${wt_path:-none}" age_days="$(( age / 86400 ))" reason="merged_clean"
    else
      log skipped branch="$branch" reason="branch_delete_failed_after_worktree_removal"
    fi
    continue
  fi

  remote=$(git config --get "branch.${branch}.remote" 2>/dev/null)
  [ -z "$remote" ] && remote=$(git config --get remote.pushDefault 2>/dev/null)
  if [ -z "$remote" ]; then
    if git remote | grep -qx origin; then remote=origin; else remote=$(git remote | head -1); fi
  fi
  if [ -z "$remote" ]; then
    skipped_no_remote=$((skipped_no_remote + 1))
    log skipped branch="$branch" worktree="${wt_path:-none}" age_days="$(( age / 86400 ))" reason="no_remote_configured_cannot_back_up"
    continue
  fi

  if [ "$DRY_RUN" = "1" ]; then
    log would_reap branch="$branch" worktree="${wt_path:-none}" age_days="$(( age / 86400 ))" remote="$remote" reason="stale_unmerged_would_push_then_delete"
    continue
  fi

  if ! git push --quiet "$remote" "refs/heads/${branch}:refs/heads/${branch}" 2>/dev/null; then
    push_failed=$((push_failed + 1))
    log skipped branch="$branch" remote="$remote" reason="backup_push_failed_leaving_branch_intact"
    continue
  fi

  [ -n "$wt_path" ] && git worktree remove "$wt_path" 2>/dev/null
  git branch -D "$branch" >/dev/null 2>&1
  reaped_pushed=$((reaped_pushed + 1))
  log reaped branch="$branch" worktree="${wt_path:-none}" age_days="$(( age / 86400 ))" remote="$remote" reason="stale_unmerged_backed_up_then_deleted"
done < <(git for-each-ref refs/heads/ --format='%(refname:short) %(committerdate:unix)' 2>/dev/null)

log summary evaluated="$evaluated" removed_merged="$removed_merged" reaped_pushed="$reaped_pushed" skipped_dirty="$skipped_dirty" skipped_no_remote="$skipped_no_remote" push_failed="$push_failed" dry_run="$DRY_RUN" stale_days="$STALE_DAYS"
exit 0
