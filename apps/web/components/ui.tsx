import type { ReactNode } from "react";

const severityStyles: Record<string, string> = {
  critical: "border-rose-500/40 bg-rose-500/10 text-rose-300",
  high: "border-orange-500/40 bg-orange-500/10 text-orange-300",
  medium: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  low: "border-sky-500/40 bg-sky-500/10 text-sky-300",
  informational: "border-zinc-500/40 bg-zinc-500/10 text-zinc-300",
};

const priorityStyles: Record<string, string> = {
  P0: "border-rose-500/50 bg-rose-500/15 text-rose-200",
  P1: "border-orange-500/50 bg-orange-500/15 text-orange-200",
  P2: "border-amber-500/50 bg-amber-500/15 text-amber-200",
  P3: "border-zinc-600/50 bg-zinc-600/10 text-zinc-300",
};

const statusStyles: Record<string, string> = {
  new: "border-lime/40 bg-lime/10 text-lime",
  triaged: "border-sky-500/40 bg-sky-500/10 text-sky-300",
  confirmed: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  in_progress: "border-indigo-500/40 bg-indigo-500/10 text-indigo-300",
  fixed: "border-teal-500/40 bg-teal-500/10 text-teal-300",
  verified: "border-emerald-500/50 bg-emerald-500/15 text-emerald-200",
  closed: "border-zinc-600/50 bg-zinc-600/10 text-zinc-400",
  needs_review: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  false_positive: "border-zinc-600/50 bg-zinc-600/10 text-zinc-400",
  duplicate: "border-zinc-600/50 bg-zinc-600/10 text-zinc-400",
  reopened: "border-rose-500/40 bg-rose-500/10 text-rose-300",
  blocked: "border-rose-500/40 bg-rose-500/10 text-rose-300",
  running: "border-lime/40 bg-lime/10 text-lime",
  queued: "border-sky-500/40 bg-sky-500/10 text-sky-300",
  paused: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  completed: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  failed: "border-rose-500/40 bg-rose-500/10 text-rose-300",
  cancelled: "border-zinc-600/50 bg-zinc-600/10 text-zinc-400",
  stopped: "border-zinc-600/50 bg-zinc-600/10 text-zinc-400",
};

const confidenceStyles: Record<string, string> = {
  confirmed: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  likely: "border-lime/40 bg-lime/10 text-lime",
  possible: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  not_a_bug: "border-zinc-600/50 bg-zinc-600/10 text-zinc-400",
};

export function Badge({
  children,
  tone = "neutral",
  title,
}: {
  children: ReactNode;
  tone?: "neutral" | "accent" | "danger" | "warn" | "success";
  title?: string;
}) {
  const tones: Record<string, string> = {
    neutral: "border-line bg-white/5 text-zinc-300",
    accent: "border-lime/40 bg-lime/10 text-lime",
    danger: "border-rose-500/40 bg-rose-500/10 text-rose-300",
    warn: "border-amber-500/40 bg-amber-500/10 text-amber-300",
    success: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  };
  return (
    <span
      title={title}
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${tones[tone]}`}
    >
      {children}
    </span>
  );
}

export function SeverityBadge({ value }: { value: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium capitalize ${
        severityStyles[value] || severityStyles.informational
      }`}
    >
      {value}
    </span>
  );
}

export function PriorityBadge({ value }: { value: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold ${
        priorityStyles[value] || priorityStyles.P3
      }`}
    >
      {value}
    </span>
  );
}

export function StatusBadge({ value }: { value: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${
        statusStyles[value] || statusStyles.new
      }`}
    >
      {value.replace(/_/g, " ")}
    </span>
  );
}

export function ConfidenceBadge({ value }: { value: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${
        confidenceStyles[value] || confidenceStyles.possible
      }`}
    >
      {value.replace(/_/g, " ")}
    </span>
  );
}

export function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  tone?: "danger" | "warn" | "success";
}) {
  const toneClass =
    tone === "danger" ? "text-rose-300" : tone === "warn" ? "text-amber-300" : tone === "success" ? "text-emerald-300" : "";
  return (
    <div className="rounded-xl border border-line bg-panel p-4">
      <p className="text-[11px] uppercase tracking-[0.14em] text-muted">{label}</p>
      <p className={`mt-1.5 text-2xl font-semibold tabular-nums ${toneClass}`}>{value}</p>
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-dashed border-line bg-panel/40 p-10 text-center">
      <p className="text-sm font-medium">{title}</p>
      {description && <p className="mx-auto mt-1 max-w-md text-sm text-muted">{description}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-4 text-sm">
      <p className="font-medium text-rose-300">Something went wrong</p>
      <p className="mt-1 text-zinc-300">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-3 rounded-lg border border-line px-3 py-1.5 text-xs hover:border-lime/50"
        >
          Try again
        </button>
      )}
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-lg bg-white/5 ${className}`} />;
}

export function Progress({ value, label }: { value: number; label?: string }) {
  const clamped = Math.max(0, Math.min(100, Math.round(value)));
  return (
    <div>
      {label && (
        <div className="mb-1 flex justify-between text-xs text-muted">
          <span>{label}</span>
          <span>{clamped}%</span>
        </div>
      )}
      <div className="h-1.5 overflow-hidden rounded-full bg-white/10" role="progressbar" aria-valuenow={clamped} aria-valuemin={0} aria-valuemax={100}>
        <div className="h-full rounded-full bg-lime transition-all" style={{ width: `${clamped}%` }} />
      </div>
    </div>
  );
}

export function Section({
  title,
  subtitle,
  action,
  children,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section>
      <div className="mb-3 flex items-end justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-zinc-300">{title}</h2>
          {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export function KeyValue({ items }: { items: { label: string; value: ReactNode }[] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
      {items.map((item) => (
        <div key={item.label}>
          <dt className="text-[11px] uppercase tracking-[0.12em] text-muted">{item.label}</dt>
          <dd className="mt-0.5 break-words text-sm">{item.value ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}