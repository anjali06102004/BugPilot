"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, relativeTime } from "@/lib/api";
import type { Dashboard, ScanScopeType } from "@/lib/types";
import { Mascot } from "@/components/Mascot";
import {
  Badge,
  EmptyState,
  ErrorState,
  PriorityBadge,
  Section,
  SeverityBadge,
  Skeleton,
  Stat,
  StatusBadge,
} from "@/components/ui";

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

const SCOPES: { id: ScanScopeType; label: string; description: string }[] = [
  {
    id: "single_url",
    label: "Current URL",
    description: "Inspect exactly one page. Never follows links.",
  },
  {
    id: "full_site",
    label: "Full website",
    description: "Crawl authorized same-origin routes within your budgets.",
  },
  {
    id: "selected_element",
    label: "Select element",
    description: "Inspect one component and its local context only.",
  },
];

const VIEWPORTS = [
  { id: "desktop", label: "Desktop 1280" },
  { id: "tablet", label: "Tablet 768" },
  { id: "mobile", label: "Mobile 390" },
  { id: "all", label: "All three" },
];

const VIEWPORT_DEFS: Record<string, { name: string; width: number; height: number }[]> = {
  desktop: [{ name: "desktop-1280", width: 1280, height: 720 }],
  tablet: [{ name: "tablet-768", width: 768, height: 1024 }],
  mobile: [{ name: "mobile-390", width: 390, height: 844 }],
  all: [
    { name: "desktop-1280", width: 1280, height: 720 },
    { name: "tablet-768", width: 768, height: 1024 },
    { name: "mobile-390", width: 390, height: 844 },
  ],
};

