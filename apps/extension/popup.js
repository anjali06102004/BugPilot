/**
 * BugPilot popup.
 *
 * The popup is the only place scope is chosen. Nothing starts until the user
 * presses "Start scan", and the chosen scope is shown for the whole run.
 */

const CATEGORIES = [
  "visual",
  "functional",
  "responsive",
  "accessibility",
  "console",
  "network",
  "navigation",
  "forms",
  "content",
];

const VIEWPORT_DEFS = {
  desktop: [{ name: "desktop-1280", width: 1280, height: 720 }],
  tablet: [{ name: "tablet-768", width: 768, height: 1024 }],
  mobile: [{ name: "mobile-390", width: 390, height: 844 }],
  all: [
    { name: "desktop-1280", width: 1280, height: 720 },
    { name: "tablet-768", width: 768, height: 1024 },
    { name: "mobile-390", width: 390, height: 844 },
  ],
};

const ui = {
  tabUrl: document.getElementById("tab-url"),
  scopeButtons: [...document.querySelectorAll(".scope")],
  elementPanel: document.getElementById("element-panel"),
  elementPreview: document.getElementById("element-preview"),
  pickButton: document.getElementById("pick-button"),
  viewport: document.getElementById("viewport"),
  interaction: document.getElementById("interaction"),
  apiKey: document.getElementById("api-key"),
  siteOptions: document.getElementById("site-options"),
  maxPages: document.getElementById("max-pages"),
  maxDepth: document.getElementById("max-depth"),
  categoryList: document.getElementById("category-list"),
  scanPanel: document.getElementById("scan-panel"),
  scanStatus: document.getElementById("scan-status"),
  scanScope: document.getElementById("scan-scope"),
  scanSummary: document.getElementById("scan-summary"),
  pauseButton: document.getElementById("pause-button"),
  resumeButton: document.getElementById("resume-button"),
  stopButton: document.getElementById("stop-button"),
  reportButton: document.getElementById("report-button"),
  message: document.getElementById("message"),
  startButton: document.getElementById("start-button"),
  soundToggle: document.getElementById("sound-toggle"),
  animationToggle: document.getElementById("animation-toggle"),
  overlayToggle: document.getElementById("overlay-toggle"),
  settingsButton: document.getElementById("settings-button"),
};

const state = {
  tab: null,
  settings: null,
  scope: "single_url",
  categories: new Set(CATEGORIES),
  element: null,
  scan: null,
  pollTimer: null,
};

function send(message) {
  return new Promise((resolve) => chrome.runtime.sendMessage(message, resolve));
}

function showMessage(text, ok = false) {
  ui.message.hidden = !text;
  ui.message.textContent = text || "";
  ui.message.classList.toggle("ok", ok);
}

function scopeLabel(scope) {
  if (scope === "full_site") return "full website";
  if (scope === "selected_element") return "selected element";
  return "current URL";
}

function renderScope() {
  ui.scopeButtons.forEach((button) => {
    button.setAttribute("aria-checked", button.dataset.scope === state.scope ? "true" : "false");
  });
  ui.elementPanel.hidden = state.scope !== "selected_element";
  ui.siteOptions.hidden = state.scope !== "full_site";
}

function renderCategories() {
  ui.categoryList.replaceChildren(
    ...CATEGORIES.map((category) => {
      const active = state.categories.has(category);
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip";
      chip.textContent = category;
      chip.setAttribute("aria-pressed", active ? "true" : "false");
      chip.addEventListener("click", () => {
        if (state.categories.has(category)) state.categories.delete(category);
        else state.categories.add(category);
        renderCategories();
      });
      return chip;
    }),
  );
}

