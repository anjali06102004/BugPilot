export const API = process.env.NEXT_PUBLIC_API_URL || "";
export const API_PREFIX = "/api/v1";

/**
 * When `NEXT_PUBLIC_API_URL` is set the browser talks to the API directly
 * (local development). In production it is left empty and requests go through
 * the Next.js proxy at `/backend`, which injects the API key server-side.
 */
const PROXY_BASE = "/backend";

function base(): string {
  return API ? `${API}${API_PREFIX}` : PROXY_BASE;
}

function publicUrl(path: string): string {
  if (path.startsWith("http")) return path;
  if (API) return `${API}${path}`;
  // Evidence and report URLs come back as /api/v1/... and must go through the
  // same proxy as the JSON API.
  return path.startsWith(API_PREFIX) ? `${PROXY_BASE}${path.slice(API_PREFIX.length)}` : `${PROXY_BASE}${path}`;
}

export class ApiError extends Error {
  status: number;
  code: string;
  constructor(message: string, status: number, code: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${base()}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    let message = res.statusText;
    let code = "http_error";
    try {
      const payload = await res.json();
      const detail = payload?.detail ?? payload?.error;
      if (typeof detail === "string") message = detail;
      else if (detail && typeof detail === "object") {
        message = detail.message || message;
        code = detail.code || code;
      }
    } catch {
      try {
        message = await res.text();
      } catch {
        /* ignore */
      }
    }
    throw new ApiError(message, res.status, code);
  }
  return res.json() as Promise<T>;
}

/**
 * WebSockets cannot be proxied by a route handler, so live events are only
 * available when the browser can reach the API directly. With the proxy the
 * workspace falls back to polling, which it labels honestly.
 */
export function wsUrl(scanId: string): string | null {
  if (!API) return null;
  const base = API.replace(/^http/, "ws");
  return `${base}${API_PREFIX}/scans/${scanId}/events`;
}

export function downloadPath(scanId: string, format: "md" | "pdf" | "zip"): string {
  return publicUrl(`${API_PREFIX}/reports/scan/${scanId}.${format}`);
}

export function apiPath(path: string): string {
  return publicUrl(path.startsWith(API_PREFIX) ? path : `${API_PREFIX}${path}`);
}

export function evidenceUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  return publicUrl(url);
}

export function relativeTime(value?: string | null): string {
  if (!value) return "—";
  const then = new Date(value.endsWith("Z") ? value : `${value}Z`).getTime();
  if (Number.isNaN(then)) return value;
  const diff = Date.now() - then;
  const minutes = Math.round(diff / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}