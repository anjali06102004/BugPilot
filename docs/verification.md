# Fix verification

Scans tell you a defect existed. Verification answers a different question:
**does it still reproduce after someone changed the code?**

## How it works

1. The agent records a structured reproduction for every finding: the URL, the
   viewport, the selector, the normalized error signature and the last actions it
   performed (`action_history`, capped at 20).
2. `POST /api/v1/issues/{id}/verify-fix` starts an isolated Playwright session,
   opens the reproduction URL and replays the safe actions (click, fill, hover,
   scroll). Navigation, form submission and destructive actions are never
   replayed.
3. The same deterministic detectors run again for the issue's category, and the
   result is compared by signature, fingerprint, selector or exact title.
4. A verdict is recorded and the issue lifecycle is updated.

## Verdicts

| Verdict | Meaning | Lifecycle effect |
| --- | --- | --- |
| `fixed` | The replay completed and the detector signal is gone | `verified`, `last_verified_at` set |
| `still_failing` | The replay completed and the same signal is present | `reopened`, `is_regression = true` |
| `inconclusive` | The page could not be loaded, the element is gone, a replay step failed, or the replay exceeded its time budget | `needs_review`, never `verified` |

The rules are deliberately conservative:

- an HTTP 200 or a fresh screenshot is never treated as proof
- a missing selector is not "fixed" — the reproduction is no longer valid, so the
  answer is `inconclusive`
- a replay that does not finish within 30 seconds, or an action that times out
  after 2.5 seconds, is `inconclusive`
- only one verification runs at a time, with a 90 second ceiling

## Audit trail

Every attempt is stored in `issue_verifications` with the verdict, method, notes,
replayed/failed action counts, author and timestamp. An `issue_events` row of kind
`verification` records the status change, so the activity feed shows who verified
what and when.

## Limitations

- Replay is best-effort: dynamic content, random IDs and time-dependent flows can
  invalidate a selector, which correctly produces `inconclusive` rather than a
  false pass.
- Verification targets the recorded URL. If the fix moved the page, point the
  issue at the new URL (or rescan) before verifying.
- It does not diff screenshots; it re-runs the same detectors that reported the
  original issue.
