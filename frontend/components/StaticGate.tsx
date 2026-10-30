"use client";

import { ExternalLink, Presentation, ServerOff } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { REPO_URL, isStaticDemo } from "@/lib/mode";
import { Button, EmptyState, PageHeader } from "./ui";

/** In the hosted static demo only /showcase works; every other route explains why and points to the local app. */
export function StaticGate({ children }: { children: ReactNode }) {
  const path = usePathname() || "/";
  if (!isStaticDemo() || path === "/" || path === "/showcase" || path.startsWith("/showcase/")) return <>{children}</>;
  return (
    <>
      <PageHeader eyebrow="Hosted static demo" title="This page needs the local backend" />
      <EmptyState icon={<ServerOff className="size-9" />} title="Not available in the hosted demo"
        action={<div className="flex flex-wrap justify-center gap-2">
          <Link href="/showcase"><Button variant="primary" icon={<Presentation className="size-4" />}>Open the showcase</Button></Link>
          <a href={REPO_URL} target="_blank" rel="noreferrer"><Button icon={<ExternalLink className="size-4" />}>Run it locally</Button></a>
        </div>}>
        Live camera analysis, potentiostat import, the experiment database and ML Studio use the Python backend, which runs on your own computer (setup-windows.ps1, run-local.ps1).
        This site only hosts the pre-computed showcase test.
      </EmptyState>
    </>
  );
}
