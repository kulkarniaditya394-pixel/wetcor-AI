"use client";

import { ExternalLink, FlaskConical, ServerOff } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { REPO_URL, isStaticDemo } from "@/lib/mode";
import { Button, EmptyState, PageHeader } from "./ui";

/** Pages that work on the hosted site: the showcase snapshot and the two labs (analysis runs in the browser). */
export const HOSTED_PATHS = ["/", "/showcase", "/wettability", "/corrosion"];

/** On the hosted site, pages that need a database or model storage explain why and point to the local app. */
export function StaticGate({ children }: { children: ReactNode }) {
  const path = (usePathname() || "/").replace(/\/+$/, "") || "/";
  if (!isStaticDemo() || HOSTED_PATHS.includes(path)) return <>{children}</>;
  return (
    <>
      <PageHeader eyebrow="Hosted site" title="This page needs the local app" />
      <EmptyState icon={<ServerOff className="size-9" />} title="Saved records are only available in the local app"
        action={<div className="flex flex-wrap justify-center gap-2">
          <Link href="/wettability"><Button variant="primary" icon={<FlaskConical className="size-4" />}>Analyse a droplet image</Button></Link>
          <Link href="/corrosion"><Button icon={<FlaskConical className="size-4" />}>Analyse potentiostat data</Button></Link>
          <a href={REPO_URL} target="_blank" rel="noreferrer"><Button variant="ghost" icon={<ExternalLink className="size-4" />}>Run the full app locally</Button></a>
        </div>}>
        The Wettability Lab and Corrosion Lab work here and analyse your files in your browser. The experiment database, saved measurements, reports and ML Studio
        store data and train models on your own computer, so they run in the local app (setup-windows.ps1, run-local.ps1).
      </EmptyState>
    </>
  );
}
