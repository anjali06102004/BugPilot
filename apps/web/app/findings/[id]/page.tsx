"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { API, api, evidenceUrl } from "@/lib/api";
import type { Finding } from "@/lib/types";
import {
  Badge,
  ConfidenceBadge,
  ErrorState,
  KeyValue,
  PriorityBadge,
  Section,
  SeverityBadge,
  Skeleton,
  StatusBadge,
} from "@/components/ui";

export default function FindingDetailPage() {
  const params = useParams<{ id: string }>();
  const findingId = params?.id as string;
  const [finding, setFinding] = useState<Finding | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<EvidenceTab>("screenshot");

  const load = useCallback(() => {
    api<Finding>(`/findings/${findingId}`)
      .then((data) => {
        setFinding(data);
        setError(null);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load finding"));
  }, [findingId]);

  useEffect(() => {
    load();
  }, [load]);

  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!finding) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-2/3" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  const screenshots = (finding.evidence ?? []).filter((e) => e.url && e.kind.includes("screenshot"));
  const otherEvidence = (finding.evidence ?? []).filter((e) => !e.kind.includes("screenshot"));
  const countFor = (tab: EvidenceTab) =>
    tab === "screenshot"
      ? screenshots.length
      : otherEvidence.filter((e) => tabFor(e.kind) === tab).length;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link href={`/scans/${finding.session_id}`} className="text-xs text-muted hover:text-lime">
          ← Back to scan
        </Link>
        {finding.issue_id && (
          <Link href={`/issues/${finding.issue_id}`} className="text-xs text-lime hover:underline">
            Open registry record
          </Link>
        )}
      </div>

      <header className="rounded-2xl border border-line bg-panel p-6">
        <div className="flex flex-wrap items-center gap-2">
          <SeverityBadge value={finding.severity} />
          <PriorityBadge value={finding.priority} />
          <ConfidenceBadge value={finding.confidence_label} />
          <StatusBadge value={finding.status} />
          <Badge>{finding.category}</Badge>
          {finding.reproduced && <Badge tone="success">reproduced in scan</Badge>}
        </div>
        <h1 className="mt-3 text-xl font-semibold tracking-tight">{finding.title}</h1>
        <p className="mt-2 max-w-3xl text-sm text-muted">{finding.description}</p>
      </header>

      <div className="grid gap-6 lg:grid-cols-[1.5fr_1fr]">
        <div className="space-y-6">
          <div className="rounded-2xl border border-line bg-panel p-6">
            <Section title="Expected vs observed">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-4">
                  <p className="text-[11px] uppercase tracking-wide text-emerald-300">Expected</p>
                  <p className="mt-1 text-sm">{finding.expected || "Not recorded"}</p>
                </div>
                <div className="rounded-xl border border-rose-500/20 bg-rose-500/5 p-4">
                  <p className="text-[11px] uppercase tracking-wide text-rose-300">Observed</p>
                  <p className="mt-1 text-sm">{finding.actual || "Not recorded"}</p>
                </div>
              </div>
            </Section>
          </div>

          {(finding.steps?.length ?? 0) > 0 && (
            <div className="rounded-2xl border border-line bg-panel p-6">
              <Section title="Reproduction steps">
                <ol className="space-y-2 text-sm">
                  {(finding.steps ?? []).map((step, index) => (
                    <li key={index} className="flex gap-3">
                      <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full border border-line text-[11px] text-muted">
                        {index + 1}
                      </span>
                      <span>{step}</span>
                    </li>
                  ))}
                </ol>
              </Section>
            </div>
          )}

          <div className="rounded-2xl border border-line bg-panel p-6">
            <Section title="Root cause and suggested fix">
              {finding.root_cause ? (
                <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4">
                  <p className="text-[11px] uppercase tracking-wide text-amber-300">
                    Root cause · unconfirmed hypothesis
                  </p>
                  <p className="mt-1 text-sm">{finding.root_cause}</p>
                </div>
              ) : (
                <p className="text-sm text-muted">No root cause has been established.</p>
              )}
              {finding.suggested_fix ? (
                <div className="mt-4 rounded-xl border border-line bg-ink p-4">
                  <p className="text-[11px] uppercase tracking-wide text-muted">Suggested fix</p>
                  <pre className="mt-2 whitespace-pre-wrap font-mono text-xs text-zinc-300">
                    {finding.suggested_fix}
                  </pre>
                </div>
              ) : (
                <p className="mt-4 text-sm text-muted">No fix suggestion was generated.</p>
              )}
              {finding.ai_disclaimer && (
                <p className="mt-3 text-xs text-amber-300/80">{finding.ai_disclaimer}</p>
              )}
            </Section>
          </div>
        </div>

        <div className="space-y-6">
          <div className="rounded-2xl border border-line bg-panel p-6">
            <Section title="Classification">
              <KeyValue
                items={[
                  { label: "Severity", value: <SeverityBadge value={finding.severity} /> },
                  { label: "Priority", value: <PriorityBadge value={finding.priority} /> },
                  { label: "Confidence", value: <ConfidenceBadge value={finding.confidence_label} /> },
                  { label: "Source", value: finding.source },
                  { label: "Detected", value: finding.created_at ?? "—" },
                  { label: "Viewport", value: finding.viewport ?? "—" },
                  { label: "Reproduced", value: `${finding.reproduced_count} / ${finding.verification_attempts} attempts` },
                  { label: "Selector", value: <code className="text-xs">{finding.selector || "—"}</code> },
                ]}
              />
              {(finding.priority_rationale?.length ?? 0) > 0 && (
                <div className="mt-4 rounded-lg border border-line bg-ink p-3">
                  <p className="text-[11px] uppercase tracking-wide text-muted">Why this priority</p>
                  <ul className="mt-1.5 space-y-1 text-xs text-zinc-300">
                    {finding.priority_rationale?.map((reason) => (
                      <li key={reason}>— {reason}</li>
                    ))}
                  </ul>
                </div>
              )}
            </Section>
          </div>

          <div className="rounded-2xl border border-line bg-panel p-6">
            <Section
              title="Evidence"
              subtitle="Everything the agent captured for this finding."
              action={
                <a
                  href={`${API}/api/v1/reports/finding/${finding.id}.md`}
                  className="text-xs text-lime hover:underline"
                >
                  Export finding
                </a>
              }
            >
              <div className="mb-3 flex flex-wrap gap-1">
                {EVIDENCE_TABS.map((tab) => (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    aria-pressed={tab.id === activeTab}
                    className={`rounded-lg border px-2.5 py-1 text-[11px] ${
                      tab.id === activeTab
                        ? "border-lime/60 bg-lime/10 text-lime"
                        : "border-line text-muted hover:border-zinc-500"
                    }`}
                  >
                    {tab.label}
                    <span className="ml-1 text-[10px] opacity-70">{countFor(tab.id)}</span>
                  </button>
                ))}
              </div>

              {activeTab === "screenshot" ? (
                screenshots.length === 0 ? (
                  <p className="text-sm text-muted">No screenshot evidence was captured for this finding.</p>
                ) : (
                  <div className="space-y-3">
                    {screenshots.map((item) => (
                      <a
                        key={item.id}
                        href={evidenceUrl(item.url) ?? "#"}
                        target="_blank"
                        rel="noreferrer"
                        className="block overflow-hidden rounded-lg border border-line"
                      >
                        <img
                          src={evidenceUrl(item.url) ?? ""}
                          alt={`Evidence for ${finding.title}`}
                          className="w-full object-cover"
                        />
                      </a>
                    ))}
                  </div>
                )
              ) : (
                <EvidenceContent items={otherEvidence} />
              )}

              <p className="mt-3 text-xs text-muted">
                Location: <span className="font-mono">{finding.url}</span>
              </p>
            </Section>
          </div>
        </div>
      </div>
    </div>
  );
}
type EvidenceTab = "screenshot" | "dom" | "runtime" | "trace";

