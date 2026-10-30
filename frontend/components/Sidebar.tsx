"use client";

import { BrainCircuit, Database, Droplets, FileText, Gauge, Presentation, Settings, Zap } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { API_URL } from "@/lib/api";
import { cx } from "./ui";

export const NAV = [
  { href: "/dashboard", label: "Overview", icon: Gauge, group: "" },
  { href: "/showcase", label: "Showcase", icon: Presentation, group: "" },
  { href: "/wettability", label: "Wettability Lab", icon: Droplets, group: "Instruments" },
  { href: "/corrosion", label: "Corrosion Lab", icon: Zap, group: "Instruments" },
  { href: "/experiments", label: "Experiments", icon: Database, group: "Data" },
  { href: "/ml-studio", label: "ML Studio", icon: BrainCircuit, group: "Data" },
  { href: "/reports", label: "Reports", icon: FileText, group: "Data" },
  { href: "/settings", label: "Settings", icon: Settings, group: "System" },
];

type Health = "checking" | "online" | "degraded" | "offline";

export function useBackendHealth(intervalMs = 15000): Health {
  const [state, setState] = useState<Health>("checking");
  useEffect(() => {
    let alive = true;
    const check = async () => {
      try {
        const r = await fetch(`${API_URL}/api/health`, { cache: "no-store" });
        const body = r.ok ? await r.json() : null;
        if (alive) setState(body?.database === "ok" ? (body.status === "ok" ? "online" : "degraded") : "offline");
      } catch {
        if (alive) setState("offline");
      }
    };
    check();
    const id = setInterval(check, intervalMs);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [intervalMs]);
  return state;
}

export function Sidebar() {
  const path = usePathname() || "/";
  const health = useBackendHealth();
  const dot = { checking: "bg-muted", online: "bg-good", degraded: "bg-warn", offline: "bg-bad" }[health];
  const text = { checking: "Checking backend…", online: "Backend connected", degraded: "Backend degraded", offline: "Backend unreachable" }[health];
  return (
    <aside className="sticky top-0 flex h-screen w-[220px] shrink-0 flex-col border-r border-line bg-panel max-md:w-16">
      <div className="flex items-center gap-2.5 border-b border-line px-4 py-4">
        <svg viewBox="0 0 32 32" className="size-7 shrink-0" aria-hidden>
          <path d="M16 3c5 7 9 11.5 9 16a9 9 0 0 1-18 0c0-4.5 4-9 9-16Z" fill="none" stroke="var(--color-accent)" strokeWidth="2" />
          <path d="M7 24h18" stroke="var(--color-warn)" strokeWidth="2" />
        </svg>
        <div className="max-md:hidden">
          <div className="text-sm font-bold tracking-[0.14em] text-ink">WETCOR AI</div>
          <div className="text-[10px] uppercase tracking-wider text-muted">Wettability · Corrosion</div>
        </div>
      </div>
      <nav aria-label="Main" className="flex-1 space-y-0.5 p-2">
        {NAV.map(({ href, label, icon: Icon, group }, i) => {
          const active = path === href || path.startsWith(href + "/");
          const heading = group && group !== NAV[i - 1]?.group;
          return (
            <div key={href}>
            {heading && <div className="px-3 pb-1 pt-4 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted/80 max-md:hidden">{group}</div>}
            <Link
              href={href}
              aria-current={active ? "page" : undefined}
              title={label}
              className={cx(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                active ? "bg-accent-soft font-semibold text-accent shadow-[inset_2px_0_0_var(--color-accent)]" : "text-ink-2 hover:bg-panel-2 hover:text-ink",
              )}
            >
              <Icon className="size-4 shrink-0" aria-hidden />
              <span className="max-md:hidden">{label}</span>
            </Link>
            </div>
          );
        })}
      </nav>
      <div className="border-t border-line px-4 py-3 text-xs text-muted" role="status" aria-live="polite">
        <div className="flex items-center gap-2">
          <span className={cx("size-2 rounded-full", dot)} aria-hidden />
          <span className="max-md:hidden">{text}</span>
        </div>
        <div className="mt-1 truncate font-mono text-[10px] max-md:hidden" title={API_URL}>{API_URL.replace(/^https?:\/\//, "")}</div>
      </div>
    </aside>
  );
}
