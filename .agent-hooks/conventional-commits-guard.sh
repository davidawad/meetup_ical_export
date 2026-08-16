#!/usr/bin/env bash
# PreToolUse hook — enforce Conventional Commits on `git commit -m` subjects.
# Adapted from buildwithclaude's hooks-git/conventional-commits.md spec.
# Editor commits (no -m) and -F/file commits can't be inspected from the
# command text alone, so they're let through; same for merge/revert/fixup.
#
# Escape hatch: CC_SKIP=1 git commit ...

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""')

echo "$COMMAND" | grep -qE '(^|[;&|]|&&)[[:space:]]*git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?[[:space:]]+commit\b' || exit 0
echo "$COMMAND" | grep -q 'CC_SKIP=1' && exit 0
echo "$COMMAND" | grep -qE -- '-m[[:space:]=]' || exit 0

SUBJECT=$(echo "$COMMAND" | grep -oE -- "-m[[:space:]=]?('[^']*'|\"[^\"]*\")" | head -1 | sed -E "s/^-m[[:space:]=]?//; s/^['\"]//; s/['\"]\$//")

# Heredoc form (`-m "$(cat <<'EOF' ... EOF)"`) — the exact multi-line commit
# pattern this harness's own instructions tell an agent to always use — has
# no closing quote right after -m, so the simple regex above can't see into
# it at all and silently no-ops (empty SUBJECT, falls through to the exit
# below). That meant this guard validated NOTHING for any heredoc commit,
# found live 2026-08-04 when asked why an obviously-fine-looking commit
# apparently sailed through unchecked. First non-blank, non-delimiter line
# after the heredoc opener is the subject.
if [ -z "$SUBJECT" ]; then
  HEREDOC_SCRIPT=$(cat << 'PYEOF'
import re, sys
command = sys.stdin.read()
m = re.search(r"""-m\s*['"]\$\(cat\s*<<-?\s*['"]?(\w+)['"]?.*$""", command, re.MULTILINE)
if not m:
    sys.exit(0)
delim = m.group(1)
for line in command[m.end():].splitlines():
    s = line.strip()
    if not s:
        continue
    if s == delim:
        break
    print(s)
    break
PYEOF
)
  SUBJECT=$(echo "$COMMAND" | python3 -c "$HEREDOC_SCRIPT")
fi

[ -z "$SUBJECT" ] && exit 0

echo "$SUBJECT" | grep -qiE '^(Merge|Revert|fixup!|squash!)' && exit 0

CC_RE='^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\([a-zA-Z0-9_/.,-]+\))?!?: .+'
echo "$SUBJECT" | grep -qE "$CC_RE" && exit 0

echo "BLOCKED: commit subject '$SUBJECT' isn't Conventional Commits format (<type>(scope)?: description — type is one of feat/fix/docs/style/refactor/perf/test/build/ci/chore/revert). Fix the message, or if this genuinely doesn't apply: CC_SKIP=1." >&2
exit 2
