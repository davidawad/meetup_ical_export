#!/usr/bin/env bash
# PreToolUse hook — Snyk is project-agnostic (npm/pip/cargo/go module
# support) so it lives in the BASE pack too, but unlike OSV-Scanner it
# needs an authenticated account (`snyk auth`) — soft-skip on ANY
# auth/network/config failure, same philosophy as socket-dev-guard.sh:
# infrastructure absence isn't a reason to block, only a real finding is.
# Overlaps with OSV-Scanner and the per-language audit hooks by design —
# independent scanners, independent blind spots.
#
# Escape hatch: SNYK_SKIP_REASON="..." git commit ...

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
[ -z "$CWD" ] && CWD="$PWD"

echo "$COMMAND" | grep -qE '(^|[;&|]|&&)[[:space:]]*git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?[[:space:]]+commit\b' || exit 0

SKIP_REASON=$(echo "$COMMAND" | grep -oE "SNYK_SKIP_REASON=('[^']*'|\"[^\"]*\"|[^ ]*)" | head -1 | sed -E "s/SNYK_SKIP_REASON=//; s/^['\"]//; s/['\"]\$//")
if [ -n "$SKIP_REASON" ]; then
  echo "WARNING: skipping snyk (SNYK_SKIP_REASON=\"$SKIP_REASON\")."
  exit 0
fi

cd "$CWD" 2>/dev/null || exit 0
command -v snyk >/dev/null 2>&1 || exit 0

OUTPUT=$(snyk test 2>&1)
EXIT_CODE=$?
[ $EXIT_CODE -eq 0 ] && exit 0

if echo "$OUTPUT" | grep -qiE 'authenticate|not logged in|unauthorized|network error|ENOTFOUND|ECONNREFUSED'; then
  echo "WARNING: snyk test couldn't run (auth/network issue — run 'snyk auth' to fix) — proceeding without a Snyk scan result." >&2
  exit 0
fi

echo "$OUTPUT"
echo "BLOCKED: snyk found known vulnerabilities in this project's dependencies. Fix or replace them, or if acknowledged: SNYK_SKIP_REASON=\"...\"" >&2
exit 2
