#!/usr/bin/env bash
# PreToolUse hook — sibling to the general credential-exfil-guard.sh,
# narrowed to PyPI publish hygiene: a plaintext token passed on the
# command line (or a .pypirc read) is exactly the failure mode Trusted
# Publishing (OIDC via CI, no stored long-lived token) exists to
# eliminate. No escape hatch — publishing with a bare token should always
# require a human decision, not a one-line bypass.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""')

if echo "$COMMAND" | grep -qE '\btwine[[:space:]]+upload\b' && echo "$COMMAND" | grep -qE -- '(-p[[:space:]]|--password[[:space:]=])|TWINE_PASSWORD='; then
  echo "BLOCKED: publishing with a plaintext PyPI token/password on the command line. Use Trusted Publishing (OIDC via CI, no stored token) instead — https://docs.pypi.org/trusted-publishers/." >&2
  exit 2
fi

if echo "$COMMAND" | grep -qE '\bcat\b.*\.pypirc\b'; then
  echo "BLOCKED: reading .pypirc directly (contains a long-lived PyPI token). Use the get-credentials skill / Trusted Publishing instead." >&2
  exit 2
fi

exit 0
