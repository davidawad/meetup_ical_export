#!/usr/bin/env bash
# PreToolUse hook — supply-chain package freeze (dot-5nb): blocks BEFORE
# `uv add` / `poetry add` / `pip install` lands a package version published
# less than 14 days ago. Belt-and-suspenders with UV_EXCLUDE_NEWER
# (dotfiles' functions.sh, exported every shell session) which already
# makes uv's own resolver refuse anything newer than the floor — this hook
# additionally covers `poetry add` and bare `pip install` (which don't
# read UV_EXCLUDE_NEWER at all), and fires in non-interactive/headless
# contexts (CI, gastown agents) that never sourced the profile UV_EXCLUDE_
# NEWER is exported from.
#
# A bare name, an exact pin, or any range/constraint specifier is resolved
# to the concrete version pip's OWN resolver would actually pick via
# `pip install <spec> --dry-run --ignore-installed --no-deps --report -`
# — real dependency resolution, no network install, nothing written to
# disk — rather than reimplementing PEP 440 specifier matching here (a
# hand-rolled matcher that's subtly wrong is worse than no check at all).
#
# Escape hatch: PKG_FRESHNESS_SKIP=1 uv add requests

_s="${BASH_SOURCE[0]}"; [ -L "$_s" ] && _s="$(cd "$(dirname "$_s")/$(dirname "$(readlink "$_s")")" && pwd)/$(basename "$_s")"
HOOKS_DIR="$(cd "$(dirname "$_s")/../.." && pwd)"
source "$HOOKS_DIR/_lib/dependency-freshness.sh"

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""')

echo "$COMMAND" | grep -q 'PKG_FRESHNESS_SKIP=1' && exit 0
command -v curl >/dev/null 2>&1 || exit 0
command -v pip >/dev/null 2>&1 || exit 0

ARGS_LINE=$(echo "$COMMAND" | grep -oE '(^|[;&|]|&&)[[:space:]]*(uv[[:space:]]+add|poetry[[:space:]]+add|pip[0-9.]*[[:space:]]+install)[[:space:]]+.*' | head -1)
[ -z "$ARGS_LINE" ] && exit 0
ARGS_LINE=$(echo "$ARGS_LINE" | sed -E 's/^[;&|]*[[:space:]]*(uv[[:space:]]+add|poetry[[:space:]]+add|pip[0-9.]*[[:space:]]+install)[[:space:]]*//')
ARGS_LINE="${ARGS_LINE%%[;&|]*}"

BLOCKED=""
for tok in $ARGS_LINE; do
  case "$tok" in
    -*) continue ;;
  esac

  RESOLVED=$(timeout 10 pip install "$tok" --dry-run --ignore-installed --no-deps --report - --quiet 2>/dev/null)
  [ -z "$RESOLVED" ] && continue
  name=$(echo "$RESOLVED" | jq -r '.install[0].metadata.name // empty')
  version=$(echo "$RESOLVED" | jq -r '.install[0].metadata.version // empty')
  [ -z "$name" ] && continue
  [ -z "$version" ] && continue

  META=$(curl -fsS --max-time 5 "https://pypi.org/pypi/${name}/${version}/json" 2>/dev/null)
  [ -z "$META" ] && continue
  published=$(echo "$META" | jq -r '.urls[0].upload_time_iso_8601 // empty')
  [ -z "$published" ] && continue

  age_days=$(dependency_age_days "$published") || continue
  if dependency_too_new "$age_days"; then
    BLOCKED="${BLOCKED}${name}==${version} (published ${age_days} day(s) ago)\n"
  fi
done

[ -z "$BLOCKED" ] && exit 0

printf '%b' "$BLOCKED" >&2
echo "BLOCKED: the package version(s) above are younger than the ${DEPENDENCY_FRESHNESS_FLOOR_DAYS}-day supply-chain freeze (dot-5nb) — a compromised release needs time to surface publicly before it lands here. Wait, pin an older version, or if acknowledged: PKG_FRESHNESS_SKIP=1." >&2
exit 2
