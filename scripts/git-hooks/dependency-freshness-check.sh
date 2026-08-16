#!/usr/bin/env bash
# dependency-freshness-check.sh — commit-time supply-chain package freeze
# (dot-5nb, 14 days): blocks a commit that pins any DIRECT dependency to a
# version published less than 14 days ago, giving a compromised release
# time to surface publicly before it lands here.
#
# This is deliberately a GIT HOOK, not a Claude Code PreToolUse hook (see
# AI/hooks/lang/*/package-freshness-guard.sh for that layer, which only
# fires inside a Claude Code session's own Bash tool calls). A git hook
# fires for every committer regardless of what wrote the change — a human
# typing `npm install` directly in a terminal, a different AI coding
# assistant, a CI job, or a hand-edited manifest file followed by a bare
# `npm install`/`uv sync`/`cargo build`/`go mod tidy` that never went
# through an "add a package" command at all. The install-time hooks are a
# fast first line of defense inside Claude Code sessions; this is the
# backstop everyone actually has to pass through, because everyone has to
# commit.
#
# Re-checks EVERY direct dependency's declared version on every commit
# that touches a manifest (not just what changed in this commit) — a
# dependency that's been in the repo for a while and already cleared 14
# days will always still pass, so this can never falsely flag old,
# unrelated deps; it costs a few extra read-only registry queries per
# commit in exchange for not needing to diff two lockfile states.
#
# Wired in as a husky pre-commit step (TS/JS) or a `local` pre-commit hook
# (everything else) — see swe-repo/rules.py's
# hooks.has_dependency_freshness_commit_check.
#
# Escape hatch: PKG_FRESHNESS_SKIP=1 git commit ...

set -u

[ "${PKG_FRESHNESS_SKIP:-0}" = "1" ] && exit 0
command -v curl >/dev/null 2>&1 || exit 0
command -v jq >/dev/null 2>&1 || exit 0

FLOOR_DAYS="${DEPENDENCY_FRESHNESS_FLOOR_DAYS:-14}"
BLOCKED=""

# Age of an RFC 3339 / ISO 8601 timestamp in whole days, or nothing if
# unparseable (GNU `date -d` — see dotfiles' functions.sh pkg-freeze
# comments for the BSD/GNU split this doesn't attempt to cover; a repo
# using this template on a non-GNU-date machine just gets a silent skip
# per finding, same fail-open policy as everything else below).
age_days() {
  local published="$1" published_epoch now_epoch
  published_epoch=$(date -u -d "$published" +%s 2>/dev/null) || return 1
  now_epoch=$(date -u +%s)
  echo $(( (now_epoch - published_epoch) / 86400 ))
}

# ---------------------------------------------------------------------------
# TypeScript / JavaScript (package.json)
# ---------------------------------------------------------------------------
check_typescript() {
  [ -f package.json ] || return 0
  command -v npm >/dev/null 2>&1 || return 0

  local specs name version resolved age published meta
  specs=$(jq -r '(.dependencies // {}) * (.devDependencies // {}) | to_entries[] | .key + " " + .value' package.json 2>/dev/null)
  [ -z "$specs" ] && return 0

  while IFS=' ' read -r name version; do
    [ -z "$name" ] && continue
    case "$version" in
      workspace:*|file:*|link:*|git+*|http:*|https:*) continue ;;  # not a registry version
    esac

    if [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([-+].*)?$ ]]; then
      resolved="$version"
    else
      resolved=$(npm view "${name}@${version}" version --json 2>/dev/null | jq -r 'if type == "array" then (if length > 0 then .[-1] else empty end) else . end')
    fi
    [ -z "$resolved" ] && continue

    meta=$(curl -fsS --max-time 5 "https://registry.npmjs.org/${name}" 2>/dev/null)
    [ -z "$meta" ] && continue
    published=$(echo "$meta" | jq -r --arg v "$resolved" '.time[$v] // empty')
    [ -z "$published" ] && continue

    age=$(age_days "$published") || continue
    if [ "$age" -lt "$FLOOR_DAYS" ]; then
      BLOCKED="${BLOCKED}[npm] ${name}@${resolved} (published ${age} day(s) ago)\n"
    fi
  done <<< "$specs"
}

# ---------------------------------------------------------------------------
# Python (pyproject.toml — PEP 621 [project.dependencies] and/or
# [tool.poetry.dependencies])
# ---------------------------------------------------------------------------
check_python() {
  [ -f pyproject.toml ] || return 0
  command -v pip >/dev/null 2>&1 || return 0
  command -v python3 >/dev/null 2>&1 || return 0

  local specs name version resolved age published meta report
  specs=$(python3 - <<'PYEOF' 2>/dev/null
import tomllib
try:
    with open("pyproject.toml", "rb") as f:
        data = tomllib.load(f)
except Exception:
    raise SystemExit(0)

out = []
for dep in data.get("project", {}).get("dependencies", []) or []:
    out.append(dep)

poetry_deps = (
    data.get("tool", {}).get("poetry", {}).get("dependencies", {}) or {}
)
for name, spec in poetry_deps.items():
    if name.lower() == "python":
        continue
    if isinstance(spec, str):
        out.append(f"{name}{spec}" if spec[:1] in "><=!~^" else f"{name}=={spec}" if spec[0].isdigit() else name)
    elif isinstance(spec, dict) and "version" in spec:
        v = spec["version"]
        out.append(f"{name}{v}" if v[:1] in "><=!~^" else f"{name}=={v}")

for line in out:
    print(line)
PYEOF
)
  [ -z "$specs" ] && return 0

  while IFS= read -r spec; do
    [ -z "$spec" ] && continue
    report=$(timeout 10 pip install "$spec" --dry-run --ignore-installed --no-deps --report - --quiet 2>/dev/null)
    [ -z "$report" ] && continue
    name=$(echo "$report" | jq -r '.install[0].metadata.name // empty')
    resolved=$(echo "$report" | jq -r '.install[0].metadata.version // empty')
    [ -z "$name" ] && continue
    [ -z "$resolved" ] && continue

    meta=$(curl -fsS --max-time 5 "https://pypi.org/pypi/${name}/${resolved}/json" 2>/dev/null)
    [ -z "$meta" ] && continue
    published=$(echo "$meta" | jq -r '.urls[0].upload_time_iso_8601 // empty')
    [ -z "$published" ] && continue

    age=$(age_days "$published") || continue
    if [ "$age" -lt "$FLOOR_DAYS" ]; then
      BLOCKED="${BLOCKED}[pypi] ${name}==${resolved} (published ${age} day(s) ago)\n"
    fi
  done <<< "$specs"
}