function renderScan() {
  const scan = state.scan;
  ui.scanPanel.hidden = !scan;
  if (!scan) return;
  ui.scanStatus.textContent = scan.status;
  ui.scanStatus.className = `pill ${scan.status}`;
  ui.scanScope.textContent = scopeLabel((scan.scope && scan.scope.type) || state.scope);
  const findings = scan.findings || [];
  ui.scanSummary.textContent =
    scan.status === "completed"
      ? `${findings.length} issue(s) found · ${scan.pages_tested ?? 0} page(s) inspected`
      : scan.status === "paused"
        ? "Paused — nothing is running until you resume."
        : scan.status === "failed" || scan.status === "cancelled"
          ? scan.error_message || scan.stop_reason || "Scan stopped."
          : `Inspecting… ${scan.pages_tested ?? 0} page(s) so far`;
  ui.pauseButton.hidden = scan.status !== "running";
  ui.resumeButton.hidden = scan.status !== "paused";
  ui.stopButton.hidden = ["completed", "failed", "cancelled", "stopped"].includes(scan.status);
  ui.reportButton.hidden = !(scan.status === "completed" || findings.length > 0);
  ui.startButton.disabled = !["completed", "failed", "cancelled", "stopped"].includes(scan.status) && Boolean(scan.id);
  ui.startButton.textContent = ui.startButton.disabled ? "Scan in progress…" : "Start scan";
}

async function refreshScan() {
  if (!state.scan?.id) return;
  const result = await send({ type: "bugpilot:tab-scan", tabId: state.tab.id });
  if (result?.ok && result.data) {
    const detail = await fetch(
      `${state.settings.backendUrl}/api/v1/scans/${result.data.id}`,
    )
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null);
    if (detail) {
      state.scan = detail;
      renderScan();
    }
  }
}

async function startScan() {
  showMessage("");
  if (!state.tab?.url?.startsWith("http")) {
    showMessage("BugPilot can only inspect http(s) pages.");
    return;
  }
  if (state.scope === "selected_element" && !state.element) {
    showMessage("Pick an element on the page first.");
    return;
  }
  if (state.categories.size === 0) {
    showMessage("Select at least one detection category.");
    return;
  }

  const origin = new URL(state.tab.url).origin;
  const permission = await send({ type: "bugpilot:request-permission", origin });
  if (!permission?.granted) {
    showMessage("BugPilot needs permission for this site before it can inspect it.");
    return;
  }

  if ((ui.apiKey.value || "") !== (state.settings.apiKey || "")) {
    const saved = await send({
      type: "bugpilot:save-settings",
      settings: { apiKey: ui.apiKey.value.trim() },
    });
    if (saved?.ok) state.settings = saved.data;
  }
  ui.startButton.disabled = true;
  ui.startButton.textContent = "Starting…";
  const payload = {
    url: state.tab.url,
    project_name: new URL(state.tab.url).hostname,
    environment: "staging",
    scope: {
      type: state.scope,
      interaction_depth: ui.interaction.value,
      max_depth: Number(ui.maxDepth.value) || 0,
      element_selector: state.scope === "selected_element" ? state.element?.selector : undefined,
      element_label: state.scope === "selected_element" ? state.element?.label : undefined,
    },
    config: {
      categories: [...state.categories],
      viewports: VIEWPORT_DEFS[ui.viewport.value] || VIEWPORT_DEFS.mobile,
      max_pages: state.scope === "full_site" ? Number(ui.maxPages.value) || 10 : 1,
      max_actions: 25,
      max_duration_seconds: 180,
      allow_destructive: false,
    },
  };
  const result = await send({ type: "bugpilot:create-scan", tabId: state.tab.id, payload });
  if (!result?.ok) {
    showMessage(result?.error || "Could not start the scan.");
    ui.startButton.disabled = false;
    ui.startButton.textContent = "Start scan";
    return;
  }
  state.scan = result.data;
  renderScan();
  showMessage("Scan started. BugPilot is inspecting this page.", true);
  clearInterval(state.pollTimer);
  state.pollTimer = setInterval(refreshScan, 2500);
}

async function control(action) {
  if (!state.scan?.id) return;
  const result = await send({ type: "bugpilot:control", scanId: state.scan.id, action, tabId: state.tab.id });
  if (!result?.ok) {
    showMessage(result?.error || `Could not ${action} the scan.`);
    return;
  }
  state.scan = { ...state.scan, ...result.data };
  renderScan();
}

