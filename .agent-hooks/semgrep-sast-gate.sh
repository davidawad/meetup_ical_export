#!/usr/bin/env bash
# PreToolUse hook — Semgrep is genuinely project-agnostic (rule packs for
# JS/TS, Python, Go, and others; runs fine even on languages with thinner
# coverage) and its core CLI is free/open-source, no account needed for
# community rule packs (`p/...` shorthand) — lives in the BASE pack so
# every language plugin inherits it, not a per-language add-on.
#
# Scoped to staged files only (fast — same "staged files, not full repo"
# philosophy as the pre-commit linter/formatter checks) rather than a
# full-repo scan, which would be too slow for a live commit-time gate.
# Soft-skips if semgrep isn't installed.
#
# Escape hatch: SEMGREP_SKIP_REASON="..." git commit ...

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
[ -z "$CWD" ] && CWD="$PWD"

echo "$COMMAND" | grep -qE '(^|[;&|]|&&)[[:space:]]*git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?[[:space:]]+commit\b' || exit 0

SKIP_REASON=$(echo "$COMMAND" | grep -oE "SEMGREP_SKIP_REASON=('[^']*'|\"[^\"]*\"|[^ ]*)" | head -1 | sed -E "s/SEMGREP_SKIP_REASON=//; s/^['\"]//; s/['\"]\$//")
if [ -n "$SKIP_REASON" ]; then
  echo "WARNING: skipping semgrep (SEMGREP_SKIP_REASON=\"$SKIP_REASON\")."
  exit 0
fi

cd "$CWD" 2>/dev/null || exit 0
git rev-parse --git-dir >/dev/null 2>&1 || exit 0
command -v semgrep >/dev/null 2>&1 || exit 0

STAGED=$(git diff --cached --name-only --diff-filter=ACM 2>/dev/null)
[ -z "$STAGED" ] && exit 0

# Scan only regular, still-on-disk files. Staged symlinks — e.g. the
# house-pattern plugin dir-symlinks under AI/plugins/*/skills/ — make
# semgrep exit 2 with zero findings, which read as a phantom "security
# finding" and blocked the commit (dot-7ae). Passing the array directly
# (no xargs) also keeps paths with spaces intact.
SCANNABLE=()
while IFS= read -r f; do
  [ -f "$f" ] && [ ! -L "$f" ] && SCANNABLE+=("$f")
done <<<"$STAGED"
[ ${#SCANNABLE[@]} -eq 0 ] && exit 0

OUTPUT=$(semgrep --config=p/security-audit --config=p/secrets --error --quiet "${SCANNABLE[@]}" 2>&1)
EXIT_CODE=$?
[ $EXIT_CODE -eq 0 ] && exit 0

echo "$OUTPUT"
echo "BLOCKED: semgrep found a security finding in staged files. Review and fix, or if a false positive: SEMGREP_SKIP_REASON=\"...\"" >&2
exit 2
