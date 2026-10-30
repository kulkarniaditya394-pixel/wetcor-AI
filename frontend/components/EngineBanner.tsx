"use client";

import { ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { engineState, ensureEngine, subscribeEngine, type EngineState } from "@/lib/engine";
import { isStaticDemo } from "@/lib/mode";
import { Alert } from "./ui";

/** Hosted site only: starts the in-browser analysis engine and shows its progress / privacy note. */
export function EngineBanner() {
  const hosted = isStaticDemo();
  const [s, setS] = useState<EngineState>(engineState());
  useEffect(() => {
    if (!hosted) return;
    const off = subscribeEngine(setS);
    ensureEngine().catch(() => undefined);
    return off;
  }, [hosted]);
  if (!hosted) return null;
  if (s.state === "error")
    return <div className="mb-4"><Alert tone="bad" title="Analysis engine could not start">{s.message} The engine downloads Python from the jsDelivr CDN; check your connection and reload the page.</Alert></div>;
  if (s.state === "ready")
    return (
      <div className="mb-4 flex items-center gap-2 rounded-md border border-good/40 bg-good-soft px-3 py-2 text-sm text-[#a7e8cc]">
        <ShieldCheck className="size-4 shrink-0" aria-hidden /> Analysis engine ready. Your files are processed inside this browser and are never uploaded.
      </div>
    );
  const pct = Math.round((s.stage / s.of) * 100);
  return (
    <div className="mb-4 rounded-md border border-accent/40 bg-accent-soft/40 px-3 py-2.5 text-sm text-ink-2" role="status">
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-medium text-ink">Loading the analysis engine (Python, OpenCV, SciPy)…</span>
        <span className="num text-xs text-muted">step {Math.max(s.stage, 1)} of {s.of}</span>
      </div>
      <div className="mt-2 h-1.5 rounded-full bg-panel-2" role="progressbar" aria-label="Analysis engine loading" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div className="h-full rounded-full bg-accent transition-[width]" style={{ width: `${Math.max(pct, 6)}%` }} />
      </div>
      <p className="mt-1.5 text-xs text-muted">{s.message}. About 45 MB on the first visit, cached by your browser afterwards. Analysis runs entirely in your browser; nothing is uploaded.</p>
    </div>
  );
}
