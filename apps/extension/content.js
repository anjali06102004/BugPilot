/**
 * BugPilot page overlay.
 *
 * Injected only after the user grants permission and explicitly starts a scan
 * or picks an element. It renders inside a closed shadow root so the host
 * page's CSS cannot leak in, and so BugPilot cannot disturb the page's own
 * styles or event handlers.
 *
 * The overlay never invents progress: mascot state, findings and counts come
 * from the scan record on the BugPilot backend.
 */

(() => {
  if (window.__bugpilotLoaded) return;
  window.__bugpilotLoaded = true;

  const API_PREFIX = "/api/v1";
  const STATES = {
    idle: { label: "Ready", glow: 0.35, beam: false },
    waking: { label: "Waking up", glow: 0.6, beam: false },
    flying: { label: "Starting", glow: 0.5, beam: false },
    exploring: { label: "Exploring", glow: 0.7, beam: false },
    inspecting: { label: "Inspecting", glow: 1, beam: true },
    suspicious: { label: "Suspicious", glow: 0.9, beam: true },
    verifying: { label: "Verifying", glow: 1, beam: false },
    bug_found: { label: "Bug found", glow: 1.3, beam: true },
    success: { label: "Complete", glow: 1.1, beam: false },
    error: { label: "Failed", glow: 0.6, beam: false },
    paused: { label: "Paused", glow: 0.25, beam: false },
  };

  const state = {
    scanId: null,
    apiBase: "http://localhost:8000",
    appUrl: "http://localhost:3000",
    scope: null,
    settings: {
      soundEnabled: false,
      volume: 0.35,
      apiKey: "",
      animationsEnabled: true,
      overlaysEnabled: true,
    },
mascot: "idle",
    minimized: false,
    collapsed: false,
    pollTimer: null,
    lastFindingIds: new Set(),
    audio: null,
    dragging: null,
    position: null,
    pickerActive: false,
  };

  // Extension APIs are optional so the overlay can run in a plain page for
  // the browser harness; in production these are always present.
  const runtime =
    typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.id ? chrome.runtime : null;
  const localStore =
    typeof chrome !== "undefined" && chrome.storage && chrome.storage.local
      ? chrome.storage.local
      : null;

  function storageGet(keys) {
    if (localStore) return localStore.get(keys);
    try {
      return Promise.resolve(JSON.parse(localStorage.getItem("bugpilot:state") || "{}"));
    } catch {
      return Promise.resolve({});
    }
  }

  function storageSet(values) {
    if (localStore) return localStore.set(values);
    try {
      const current = JSON.parse(localStorage.getItem("bugpilot:state") || "{}");
      localStorage.setItem("bugpilot:state", JSON.stringify({ ...current, ...values }));
    } catch {
      /* storage is best effort */
    }
    return Promise.resolve();
  }

  function notify(message) {
    if (!runtime) return;
    try {
      runtime.sendMessage(message, () => {
        void (chrome.runtime && chrome.runtime.lastError);
      });
    } catch {
      /* the popup may be closed */
    }
  }

  function mascotSvg(size) {
    const accent = "#84cc16";
    return `
      <svg viewBox="0 0 120 120" width="${size}" height="${size}" aria-hidden="true">
        <defs>
          <radialGradient id="bpg" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stop-color="${accent}" stop-opacity="0.35"/>
            <stop offset="100%" stop-color="${accent}" stop-opacity="0"/>
          </radialGradient>
          <linearGradient id="bps" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#2b3038"/>
            <stop offset="100%" stop-color="#1c1f24"/>
          </linearGradient>
          <linearGradient id="bpv" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stop-color="#eaffb0"/>
            <stop offset="100%" stop-color="${accent}"/>
          </linearGradient>
        </defs>
        <circle cx="60" cy="62" r="52" fill="url(#bpg)"/>
        <path class="bp-beam" d="M60 66 L20 112 L100 112 Z" fill="${accent}" opacity="0"/>
        <g class="bp-wings" opacity="0.6">
          <ellipse cx="33" cy="48" rx="20" ry="13" transform="rotate(-28 33 48)" fill="#d7f5a7" opacity="0.22"/>
          <ellipse cx="87" cy="48" rx="20" ry="13" transform="rotate(28 87 48)" fill="#d7f5a7" opacity="0.22"/>
        </g>
        <g stroke="#2b3038" stroke-width="3" stroke-linecap="round">
          <path d="M40 78 L24 88"/><path d="M44 88 L30 100"/>
          <path d="M80 78 L96 88"/><path d="M76 88 L90 100"/>
          <path d="M52 96 L46 110"/><path d="M68 96 L74 110"/>
        </g>
        <ellipse cx="60" cy="72" rx="30" ry="26" fill="url(#bps)" stroke="#3f4650" stroke-width="2"/>
        <path d="M60 47 V98" stroke="#3f4650" stroke-width="2" opacity="0.7"/>
        <ellipse cx="60" cy="72" rx="30" ry="26" fill="none" stroke="${accent}" stroke-width="1.5" opacity="0.35"/>
        <circle cx="60" cy="42" r="19" fill="url(#bps)" stroke="#3f4650" stroke-width="2"/>
        <rect x="47" y="35" width="26" height="13" rx="6.5" fill="#0b0c0e" stroke="#3f4650" stroke-width="1.5"/>
        <g class="bp-eyes">
          <circle cx="55" cy="41.5" r="3.4" fill="url(#bpv)"/>
          <circle cx="65" cy="41.5" r="3.4" fill="url(#bpv)"/>
        </g>
        <g stroke="#2b3038" stroke-width="2.5" stroke-linecap="round" fill="none">
          <path d="M52 26 Q46 16 40 13"/><path d="M68 26 Q74 16 80 13"/>
        </g>
        <circle cx="40" cy="12" r="3.4" fill="${accent}"/>
        <circle cx="80" cy="12" r="3.4" fill="${accent}"/>
        <g class="bp-magnifier" opacity="0">
          <circle cx="92" cy="86" r="10" fill="none" stroke="${accent}" stroke-width="3"/>
          <path d="M99 93 L108 102" stroke="${accent}" stroke-width="3.5" stroke-linecap="round"/>
        </g>
      </svg>`;
  }

  const host = document.createElement("div");
  host.id = "bugpilot-overlay-root";
  // Explicit, important host styles: page CSS (including fixed, high-z-index
  // navigations) must not paint over or restyle the overlay.
  for (const [property, value] of Object.entries({
    position: "fixed",
    inset: "0",
    "z-index": "2147483647",
    "pointer-events": "none",
    display: "block",
  })) {
    host.style.setProperty(property, value, "important");
  }
  const isLoopback =
    location.hostname === "127.0.0.1" ||
    location.hostname === "localhost" ||
    location.hostname === "[::1]";
  // Closed in production. Opened only for the loopback browser harness, which
  // needs to assert on the widget it rendered.
  const shadow = host.attachShadow({
    mode: window.__BUGPILOT_TEST__ === true && isLoopback ? "open" : "closed",
  });

  const style = document.createElement("style");
  style.textContent = `
    * { box-sizing: border-box; }
    .bp-wrap {
      position: fixed; right: 20px; bottom: 20px; pointer-events: auto;
      font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
      color: #f4f4f5; width: 320px;
      background: #101114; border: 1px solid #2a2b30; border-radius: 16px;
      box-shadow: 0 18px 50px rgba(0,0,0,.5);
      overflow: hidden;
      transition: width .18s ease, height .18s ease;
    }
    .bp-wrap.min { width: 68px; }
    .bp-scope {
      display: flex; align-items: center; justify-content: space-between;
      gap: 8px; padding: 8px 12px; background: #0b0c0e;
      border-bottom: 1px solid #232429; font-size: 11px; color: #a1a1aa;
      cursor: grab; user-select: none;
    }
    .bp-scope:active { cursor: grabbing; }
    .bp-scope strong { color: #d9f99d; font-weight: 600; letter-spacing: .02em; }
    .bp-head { display: flex; align-items: center; gap: 10px; padding: 12px; }
    .bp-mascot { flex: 0 0 56px; height: 56px; position: relative; }
    .bp-mascot svg { animation: bp-float 3.2s ease-in-out infinite; }
    .bp-mascot .bp-beam { transition: opacity .3s ease; }
    .bp-mascot.inspecting .bp-beam, .bp-mascot.suspicious .bp-beam,
    .bp-mascot.bug_found .bp-beam { opacity: .18; animation: bp-pulse 1.8s infinite; }
    .bp-mascot .bp-wings { transform-origin: 60px 56px; animation: bp-flap 1s ease-in-out infinite; }
    .bp-mascot.idle .bp-wings, .bp-mascot.paused .bp-wings { animation-duration: 2.6s; }
    .bp-mascot.verifying .bp-magnifier { opacity: 1; }
    .bp-mascot.verifying .bp-eyes { animation: bp-blink 1.2s infinite; }
    .bp-mascot.bug_found { filter: drop-shadow(0 0 10px rgba(132,204,22,.45)); }
    @keyframes bp-float { 0%,100% { transform: translateY(0) } 50% { transform: translateY(-4px) } }
    @keyframes bp-flap { 0%,100% { transform: scaleY(.8) } 50% { transform: scaleY(1.05) } }
    @keyframes bp-pulse { 0%,100% { opacity: .08 } 50% { opacity: .24 } }
    @keyframes bp-blink { 0%,100% { opacity: 1 } 50% { opacity: .35 } }
    .bp-title { font-size: 13px; font-weight: 600; line-height: 1.25; }
    .bp-sub { font-size: 11px; color: #a1a1aa; margin-top: 2px; }
    .bp-counts { display: flex; gap: 6px; margin-top: 6px; flex-wrap: wrap; }
    .bp-chip {
      font-size: 10px; padding: 1px 6px; border-radius: 999px;
      border: 1px solid #3f3f46; color: #d4d4d8;
    }
    .bp-chip.critical, .bp-chip.high { border-color: #f43f5e66; color: #fecdd3; }
    .bp-chip.medium { border-color: #f59e0b66; color: #fde68a; }
    .bp-chip.low { border-color: #0ea5e966; color: #bae6fd; }
    .bp-body { border-top: 1px solid #232429; max-height: 260px; overflow: auto; }
    .bp-finding { padding: 9px 12px; border-bottom: 1px solid #1c1d21; font-size: 12px; cursor: pointer; }
    .bp-finding:hover { background: #17181c; }
    .bp-finding .bp-f-title { font-weight: 500; }
    .bp-finding .bp-f-meta { font-size: 10px; color: #8b8b93; margin-top: 2px; text-transform: uppercase; letter-spacing: .06em; }
    .bp-empty { padding: 16px 12px; font-size: 12px; color: #a1a1aa; text-align: center; }
    .bp-actions { display: flex; gap: 6px; padding: 10px 12px; border-top: 1px solid #232429; flex-wrap: wrap; }
    .bp-btn {
      all: unset; cursor: pointer; font-size: 11px; padding: 5px 9px;
      border-radius: 8px; border: 1px solid #34353b; color: #e4e4e7; text-align: center;
    }
    .bp-btn:hover { border-color: #84cc16aa; }
    .bp-btn.primary { background: #84cc16; color: #0b0c0e; border-color: #84cc16; font-weight: 600; }
    .bp-btn.danger { border-color: #f43f5e55; color: #fecdd3; }
    .bp-mini { width: 100%; display: flex; align-items: center; justify-content: center; padding: 10px; }
    .bp-footer { padding: 0 12px 10px; font-size: 10px; color: #71717a; }
    .bp-picker-hint {
      position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%);
      background: #101114; border: 1px solid #84cc1666; color: #d9f99d;
      padding: 8px 14px; border-radius: 999px; font-size: 12px;
      font-family: ui-sans-serif, system-ui, sans-serif; pointer-events: auto;
      box-shadow: 0 10px 30px rgba(0,0,0,.4);
    }
    .bp-highlight {
      position: fixed; pointer-events: none; border: 2px solid #84cc16;
      background: rgba(132,204,22,.10); border-radius: 4px; z-index: 2147483001;
      transition: all .05s linear;
    }
    .bp-highlight span {
      position: absolute; top: -22px; left: 0; background: #84cc16; color: #0b0c0e;
      font-size: 10px; font-family: ui-monospace, monospace; padding: 2px 6px; border-radius: 4px;
      white-space: nowrap;
    }
    @media (prefers-reduced-motion: reduce) {
      .bp-mascot svg, .bp-mascot .bp-wings, .bp-mascot .bp-eyes, .bp-mascot .bp-beam { animation: none !important; }
      .bp-wrap { transition: none; }
    }`;
  shadow.appendChild(style);

  const wrap = document.createElement("div");
  wrap.className = "bp-wrap";
  shadow.appendChild(wrap);

  const highlight = document.createElement("div");
  highlight.className = "bp-highlight";
  highlight.style.display = "none";
  shadow.appendChild(highlight);

  const pickerHint = document.createElement("div");
  pickerHint.className = "bp-picker-hint";
  pickerHint.textContent = "Click an element to inspect · Esc to cancel";
  pickerHint.style.display = "none";
  shadow.appendChild(pickerHint);

  document.documentElement.appendChild(host);

  // ---------- audio ----------
  function tone(frequency, duration, when = 0) {
    if (!state.settings.soundEnabled) return;
    try {
      state.audio = state.audio || new (window.AudioContext || window.webkitAudioContext)();
      if (state.audio.state === "suspended") state.audio.resume();
      const osc = state.audio.createOscillator();
      const gain = state.audio.createGain();
      const start = state.audio.currentTime + when;
      osc.type = "sine";
      osc.frequency.setValueAtTime(frequency, start);
      gain.gain.setValueAtTime(0, start);
      gain.gain.linearRampToValueAtTime(state.settings.volume * 0.25, start + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
      osc.connect(gain).connect(state.audio.destination);
      osc.start(start);
      osc.stop(start + duration + 0.02);
    } catch {
      /* audio is optional */
    }
  }

  const sounds = {
    activation: () => {
      tone(440, 0.12);
      tone(660, 0.16, 0.1);
    },
    discovery: () => {
      tone(520, 0.1);
      tone(780, 0.14, 0.09);
    },
    complete: () => {
      tone(523, 0.12);
      tone(659, 0.12, 0.1);
      tone(784, 0.2, 0.2);
    },
  };

  // ---------- rendering ----------
  function counts(findings) {
    const map = { critical: 0, high: 0, medium: 0, low: 0 };
    for (const finding of findings) {
      if (map[finding.severity] !== undefined) map[finding.severity] += 1;
    }
    const chips = Object.entries(map)
      .filter(([, value]) => value > 0)
      .map(([severity, value]) => `<span class="bp-chip ${severity}">${value} ${severity}</span>`)
      .join("");
    return chips || `<span class="bp-chip">0 issues</span>`;
  }

  function mascotClass() {
    return `bp-mascot ${state.mascot}`;
  }

  function render(scan) {
    const findings = scan?.findings || [];
    const status = scan?.status || "idle";
    const signature = JSON.stringify({
      status,
      minimized: state.minimized,
      mascot: state.mascot,
      pages: scan?.pages_tested || 0,
      ids: findings.map((f) => f.id),
    });
    if (signature === state.renderedSignature) return;
    state.renderedSignature = signature;
    const scopeLabel = state.scope?.summary || "Ready";
    const title = state.minimized
      ? ""
      : status === "completed"
        ? "Inspection complete"
        : status === "paused"
          ? "Scan paused"
          : status === "failed" || status === "cancelled"
            ? "Scan stopped"
            : status === "running" || status === "queued"
              ? "BugPilot is inspecting…"
              : "BugPilot is ready";
    const subtitle =
      status === "completed"
        ? `${findings.length} issue${findings.length === 1 ? "" : "s"} found · ${scan.pages_tested || 0} page(s)`
        : status === "running" || status === "queued"
          ? `${STATES[state.mascot]?.label || "Working"} · ${scan.pages_tested || 0} pages`
          : status === "paused"
            ? "Resume from the popup or below"
            : "Choose a scope in the popup";
    const list =
      findings.length === 0
        ? `<div class="bp-empty">${
            status === "completed"
              ? "No issues found in the inspected scope."
              : "Findings will appear here as the agent verifies them."
          }</div>`
        : findings
            .map(
              (finding) => `
          <div class="bp-finding" data-finding="${finding.id}">
            <div class="bp-f-title">${escapeHtml(finding.title)}</div>
            <div class="bp-f-meta">${escapeHtml(finding.severity)} · ${escapeHtml(finding.priority)} · ${escapeHtml(
              finding.confidence_label,
            )}</div>
          </div>`,
            )
            .join("");

    const actions = [];
    if (status === "running") actions.push(`<button class="bp-btn" data-action="pause">Pause</button>`);
    if (status === "paused") actions.push(`<button class="bp-btn primary" data-action="resume">Resume</button>`);
    if (!["completed", "failed", "cancelled"].includes(status))
      actions.push(`<button class="bp-btn danger" data-action="stop">Stop</button>`);
    if (status === "completed" || findings.length > 0) {
      actions.push(`<button class="bp-btn" data-action="report">Report</button>`);
      actions.push(`<button class="bp-btn" data-action="download">Download</button>`);
    }
    actions.push(`<button class="bp-btn" data-action="open-scan">Open in app</button>`);

    const body = state.minimized
      ? `<div class="bp-mini"><button class="bp-btn" data-action="expand">${findings.length} issues</button></div>`
      : `
        <div class="bp-scope" data-drag>
          <span>BUGPILOT · <strong>${escapeHtml(state.scope?.type?.replace(/_/g, " ") || "ready")}</strong></span>
          <button class="bp-btn" data-action="minimize" aria-label="Minimize">–</button>
        </div>
        <div class="bp-head" role="status" aria-live="polite">
          <div class="${mascotClass()}">${mascotSvg(56)}</div>
          <div style="min-width:0">
            <div class="bp-title">${escapeHtml(title)}</div>
            <div class="bp-sub">${escapeHtml(subtitle)}</div>
            <div class="bp-counts">${counts(findings)}</div>
          </div>
        </div>
        <div class="bp-body">${list}</div>
        <div class="bp-actions">${actions.join("")}</div>
        <div class="bp-footer">${escapeHtml(scopeLabel)}</div>`;

    wrap.innerHTML = body;
    bind();
    if (state.position && !state.minimized) applyPosition();
  }

  function applyPosition() {
    if (!state.position) return;
    wrap.style.left = `${state.position.x}px`;
    wrap.style.top = `${state.position.y}px`;
    wrap.style.right = "auto";
    wrap.style.bottom = "auto";
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function playSound(name) {
    if (!state.settings.soundEnabled) return;
    try {
      sounds[name]?.();
    } catch {
      /* ignore */
    }
  }

  function bind() {
    wrap.querySelectorAll("[data-action]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        const action = button.getAttribute("data-action");
        handleAction(action);
      });
    });
wrap.querySelectorAll("[data-finding]").forEach((item) => {
      item.addEventListener("click", () => {
        const findingId = item.getAttribute("data-finding");
        window.open(`${state.appUrl}/findings/${findingId}`, "_blank", "noopener");
      });
    });
    const drag = wrap.querySelector("[data-drag]");
    if (drag) enableDrag(drag);
  }

  function handleAction(action) {
    if (action === "minimize") {
      state.minimized = true;
      storageSet({ bugpilotWidgetMinimized: true });
      state.renderedSignature = null;
      render(state.lastScan);
    } else if (action === "expand") {
      state.minimized = false;
      storageSet({ bugpilotWidgetMinimized: false });
      state.renderedSignature = null;
      render(state.lastScan);
    } else if (action === "open-scan") {
      window.open(`${state.appUrl}/scans/${state.scanId}`, "_blank", "noopener");
    } else if (action === "report") {
      window.open(`${state.apiBase}/api/v1/reports/scan/${state.scanId}.md`, "_blank", "noopener");
    } else if (action === "download") {
      window.open(`${state.apiBase}/api/v1/reports/scan/${state.scanId}.zip`, "_blank", "noopener");
    } else if (["pause", "resume", "stop"].includes(action)) {
      notify({ type: "bugpilot:control", scanId: state.scanId, action, tabId: null });
      setTimeout(pollOnce, 400);
    }
  }

  function enableDrag(handle) {
    handle.addEventListener("pointerdown", (event) => {
      // Buttons inside the drag handle must stay clickable.
      if (event.target && event.target.closest && event.target.closest("button")) return;
      const rect = wrap.getBoundingClientRect();
      state.dragging = { dx: event.clientX - rect.left, dy: event.clientY - rect.top };
      handle.setPointerCapture(event.pointerId);
    });
    handle.addEventListener("pointermove", (event) => {
      if (!state.dragging) return;
      const x = Math.max(8, Math.min(window.innerWidth - wrap.offsetWidth - 8, event.clientX - state.dragging.dx));
      const y = Math.max(8, Math.min(window.innerHeight - 80, event.clientY - state.dragging.dy));
      state.position = { x, y };
      applyPosition();
    });
    handle.addEventListener("pointerup", () => {
      state.dragging = null;
      if (state.position) {
        storageSet({ bugpilotWidgetPosition: state.position });
      }
    });
  }

  // ---------- scan polling ----------
  async function fetchScan() {
    const headers = state.settings.apiKey ? { "X-API-Key": state.settings.apiKey } : {};
    const response = await fetch(`${state.apiBase}${API_PREFIX}/scans/${state.scanId}`, {
      headers,
    });
    if (!response.ok) throw new Error("Scan unavailable");
    return response.json();
  }

  async function pollOnce() {
    if (!state.scanId) return;
    try {
      const scan = await fetchScan();
      state.lastScan = scan;
      const findings = scan.findings || [];
      const newOnes = findings.filter((f) => !state.lastFindingIds.has(f.id));
      if (newOnes.length > 0) {
        state.lastFindingIds = new Set(findings.map((f) => f.id));
        playSound(findings.length === newOnes.length ? "discovery" : "discovery");
      }
      state.mascot = mascotFor(scan);
      render(scan);
      if (state.settings.overlaysEnabled) {
        highlightFinding(newOnes[0] || findings[findings.length - 1]);
      }
      notify({ type: "bugpilot:scan-update", scan });
      if (state.mascot === "success" && !state.completedSoundPlayed) {
        state.completedSoundPlayed = true;
        playSound("complete");
      }
      if (["completed", "failed", "cancelled", "stopped"].includes(scan.status)) {
        clearInterval(state.pollTimer);
        state.pollTimer = null;
      }
    } catch {
      /* keep polling; a transient error must not fabricate progress */
    }
  }

  function mascotFor(scan) {
    if (!scan) return "idle";
    if (scan.status === "paused") return "paused";
    if (scan.status === "failed" || scan.status === "cancelled") return "error";
    if (scan.status === "completed") return (scan.findings || []).length > 0 ? "success" : "success";
    const event = (scan.events || []).slice(-1)[0];
    if (event?.mascot) return event.mascot;
    return scan.pages_tested > 0 ? "exploring" : "flying";
  }

  function highlightFinding(finding) {
    if (!finding?.selector) return;
    let element = null;
    try {
      element = document.querySelector(finding.selector);
    } catch {
      element = null;
    }
    if (!element) {
      highlight.style.display = "none";
      return;
    }
    const rect = element.getBoundingClientRect();
    highlight.style.display = "block";
    highlight.style.left = `${rect.left}px`;
    highlight.style.top = `${rect.top}px`;
    highlight.style.width = `${rect.width}px`;
    highlight.style.height = `${rect.height}px`;
    highlight.innerHTML = `<span>${escapeHtml(finding.severity)}</span>`;
    clearTimeout(highlight.__timer);
    highlight.__timer = setTimeout(() => {
      highlight.style.display = "none";
    }, 2600);
  }

  // ---------- element picker ----------
  function cssPath(element) {
    if (!(element instanceof Element)) return "";
    const parts = [];
    let node = element;
    while (node && node.nodeType === 1 && parts.length < 6) {
      let selector = node.nodeName.toLowerCase();
      if (node.id) {
        selector += `#${CSS.escape(node.id)}`;
        parts.unshift(selector);
        break;
      }
      const classes = [...node.classList].slice(0, 2).map((c) => `.${CSS.escape(c)}`).join("");
      selector += classes;
      const parent = node.parentElement;
      if (parent) {
        const sameTag = [...parent.children].filter((c) => c.nodeName === node.nodeName);
        if (sameTag.length > 1) selector += `:nth-of-type(${sameTag.indexOf(node) + 1})`;
      }
      parts.unshift(selector);
      node = node.parentElement;
    }
    return parts.join(" > ");
  }

  let hovered = null;

  function onPickerMove(event) {
    const target = event.target;
    if (!(target instanceof Element)) return;
    if (host.contains(target)) return;
    hovered = target;
    const rect = target.getBoundingClientRect();
    highlight.style.display = "block";
    highlight.style.left = `${rect.left}px`;
    highlight.style.top = `${rect.top}px`;
    highlight.style.width = `${rect.width}px`;
    highlight.style.height = `${rect.height}px`;
    highlight.innerHTML = `<span>${escapeHtml(cssPath(target).slice(0, 60))}</span>`;
  }

  function stopPicker() {
    state.pickerActive = false;
    document.removeEventListener("mousemove", onPickerMove, true);
    document.removeEventListener("click", onPickerClick, true);
    document.removeEventListener("keydown", onPickerKey, true);
    pickerHint.style.display = "none";
    highlight.style.display = "none";
  }

  function onPickerClick(event) {
    if (!state.pickerActive) return;
    if (host.contains(event.target)) return;
    event.preventDefault();
    event.stopPropagation();
    const target = hovered || event.target;
    const selector = cssPath(target);
    const label = (target.innerText || target.getAttribute("aria-label") || target.tagName || "")
      .trim()
      .slice(0, 60);
    const role = target.getAttribute("role") || target.tagName.toLowerCase();
    storageSet({
      bugpilotPickedElement: { selector, label, role, url: location.href },
    });
    notify({
      type: "bugpilot:element-picked",
      element: { selector, label, role, url: location.href },
    });
    stopPicker();
  }

  function onPickerKey(event) {
    if (event.key === "Escape") stopPicker();
  }

  function startPicker() {
    state.pickerActive = true;
    pickerHint.style.display = "block";
    document.addEventListener("mousemove", onPickerMove, true);
    document.addEventListener("click", onPickerClick, true);
    document.addEventListener("keydown", onPickerKey, true);
  }

  // ---------- messaging ----------
  const messageListener = (message, _sender, sendResponse) => {
    (async () => {
      if (message?.type === "bugpilot:attach") {
        state.scanId = message.scanId;
        state.scope = message.scope;
        state.settings = { ...state.settings, ...(message.settings || {}) };
        state.apiBase = message.settings?.backendUrl || state.apiBase;
        state.appUrl = message.settings?.appUrl || state.appUrl;
        const stored = await storageGet(["bugpilotWidgetPosition", "bugpilotWidgetMinimized"]);
        state.position = stored.bugpilotWidgetPosition || null;
        state.minimized = Boolean(stored.bugpilotWidgetMinimized);
        if (!state.settings.overlaysEnabled) {
          wrap.style.display = "none";
        } else {
          wrap.style.display = "block";
        }
        if (state.settings.animationsEnabled === false) {
          wrap.classList.add("reduce-motion");
        }
        playSound("activation");
        await pollOnce();
        clearInterval(state.pollTimer);
        state.pollTimer = setInterval(pollOnce, 2500);
        sendResponse({ ok: true });
      } else if (message?.type === "bugpilot:start-picker") {
        startPicker();
        sendResponse({ ok: true });
      } else if (message?.type === "bugpilot:detach") {
        clearInterval(state.pollTimer);
        host.remove();
        window.__bugpilotLoaded = false;
        sendResponse({ ok: true });
      } else if (message?.type === "bugpilot:update-settings") {
        state.settings = { ...state.settings, ...(message.settings || {}) };
        wrap.style.display = state.settings.overlaysEnabled ? "block" : "none";
        sendResponse({ ok: true });
      } else {
        sendResponse({ ok: false });
      }
    })();
    return true;
  };

  if (runtime && runtime.onMessage) {
    runtime.onMessage.addListener(messageListener);
  }

  // Browser-harness hook. It only renders the widget from data the page
  // supplies on loopback, so a real site cannot use it to impersonate results.
  if (window.__BUGPILOT_TEST__ === true && isLoopback) {
    window.addEventListener("bugpilot:test-picker", () => startPicker());
    window.addEventListener("bugpilot:test-attach", (event) => {
      const detail = event.detail || {};
      state.scanId = detail.scanId || null;
      state.scope = detail.scope || null;
      state.settings = { ...state.settings, ...(detail.settings || {}) };
      state.apiBase = detail.settings?.backendUrl || state.apiBase;
      state.appUrl = detail.settings?.appUrl || state.appUrl;
      state.completedSoundPlayed = false;
      state.renderedSignature = null;
      pollOnce();
      clearInterval(state.pollTimer);
      state.pollTimer = setInterval(pollOnce, 2500);
    });
  }

  // Keep the highlight aligned when the page scrolls or resizes.
  const reposition = () => {
    if (highlight.style.display === "none") return;
    // The next poll or hover re-anchors it; this only prevents stale boxes.
    if (!state.pickerActive) highlight.style.display = "none";
  };
  window.addEventListener("scroll", reposition, { passive: true });
  window.addEventListener("resize", reposition, { passive: true });

  window.addEventListener("pagehide", () => {
    clearInterval(state.pollTimer);
  });
})();