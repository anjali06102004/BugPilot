"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api, downloadPath, evidenceUrl, wsUrl } from "@/lib/api";
import type { Finding, Scan, ScanEvent } from "@/lib/types";
import { Mascot } from "@/components/Mascot";
import {
  Badge,
  ConfidenceBadge,
  EmptyState,
  ErrorState,
  KeyValue,
  PriorityBadge,
  Progress,
  Section,
  SeverityBadge,
  Skeleton,
  Stat,
  StatusBadge,
} from "@/components/ui";

const TERMINAL = new Set(["completed", "failed", "cancelled", "stopped"]);

export default function ScanWorkspacePage() {
  const params = useParams<{ id: string }>();
  const scanId = params?.id as string;
  const [scan, setScan] = useState<Scan | null>(null);
  const [events, setEvents] = useState<ScanEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [liveConnected, setLiveConnected] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api<Scan>(`/scans/${scanId}`);
      setScan(data);
      setEvents(data.events ?? []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load scan");
    } finally {
      setLoading(false);
    }
  }, [scanId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!scanId) return;
    let closed = false;
    let socket: WebSocket | null = null;
    let retry = 0;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      if (closed) return;
      const endpoint = wsUrl(scanId);
      if (!endpoint) {
        // Behind the server-side proxy there is no WebSocket path; polling
        // below remains the source of truth.
        setLiveConnected(false);
        return;
      }
      try {
        socket = new WebSocket(endpoint);
        socketRef.current = socket;
        socket.onopen = () => {
          retry = 0;
          setLiveConnected(true);
        };
        socket.onclose = () => {
          setLiveConnected(false);
          if (closed) return;
          // Reconnect with a bounded backoff; polling below keeps the UI
          // accurate in the meantime, so a dropped socket never fakes progress.
          retry = Math.min(retry + 1, 5);
          retryTimer = setTimeout(connect, 1000 * retry);
        };
        socket.onerror = () => setLiveConnected(false);
        socket.onmessage = (message) => {
          try {
            const event = JSON.parse(message.data) as ScanEvent;
            if (!event?.type) return;
            setEvents((current) =>
              current.some((e) => e.timestamp === event.timestamp && e.message === event.message)
                ? current
                : [...current, event],
            );
            if (event.type === "scan.completed" || event.type === "finding.created") {
              load();
            }
          } catch {
            /* ignore malformed frames */
          }
        };
      } catch {
        setLiveConnected(false);
      }
    };
    connect();

    return () => {
      closed = true;
      if (retryTimer) clearTimeout(retryTimer);
      socket?.close();
      socketRef.current = null;
    };
  }, [scanId, load]);

  useEffect(() => {
    if (!scan || TERMINAL.has(scan.status)) return;
    const timer = setInterval(load, 4000);
    return () => clearInterval(timer);
  }, [scan, load]);

  async function control(action: "pause" | "resume" | "stop") {
    setBusy(true);
    try {
      await api(`/scans/${scanId}/${action}`, { method: "POST" });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : `Could not ${action} the scan`);
    } finally {
      setBusy(false);
    }
  }

  const lastMascot = useMemo(() => {
    for (let i = events.length - 1; i >= 0; i -= 1) {
      if (events[i].mascot) return events[i].mascot;
    }
    return "idle";
  }, [events]);

  const findings = scan?.findings ?? [];
  const severityCounts = findings.reduce<Record<string, number>>((acc, f) => {
    acc[f.severity] = (acc[f.severity] || 0) + 1;
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      <Link href="/" className="text-xs text-muted hover:text-lime">
        ← Back to overview
      </Link>

      {error && <ErrorState message={error} onRetry={load} />}
      {loading && !scan ? (
        <div className="grid gap-4 lg:grid-cols-3">
          <Skeleton className="h-48 lg:col-span-2" />
          <Skeleton className="h-48" />
        </div>
      ) : scan ? (
        <>
          <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
            <div className="rounded-2xl border border-line bg-panel p-6">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <StatusBadge value={scan.status} />
                    <Badge tone="accent">{scan.scope.type.replace(/_/g, " ")}</Badge>
                    {liveConnected ? <Badge tone="success">live</Badge> : <Badge>polling</Badge>}
                  </div>
                  <h1 className="mt-2 break-all text-lg font-semibold">{scan.start_url}</h1>
                  <p className="mt-1 text-sm text-muted">{scan.scope.summary}</p>
                </div>
                <Mascot state={lastMascot} size={84} showLabel />
              </div>

              <div className="mt-5 grid gap-3 sm:grid-cols-4">
                <Stat label="Pages" value={scan.pages_tested} hint={`${scan.pages_skipped} skipped`} />
                <Stat label="Actions" value={scan.actions_taken} />
                <Stat label="Findings" value={findings.length} />
                <Stat label="Model calls" value={scan.model_calls} />
              </div>

              <div className="mt-5 grid gap-4 sm:grid-cols-2">
                <Progress
                  value={budgetPercent(scan.pages_tested, scan.budgets?.pages)}
                  label={`Pages ${scan.pages_tested}/${scan.budgets?.pages ?? "∞"}`}
                />
                <Progress
                  value={budgetPercent(scan.actions_taken, scan.budgets?.actions)}
                  label={`Actions ${scan.actions_taken}/${scan.budgets?.actions ?? "∞"}`}
                />
                <Progress
                  value={budgetPercent(scan.model_calls, scan.budgets?.model_calls)}
                  label={`Model calls ${scan.model_calls}/${scan.budgets?.model_calls ?? "∞"}`}
                />
                <div className="flex items-center gap-2 text-xs text-muted">
                  <span className="uppercase tracking-[0.14em]">Phase</span>
                  <Badge tone="accent">{phaseLabel(scan, events)}</Badge>
                </div>
              </div>

              <div className="mt-5 flex flex-wrap gap-2">
                {scan.status === "running" && (
                  <button
                    onClick={() => control("pause")}
                    disabled={busy}
                    className="rounded-lg border border-line px-3 py-1.5 text-sm hover:border-amber-400/60 disabled:opacity-50"
                  >
                    Pause
                  </button>
                )}
                {scan.status === "paused" && (
                  <button
                    onClick={() => control("resume")}
                    disabled={busy}
                    className="rounded-lg bg-lime px-3 py-1.5 text-sm font-medium text-black disabled:opacity-50"
                  >
                    Resume
                  </button>
                )}
                {!TERMINAL.has(scan.status) && (
                  <button
                    onClick={() => control("stop")}
                    disabled={busy}
                    className="rounded-lg border border-rose-500/40 px-3 py-1.5 text-sm text-rose-300 hover:bg-rose-500/10 disabled:opacity-50"
                  >
                    Stop scan
                  </button>
                )}
                <a
                  href={downloadPath(scan.id, "md")}
                  className="rounded-lg border border-line px-3 py-1.5 text-sm hover:border-lime/50"
                >
                  Markdown
                </a>
                <a
                  href={downloadPath(scan.id, "pdf")}
                  className="rounded-lg border border-line px-3 py-1.5 text-sm hover:border-lime/50"
                >
                  PDF
                </a>
                <a
                  href={downloadPath(scan.id, "zip")}
                  className="rounded-lg border border-line px-3 py-1.5 text-sm hover:border-lime/50"
                >
                  ZIP + evidence
                </a>
              </div>

              {(scan.stop_reason || scan.error_message) && (
                <p className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-sm text-amber-200">
                  {scan.error_message || scan.stop_reason}
                </p>
              )}
            </div>

            <div className="rounded-2xl border border-line bg-panel p-6">
              <Section title="Scan details">
                <KeyValue
                  items={[
                    { label: "Scan id", value: <span className="font-mono text-xs">{scan.id}</span> },
                    { label: "Project", value: <span className="font-mono text-xs">{scan.project_id}</span> },
                    { label: "Environment", value: String((scan.config as Record<string, unknown>)?.environment ?? "—") },
                    { label: "Started", value: scan.started_at ?? "—" },
                    { label: "Completed", value: scan.completed_at ?? "—" },
                    { label: "Stop reason", value: scan.stop_reason ?? "—" },
                  ]}
                />
              </Section>
              <div className="mt-5 flex flex-wrap gap-2">
                {Object.entries(severityCounts).map(([severity, count]) => (
                  <span key={severity} className="flex items-center gap-1.5">
                    <SeverityBadge value={severity} />
                    <span className="text-xs text-muted">{count}</span>
                  </span>
                ))}
              </div>
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
            <div className="rounded-2xl border border-line bg-panel p-6">
              <Section
                title="Inspected pages"
                subtitle="Exactly the pages the worker opened, with the captured view."
              >
                {(scan.pages?.length ?? 0) === 0 ? (
                  <EmptyState title="No pages recorded yet" description="Pages appear as the worker inspects them." />
                ) : (
                  <ul className="grid gap-3 sm:grid-cols-2">
                    {scan.pages?.map((page) => (
                      <li key={page.id} className="overflow-hidden rounded-xl border border-line bg-ink">
                        {page.screenshot ? (
                          <a href={evidenceUrl(page.screenshot) ?? "#"} target="_blank" rel="noreferrer">
                            {/* eslint-disable-next-line @next/next/no-img-element */}
                            <img
                              src={evidenceUrl(page.screenshot) ?? ""}
                              alt={`Screenshot of ${page.url}`}
                              className="h-40 w-full object-cover object-top"
                            />
                          </a>
                        ) : (
                          <div className="grid h-40 place-items-center text-xs text-muted">No screenshot</div>
                        )}
                        <div className="p-3">
                          <p className="truncate text-sm font-medium">{page.title || "Untitled page"}</p>
                          <p className="mt-0.5 truncate font-mono text-[11px] text-muted">{page.url}</p>
                          <div className="mt-2 flex items-center gap-2">
                            <Badge>{page.viewport_name}</Badge>
                            {!page.in_scope && <Badge tone="danger">skipped</Badge>}
                          </div>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </Section>
            </div>

            <div className="rounded-2xl border border-line bg-panel p-6">
              <Section title="Actions performed" subtitle="Blocked attempts are shown, never hidden.">
                {(scan.actions?.length ?? 0) === 0 ? (
                  <EmptyState title="No actions yet" />
                ) : (
                  <ol className="max-h-[24rem] space-y-1.5 overflow-y-auto pr-1">
                    {scan.actions?.map((action) => (
                      <li key={action.id} className="flex items-start gap-2 text-xs">
                        <span
                          className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${
                            action.blocked ? "bg-amber-400" : "bg-lime/70"
                          }`}
                        />
                        <div className="min-w-0">
                          <p className="text-zinc-300">
                            <span className="uppercase tracking-wide text-muted">{action.type}</span>{" "}
                            {action.description}
                          </p>
                          {action.blocked && (
                            <p className="text-[11px] text-amber-300">{action.block_reason}</p>
                          )}
                        </div>
                      </li>
                    ))}
                  </ol>
                )}
              </Section>
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
            <div className="rounded-2xl border border-line bg-panel p-6">
              <Section
                title="Findings"
                subtitle="Written to the Bug Registry as they are confirmed."
                action={
                  <Link href="/issues" className="text-xs text-lime hover:underline">
                    View registry
                  </Link>
                }
              >
                {findings.length === 0 ? (
                  <EmptyState
                    title={TERMINAL.has(scan.status) ? "No issues found in this scope" : "No findings yet"}
                    description={
                      TERMINAL.has(scan.status)
                        ? "The agent inspected the selected scope and recorded no defects. That is not a guarantee the app is bug-free."
                        : "The mascot is inspecting the page. Findings appear here as they are verified."
                    }
                  />
                ) : (
                  <ul className="space-y-2">
                    {findings.map((finding) => (
                      <FindingRow key={finding.id} finding={finding} />
                    ))}
                  </ul>
                )}
              </Section>
            </div>

            <div className="rounded-2xl border border-line bg-panel p-6">
              <Section title="Agent activity" subtitle="Only events the agent actually emitted.">
                {events.length === 0 ? (
                  <EmptyState title="Waiting for the worker" description="Scan events will appear here." />
                ) : (
                  <ol className="max-h-[28rem] space-y-2 overflow-y-auto pr-1">
                    {events
                      .slice()
                      .reverse()
                      .map((event, index) => (
                        <li key={`${event.timestamp}-${index}`} className="flex gap-2 text-xs">
                          <span
                            className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${
                              event.type === "finding.created"
                                ? "bg-rose-400"
                                : event.type === "scan.completed"
                                  ? "bg-emerald-400"
                                  : "bg-lime/70"
                            }`}
                          />
                          <div className="min-w-0">
                            <p className="text-zinc-300">{event.message}</p>
                            <p className="text-[10px] uppercase tracking-wide text-muted">
                              {event.type} · {new Date(event.timestamp).toLocaleTimeString()}
                            </p>
                          </div>
                        </li>
                      ))}
                  </ol>
                )}
              </Section>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}

function budgetPercent(used: number, budget?: number): number {
  if (!budget || budget <= 0) return 0;
  return Math.min(100, (used / budget) * 100);
}

const PHASE_LABELS: Record<string, string> = {
  "scan.started": "starting",
  "page.loaded": "inspecting page",
  "action.planned": "planning",
  "action.started": "interacting",
  "action.completed": "observing",
  "action.blocked": "scope guard",
  "detector.triggered": "detecting",
  "verification.started": "verifying",
  "verification.completed": "verifying",
  "finding.created": "documenting",
  "scan.paused": "paused",
  "scan.resumed": "inspecting",
  "scan.completed": "complete",
};

function phaseLabel(scan: Scan, events: ScanEvent[]): string {
  if (scan.status === "queued") return "queued";
  if (scan.status === "paused") return "paused";
  if (["completed", "failed", "cancelled", "stopped"].includes(scan.status)) return "complete";
  const latest = events[events.length - 1];
  return (latest && PHASE_LABELS[latest.type]) || scan.status;
}

function FindingRow({ finding }: { finding: Finding }) {
  return (
    <li className="rounded-xl border border-line bg-ink/60 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge value={finding.severity} />
        <PriorityBadge value={finding.priority} />
        <ConfidenceBadge value={finding.confidence_label} />
        <span className="text-[11px] uppercase tracking-wide text-muted">{finding.category}</span>
        {finding.reproduced && <Badge tone="success">reproduced</Badge>}
      </div>
      <Link href={`/findings/${finding.id}`} className="mt-1.5 block text-sm font-medium hover:text-lime">
        {finding.title}
      </Link>
      <p className="mt-1 line-clamp-2 text-xs text-muted">{finding.description}</p>
      {finding.screenshot && (
        <a
          href={evidenceUrl(finding.screenshot) ?? "#"}
          target="_blank"
          rel="noreferrer"
          className="mt-2 inline-block text-[11px] text-lime hover:underline"
        >
          Open screenshot evidence
        </a>
      )}
    </li>
  );
}