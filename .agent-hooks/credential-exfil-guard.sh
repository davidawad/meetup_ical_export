#!/usr/bin/env bash
# PreToolUse hook — block Bash-side credential exfiltration reads. The
# complement to pre-write-sensitive.sh (which blocks writing TO secret
# paths); this blocks reading FROM them and shipping the result out.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""')

if echo "$COMMAND" | grep -qE '\benv\b[^|]*\|[^|]*grep[^|]*-i[^|]*(secret|token|password|api[_-]?key)'; then
  echo "BLOCKED: dumping environment variables filtered for secrets/tokens/keys. Resolve a specific value via the get-credentials skill instead of grepping env." >&2
  exit 2
fi

if echo "$COMMAND" | grep -qE '\bcat\b.*(\.ssh/id_(rsa|ed25519|ecdsa|dsa)|\.aws/credentials|\.netrc|\.npmrc|gcloud/.*credentials|\.pgpass)\b'; then
  echo "BLOCKED: reading a private key or credential file directly. Use the get-credentials skill / relevant secret manager instead." >&2
  exit 2
fi

if echo "$COMMAND" | grep -qE '\b(curl|wget)\b.*(-d|--data|--data-binary|-F|--form|-T|--upload-file)[[:space:]=]?@?[^[:space:]]*(\.env|id_rsa|id_ed25519|credentials|\.pem|\.pgpass)\b'; then
  echo "BLOCKED: this command appears to upload a credential/secret file over the network. Confirm with the user before sending any secret material off this machine." >&2
  exit 2
fi

exit 0
