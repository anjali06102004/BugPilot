export type ScanStatus = "queued" | "running" | "completed" | "failed" | "stopped";

export type Finding = {
  id: string;
  session_id: string;
  category: string;
  title: string;
  description: string;
  severity: string;
  confidence: number;
  confidence_label: string;
  status: string;
  source: string;
  url: string;
  selector?: string | null;
  expected?: string | null;
  actual?: string | null;
  steps?: string[];
  suggested_fix?: string | null;
  root_cause?: string | null;
  reproduced_count: number;
  verification_attempts: number;
};

export type ScanEvent = {
  type: string;
  session_id: string;
  message: string;
  mascot: string;
  payload: Record<string, unknown>;
  timestamp: string;
};

export type Scan = {
  id: string;
  start_url: string;
  status: ScanStatus;
  error_message?: string | null;
  pages_tested: number;
  actions_taken: number;
  findings: Finding[];
  events: ScanEvent[];
  config: Record<string, unknown>;
};

export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || res.statusText);
  }
  return res.json() as Promise<T>;
}