export default function OverviewPage() {
  const router = useRouter();
  const [dash, setDash] = useState<Dashboard | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [url, setUrl] = useState("http://127.0.0.1:4173/");
  const [projectName, setProjectName] = useState("Broken Shop");
  const [projectId, setProjectId] = useState<string | null>(null);
  const [environment, setEnvironment] = useState("development");
  const [scope, setScope] = useState<ScanScopeType>("single_url");
  const [selector, setSelector] = useState("");
  const [elementLabel, setElementLabel] = useState("");
  const [viewport, setViewport] = useState("mobile");
  const [categories, setCategories] = useState<string[]>(CATEGORIES);
  const [maxPages, setMaxPages] = useState(10);
  const [maxDepth, setMaxDepth] = useState(2);
  const [interactionDepth, setInteractionDepth] = useState("safe");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    api<Dashboard>("/dashboard")
      .then((data) => {
        setDash(data);
        setLoadError(null);
      })
      .catch((err) => setLoadError(err instanceof Error ? err.message : "Could not load dashboard"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      let activeProject = projectId;
      if (!activeProject) {
        const projects = await api<{ id: string; website_url: string }[]>("/projects").catch(() => []);
        const match = projects.find((p) => p.website_url === url);
        if (match) activeProject = match.id;
        else {
          const created = await api<{ id: string }>("/projects", {
            method: "POST",
            body: JSON.stringify({ name: projectName, website_url: url, environment }),
          });
          activeProject = created.id;
        }
        setProjectId(activeProject);
      }

      const scan = await api<{ id: string }>("/scans", {
        method: "POST",
        body: JSON.stringify({
          url,
          project_id: activeProject,
          project_name: projectName,
          environment,
          scope: {
            type: scope,
            max_depth: maxDepth,
            interaction_depth: interactionDepth,
            element_selector: scope === "selected_element" ? selector : undefined,
            element_label: scope === "selected_element" ? elementLabel || selector : undefined,
          },
          config: {
            categories,
            viewports: VIEWPORT_DEFS[viewport],
            max_pages: scope === "full_site" ? maxPages : 1,
            max_duration_seconds: 180,
            max_actions: 25,
            allow_destructive: false,
          },
        }),
      });
      router.push(`/scans/${scan.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start scan");
    } finally {
      setBusy(false);
    }
  }

  const severityTotal = dash ? Object.values(dash.by_severity).reduce((a, b) => a + b, 0) : 0;

  return (
    <div className="space-y-8">
      <div className="flex flex-col gap-4 rounded-2xl border border-line bg-panel p-6 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-4">
          <Mascot state="exploring" size={72} />
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Your UI quality cockpit</h1>
            <p className="mt-1 max-w-xl text-sm text-muted">
              Discover, investigate, verify and document real UI defects. Every finding is tied to the
              evidence the agent actually collected.
            </p>
          </div>
        </div>
        {dash && (
          <div className="flex flex-wrap gap-2">
            <Badge tone="accent">{dash.open_issues} open issues</Badge>
            <Badge tone="warn">{dash.regressions} regressions</Badge>
            <Badge>{dash.active_scans} active scans</Badge>
          </div>
        )}
      </div>

      {loadError && <ErrorState message={loadError} onRetry={load} />}

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {loading && !dash ? (
          Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24" />)
        ) : (
          <>
            <Stat label="Open issues" value={dash?.open_issues ?? 0} hint="across all projects" />
            <Stat
              label="Regressions"
              value={dash?.regressions ?? 0}
              hint="fixed then reappeared"
              tone={(dash?.regressions ?? 0) > 0 ? "danger" : undefined}
            />
            <Stat label="Pages inspected" value={dash?.pages_tested ?? 0} />
            <Stat
              label="False positive rate"
              value={`${Math.round((dash?.false_positive_rate ?? 0) * 100)}%`}
              hint="from triage decisions"
            />
          </>
        )}
      </section>

      <div className="grid gap-6 lg:grid-cols-[1.05fr_0.95fr]">
        <form onSubmit={onSubmit} className="space-y-5 rounded-2xl border border-line bg-panel p-6">
          <div>
            <h2 className="text-lg font-semibold">Start a scan</h2>
            <p className="mt-1 text-sm text-muted">
              You choose what to inspect. The agent only investigates inside that boundary.
            </p>
          </div>

          <label className="block text-sm">
            Website URL
            <input
              required
              type="url"
              value={url}
              onChange={(e) => {
                setUrl(e.target.value);
                setProjectId(null);
              }}
              className="mt-1 w-full rounded-lg border border-line bg-ink px-3 py-2 outline-none focus:border-lime/60"
            />
          </label>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="text-sm">
              Project name
              <input
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                className="mt-1 w-full rounded-lg border border-line bg-ink px-3 py-2 outline-none focus:border-lime/60"
              />
            </label>
            <label className="text-sm">
              Environment
              <select
                value={environment}
                onChange={(e) => setEnvironment(e.target.value)}
                className="mt-1 w-full rounded-lg border border-line bg-ink px-3 py-2"
              >
                <option value="development">Development</option>
                <option value="staging">Staging</option>
                <option value="production">Production</option>
              </select>
            </label>
          </div>

          <fieldset>
            <legend className="text-sm font-medium">What should BugPilot inspect?</legend>
            <div className="mt-2 grid gap-2 sm:grid-cols-3">
              {SCOPES.map((item) => {
                const active = scope === item.id;
                return (
                  <button
                    key={item.id}
                    type="button"
                    aria-pressed={active}
                    onClick={() => setScope(item.id)}
                    className={`rounded-xl border p-3 text-left transition-colors ${
                      active
                        ? "border-lime/60 bg-lime/10"
                        : "border-line bg-ink hover:border-zinc-500"
                    }`}
                  >
                    <span className={`block text-sm font-medium ${active ? "text-lime" : ""}`}>
                      {item.label}
                    </span>
                    <span className="mt-1 block text-xs text-muted">{item.description}</span>
                  </button>
                );
              })}
            </div>
          </fieldset>

          {scope === "selected_element" && (
            <div className="grid gap-4 rounded-xl border border-line bg-ink p-3 sm:grid-cols-2">
              <label className="text-sm">
                CSS selector
                <input
                  required
                  value={selector}
                  onChange={(e) => setSelector(e.target.value)}
                  placeholder="#pay, form.checkout, button.cta"
                  className="mt-1 w-full rounded-lg border border-line bg-panel px-3 py-2 outline-none focus:border-lime/60"
                />
              </label>
              <label className="text-sm">
                Element label (optional)
                <input
                  value={elementLabel}
                  onChange={(e) => setElementLabel(e.target.value)}
                  placeholder="Pay now button"
                  className="mt-1 w-full rounded-lg border border-line bg-panel px-3 py-2 outline-none focus:border-lime/60"
                />
              </label>
            </div>
          )}

          <div className="grid gap-4 sm:grid-cols-3">
            <label className="text-sm">
              Viewports
              <select
                value={viewport}
                onChange={(e) => setViewport(e.target.value)}
                className="mt-1 w-full rounded-lg border border-line bg-ink px-3 py-2"
              >
                {VIEWPORTS.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm">
              Interaction depth
              <select
                value={interactionDepth}
                onChange={(e) => setInteractionDepth(e.target.value)}
                className="mt-1 w-full rounded-lg border border-line bg-ink px-3 py-2"
              >
                <option value="none">None (passive)</option>
                <option value="safe">Safe interactions</option>
                <option value="deep">Deep (still non-destructive)</option>
              </select>
            </label>
            {scope === "full_site" && (
              <>
                <label className="text-sm">
                  Max pages
                  <input
                    type="number"
                    min={1}
                    max={100}
                    value={maxPages}
                    onChange={(e) => setMaxPages(Number(e.target.value))}
                    className="mt-1 w-full rounded-lg border border-line bg-ink px-3 py-2"
                  />
                </label>
                <label className="text-sm">
                  Max depth
                  <input
                    type="number"
                    min={0}
                    max={6}
                    value={maxDepth}
                    onChange={(e) => setMaxDepth(Number(e.target.value))}
                    className="mt-1 w-full rounded-lg border border-line bg-ink px-3 py-2"
                  />
                </label>
              </>
            )}
          </div>

          <fieldset>
            <legend className="text-sm">Detection categories</legend>
            <div className="mt-2 flex flex-wrap gap-2">
              {CATEGORIES.map((cat) => {
                const on = categories.includes(cat);
                return (
                  <label
                    key={cat}
                    className={`cursor-pointer rounded-full border px-3 py-1 text-xs ${
                      on ? "border-lime/60 bg-lime/10 text-lime" : "border-line text-zinc-400"
                    }`}
                  >
                    <input
                      className="sr-only"
                      type="checkbox"
                      checked={on}
                      onChange={() =>
                        setCategories((cur) => (on ? cur.filter((c) => c !== cat) : [...cur, cat]))
                      }
                    />
                    {cat}
                  </label>
                );
              })}
            </div>
          </fieldset>

          {environment === "production" && (
            <p className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-sm text-amber-200">
              Production mode: destructive actions and form submission stay disabled.
            </p>
          )}
          {error && <ErrorState message={error} />}
          <button
            disabled={busy || categories.length === 0}
            className="rounded-lg bg-lime px-4 py-2 text-sm font-semibold text-black transition-opacity disabled:opacity-50"
          >
            {busy ? "Queuing scan…" : "Start scan"}
          </button>
        </form>

        <div className="space-y-6">
          <div className="rounded-2xl border border-line bg-panel p-6">
            <Section
              title="Severity mix"
              action={
                <Link href="/issues" className="text-xs text-lime hover:underline">
                  Open registry
                </Link>
              }
            >
              {severityTotal === 0 ? (
                <EmptyState
                  title="No issues recorded yet"
                  description="Run a scan against your staging site to populate the registry."
                />
              ) : (
                <div className="space-y-2">
                  {Object.entries(dash?.by_severity || {})
                    .sort((a, b) => b[1] - a[1])
                    .map(([severity, count]) => (
                      <div key={severity} className="flex items-center gap-3">
                        <SeverityBadge value={severity} />
                        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/5">
                          <div
                            className="h-full rounded-full bg-lime/60"
                            style={{ width: `${(count / severityTotal) * 100}%` }}
                          />
                        </div>
                        <span className="w-8 text-right text-xs tabular-nums text-muted">{count}</span>
                      </div>
                    ))}
                </div>
              )}
            </Section>
          </div>

          <div className="rounded-2xl border border-line bg-panel p-6">
            <Section title="Recent scans">
              {loading && !dash ? (
                <div className="space-y-2">
                  <Skeleton className="h-10" />
                  <Skeleton className="h-10" />
                </div>
              ) : dash && dash.recent_scans.length > 0 ? (
                <ul className="space-y-2">
                  {dash.recent_scans.map((scan) => (
                    <li key={scan.id}>
                      <Link
                        href={`/scans/${scan.id}`}
                        className="flex items-center justify-between gap-3 rounded-lg border border-transparent px-2 py-2 text-sm hover:border-line hover:bg-white/[0.03]"
                      >
                        <span className="min-w-0 flex-1 truncate font-mono text-xs text-zinc-300">{scan.url}</span>
                        <StatusBadge value={scan.status} />
                        <span className="text-xs text-muted">{relativeTime(scan.created_at)}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState title="No scans yet" description="Your first scan will appear here." />
              )}
            </Section>
          </div>

          <div className="rounded-2xl border border-dashed border-line p-5 text-xs text-muted">
            <p className="font-medium text-zinc-300">What BugPilot will not do</p>
            <ul className="mt-2 space-y-1">
              <li>— Submit forms or place orders without explicit authorization.</li>
              <li>— Leave the scope you selected.</li>
              <li>— Treat an unverified AI hypothesis as a confirmed bug.</li>
            </ul>
          </div>
        </div>
      </div>

      <Section title="Priority distribution">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {(["P0", "P1", "P2", "P3"] as const).map((priority) => (
            <div key={priority} className="rounded-xl border border-line bg-panel p-4">
              <PriorityBadge value={priority} />
              <p className="mt-2 text-2xl font-semibold tabular-nums">{dash?.by_priority?.[priority] ?? 0}</p>
            </div>
          ))}
        </div>
      </Section>
    </div>
  );
}