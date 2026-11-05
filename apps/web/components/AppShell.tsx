"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/", label: "Overview" },
  { href: "/issues", label: "Bug Registry" },
  { href: "/reports", label: "Reports" },
  { href: "/settings", label: "Settings" },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="min-h-screen bg-ink text-zinc-100">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:bg-lime focus:px-3 focus:py-2 focus:text-black"
      >
        Skip to content
      </a>
      <header className="sticky top-0 z-40 border-b border-line bg-ink/85 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-6 px-6 py-3">
          <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
            <span aria-hidden="true" className="grid h-7 w-7 place-items-center rounded-lg border border-lime/40 bg-lime/10 text-sm">
              🐞
            </span>
            <span>
              BugPilot <span className="text-lime">AI</span>
            </span>
          </Link>
          <nav aria-label="Primary" className="flex items-center gap-1 text-sm">
            {NAV.map((item) => {
              const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={`rounded-lg px-3 py-1.5 transition-colors ${
                    active ? "bg-white/5 text-lime" : "text-zinc-400 hover:text-zinc-100"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
          <p className="hidden text-xs text-muted lg:block">Discover · Investigate · Verify · Document</p>
        </div>
      </header>
      <main id="main" className="mx-auto max-w-7xl px-6 py-8">
        {children}
      </main>
      <footer className="mx-auto max-w-7xl px-6 pb-10 pt-4 text-xs text-muted">
        BugPilot reports only what it actually inspected. AI suggestions are labelled and must be verified
        by an engineer.
      </footer>
    </div>
  );
}