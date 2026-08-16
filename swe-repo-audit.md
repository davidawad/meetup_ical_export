# swe-repo audit — outstanding TODOs

Regenerate with:

```bash
uv run ~/.dotfiles/AI/skills/swe-repo/run.py audit .
```

Current state: **53 pass · 0 fail · 5 warn**. Everything auto-fixable has been
applied. What remains needs judgement or a tool this machine doesn't have:

- [ ] **nix.flake_lock_committed** — commit a `flake.lock` for a reproducible
      dev shell. Needs `nix flake lock` run on a machine with Nix installed.
- [ ] **gitignore.baseline** / **gitignore.worktrees** — the auditor greps for
      its patterns in its own generated block; the patterns themselves *are*
      present (see the `swe-repo additions` section of `.gitignore`). Cosmetic.
- [ ] **general.runs_typo_check** — wire `codespell` into
      `.pre-commit-config.yaml` and CI.
- [ ] **ci.runs_actions_self_lint** — add a `zizmor` / `actionlint` job that
      lints this repo's own `.github/workflows/`.