const EVIDENCE_TABS: { id: EvidenceTab; label: string }[] = [
  { id: "screenshot", label: "Screenshot" },
  { id: "dom", label: "DOM / CSS" },
  { id: "runtime", label: "Console & network" },
  { id: "trace", label: "Trace" },
];

function tabFor(kind: string): EvidenceTab {
  if (kind.includes("screenshot")) return "screenshot";
  if (kind === "dom" || kind === "css") return "dom";
  if (kind === "console" || kind === "network") return "runtime";
  return "trace";
}

function EvidenceContent({ items }: { items: Finding["evidence"] }) {
  const visible = (items ?? []).filter((item) => tabFor(item.kind) !== "screenshot");
  if (visible.length === 0) {
    return <p className="text-sm text-muted">No evidence of this kind was captured.</p>;
  }
  return (
    <ul className="space-y-2">
      {visible.map((item) => (
        <li key={item.id} className="rounded-lg border border-line bg-ink p-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[11px] uppercase tracking-wide text-muted">{item.kind}</span>
            {item.redacted && <span className="text-[10px] text-amber-300">redacted</span>}
          </div>
          <pre className="mt-1.5 max-h-56 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] text-zinc-300">
            {item.content ? JSON.stringify(item.content, null, 2) : item.path || "No content captured"}
          </pre>
        </li>
      ))}
    </ul>
  );
}