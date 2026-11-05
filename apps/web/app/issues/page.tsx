"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, relativeTime } from "@/lib/api";
import type { Issue, IssueStatus, IssueTrendPoint, Project } from "@/lib/types";
import {
  Badge,
  ConfidenceBadge,
  EmptyState,
  ErrorState,
  PriorityBadge,
  Section,
  SeverityBadge,
  Skeleton,
  Stat,
  StatusBadge,
} from "@/components/ui";

const SEVERITIES = ["critical", "high", "medium", "low", "informational"];
const PRIORITIES = ["P0", "P1", "P2", "P3"];
const CATEGORIES = [
  "visual",
  "layout",
  "overflow",
  "broken_image",
  "console",
  "network",
  "accessibility",
  "responsive",
  "navigation",
  "forms",
  "content",
  "functional",
];
const STATUSES: IssueStatus[] = [
  "new",
  "triaged",
  "needs_review",
  "confirmed",
  "in_progress",
  "blocked",
  "fixed",
  "verified",
  "reopened",
  "closed",
  "false_positive",
  "duplicate",
];
const SORTS = [
  { id: "last_seen_at", label: "Last seen" },
  { id: "priority", label: "Priority" },
  { id: "severity", label: "Severity" },
  { id: "occurrence_count", label: "Recurrence" },
  { id: "first_seen_at", label: "First seen" },
  { id: "status", label: "Status" },
  { id: "title", label: "Title" },
];
const PAGE_SIZE = 50;

type Stats = {
  total: number;
  open: number;
  regressions: number;
  by_severity: Record<string, number>;
  by_priority: Record<string, number>;
  by_status: Record<string, number>;
  by_confidence: Record<string, number>;
};

const BULK_TARGETS = ["triaged", "confirmed", "needs_review", "false_positive", "closed"];

