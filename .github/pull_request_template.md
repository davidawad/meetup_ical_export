<!--
Title MUST follow Conventional Commits: <type>(<scope>)!: <description>
Branch name MUST match the Linear or Plane issue ID (e.g. ADM-123).
-->

## Issue

<!-- Required. Link the Linear/Plane ticket this PR closes. -->
Closes: ADM-XXX

## Summary

<!-- 1–3 bullet points. What changed, why, who benefits. -->
-
-

## Test plan

<!-- Bulleted checklist. CI must be green before merge. -->
- [ ] `just test` passes locally
- [ ] `just lint` passes locally
- [ ] `just typecheck` passes locally
- [ ] Tested the affected user flow end-to-end
- [ ] No new secrets committed (gitleaks clean)

## Screenshots / Recordings

<!-- UI-facing PR: link the BrowserClaw replay URL from driving the changed
     flow end-to-end (see swe-engineering-standards "PR Requirements —
     Recorded Verification"). No UI surface? Write N/A — do not delete
     this section. -->

## SemVer impact

<!-- Mark one. release-please reads commit messages, not this box —
     but flag it so reviewers know what to expect. -->
- [ ] Patch (`fix:`) — backward-compatible bug fix
- [ ] Minor (`feat:`) — backward-compatible feature
- [ ] Major (`feat!:` or `BREAKING CHANGE:` footer) — backward-incompatible
- [ ] None (`docs:` / `chore:` / `refactor:` / etc.)