# ---------------------------------------------------------------------------
# Rust (Cargo.toml [dependencies])
# ---------------------------------------------------------------------------
check_rust() {
  [ -f Cargo.toml ] || return 0
  command -v cargo >/dev/null 2>&1 || return 0
  command -v python3 >/dev/null 2>&1 || return 0

  local specs name requirement resolved age published meta scratch out
  specs=$(python3 - <<'PYEOF' 2>/dev/null
import tomllib
try:
    with open("Cargo.toml", "rb") as f:
        data = tomllib.load(f)
except Exception:
    raise SystemExit(0)

for name, spec in (data.get("dependencies", {}) or {}).items():
    if isinstance(spec, str):
        print(f"{name} {spec}")
    elif isinstance(spec, dict) and "version" in spec and "path" not in spec and "git" not in spec:
        print(f"{name} {spec['version']}")
PYEOF
)
  [ -z "$specs" ] && return 0

  local ua="swe-project-plugin-pack-rust-dependency-freshness-check (dot-5nb)"
  while IFS=' ' read -r name requirement; do
    [ -z "$name" ] && continue
    scratch=$(mktemp -d) || continue
    out=$(
      cat > "$scratch/Cargo.toml" <<CARGOEOF
[package]
name = "dependency-freshness-check-scratch"
version = "0.0.0"
edition = "2021"

[dependencies]
${name} = "${requirement:-*}"
CARGOEOF
      mkdir -p "$scratch/src" && echo "fn main() {}" > "$scratch/src/main.rs"
      cd "$scratch" && timeout 20 cargo generate-lockfile >/dev/null 2>&1
    )
    resolved=$(grep -A2 "^name = \"${name}\"\$" "$scratch/Cargo.lock" 2>/dev/null | grep '^version = ' | head -1 | sed -E 's/^version = "(.*)"$/\1/')
    rm -rf "$scratch"
    [ -z "$resolved" ] && continue

    meta=$(curl -fsS --max-time 5 -A "$ua" "https://crates.io/api/v1/crates/${name}/${resolved}" 2>/dev/null)
    [ -z "$meta" ] && continue
    published=$(echo "$meta" | jq -r '.version.created_at // empty')
    [ -z "$published" ] && continue

    age=$(age_days "$published") || continue
    if [ "$age" -lt "$FLOOR_DAYS" ]; then
      BLOCKED="${BLOCKED}[crates.io] ${name}@${resolved} (published ${age} day(s) ago)\n"
    fi
  done <<< "$specs"
}

# ---------------------------------------------------------------------------
# Go (go.mod `require` — always an exact version or pseudo-version, no
# ranges, so no resolution step is needed here)
# ---------------------------------------------------------------------------
check_go() {
  [ -f go.mod ] || return 0
  command -v go >/dev/null 2>&1 || return 0

  local specs mod version age published scratch out
  # Matches both `require modpath version` (single-line form) and bare
  # `modpath version` lines inside a `require (...)` block; strips the
  # `require ` prefix and any trailing `// comment` either way.
  specs=$(grep -E '^[[:space:]]*(require[[:space:]]+)?[^[:space:]]+[[:space:]]+v[0-9][^[:space:]]*' go.mod \
    | grep -vE '^[[:space:]]*(module|go|toolchain)[[:space:]]' \
    | sed -E 's/^[[:space:]]*require[[:space:]]+//; s/^[[:space:]]*//; s/[[:space:]]*\/\/.*$//' \
    | awk '{print $1, $2}')
  [ -z "$specs" ] && return 0

  while IFS=' ' read -r mod version; do
    [ -z "$mod" ] && continue
    [ -z "$version" ] && continue
    scratch=$(mktemp -d) || continue
    out=$(
      cd "$scratch" && go mod init dependency-freshness-check-scratch >/dev/null 2>&1
      GOFLAGS=-mod=mod timeout 20 go list -m -json "${mod}@${version}" 2>/dev/null
    )
    rm -rf "$scratch"
    [ -z "$out" ] && continue
    published=$(echo "$out" | jq -r '.Time // empty')
    [ -z "$published" ] && continue

    age=$(age_days "$published") || continue
    if [ "$age" -lt "$FLOOR_DAYS" ]; then
      BLOCKED="${BLOCKED}[go] ${mod}@${version} (published ${age} day(s) ago)\n"
    fi
  done <<< "$specs"
}

check_typescript
check_python
check_rust
check_go

[ -z "$BLOCKED" ] && exit 0

printf '%b' "$BLOCKED" >&2
echo "BLOCKED: the dependency version(s) above are younger than the ${FLOOR_DAYS}-day supply-chain freeze (dot-5nb) — a compromised release needs time to surface publicly before it lands here. Pin an older version, or if acknowledged: PKG_FRESHNESS_SKIP=1." >&2
exit 1
