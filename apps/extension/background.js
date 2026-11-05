/**
 * BugPilot extension service worker.
 *
 * Responsibilities:
 *  - hold settings (backend URL, sound, animation, consent)
 *  - validate the backend URL before any request leaves the extension
 *  - keep the toolbar badge in sync with the active scan for each tab
 *  - relay messages between the popup and the page overlay
 *
 * No provider API key ever reaches the extension: all AI calls happen on the
 * BugPilot backend.
 */

const DEFAULT_SETTINGS = {
  backendUrl: "http://localhost:8000",
  appUrl: "http://localhost:3000",
  apiKey: "",
  soundEnabled: false,
  volume: 0.35,
  animationsEnabled: true,
  overlaysEnabled: true,
  sendPageText: false,
};

const scansByTab = new Map();

chrome.runtime.onInstalled.addListener(async () => {
  const stored = await chrome.storage.sync.get(DEFAULT_SETTINGS);
  await chrome.storage.sync.set({ ...DEFAULT_SETTINGS, ...stored });
});

function normalizeBackend(value) {
  try {
    const url = new URL(String(value || "").trim());
    if (!["http:", "https:"].includes(url.protocol)) return null;
    if (url.username || url.password) return null;
    if (url.pathname !== "/" && url.pathname !== "") return null;
    return url.origin;
  } catch {
    return null;
  }
}

async function getSettings() {
  const stored = await chrome.storage.sync.get(DEFAULT_SETTINGS);
  const backendUrl = normalizeBackend(stored.backendUrl) || DEFAULT_SETTINGS.backendUrl;
  return { ...DEFAULT_SETTINGS, ...stored, backendUrl };
}

async function api(path, init = {}) {
  const settings = await getSettings();
  const headers = { "Content-Type": "application/json", ...(init.headers || {}) };
  if (settings.apiKey) headers["X-API-Key"] = settings.apiKey;
  const response = await fetch(`${settings.backendUrl}/api/v1${path}`, {
    ...init,
    headers,
  });
  if (!response.ok) {
    let message = response.statusText;
    try {
      const payload = await response.json();
      const detail = payload?.detail ?? payload?.error;
      if (typeof detail === "string") message = detail;
      else if (detail?.message) message = detail.message;
    } catch {
      /* keep status text */
    }
    throw new Error(message);
  }
  return response.json();
}

function setBadge(tabId, scan) {
  if (!tabId) return;
  if (!scan) {
    chrome.action.setBadgeText({ tabId, text: "" });
    return;
  }
  if (scan.status === "running") {
    chrome.action.setBadgeText({ tabId, text: "…" });
    chrome.action.setBadgeBackgroundColor({ tabId, color: "#84cc16" });
  } else if (scan.status === "paused") {
    chrome.action.setBadgeText({ tabId, text: "II" });
    chrome.action.setBadgeBackgroundColor({ tabId, color: "#d97706" });
  } else if (scan.status === "completed") {
    const count = String((scan.findings || []).length);
    chrome.action.setBadgeText({ tabId, text: count });
    chrome.action.setBadgeBackgroundColor({ tabId, color: "#059669" });
  } else if (scan.status === "failed" || scan.status === "cancelled") {
    chrome.action.setBadgeText({ tabId, text: "!" });
    chrome.action.setBadgeBackgroundColor({ tabId, color: "#e11d48" });
  }
}

async function ensurePermission(origin) {
  const pattern = `${origin}/*`;
  const granted = await chrome.permissions.contains({ origins: [pattern] });
  if (granted) return true;
  return chrome.permissions.request({ origins: [pattern] });
}

async function injectOverlay(tabId) {
  await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    try {
      switch (message?.type) {
        case "bugpilot:settings":
          sendResponse({ ok: true, data: await getSettings() });
          return;
        case "bugpilot:save-settings": {
          const clean = { ...message.settings };
          if (clean.backendUrl) {
            const normalized = normalizeBackend(clean.backendUrl);
            if (!normalized) throw new Error("Backend URL must be a bare http(s) origin.");
            clean.backendUrl = normalized;
          }
          if (clean.appUrl) {
            const normalized = normalizeBackend(clean.appUrl);
            if (!normalized) throw new Error("App URL must be a bare http(s) origin.");
            clean.appUrl = normalized;
          }
          await chrome.storage.sync.set(clean);
          sendResponse({ ok: true, data: await getSettings() });
          return;
        }
        case "bugpilot:request-permission": {
          const granted = await ensurePermission(message.origin);
          sendResponse({ ok: true, granted });
          return;
        }
        case "bugpilot:create-scan": {
          const scan = await api("/scans", {
            method: "POST",
            body: JSON.stringify(message.payload),
          });
          const tabId = message.tabId ?? sender?.tab?.id;
          scansByTab.set(tabId, { id: scan.id, status: scan.status, scope: scan.scope });
          await chrome.storage.session.set({ [`bugpilot:tab:${tabId}`]: { id: scan.id, status: scan.status, scope: scan.scope } });
          setBadge(tabId, scan);
          await injectOverlay(tabId);
          await chrome.tabs.sendMessage(tabId, {
            type: "bugpilot:attach",
            scanId: scan.id,
            scope: scan.scope,
            settings: await getSettings(),
          });
          sendResponse({ ok: true, data: scan });
          return;
        }
        case "bugpilot:tab-scan": {
          const tabId = message.tabId;
          let stored = scansByTab.get(tabId);
          if (!stored) {
            const fromSession = await chrome.storage.session.get(`bugpilot:tab:${tabId}`);
            stored = fromSession[`bugpilot:tab:${tabId}`] || null;
          }
          sendResponse({ ok: true, data: stored });
          return;
        }
        case "bugpilot:attach-existing": {
          await injectOverlay(message.tabId);
          await chrome.tabs.sendMessage(message.tabId, {
            type: "bugpilot:attach",
            scanId: message.scanId,
            scope: message.scope,
            settings: await getSettings(),
          });
          sendResponse({ ok: true });
          return;
        }
        case "bugpilot:control": {
          const scan = await api(`/scans/${message.scanId}/${message.action}`, { method: "POST" });
          const tabId = message.tabId ?? sender?.tab?.id;
          setBadge(tabId, scan);
          if (tabId) {
            await chrome.storage.session.set({
              [`bugpilot:tab:${tabId}`]: { id: scan.id, status: scan.status, scope: scan.scope },
            });
          }
          sendResponse({ ok: true, data: scan });
          return;
        }
        case "bugpilot:scan-update": {
          const tabId = sender?.tab?.id;
          setBadge(tabId, { status: message.scan.status, findings: message.scan.findings || [] });
          if (tabId && message.scan?.id) {
            await chrome.storage.session.set({
              [`bugpilot:tab:${tabId}`]: {
                id: message.scan.id,
                status: message.scan.status,
                scope: message.scan.scope,
                findings: (message.scan.findings || []).length,
              },
            });
          }
          sendResponse({ ok: true });
          return;
        }
        case "bugpilot:detach": {
          if (message.tabId) chrome.action.setBadgeText({ tabId: message.tabId, text: "" });
          sendResponse({ ok: true });
          return;
        }
        default:
          sendResponse({ ok: false, error: "Unknown message" });
      }
    } catch (error) {
      sendResponse({ ok: false, error: error?.message || String(error) });
    }
  })();
  return true;
});

chrome.tabs.onRemoved.addListener((tabId) => {
  scansByTab.delete(tabId);
});