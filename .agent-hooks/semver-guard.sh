#!/usr/bin/env bash
# PreToolUse hook — enforce actual semver discipline on release tags, not
# just commit-message format. Complements conventional-commits-guard.sh:
# that one keeps commit messages honest about intent; this one keeps the
# version number honest about what those commits actually imply (any
# `feat:` since the last tag needs at least a MINOR bump, any `!:` /
# `BREAKING CHANGE:` needs a MAJOR bump). Fires on `git tag vX.Y.Z`.
#
# Not a competitor to release-please (see swe-repo's release_please.exists
# rule) — that bot owns the automated release-PR path: it parses commits,
# bumps the version file, writes the changelog, and tags on merge. This hook
# is the safety net for the OTHER path: a human or agent hand-running
# `git tag` outside that flow. If a repo's release-please is wired and
# working, this hook should rarely fire — it exists for the repos that don't
# have it yet, or the manual tag that bypasses it.
#
# v1 / heuristic: only checks `git tag`, not language-specific version
# bump commands (npm version, cargo release, poetry version) — those are
# more idiomatic in per-language plugin variants.
#
# Escape hatch: SEMVER_SKIP=1 git tag ...

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
[ -z "$CWD" ] && CWD="$PWD"

# Extract the tag name from `git tag [-a] <name> ...`. Only match a create
# invocation (not -d/-l/-v/--list, which take a flag as the next token) and
# only when the name looks version-shaped (v-or-digit leading) — anything
# that still doesn't parse as valid semver falls through to the check below
# rather than being silently skipped here.
REST=$(echo "$COMMAND" | sed -nE 's/^.*(^|[;&|]|&&)[[:space:]]*git tag[[:space:]]+//p' | head -1)
[ -z "$REST" ] && exit 0
REST=$(echo "$REST" | sed -E 's/^-a[[:space:]]+//')
echo "$REST" | grep -qE '^-' && exit 0
TAG=$(echo "$REST" | awk '{print $1}')
echo "$TAG" | grep -qE '^v?[0-9]' || exit 0
echo "$COMMAND" | grep -q 'SEMVER_SKIP=1' && exit 0

cd "$CWD" 2>/dev/null || exit 0
git rev-parse --git-dir >/dev/null 2>&1 || exit 0

VERSION="${TAG#v}"
echo "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$' || {
  echo "BLOCKED: '$TAG' isn't valid semver (MAJOR.MINOR.PATCH[-prerelease][+build]). Fix the version string." >&2
  exit 2
}

CORE_VERSION="${VERSION%%[-+]*}"
LAST_TAG=$(git tag --list 'v[0-9]*.[0-9]*.[0-9]*' 2>/dev/null | sed 's/^v//' | sort -t. -k1,1n -k2,2n -k3,3n | tail -1)

[ -z "$LAST_TAG" ] && exit 0  # first release ever — nothing to compare against

HIGHER=$(printf '%s\n%s\n' "${LAST_TAG%%[-+]*}" "$CORE_VERSION" | sort -t. -k1,1n -k2,2n -k3,3n | tail -1)
if [ "$HIGHER" != "$CORE_VERSION" ] || [ "$CORE_VERSION" = "${LAST_TAG%%[-+]*}" ]; then
  echo "BLOCKED: new tag v$VERSION is not greater than the latest existing tag v$LAST_TAG. Semver requires strictly increasing versions." >&2
  exit 2
fi

IFS=. read -r OLD_MAJ OLD_MIN _ <<< "${LAST_TAG%%[-+]*}"
IFS=. read -r NEW_MAJ NEW_MIN _ <<< "$CORE_VERSION"

LOG_RANGE="v$LAST_TAG..HEAD"
git rev-parse "v$LAST_TAG" >/dev/null 2>&1 || LOG_RANGE="HEAD"

HAS_BREAKING=$(git log "$LOG_RANGE" --format='%s%n%b' 2>/dev/null | grep -cE '^[a-z]+(\([^)]*\))?!:|BREAKING CHANGE:')
HAS_FEAT=$(git log "$LOG_RANGE" --format='%s' 2>/dev/null | grep -cE '^feat(\([^)]*\))?: ')

if [ "$HAS_BREAKING" -gt 0 ] && [ "$NEW_MAJ" -le "$OLD_MAJ" ] 2>/dev/null; then
  echo "BLOCKED: $HAS_BREAKING breaking-change commit(s) since v$LAST_TAG require a MAJOR bump (proposing v$VERSION only bumps minor/patch). If this genuinely isn't a real MAJOR bump: SEMVER_SKIP=1." >&2
  exit 2
fi
if [ "$HAS_FEAT" -gt 0 ] && [ "$NEW_MAJ" -eq "$OLD_MAJ" ] && [ "$NEW_MIN" -le "$OLD_MIN" ] 2>/dev/null; then
  echo "BLOCKED: $HAS_FEAT feat commit(s) since v$LAST_TAG require at least a MINOR bump (proposing v$VERSION). If this genuinely isn't a real MINOR bump: SEMVER_SKIP=1." >&2
  exit 2
fi

exit 0
