# Security and trust

BugPilot is designed to be pointed at real websites with authorization. That means the dangerous
parts are explicit and tested.

## Target validation

- Only `http` and `https` are accepted.
- Outside development, hosts are resolved and private, loopback and link-local addresses are
  rejected (SSRF defence).
- `ALLOWED_HOST_SUFFIXES` can restrict scans to an organization's domains.
- Localhost is only permitted when `BUGPILOT_ENV=development`.

## Scope enforcement

The scope the user selects is a server-side boundary:

- `single_url` never follows links, never changes route and never submits forms.
- `selected_element` only interacts with the selected element's subtree.
- `full_site` only stays on the authorized origin, within depth and URL patterns.
- Clicks that navigate are re-checked after the fact; unauthorized destinations are rolled back.

The agent cannot widen the scope. Additional exploration requires a new scan from the user.

## Destructive actions

`ActionPolicy` blocks elements whose text or href looks destructive (delete, purchase, pay, transfer,
unsubscribe, change password) and blocks form submission in production. Production scans also force
`allow_destructive = false` regardless of what the client requests. This is a safety net, not a
guarantee: labels are heuristics, which is why the policy is conservative.

## Extension

- Permissions: `activeTab`, `scripting`, `storage`. Site access is requested at runtime per origin.
- No provider keys are present in the extension bundle.
- The backend URL and app URL are validated as bare `http(s)` origins without credentials.
- UI is injected into a closed shadow root, so host CSS cannot leak in and the overlay cannot change
  the page's styles.
- Message handlers validate message types and never execute page-provided code.
- Sound is off by default; animations respect `prefers-reduced-motion`.
- Page content is not transmitted by the extension. The backend fetches the page itself.

## Evidence

- Evidence files are stored outside the database by a storage adapter.
- File extensions are allow-listed and size is capped (`EVIDENCE_MAX_BYTES`).
- Evidence URLs are HMAC-signed; a public URL requires `EVIDENCE_PUBLIC=true`.
- Text evidence is redacted for emails, bearer tokens, JWTs, API keys, passwords, card numbers and
  SSN-shaped strings before it is written.
- Retention is configurable per project and `purge_older_than` removes expired artifacts.
- S3 storage deliberately fails closed until it is configured; it never silently writes locally.

## Prompt injection and untrusted content

Page text, DOM and network responses are untrusted. Detectors run deterministic rules; the model is
used only for hypotheses and explanation, and its output is parsed into a strict schema. A model
cannot execute an action directly: actions are planned, scored and checked by the scope guard and
action policy first. Findings produced by AI are marked with `source=ai_reasoning` and confidence
labels; root causes are labelled `unconfirmed` until a human confirms them.

## Isolation

The browser worker runs in its own container in production, and the browser context is headless.
No shell execution or arbitrary code execution is exposed through the API. The agent only calls a
fixed set of Playwright actions (click, fill, hover, scroll, resize, navigate).

## Known gaps

- No authentication or per-user authorization yet. Do not expose the API publicly as-is.
- No rate limiting yet.
- The extension polls the API rather than streaming events.
- The S3 adapter is a fail-closed placeholder.
- Authenticated scans rely on the worker's fresh browser session; there is no credential vault.

These are listed rather than hidden, because a security page that claims completeness would itself
be a risk.