async function loadPickedElement() {
  const stored = await chrome.storage.local.get("bugpilotPickedElement");
  const element = stored.bugpilotPickedElement;
  if (!element) return;
  if (state.tab?.url && element.url && !element.url.startsWith(state.tab.url.split("?")[0])) {
    // Ignore selections from another page.
    return;
  }
  state.element = element;
  ui.elementPreview.textContent = `${element.selector}${element.label ? ` — ${element.label}` : ""}`;
}

async function init() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  state.tab = tab;
  ui.tabUrl.textContent = tab?.url || "Unknown tab";

  const settings = await send({ type: "bugpilot:settings" });
  state.settings = settings?.data || { backendUrl: "http://localhost:8000" };
  ui.apiKey.value = state.settings.apiKey || "";
  ui.soundToggle.checked = Boolean(state.settings.soundEnabled);
  ui.animationToggle.checked = state.settings.animationsEnabled !== false;
  ui.overlayToggle.checked = state.settings.overlaysEnabled !== false;

  renderScope();
  renderCategories();
  await loadPickedElement();

  const existing = await send({ type: "bugpilot:tab-scan", tabId: tab?.id });
  if (existing?.ok && existing.data?.id) {
    state.scan = existing.data;
    renderScan();
    await refreshScan();
    clearInterval(state.pollTimer);
    state.pollTimer = setInterval(refreshScan, 2500);
  }
}

ui.scopeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    state.scope = button.dataset.scope;
    renderScope();
  });
});

ui.pickButton.addEventListener("click", async () => {
  const result = await send({ type: "bugpilot:start-picker", tabId: state.tab.id });
  if (!result?.ok) {
    // The overlay may not be injected yet; inject it, then retry.
    await send({
      type: "bugpilot:attach-existing",
      tabId: state.tab.id,
      scanId: null,
      scope: null,
    }).catch(() => {});
    await send({ type: "bugpilot:start-picker", tabId: state.tab.id }).catch(() => {});
  }
  showMessage("Click an element on the page. Press Esc to cancel.");
  window.close();
});

chrome.runtime.onMessage.addListener((message) => {
  if (message?.type === "bugpilot:element-picked") {
    state.element = message.element;
    ui.elementPreview.textContent = `${message.element.selector}${
      message.element.label ? ` — ${message.element.label}` : ""
    }`;
    showMessage("Element selected. Start the scan when ready.", true);
  }
});

ui.startButton.addEventListener("click", startScan);
ui.pauseButton.addEventListener("click", () => control("pause"));
ui.resumeButton.addEventListener("click", () => control("resume"));
ui.stopButton.addEventListener("click", () => control("stop"));
ui.reportButton.addEventListener("click", () => {
  if (!state.scan?.id) return;
  chrome.tabs.create({
    url: `${state.settings.appUrl || "http://localhost:3000"}/scans/${state.scan.id}`,
  });
});
ui.settingsButton.addEventListener("click", () => chrome.runtime.openOptionsPage());

ui.soundToggle.addEventListener("change", async () => {
  const result = await send({
    type: "bugpilot:save-settings",
    settings: { soundEnabled: ui.soundToggle.checked },
  });
  if (result?.ok) state.settings = result.data;
});

ui.animationToggle.addEventListener("change", async () => {
  const result = await send({
    type: "bugpilot:save-settings",
    settings: { animationsEnabled: ui.animationToggle.checked },
  });
  if (result?.ok) {
    state.settings = result.data;
    send({ type: "bugpilot:update-settings", settings: state.settings }).catch(() => {});
  }
});

ui.overlayToggle.addEventListener("change", async () => {
  const result = await send({
    type: "bugpilot:save-settings",
    settings: { overlaysEnabled: ui.overlayToggle.checked },
  });
  if (result?.ok) {
    state.settings = result.data;
    if (state.tab?.id) {
      chrome.tabs
        .sendMessage(state.tab.id, { type: "bugpilot:update-settings", settings: state.settings })
        .catch(() => {});
    }
  }
});

window.addEventListener("unload", () => clearInterval(state.pollTimer));

init().catch((error) => showMessage(error?.message || "Could not initialise BugPilot."));