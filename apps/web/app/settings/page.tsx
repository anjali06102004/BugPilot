"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";
import { Badge, ErrorState, Section, Skeleton } from "@/components/ui";

export default function SettingsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [routes, setRoutes] = useState<Record<string, string>>({});
  const [retention, setRetention] = useState<Record<string, number>>({});
  const [saved, setSaved] = useState<string | null>(null);

  function load() {
    setLoading(true);
    api<Project[]>("/projects")
      .then((data) => {
        setProjects(data);
        setRoutes(Object.fromEntries(data.map((p) => [p.id, p.critical_routes.join(", ")])));
        setRetention(Object.fromEntries(data.map((p) => [p.id, p.evidence_retention_days])));
        setError(null);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load settings"))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
  }, []);

  async function save(project: Project) {
    setSaved(null);
    try {
      await api(`/projects/${project.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          critical_routes: (routes[project.id] || "")
            .split(",")
            .map((r) => r.trim())
            .filter(Boolean),
          evidence_retention_days: retention[project.id] ?? project.evidence_retention_days,
        }),
      });
      setSaved(project.id);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save settings");
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Settings</h1>
        <p className="mt-1 text-sm text-muted">
          Per-project business context and evidence policy. AI provider credentials live in the API
          environment, never in the browser.
        </p>
      </header>

      {error && <ErrorState message={error} onRetry={load} />}

      <div className="rounded-2xl border border-line bg-panel p-6">
        <Section title="Projects" subtitle="Critical routes raise priority. Retention controls evidence lifetime.">
          {loading ? (
            <Skeleton className="h-24" />
          ) : projects.length === 0 ? (
            <p className="text-sm text-muted">Create a project by running a scan.</p>
          ) : (
            <div className="space-y-6">
              {projects.map((project) => (
                <div key={project.id} className="rounded-xl border border-line bg-ink p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <p className="text-sm font-medium">{project.name}</p>
                      <p className="font-mono text-xs text-muted">{project.website_url}</p>
                    </div>
                    <Badge>{project.environment}</Badge>
                  </div>
                  <div className="mt-3 grid gap-3 sm:grid-cols-[2fr_1fr_auto]">
                    <label className="text-xs">
                      Critical routes (comma separated)
                      <input
                        value={routes[project.id] ?? ""}
                        onChange={(e) => setRoutes({ ...routes, [project.id]: e.target.value })}
                        placeholder="/checkout, /login"
                        className="mt-1 w-full rounded-lg border border-line bg-panel px-3 py-2 text-sm outline-none focus:border-lime/60"
                      />
                    </label>
                    <label className="text-xs">
                      Evidence retention (days)
                      <input
                        type="number"
                        min={0}
                        value={retention[project.id] ?? project.evidence_retention_days}
                        onChange={(e) => setRetention({ ...retention, [project.id]: Number(e.target.value) })}
                        className="mt-1 w-full rounded-lg border border-line bg-panel px-3 py-2 text-sm"
                      />
                    </label>
                    <button
                      onClick={() => save(project)}
                      className="mt-5 h-9 rounded-lg bg-lime px-4 text-xs font-semibold text-black"
                    >
                      Save
                    </button>
                  </div>
                  {saved === project.id && <p className="mt-1 text-xs text-emerald-300">Saved.</p>}
                </div>
              ))}
            </div>
          )}
        </Section>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-2xl border border-line bg-panel p-6">
          <Section title="Safety defaults">
            <ul className="space-y-2 text-sm text-zinc-300">
              <li>— Destructive actions are blocked in every scan.</li>
              <li>— Production scans never submit forms.</li>
              <li>— Private networks are rejected outside development.</li>
              <li>— Page text is not sent to an AI provider unless enabled server-side.</li>
            </ul>
          </Section>
        </div>
        <div className="rounded-2xl border border-line bg-panel p-6">
          <Section title="Browser extension">
            <p className="text-sm text-muted">
              The extension connects to this API. Set its backend URL to{" "}
              <code className="rounded bg-white/5 px-1.5 py-0.5 text-xs">
                {process.env.NEXT_PUBLIC_API_URL || "/backend (server proxy)"}
              </code>{" "}
              and choose a scope before scanning. Enabling the extension never starts a scan by itself.
            </p>
            <p className="mt-3 text-xs text-muted">
              Sound and animation preferences are stored locally in the extension.
            </p>
          </Section>
        </div>
      </div>
    </div>
  );
}