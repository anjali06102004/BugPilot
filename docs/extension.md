# Browser extension

`apps/extension` is a Manifest V3 extension. It is the "experience layer": it chooses a scope,
starts a scan, and shows real agent events on the page. Deep exploration happens in the isolated
Playwright worker, not in your browser tab.

## Install (unpacked)

1. Start the API and the dashboard.
2. Open `chrome://extensions`, enable **Developer mode**.
3. **Load unpacked** → select `apps/extension`.
4. Open the popup → ⚙ → confirm `http://localhost:8000` and `http://localhost:3000`.

## Flow

1. Open a site you are authorized to test.
2. Open the popup. The first thing you see is **What should BugPilot inspect?**
3. Choose **Current URL**, **Full website** or **Select element**.
4. For element scans, press **Pick an element** and click the component. Esc cancels.
5. Adjust viewports, interaction depth, pages/depth (full site) and categories.
6. Press **Start scan**. Chrome asks for permission for that origin if needed.
7. The mascot attaches to the page and follows the scan.

## What the mascot represents

| State | Meaning |
| --- | --- |
| Waking / flying | The worker is starting and navigating |
| Exploring | Pages are being inspected |
| Inspecting | Detectors or visual analysis are running |
| Suspicious | Signals were found and are being investigated |
| Verifying | Findings are being re-checked |
| Bug found | A verified finding was recorded |
| Paused | The scan is paused; nothing is running |
| Complete | The scan ended; the widget shows counts |

States come from the scan record's events. The overlay never animates a discovery that did not
happen.

## Completion widget

- Docked bottom-right by default; drag it by the header to reposition.
- Shows counts by severity and the inspected scope.
- Lists findings; clicking one opens the finding workspace.
- Pause / resume / stop, open the scan in the dashboard, download Markdown or the ZIP bundle.
- Minimize without losing results; the position and minimized state persist in
  `chrome.storage.local`.
- Empty state when the inspected scope had no defects.

## Settings

- Backend URL and app URL, validated as bare http(s) origins.
- Sound (off by default), volume, animations, overlay visibility.
- Consent flag for page-text sharing (the server decides; the extension never sends page content).

## Limitations

- The extension inspects the page you are on. Full-site crawling is performed by the worker against
  the URL you supply.
- Cross-origin iframes, CAPTCHAs and authentication walls are not bypassed.
- Authenticated pages work only if the worker's own browser session is authenticated. There is no
  credential delegation from your browser profile.
- The extension polls the API every 2.5s; there is no push channel yet.

## Development

```bash
node --check apps/extension/background.js
node --check apps/extension/content.js
node --check apps/extension/popup.js
node --check apps/extension/options.js
```

`python scripts/make_icons.py` regenerates the icons from code, so no binary asset is hand-edited.

Tests in `tests/unit/test_extension.py` assert the least-privilege permission set, absence of remote
code, absence of provider keys, and that installation never starts a scan.