export default function RegistryPage() {
  const [issues, setIssues] = useState<Issue[]>([]);
  const [total, setTotal] = useState(0);
  const [groupCounts, setGroupCounts] = useState<Record<string, number> | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [trends, setTrends] = useState<IssueTrendPoint[]>([]);
  const [trendTotals, setTrendTotals] = useState({ new: 0, resolved: 0, reopened: 0 });
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const [severity, setSeverity] = useState("");
  const [priority, setPriority] = useState("");
  const [status, setStatus] = useState("");
  const [confidence, setConfidence] = useState("");
  const [category, setCategory] = useState("");
  const [projectId, setProjectId] = useState("");
  const [assigned, setAssigned] = useState("");
  const [regressionOnly, setRegressionOnly] = useState(false);
  const [recurringOnly, setRecurringOnly] = useState(false);
  const [firstSeenAfter, setFirstSeenAfter] = useState("");
  const [sort, setSort] = useState("last_seen_at");
  const [groupBy, setGroupBy] = useState("");
  const [offset, setOffset] = useState(0);

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirmBulk, setConfirmBulk] = useState<string | null>(null);
  const [bulkBusy, setBulkBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (severity) params.set("severity", severity);
      if (priority) params.set("priority", priority);
      if (status) params.set("status", status);
      if (confidence) params.set("confidence", confidence);
      if (category) params.set("category", category);
      if (projectId) params.set("project_id", projectId);
      if (assigned) params.set("assigned_to", assigned);
      if (regressionOnly) params.set("regression", "true");
      if (recurringOnly) params.set("recurring", "true");
      if (firstSeenAfter) params.set("first_seen_after", firstSeenAfter);
      if (query) params.set("q", query);
      if (groupBy) params.set("group_by", groupBy);
      params.set("sort", sort);
      params.set("order", ["severity", "priority", "status"].includes(sort) ? "asc" : "desc");
      params.set("limit", String(PAGE_SIZE));
      params.set("offset", String(offset));
      const data = await api<{
        items: Issue[];
        total: number;
        group_counts?: Record<string, number>;
      }>(`/issues?${params.toString()}`);
      setIssues(data.items);
      setTotal(data.total);
      setGroupCounts(data.group_counts ?? null);
      setError(null);
      setSelected(new Set());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the registry");
    } finally {
      setLoading(false);
    }
  }, [
    severity,
    priority,
    status,
    confidence,
    category,
    projectId,
    assigned,
    regressionOnly,
    recurringOnly,
    firstSeenAfter,
    query,
    groupBy,
    sort,
    offset,
  ]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    setOffset(0);
  }, [severity, priority, status, confidence, category, projectId, assigned, regressionOnly, recurringOnly, firstSeenAfter, query, groupBy, sort]);

  useEffect(() => {
    api<Stats>("/issues/stats")
      .then(setStats)
      .catch(() => setStats(null));
    api<{ points: IssueTrendPoint[]; totals: { new: number; resolved: number; reopened: number } }>(
      "/issues/trends?days=14",
    )
      .then((data) => {
        setTrends(data.points);
        setTrendTotals(data.totals);
      })
      .catch(() => setTrends([]));
    api<Project[]>("/projects")
      .then(setProjects)
      .catch(() => setProjects([]));
  }, []);

  const grouped = useMemo(() => {
    if (!groupBy) return null;
    const map: Record<string, Issue[]> = {};
    for (const issue of issues) {
      const key = String((issue as unknown as Record<string, unknown>)[groupBy] ?? "unknown");
      map[key] = map[key] ? [...map[key], issue] : [issue];
    }
    return map;
  }, [issues, groupBy]);

  function toggle(id: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function runBulk(action: string) {
    if (!confirmBulk) return;
    setBulkBusy(true);
    setNotice(null);
    try {
      const result = await api<{ updated: number; failed: number }>("/issues/bulk", {
        method: "POST",
        body: JSON.stringify({
          issue_ids: [...selected],
          action: "transition",
          status: action,
          author: "dashboard",
        }),
      });
      setNotice(
        `Updated ${result.updated} issue(s)${result.failed ? `, ${result.failed} skipped` : ""}.`,
      );
      setConfirmBulk(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bulk update failed");
    } finally {
      setBulkBusy(false);
    }
  }

  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const pageIndex = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Living Bug Registry</h1>
          <p className="mt-1 text-sm text-muted">
            One canonical record per defect. Every scan adds an occurrence instead of a duplicate.
          </p>
        </div>
        <Badge tone="accent">{total} issues</Badge>
      </header>

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Total issues" value={stats?.total ?? "—"} />
        <Stat label="Open" value={stats?.open ?? "—"} />
        <Stat
          label="Regressions"
          value={stats?.regressions ?? "—"}
          tone={(stats?.regressions ?? 0) > 0 ? "danger" : undefined}
        />
        <Stat label="Confirmed" value={stats?.by_confidence?.confirmed ?? "—"} />
      </section>

      <div className="rounded-2xl border border-line bg-panel p-6">
        <Section
          title="Last 14 days"
          subtitle="New, resolved and reopened issues from registry history."
          action={
            <div className="flex gap-2 text-xs">
              <Badge tone="accent">new {trendTotals.new}</Badge>
              <Badge tone="success">resolved {trendTotals.resolved}</Badge>
              <Badge tone={trendTotals.reopened > 0 ? "danger" : "neutral"}>
                reopened {trendTotals.reopened}
              </Badge>
            </div>
          }
        >
          {trends.length === 0 ? (
            <p className="text-sm text-muted">No trend data yet.</p>
          ) : (
            <div className="h-48">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={trends}>
                  <CartesianGrid stroke="#27272a" strokeDasharray="3 3" vertical={false} />
                  <XAxis
                    dataKey="date"
                    tickFormatter={(value: string) => value.slice(5)}
                    stroke="#71717a"
                    fontSize={11}
                    minTickGap={24}
                  />
                  <YAxis stroke="#71717a" fontSize={11} allowDecimals={false} width={28} />
                  <Tooltip
                    contentStyle={{ background: "#101114", border: "1px solid #27272a", fontSize: 12 }}
                  />
                  <Area type="monotone" dataKey="new" name="New" stroke="#84cc16" fill="#84cc1633" />
                  <Area type="monotone" dataKey="resolved" name="Resolved" stroke="#34d399" fill="#34d39922" />
                  <Area type="monotone" dataKey="reopened" name="Reopened" stroke="#f43f5e" fill="#f43f5e22" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </Section>
      </div>

      <div className="rounded-2xl border border-line bg-panel p-4">
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          <label className="text-sm lg:col-span-2">
            Search
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Title, summary, route or selector"
              className="mt-1 w-full rounded-lg border border-line bg-ink px-3 py-2 text-sm outline-none focus:border-lime/60"
            />
          </label>
          <label className="text-sm">
            Project
            <select
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              className="mt-1 w-full rounded-lg border border-line bg-ink px-3 py-2 text-sm"
            >
              <option value="">All projects</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            Category
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="mt-1 w-full rounded-lg border border-line bg-ink px-3 py-2 text-sm"
            >
              <option value="">All</option>
              {CATEGORIES.map((item) => (
                <option key={item} value={item}>
                  {item.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            Severity
            <select
              value={severity}
              onChange={(e) => setSeverity(e.target.value)}
              className="mt-1 w-full rounded-lg border border-line bg-ink px-3 py-2 text-sm"
            >
              <option value="">All</option>
              {SEVERITIES.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            Priority
            <select
              value={priority}
              onChange={(e) => setPriority(e.target.value)}
              className="mt-1 w-full rounded-lg border border-line bg-ink px-3 py-2 text-sm"
            >
              <option value="">All</option>
              {PRIORITIES.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            Status
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="mt-1 w-full rounded-lg border border-line bg-ink px-3 py-2 text-sm"
            >
              <option value="">All</option>
              {STATUSES.map((item) => (
                <option key={item} value={item}>
                  {item.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            Confidence
            <select
              value={confidence}
              onChange={(e) => setConfidence(e.target.value)}
              className="mt-1 w-full rounded-lg border border-line bg-ink px-3 py-2 text-sm"
            >
              <option value="">All</option>
              <option value="confirmed">confirmed</option>
              <option value="likely">likely</option>
              <option value="possible">possible</option>
              <option value="not_a_bug">not a bug</option>
            </select>
          </label>
          <label className="text-sm">
            Owner
            <input
              value={assigned}
              onChange={(e) => setAssigned(e.target.value)}
              placeholder="assigned to"
              className="mt-1 w-full rounded-lg border border-line bg-ink px-3 py-2 text-sm outline-none focus:border-lime/60"
            />
          </label>
          <label className="text-sm">
            First seen after
            <input
              type="date"
              value={firstSeenAfter}
              onChange={(e) => setFirstSeenAfter(e.target.value)}
              className="mt-1 w-full rounded-lg border border-line bg-ink px-3 py-2 text-sm"
            />
          </label>
          <label className="text-sm">
            Sort
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value)}
              className="mt-1 w-full rounded-lg border border-line bg-ink px-3 py-2 text-sm"
            >
              {SORTS.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            Group by
            <select
              value={groupBy}
              onChange={(e) => setGroupBy(e.target.value)}
              className="mt-1 w-full rounded-lg border border-line bg-ink px-3 py-2 text-sm"
            >
              <option value="">No grouping</option>
              <option value="severity">Severity</option>
              <option value="priority">Priority</option>
              <option value="status">Status</option>
              <option value="category">Category</option>
              <option value="project_id">Project</option>
              <option value="assigned_to">Owner</option>
            </select>
          </label>
        </div>
        <div className="mt-3 flex flex-wrap gap-4">
          <label className="flex items-center gap-2 text-sm text-zinc-300">
            <input
              type="checkbox"
              checked={regressionOnly}
              onChange={(e) => setRegressionOnly(e.target.checked)}
              className="h-4 w-4 rounded border-line bg-ink"
            />
            Regressions only
          </label>
          <label className="flex items-center gap-2 text-sm text-zinc-300">
            <input
              type="checkbox"
              checked={recurringOnly}
              onChange={(e) => setRecurringOnly(e.target.checked)}
              className="h-4 w-4 rounded border-line bg-ink"
            />
            Recurring only (seen more than once)
          </label>
          {(query ||
            severity ||
            priority ||
            status ||
            confidence ||
            category ||
            projectId ||
            assigned ||
            firstSeenAfter ||
            regressionOnly ||
            recurringOnly) && (
            <button
              onClick={() => {
                setQuery("");
                setSeverity("");
                setPriority("");
                setStatus("");
                setConfidence("");
                setCategory("");
                setProjectId("");
                setAssigned("");
                setFirstSeenAfter("");
                setRegressionOnly(false);
                setRecurringOnly(false);
              }}
              className="text-xs text-lime hover:underline"
            >
              Clear filters
            </button>
          )}
        </div>
      </div>

      {notice && <p className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-3 py-2 text-sm text-emerald-200">{notice}</p>}
      {error && <ErrorState message={error} onRetry={load} />}

      {selected.size > 0 && (
        <div className="sticky top-16 z-30 flex flex-wrap items-center gap-2 rounded-xl border border-lime/40 bg-panel/95 px-3 py-2 backdrop-blur">
          <span className="text-xs text-zinc-300">{selected.size} selected</span>
          {confirmBulk ? (
            <>
              <span className="text-xs text-amber-200">Move {selected.size} issue(s) to “{confirmBulk.replace(/_/g, " ")}”?</span>
              <button
                onClick={() => runBulk(confirmBulk)}
                disabled={bulkBusy}
                className="rounded-lg bg-lime px-3 py-1 text-xs font-semibold text-black disabled:opacity-50"
              >
                {bulkBusy ? "Applying…" : "Confirm"}
              </button>
              <button
                onClick={() => setConfirmBulk(null)}
                disabled={bulkBusy}
                className="rounded-lg border border-line px-3 py-1 text-xs"
              >
                Cancel
              </button>
            </>
          ) : (
            <>
              {BULK_TARGETS.map((target) => (
                <button
                  key={target}
                  onClick={() => setConfirmBulk(target)}
                  className="rounded-lg border border-line px-2.5 py-1 text-xs capitalize hover:border-lime/60"
                >
                  {target.replace(/_/g, " ")}
                </button>
              ))}
              <button onClick={() => setSelected(new Set())} className="text-xs text-muted hover:text-zinc-200">
                Clear selection
              </button>
            </>
          )}
        </div>
      )}

      {loading ? (
        <div className="space-y-2">
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
        </div>
      ) : issues.length === 0 ? (
        <EmptyState
          title="No issues match these filters"
          description="Either the registry is empty or your filters are excluding everything."
        />
      ) : grouped ? (
        <div className="space-y-6">
          {Object.entries(grouped).map(([key, items]) => (
            <Section
              key={key}
              title={`${key.replace(/_/g, " ")} · ${groupCounts?.[key] ?? items.length}`}
            >
              <IssueTable issues={items} selected={selected} onToggle={toggle} />
            </Section>
          ))}
        </div>
      ) : (
        <IssueTable issues={issues} selected={selected} onToggle={toggle} />
      )}

      <div className="flex items-center justify-between text-xs text-muted">
        <span>
          Showing {issues.length} of {total} · page {pageIndex} of {pages}
        </span>
        <div className="flex gap-2">
          <button
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            className="rounded-lg border border-line px-3 py-1 disabled:opacity-40"
          >
            Previous
          </button>
          <button
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => setOffset(offset + PAGE_SIZE)}
            className="rounded-lg border border-line px-3 py-1 disabled:opacity-40"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}

function IssueTable({
  issues,
  selected,
  onToggle,
}: {
  issues: Issue[];
  selected: Set<string>;
  onToggle: (id: string) => void;
}) {
  return (
    <div className="overflow-hidden rounded-2xl border border-line">
      <table className="w-full text-left text-sm">
        <thead className="bg-white/[0.03] text-[11px] uppercase tracking-wide text-muted">
          <tr>
            <th className="w-8 px-3 py-2">
              <span className="sr-only">Select</span>
            </th>
            <th className="px-4 py-2 font-medium">Issue</th>
            <th className="px-3 py-2 font-medium">Severity</th>
            <th className="px-3 py-2 font-medium">Priority</th>
            <th className="px-3 py-2 font-medium">Confidence</th>
            <th className="px-3 py-2 font-medium">Status</th>
            <th className="px-3 py-2 font-medium">Occurrences</th>
            <th className="px-3 py-2 font-medium">Last seen</th>
          </tr>
        </thead>
        <tbody>
          {issues.map((issue) => (
            <tr key={issue.id} className="border-t border-line hover:bg-white/[0.02]">
              <td className="px-3 py-3 align-top">
                <input
                  type="checkbox"
                  checked={selected.has(issue.id)}
                  onChange={() => onToggle(issue.id)}
                  aria-label={`Select ${issue.title}`}
                  className="h-4 w-4 rounded border-line bg-ink"
                />
              </td>
              <td className="max-w-md px-4 py-3">
                <Link href={`/issues/${issue.id}`} className="font-medium hover:text-lime">
                  {issue.title}
                </Link>
                <p className="mt-0.5 truncate font-mono text-[11px] text-muted">
                  {issue.route || issue.url}
                </p>
                <div className="mt-1 flex flex-wrap gap-1">
                  {issue.is_regression && <Badge tone="danger">regression</Badge>}
                  {issue.assigned_to && <Badge>owner: {issue.assigned_to}</Badge>}
                </div>
              </td>
              <td className="px-3 py-3">
                <SeverityBadge value={issue.severity} />
              </td>
              <td className="px-3 py-3">
                <PriorityBadge value={issue.priority} />
              </td>
              <td className="px-3 py-3">
                <ConfidenceBadge value={issue.confidence_label} />
              </td>
              <td className="px-3 py-3">
                <StatusBadge value={issue.status} />
              </td>
              <td className="px-3 py-3 tabular-nums text-zinc-300">{issue.occurrence_count}</td>
              <td className="whitespace-nowrap px-3 py-3 text-xs text-muted">
                {relativeTime(issue.last_seen_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}