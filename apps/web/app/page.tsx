"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

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

type Dashboard = {
  projects: number;
  scans: number;
  active_scans: number;
  total_bugs: number;
  verified_bugs: number;
  false_positive_rate: number;
  pages_tested: number;
  recent_activity: { id: string; url: string; status: string; pages_tested: number }[];
};

export default function HomePage() {
  const router = useRouter();
  const [dash, setDash] = useState<Dashboard | null>(null);
  const [url, setUrl] = useState("http://127.0.0.1:4173");
  const [depth, setDepth] = useState("standard");
  const [env, setEnv] = useState("staging");
  const [categories, setCategories] = useState<string[]>(CATEGORIES);
  const [maxPages, setMaxPages] = useState(10);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Dashboard>("/dashboard")
      .then(setDash)
      .catch(() => setDash(null));
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const scan = await api<{ id: string }>("/scans", {
        method: "POST",
        body: JSON.stringify({
          url,
          project_name: "Phase 1 project",
          environment: env,
          description: "Created from BugPilot dashboard",
          config: {
            depth,
            categories,
            browser: "chromium",
            viewports: [
              { name: "desktop-1280", width: 1280, height: 720 },
              { name: "mobile-390", width: 390, height: 844 },
            ],
            max_pages: maxPages,
            max_duration_seconds: 180,
            max_actions: 20,
            allow_destructive: false,
            environment: env,
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

  const chart = dash
    ? [
        { name: "Projects", value: dash.projects },
        { name: "Scans", value: dash.scans },
        { name: "Bugs", value: dash.total_bugs },
        { name: "Verified", value: dash.verified_bugs },
      ]
    : [];

  return (
    <div className="space-y-10">
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Projects" value={dash?.projects ?? "—"} />
        <Stat label="Active scans" value={dash?.active_scans ?? "—"} />
        <Stat label="Verified bugs" value={dash?.verified_bugs ?? "—"} />
        <Stat
          label="False positive rate"
          value={dash ? `${Math.round(dash.false_positive_rate * 100)}%` : "—"}
        />
      </section>

      <section className="grid gap-8 lg:grid-cols-[1.1fr_0.9fr]">
        <form onSubmit={onSubmit} className="space-y-5 rounded-2xl border border-line bg-panel p-6">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Give me your staging URL.</h1>
            <p className="mt-1 text-sm text-zinc-400">Phase 1: autonomous explore → detectors → verify → evidence.</p>
          </div>
          <label className="block text-sm">
            Website URL
            <input
              required
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className="mt-1 w-full rounded-lg border border-line bg-ink px-3 py-2"
            />
          </label>
          <div className="grid gap-4 sm:grid-cols-3">
            <label className="text-sm">
              Environment
              <select
                value={env}
                onChange={(e) => setEnv(e.target.value)}
                className="mt-1 w-full rounded-lg border border-line bg-ink px-3 py-2"
              >
                <option value="development">Development</option>
                <option value="staging">Staging</option>
                <option value="production">Production</option>
              </select>
            </label>
            <label className="text-sm">
              Scan depth
              <select
                value={depth}
                onChange={(e) => setDepth(e.target.value)}
                className="mt-1 w-full rounded-lg border border-line bg-ink px-3 py-2"
              >
                <option value="quick">Quick</option>
                <option value="standard">Standard</option>
                <option value="deep">Deep</option>
                <option value="custom">Custom</option>
              </select>
            </label>
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
          </div>
          <fieldset>
            <legend className="text-sm">Test categories</legend>
            <div className="mt-2 flex flex-wrap gap-2">
              {CATEGORIES.map((cat) => {
                const on = categories.includes(cat);
                return (
                  <label
                    key={cat}
                    className={`cursor-pointer rounded-full border px-3 py-1 text-xs ${on ? "border-lime/60 bg-lime/10 text-lime" : "border-line text-zinc-400"}`}
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
          {env === "production" && (
            <p className="text-sm text-amber-300">Destructive actions are disabled for production targets.</p>
          )}
          {error && <p className="text-sm text-danger">{error}</p>}
          <button
            disabled={busy}
            className="rounded-lg bg-lime px-4 py-2 font-medium text-black disabled:opacity-50"
          >
            {busy ? "Queuing…" : "🐞 Start Scan"}
          </button>
        </form>

        <div className="space-y-4">
          <div className="rounded-2xl border border-line bg-panel p-6">
            <h2 className="text-sm font-medium text-zinc-400">Coverage snapshot</h2>
            <div className="mt-4 h-40">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chart}>
                  <XAxis dataKey="name" stroke="#71717a" fontSize={12} />
                  <YAxis stroke="#71717a" fontSize={12} allowDecimals={false} />
                  <Tooltip />
                  <Area dataKey="value" stroke="#84cc16" fill="#84cc1633" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
          <div className="rounded-2xl border border-line bg-panel p-6">
            <h2 className="text-sm font-medium text-zinc-400">Recent activity</h2>
            <ul className="mt-3 space-y-2 text-sm">
              {(dash?.recent_activity || []).map((item) => (
                <li key={item.id}>
                  <a className="text-lime hover:underline" href={`/scans/${item.id}`}>
                    {item.status} · {item.url}
                  </a>
                </li>
              ))}
              {!dash?.recent_activity?.length && <li className="text-zinc-500">No scans yet.</li>}
            </ul>
          </div>
          <p className="text-xs text-zinc-500">
            GitHub, Jira, Slack, billing, and the browser extension are coming soon — they are not stubbed as working
            features.
          </p>
        </div>
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-2xl border border-line bg-panel p-4">
      <p className="text-xs uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
    </div>
  );
}
