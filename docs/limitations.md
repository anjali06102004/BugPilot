# Known limitations

This file exists so the project never overstates itself.

## Coverage

- BugPilot reports what it inspected. A clean scan is not proof that an application is bug-free.
- Detectors are heuristic: overlap thresholds, overflow tolerances and a11y checks are pragmatic,
  not exhaustive. There is no axe-core integration yet.
- Cross-viewport comparison re-runs detectors at each viewport; it does not diff screenshots.
- Visual regression between scans is not implemented as image diffing. "Regression" means a resolved
  issue reappeared, which is evidence-based but narrower than pixel comparison.

## Verification

- Verification replays the recorded safe actions (click/fill/hover/scroll) and re-runs the
  detectors. It is bounded (30s replay budget) and reports `inconclusive` when selectors moved,
  a step failed or the page could not be loaded.
- Fix verification is therefore "still failing / no longer detected / inconclusive", not a formal
  proof.
- AI root causes are hypotheses. They are labelled as unconfirmed and must be reviewed.

## Scope and authentication

- Scans run in the worker's own browser session. Authenticated targets require a worker-side session;
  no credential vault or browser-profile delegation exists.
- Cross-origin iframes are not inspected.
- CAPTCHAs and anti-bot controls are not bypassed by design.

## Platform

- The API has no authentication, rate limiting or multi-tenancy yet. Run it privately.
- The extension polls the API every 2.5 seconds; there is no push channel.
- Object storage for evidence is a fail-closed placeholder; only local disk is implemented.
- Retention purge exists as a method but no scheduler invokes it yet.
- GitHub/Jira/Slack integrations are not implemented.
- There is no billing, team management or role model.

## Tooling

- Python 3.14 is used in this environment; the project targets 3.12+. CI runs 3.12.
- Firefox and WebKit are selectable in the model but only Chromium is exercised in tests.
- The extension's end-to-end test uses a loopback-only harness hook to attach the overlay,
  because Playwright cannot click the browser's extension button to grant `activeTab`.
- The web dashboard has not been evaluated with a screen reader; keyboard navigation and contrast
  have been designed for but require an accessibility audit.