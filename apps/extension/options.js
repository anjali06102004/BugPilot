const ui = {
  backendUrl: document.getElementById("backend-url"),
  appUrl: document.getElementById("app-url"),
  apiKey: document.getElementById("api-key"),
  testButton: document.getElementById("test-button"),
  saveButton: document.getElementById("save-button"),
  status: document.getElementById("status"),
  sound: document.getElementById("sound"),
  volume: document.getElementById("volume"),
  animations: document.getElementById("animations"),
  overlays: document.getElementById("overlays"),
  pageText: document.getElementById("page-text"),
};

function send(message) {
  return new Promise((resolve) => chrome.runtime.sendMessage(message, resolve));
}

function showStatus(text, tone = "") {
  ui.status.hidden = !text;
  ui.status.textContent = text || "";
  ui.status.className = `status ${tone}`.trim();
}

async function load() {
  const result = await send({ type: "bugpilot:settings" });
  const settings = result?.data || {};
  ui.backendUrl.value = settings.backendUrl || "http://localhost:8000";
  ui.appUrl.value = settings.appUrl || "http://localhost:3000";
  ui.apiKey.value = settings.apiKey || "";
  ui.sound.checked = Boolean(settings.soundEnabled);
  ui.volume.value = String(settings.volume ?? 0.35);
  ui.animations.checked = settings.animationsEnabled !== false;
  ui.overlays.checked = settings.overlaysEnabled !== false;
  ui.pageText.checked = Boolean(settings.sendPageText);
}

async function save() {
  showStatus("");
  const result = await send({
    type: "bugpilot:save-settings",
    settings: {
      backendUrl: ui.backendUrl.value.trim(),
      appUrl: ui.appUrl.value.trim(),
      apiKey: ui.apiKey.value.trim(),
      soundEnabled: ui.sound.checked,
      volume: Number(ui.volume.value),
      animationsEnabled: ui.animations.checked,
      overlaysEnabled: ui.overlays.checked,
      sendPageText: ui.pageText.checked,
    },
  });
  if (result?.ok) {
    showStatus("Settings saved.", "ok");
    await load();
  } else {
    showStatus(result?.error || "Could not save settings.", "error");
  }
}

async function test() {
  showStatus("Checking…");
  try {
    const base = ui.backendUrl.value.trim().replace(/\/$/, "");
    const headers = ui.apiKey.value.trim() ? { "X-API-Key": ui.apiKey.value.trim() } : {};
    const response = await fetch(`${base}/api/v1/health`, { headers });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    showStatus(
      `Connected to ${payload.service} ${payload.version} (${payload.env}) · events: ${
        payload.redis ? "redis" : "database"
      }`,
      "ok",
    );
  } catch (error) {
    showStatus(
      `Could not reach the backend. ${error?.message || ""} Make sure the API is running and the URL is reachable.`,
      "error",
    );
  }
}

ui.saveButton.addEventListener("click", save);
ui.testButton.addEventListener("click", test);
ui.volume.addEventListener("input", () => {
  // Volume is persisted with the next save, but keep the label responsive.
  ui.volume.setAttribute("aria-valuetext", `${Math.round(Number(ui.volume.value) * 100)}%`);
});

load().catch((error) => showStatus(error?.message || "Could not load settings.", "error"));