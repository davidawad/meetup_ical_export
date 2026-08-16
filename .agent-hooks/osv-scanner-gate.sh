#!/usr/bin/env bash
# PreToolUse hook — OSV-Scanner (Google-maintained) is genuinely
# project-agnostic: it auto-detects whichever lockfiles exist
# (package-lock.json/pnpm-lock.yaml/yarn.lock, poetry.lock/uv.lock,
# Cargo.lock, go.sum, ...) and queries the free, open OSV.dev database —
# no account, no token. Lives in the BASE pack so every language plugin
# inherits it. Overlaps in purpose with the per-language audit hooks
# (npm-audit-nudge, pip-audit via dependency-vuln-scan, cargo-audit,
# govulncheck) — kept anyway per explicit request, as independent
# defense-in-depth against any one scanner's blind spots.
#
# Scoped to the repo root (not recursive) for commit-time speed.
# Soft-skips if osv-scanner isn't installed.
#
# Escape hatch: OSV_SCANNER_SKIP_REASON="..." git commit ...

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
[ -z "$CWD" ] && CWD="$PWD"

echo "$COMMAND" | grep -qE '(^|[;&|]|&&)[[:space:]]*git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?[[:space:]]+commit\b' || exit 0

SKIP_REASON=$(echo "$COMMAND" | grep -oE "OSV_SCANNER_SKIP_REASON=('[^']*'|\"[^\"]*\"|[^ ]*)" | head -1 | sed -E "s/OSV_SCANNER_SKIP_REASON=//; s/^['\"]//; s/['\"]\$//")
if [ -n "$SKIP_REASON" ]; then
  echo "WARNING: skipping osv-scanner (OSV_SCANNER_SKIP_REASON=\"$SKIP_REASON\")."
  exit 0
fi

cd "$CWD" 2>/dev/null || exit 0
command -v osv-scanner >/dev/null 2>&1 || exit 0

# Only worth running when this commit actually touches a dependency
# manifest/lockfile -- checking staged (--cached) AND unstaged tracked diffs
# so `git commit -a`/`-am` (which never populates the index first) is still
# caught, without needing to parse -a/--all out of $COMMAND by hand. A
# commit that only touches docs/scripts/etc. can't have changed what
# osv-scanner would find anyway, so there's nothing new to gate on.
LOCKFILE_RE='(^|/)(package-lock\.json|pnpm-lock\.yaml|yarn\.lock|bun\.lockb|poetry\.lock|uv\.lock|Pipfile\.lock|requirements[^/]*\.txt|Cargo\.lock|go\.sum|go\.mod|composer\.lock|Gemfile\.lock|mix\.lock|packages\.lock\.json)$'
CHANGED=$( { git diff --cached --name-only 2>/dev/null; git diff --name-only 2>/dev/null; } | grep -E "$LOCKFILE_RE" )
[ -z "$CHANGED" ] && exit 0

OUTPUT=$(osv-scanner . 2>&1)
EXIT_CODE=$?
[ $EXIT_CODE -eq 0 ] && exit 0

# osv-scanner's documented exit codes: 0 = clean, 1 = vulnerabilities
# found. Anything else (128 = "no package sources found", or a scan
# error) is not a vulnerability finding — don't block on it.
if [ $EXIT_CODE -ne 1 ]; then
  echo "WARNING: osv-scanner exited $EXIT_CODE (not a vulnerability finding — likely nothing to scan yet, or a scan error). Proceeding without a result." >&2
  exit 0
fi

echo "$OUTPUT"
echo "BLOCKED: osv-scanner found known vulnerabilities in this project's dependencies. Fix or replace them, or if acknowledged: OSV_SCANNER_SKIP_REASON=\"...\"" >&2
exit 2
