"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api, apiPath, evidenceUrl, relativeTime } from "@/lib/api";
import type { DuplicateSuggestion, Issue, IssueVerification } from "@/lib/types";
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

const TRANSITIONS: Record<string, string[]> = {
  new: ["triaged", "confirmed", "needs_review", "false_positive", "duplicate", "closed"],
  triaged: ["confirmed", "in_progress", "needs_review", "false_positive", "duplicate", "blocked", "closed"],
  confirmed: ["in_progress", "needs_review", "false_positive", "duplicate", "blocked", "closed"],
  in_progress: ["fixed", "blocked", "needs_review", "closed"],
  fixed: ["verified", "reopened", "in_progress"],
  verified: ["closed", "reopened"],
  closed: ["reopened"],
  needs_review: ["triaged", "confirmed", "false_positive", "duplicate", "closed"],
  false_positive: ["new", "triaged"],
  duplicate: ["new"],
  reopened: ["triaged", "confirmed", "in_progress", "false_positive", "closed"],
  blocked: ["in_progress", "triaged", "closed"],
};

export default function IssueDetailPage() {
  const params = useParams<{ id: string }>();
  const issueId = params?.id as string;
  const [issue, setIssue] = useState<Issue | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [assignee, setAssignee] = useState("");
  const [duplicates, setDuplicates] = useState<DuplicateSuggestion[]>([]);
  const [confirmMerge, setConfirmMerge] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [lastVerdict, setLastVerdict] = useState<IssueVerification | null>(null);
  const [form, setForm] = useState({
    summary: "",
    business_impact: "",
    preconditions: "",
    root_cause: "",
    root_cause_status: "unconfirmed",
    suggested_fix: "",
    reproduction_steps: "",
  });

  const load = useCallback(() => {
    api<Issue>(`/issues/${issueId}`)
      .then((data) => {
        setIssue(data);
        setAssignee(data.assigned_to || "");
        setForm({
          summary: data.summary || "",
          business_impact: data.business_impact || "",
          preconditions: data.preconditions || "",
          root_cause: data.root_cause || "",
          root_cause_status: data.root_cause_status || "unconfirmed",
          suggested_fix: data.suggested_fix || "",
          reproduction_steps: (data.reproduction_steps || []).join("\n"),
        });
        setError(null);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load issue"));
  }, [issueId]);

  useEffect(() => {
    load();
  }, [load]);

  const loadDuplicates = useCallback(() => {
    api<{ items: DuplicateSuggestion[] }>(`/issues/${issueId}/duplicates`)
      .then((data) => setDuplicates(data.items))
      .catch(() => setDuplicates([]));
  }, [issueId]);

  useEffect(() => {
    loadDuplicates();
  }, [loadDuplicates]);

  async function saveDocumentation() {
    setBusy(true);
    try {
      await api(`/issues/${issueId}`, {
        method: "PATCH",
        body: JSON.stringify({
          summary: form.summary,
          business_impact: form.business_impact,
          preconditions: form.preconditions,
          root_cause: form.root_cause,
          root_cause_status: form.root_cause_status,
          suggested_fix: form.suggested_fix,
          reproduction_steps: form.reproduction_steps
            .split("\n")
            .map((step) => step.trim())
            .filter(Boolean),
        }),
      });
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the documentation");
    } finally {
      setBusy(false);
    }
  }

  async function mergeSource(sourceId: string) {
    setBusy(true);
    try {
      await api(`/issues/${issueId}/merge`, {
        method: "POST",
        body: JSON.stringify({ source_issue_id: sourceId, author: "dashboard" }),
      });
      setConfirmMerge(null);
      load();
      loadDuplicates();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not merge the issue");
    } finally {
      setBusy(false);
    }
  }

  async function verifyFix() {
    setVerifying(true);
    setLastVerdict(null);
    try {
      const result = await api<IssueVerification & { issue: Issue }>(
        `/issues/${issueId}/verify-fix`,
        {
          method: "POST",
          body: JSON.stringify({ author: "dashboard" }),
        },
      );
      setLastVerdict(result);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not verify the fix");
    } finally {
      setVerifying(false);
    }
  }

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    try {
      await action();
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  function transition(status: string) {
    run(() =>
      api(`/issues/${issueId}/transition`, {
        method: "POST",
        body: JSON.stringify({ status, author: "dashboard" }),
      }),
    );
  }

  function addNote() {
    if (!note.trim()) return;
    run(async () => {
      await api(`/issues/${issueId}/notes`, {
        method: "POST",
        body: JSON.stringify({ body: note, author: "dashboard" }),
      });
      setNote("");
    });
  }

  function assign() {
    run(() =>
      api(`/issues/${issueId}/assign`, {
        method: "POST",
        body: JSON.stringify({ assignee: assignee || null, author: "dashboard" }),
      }),
    );
  }

  if (error && !issue) return <ErrorState message={error} onRetry={load} />;
  if (!issue) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-24" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  const allowed = TRANSITIONS[issue.status] ?? [];
  const screenshots = (issue.evidence ?? []).filter((e) => e.url && e.kind.includes("screenshot"));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link href="/issues" className="text-xs text-muted hover:text-lime">
          ← Back to registry
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <a
            href={apiPath(`/reports/issue/${issue.id}.md`)}
            className="text-xs text-lime hover:underline"
          >
            Export issue Markdown
          </a>
          <a
            href={apiPath(`/reports/issue/${issue.id}.json`)}
            className="text-xs text-muted hover:text-lime"
          >
            JSON
          </a>
        </div>
      </div>

      <header className="rounded-2xl border border-line bg-panel p-6">
        <div className="flex flex-wrap items-center gap-2">
          <SeverityBadge value={issue.severity} />
          <PriorityBadge value={issue.priority} />
          <ConfidenceBadge value={issue.confidence_label} />
          <StatusBadge value={issue.status} />
          <Badge>{issue.category}</Badge>
          {issue.is_regression && <Badge tone="danger">regression</Badge>}
          {issue.assigned_to && <Badge tone="accent">owner: {issue.assigned_to}</Badge>}
        </div>
        <h1 className="mt-3 text-xl font-semibold tracking-tight">{issue.title}</h1>
        <p className="mt-2 max-w-3xl text-sm text-muted">{issue.summary || issue.description}</p>
        <p className="mt-3 break-all font-mono text-xs text-muted">{issue.url}</p>
      </header>

      {error && <ErrorState message={error} onRetry={load} />}

      <div className="grid gap-6 lg:grid-cols-[1.5fr_1fr]">
        <div className="space-y-6">
          <div className="rounded-2xl border border-line bg-panel p-6">
            <Section title="Classification">
              <KeyValue
                items={[
                  { label: "Severity", value: <SeverityBadge value={issue.severity} /> },
                  { label: "Priority", value: <PriorityBadge value={issue.priority} /> },
                  { label: "Confidence", value: <ConfidenceBadge value={issue.confidence_label} /> },
                  { label: "Category", value: issue.category },
                  { label: "Route", value: <code className="text-xs">{issue.route || "—"}</code> },
                  { label: "Component", value: <code className="text-xs">{issue.component || issue.selector || "—"}</code> },
                  { label: "Environment", value: issue.environment || "—" },
                  { label: "Browser", value: issue.browser || "—" },
                  { label: "Viewport", value: issue.viewport || "—" },
                  { label: "Occurrences", value: issue.occurrence_count },
                  { label: "Scans", value: issue.affected_scan_count },
                  { label: "First seen", value: relativeTime(issue.first_seen_at) },
                  { label: "Last seen", value: relativeTime(issue.last_seen_at) },
                  { label: "Last verified", value: issue.last_verified_at ? relativeTime(issue.last_verified_at) : "never" },
                ]}
              />
              {(issue.priority_rationale?.length ?? 0) > 0 && (
                <div className="mt-4 rounded-lg border border-line bg-ink p-3">
                  <p className="text-[11px] uppercase tracking-wide text-muted">Why this priority</p>
                  <ul className="mt-1.5 space-y-1 text-xs text-zinc-300">
                    {issue.priority_rationale?.map((reason) => (
                      <li key={reason}>— {reason}</li>
                    ))}
                  </ul>
                </div>
              )}
            </Section>
          </div>

          <div className="rounded-2xl border border-line bg-panel p-6">
            <Section
              title="Documentation"
              subtitle="Expected and observed behaviour are captured; the rest is yours to complete."
              action={
                <button
                  onClick={saveDocumentation}
                  disabled={busy}
                  className="rounded-lg bg-lime px-3 py-1.5 text-xs font-semibold text-black disabled:opacity-50"
                >
                  Save
                </button>
              }
            >
              <div className="space-y-4 text-sm">
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="Expected behaviour" value={issue.expected} />
                  <Field label="Observed behaviour" value={issue.actual} />
                </div>
                <label className="block text-xs">
                  <span className="uppercase tracking-wide text-muted">Summary</span>
                  <textarea
                    value={form.summary}
                    onChange={(e) => setForm({ ...form, summary: e.target.value })}
                    rows={2}
                    className="mt-1 w-full rounded-lg border border-line bg-ink px-3 py-2 text-sm outline-none focus:border-lime/60"
                  />
                </label>
                <label className="block text-xs">
                  <span className="uppercase tracking-wide text-muted">Business / user impact</span>
                  <textarea
                    value={form.business_impact}
                    onChange={(e) => setForm({ ...form, business_impact: e.target.value })}
                    rows={2}
                    placeholder="Who is affected and how badly?"
                    className="mt-1 w-full rounded-lg border border-line bg-ink px-3 py-2 text-sm outline-none focus:border-lime/60"
                  />
                </label>
                <label className="block text-xs">
                  <span className="uppercase tracking-wide text-muted">Preconditions</span>
                  <input
                    value={form.preconditions}
                    onChange={(e) => setForm({ ...form, preconditions: e.target.value })}
                    placeholder="Signed in as a returning customer, cart not empty…"
                    className="mt-1 w-full rounded-lg border border-line bg-ink px-3 py-2 text-sm outline-none focus:border-lime/60"
                  />
                </label>
                <label className="block text-xs">
                  <span className="uppercase tracking-wide text-muted">Reproduction steps (one per line)</span>
                  <textarea
                    value={form.reproduction_steps}
                    onChange={(e) => setForm({ ...form, reproduction_steps: e.target.value })}
                    rows={3}
                    className="mt-1 w-full rounded-lg border border-line bg-ink px-3 py-2 text-sm outline-none focus:border-lime/60"
                  />
                </label>
                <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] uppercase tracking-wide text-amber-300">Root cause</span>
                    <select
                      value={form.root_cause_status}
                      onChange={(e) => setForm({ ...form, root_cause_status: e.target.value })}
                      className="rounded-md border border-amber-500/30 bg-ink px-2 py-1 text-[11px]"
                    >
                      <option value="unconfirmed">unconfirmed hypothesis</option>
                      <option value="confirmed">confirmed</option>
                    </select>
                  </div>
                  <textarea
                    value={form.root_cause}
                    onChange={(e) => setForm({ ...form, root_cause: e.target.value })}
                    rows={2}
                    placeholder="Only mark confirmed when you have evidence."
                    className="mt-2 w-full rounded-lg border border-line bg-ink px-3 py-2 text-sm outline-none focus:border-amber-400/60"
                  />
                </div>
                <label className="block text-xs">
                  <span className="uppercase tracking-wide text-muted">Suggested fix</span>
                  <textarea
                    value={form.suggested_fix}
                    onChange={(e) => setForm({ ...form, suggested_fix: e.target.value })}
                    rows={2}
                    className="mt-1 w-full rounded-lg border border-line bg-ink px-3 py-2 font-mono text-xs outline-none focus:border-lime/60"
                  />
                </label>
              </div>
            </Section>
          </div>

          <div className="rounded-2xl border border-line bg-panel p-6">
            <Section title="Occurrence history">
              {(issue.occurrences?.length ?? 0) === 0 ? (
                <p className="text-sm text-muted">No occurrences recorded.</p>
              ) : (
                <ul className="divide-y divide-line">
                  {issue.occurrences?.map((occurrence) => (
                    <li key={occurrence.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                      <div className="min-w-0">
                        <p className="truncate font-mono text-xs text-zinc-300">{occurrence.url}</p>
                        <p className="text-[11px] text-muted">
                          {occurrence.viewport || "viewport unknown"} ·{" "}
                          {occurrence.verified ? "verified" : "unverified"}
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        <SeverityBadge value={occurrence.severity} />
                        <Link
                          href={`/scans/${occurrence.session_id}`}
                          className="text-xs text-lime hover:underline"
                        >
                          scan
                        </Link>
                        <span className="text-xs text-muted">{relativeTime(occurrence.created_at)}</span>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Section>
          </div>
        </div>

        <div className="space-y-6">
          <div className="rounded-2xl border border-line bg-panel p-6">
            <Section title="Lifecycle">
              {allowed.length === 0 ? (
                <p className="text-sm text-muted">This issue is in a terminal state.</p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {allowed.map((status) => (
                    <button
                      key={status}
                      disabled={busy}
                      onClick={() => transition(status)}
                      className="rounded-lg border border-line px-3 py-1.5 text-xs capitalize hover:border-lime/60 disabled:opacity-50"
                    >
                      Move to {status.replace(/_/g, " ")}
                    </button>
                  ))}
                </div>
              )}
              <div className="mt-4 flex gap-2">
                <input
                  value={assignee}
                  onChange={(e) => setAssignee(e.target.value)}
                  placeholder="Assignee"
                  className="w-full rounded-lg border border-line bg-ink px-3 py-2 text-sm outline-none focus:border-lime/60"
                />
                <button
                  onClick={assign}
                  disabled={busy}
                  className="shrink-0 rounded-lg border border-line px-3 py-2 text-xs hover:border-lime/60 disabled:opacity-50"
                >
                  Assign
                </button>
              </div>
              <div className="mt-4 border-t border-line pt-4">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-[11px] uppercase tracking-wide text-muted">Post-fix verification</p>
                  <button
                    onClick={verifyFix}
                    disabled={verifying}
                    className="rounded-lg border border-lime/50 bg-lime/10 px-3 py-1.5 text-xs font-medium text-lime disabled:opacity-50"
                  >
                    {verifying ? "Replaying…" : "Verify fix"}
                  </button>
                </div>
                <p className="mt-1 text-[11px] text-muted">
                  Replays the recorded actions and re-runs the detector. A screenshot or a 200
                  response is never treated as proof.
                </p>
                {lastVerdict && <VerdictBox verification={lastVerdict} />}
                {(issue.verifications?.length ?? 0) > 0 && (
                  <ul className="mt-3 space-y-1.5">
                    {issue.verifications?.slice(0, 5).map((verification) => (
                      <li key={verification.id} className="flex items-start gap-2 text-[11px]">
                        <VerdictBadge verdict={verification.verdict} />
                        <span className="min-w-0 flex-1 text-zinc-300">
                          {verification.notes}
                          <span className="ml-1 text-muted">· {relativeTime(verification.created_at)}</span>
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </Section>
          </div>

          <div className="rounded-2xl border border-line bg-panel p-6">
            <Section title="Evidence">
              {screenshots.length === 0 ? (
                <p className="text-sm text-muted">No screenshot evidence stored.</p>
              ) : (
                <div className="space-y-2">
                  {screenshots.slice(0, 4).map((item) => (
                    <a
                      key={item.id}
                      href={evidenceUrl(item.url) ?? "#"}
                      target="_blank"
                      rel="noreferrer"
                      className="block overflow-hidden rounded-lg border border-line"
                    >
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={evidenceUrl(item.url) ?? ""} alt={`Evidence for ${issue.title}`} className="w-full" />
                    </a>
                  ))}
                </div>
              )}
              <p className="mt-2 text-xs text-muted">
                {(issue.evidence?.length ?? 0)} evidence records · retention controlled per project.
              </p>
            </Section>
          </div>

          <div className="rounded-2xl border border-line bg-panel p-6">
            <Section
              title="Possible duplicates"
              subtitle="Suggestions only. Merging keeps both histories under one record."
            >
              {duplicates.length === 0 ? (
                <p className="text-sm text-muted">No similar issues found in this project.</p>
              ) : (
                <ul className="space-y-2">
                  {duplicates.map((candidate) => (
                    <li key={candidate.id} className="rounded-lg border border-line bg-ink p-3">
                      <div className="flex items-start justify-between gap-2">
                        <Link href={`/issues/${candidate.id}`} className="text-sm font-medium hover:text-lime">
                          {candidate.title}
                        </Link>
                        <Badge tone={candidate.score >= 0.75 ? "danger" : "warn"}>
                          {Math.round(candidate.score * 100)}%
                        </Badge>
                      </div>
                      <p className="mt-1 text-[11px] text-muted">{candidate.reasons.join(" · ")}</p>
                      <div className="mt-2 flex items-center gap-2">
                        <SeverityBadge value={candidate.severity} />
                        <PriorityBadge value={candidate.priority} />
                        <StatusBadge value={candidate.status} />
                      </div>
                      {confirmMerge === candidate.id ? (
                        <div className="mt-2 flex items-center gap-2">
                          <span className="text-[11px] text-amber-200">Merge this issue into the current one?</span>
                          <button
                            onClick={() => mergeSource(candidate.id)}
                            disabled={busy}
                            className="rounded-md bg-lime px-2 py-1 text-[11px] font-semibold text-black disabled:opacity-50"
                          >
                            Confirm
                          </button>
                          <button
                            onClick={() => setConfirmMerge(null)}
                            className="rounded-md border border-line px-2 py-1 text-[11px]"
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={() => setConfirmMerge(candidate.id)}
                          className="mt-2 rounded-md border border-line px-2 py-1 text-[11px] hover:border-lime/60"
                        >
                          Merge into this issue
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </Section>
          </div>

          <div className="rounded-2xl border border-line bg-panel p-6">
            <Section title="Activity">
              <div className="mb-3 flex gap-2">
                <input
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="Add a note"
                  className="w-full rounded-lg border border-line bg-ink px-3 py-2 text-sm outline-none focus:border-lime/60"
                />
                <button
                  onClick={addNote}
                  disabled={busy || !note.trim()}
                  className="shrink-0 rounded-lg bg-lime px-3 py-2 text-xs font-medium text-black disabled:opacity-50"
                >
                  Save
                </button>
              </div>
              {(issue.events?.length ?? 0) === 0 ? (
                <p className="text-sm text-muted">No activity yet.</p>
              ) : (
                <ol className="max-h-72 space-y-2 overflow-y-auto">
                  {issue.events
                    ?.slice()
                    .reverse()
                    .map((event) => (
                      <li key={event.id} className="text-xs">
                        <p className="text-zinc-300">
                          {event.kind === "status_change"
                            ? `${event.from_value} → ${event.to_value}`
                            : event.body || event.kind}
                        </p>
                        <p className="text-[10px] uppercase tracking-wide text-muted">
                          {event.author || "system"} · {relativeTime(event.created_at)}
                        </p>
                      </li>
                    ))}
                </ol>
              )}
            </Section>
          </div>
        </div>
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value?: string | null }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-0.5 whitespace-pre-wrap">{value || "Not recorded."}</p>
    </div>
  );
}
function VerdictBadge({ verdict }: { verdict: string }) {
  const tone =
    verdict === "fixed"
      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
      : verdict === "still_failing"
        ? "border-rose-500/40 bg-rose-500/10 text-rose-300"
        : "border-amber-500/40 bg-amber-500/10 text-amber-300";
  return (
    <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-medium ${tone}`}>
      {verdict.replace(/_/g, " ")}
    </span>
  );
}

function VerdictBox({ verification }: { verification: IssueVerification }) {
  const tone =
    verification.verdict === "fixed"
      ? "border-emerald-500/30 bg-emerald-500/5 text-emerald-200"
      : verification.verdict === "still_failing"
        ? "border-rose-500/30 bg-rose-500/5 text-rose-200"
        : "border-amber-500/30 bg-amber-500/5 text-amber-200";
  return (
    <div className={`mt-3 rounded-lg border px-3 py-2 text-xs ${tone}`}>
      <p className="font-medium capitalize">{verification.verdict.replace(/_/g, " ")}</p>
      <p className="mt-1 text-zinc-200">{verification.notes}</p>
      <p className="mt-1 text-[11px] opacity-80">
        replayed {verification.actions_replayed} action(s)
        {verification.actions_failed > 0 ? `, ${verification.actions_failed} failed` : ""} ·{" "}
        {verification.method}
      </p>
    </div>
  );
}
