#!/usr/bin/env bash
# PostToolUse hook — catch a vulnerable dependency at the exact moment
# it's introduced (right after `uv add`/`poetry add` succeeds) instead of
# waiting for a scheduled CI scan days later. Soft-skips if pip-audit
# isn't installed — this is a nudge riding on a real tool, not a
# hard requirement to have that tool present.
#
# Escape hatch: SKIP_VULN_CHECK=1 uv add ...

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
[ -z "$CWD" ] && CWD="$PWD"

PKG=$(echo "$COMMAND" | grep -oE '(^|[;&|]|&&)[[:space:]]*(uv add|poetry add)[[:space:]]+[^[:space:]&|;]+' | grep -oE '[^[:space:]]+$')
[ -z "$PKG" ] && exit 0
echo "$COMMAND" | grep -q 'SKIP_VULN_CHECK=1' && exit 0

cd "$CWD" 2>/dev/null || exit 0
[ -f "pyproject.toml" ] || exit 0

if command -v pip-audit >/dev/null 2>&1; then
  AUDIT_CMD="pip-audit"
elif command -v uv >/dev/null 2>&1 && uv run pip-audit --version >/dev/null 2>&1; then
  AUDIT_CMD="uv run pip-audit"
else
  exit 0  # pip-audit not available — silent skip, not a hard requirement
fi

OUTPUT=$($AUDIT_CMD 2>&1)
FINDING=$(echo "$OUTPUT" | grep -iF "$PKG")
[ -z "$FINDING" ] && exit 0

echo "$FINDING"
echo "BLOCKED: pip-audit found a known vulnerability in '$PKG', just added. Pin a patched version, or if acknowledged: SKIP_VULN_CHECK=1." >&2
exit 2
