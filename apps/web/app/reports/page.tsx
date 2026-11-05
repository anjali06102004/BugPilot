"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, apiPath, downloadPath, relativeTime } from "@/lib/api";
import type { Project, Scan } from "@/lib/types";
import { Badge, EmptyState, ErrorState, Section, Skeleton, StatusBadge } from "@/components/ui";

export default function ReportsPage() {
  const [scans, setScans] = useState<Scan[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api<{ items: Scan[] }>("/scans?limit=50"), api<Project[]>("/projects")])
      .then(([scanData, projectData]) => {
        setScans(scanData.items);
        setProjects(projectData);
        setError(null);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load reports"))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Reports</h1>
        <p className="mt-1 text-sm text-muted">
          Exports are generated from stored findings and evidence — never from example data.
        </p>
      </header>

      {error && <ErrorState message={error} />}

      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <div className="rounded-2xl border border-line bg-panel p-6">
          <Section title="Scan reports" subtitle="Markdown, PDF, or a ZIP that includes screenshots.">
            {loading ? (
              <div className="space-y-2">
                <Skeleton className="h-14" />
                <Skeleton className="h-14" />
              </div>
            ) : scans.length === 0 ? (
              <EmptyState title="No scans to report on yet" />
            ) : (
              <ul className="divide-y divide-line">
                {scans.map((scan) => (
                  <li key={scan.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                    <div className="min-w-0">
                      <Link href={`/scans/${scan.id}`} className="block truncate font-mono text-xs text-zinc-200 hover:text-lime">
                        {scan.start_url}
                      </Link>
                      <p className="mt-1 flex items-center gap-2 text-[11px] text-muted">
                        <StatusBadge value={scan.status} />
                        <span>{scan.pages_tested} pages</span>
                        <span>{relativeTime(scan.created_at)}</span>
                      </p>
                    </div>
                    <div className="flex gap-1.5">
                      {(["md", "pdf", "zip"] as const).map((format) => (
                        <a
                          key={format}
                          href={downloadPath(scan.id, format)}
                          className="rounded-lg border border-line px-2.5 py-1 text-[11px] uppercase hover:border-lime/60"
                        >
                          {format}
                        </a>
                      ))}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Section>
        </div>

        <div className="space-y-4">
          <div className="rounded-2xl border border-line bg-panel p-6">
            <Section title="Project reports">
              {loading ? (
                <Skeleton className="h-14" />
              ) : projects.length === 0 ? (
                <EmptyState title="No projects yet" />
              ) : (
                <ul className="space-y-2">
                  {projects.map((project) => (
                    <li key={project.id} className="flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-sm">{project.name}</p>
                        <p className="truncate font-mono text-[11px] text-muted">{project.website_url}</p>
                      </div>
                      <a
                        href={apiPath(`/reports/project/${project.id}.md`)}
                        className="shrink-0 rounded-lg border border-line px-2.5 py-1 text-[11px] uppercase hover:border-lime/60"
                      >
                        md
                      </a>
                    </li>
                  ))}
                </ul>
              )}
            </Section>
          </div>

          <div className="rounded-2xl border border-line bg-panel p-6 text-xs text-muted">
            <p className="font-medium text-zinc-300">What is inside a report</p>
            <ul className="mt-2 space-y-1">
              <li>— Executive summary and coverage limits</li>
              <li>— Findings grouped by severity and priority</li>
              <li>— Reproduction steps and expected vs observed</li>
              <li>— Labelled root-cause hypotheses and suggested fixes</li>
              <li>— Screenshots, console and network evidence</li>
              <li>— Verification history</li>
            </ul>
          </div>
        </div>
      </div>
      <Badge>Reports describe what was inspected, not what was missed.</Badge>
    </div>
  );
}