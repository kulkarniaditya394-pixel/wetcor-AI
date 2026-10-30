"use client";

import { AlertTriangle, CheckCircle2, Info, Loader2, XCircle } from "lucide-react";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";
import { useId } from "react";

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

export function PageHeader({ title, subtitle, actions, eyebrow }: { title: string; subtitle?: ReactNode; actions?: ReactNode; eyebrow?: string }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4 border-b border-line pb-5">
      <div className="min-w-0">
        {eyebrow && <div className="mb-1 font-mono text-[11px] uppercase tracking-[0.18em] text-accent/80">{eyebrow}</div>}
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
        {subtitle && <p className="mt-1 max-w-3xl text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  );
}

export function Card({ title, actions, children, className, pad = true }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; pad?: boolean }) {
  return (
    <section className={cx("rounded-lg border border-line bg-panel", className)}>
      {(title || actions) && (
        <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
          <h2 className="text-[13px] font-semibold uppercase tracking-wider text-ink-2">{title}</h2>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={pad ? "p-4" : ""}>{children}</div>
    </section>
  );
}

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger"; size?: "sm" | "md" | "lg"; busy?: boolean; icon?: ReactNode };
export function Button({ variant = "secondary", size = "md", busy, icon, className, children, disabled, ...rest }: BtnProps) {
  const v = {
    primary: "bg-accent text-accent-ink hover:bg-[#45cad7] font-semibold",
    secondary: "border border-line-2 bg-panel-2 text-ink hover:border-accent/60",
    ghost: "text-ink-2 hover:bg-panel-2 hover:text-ink",
    danger: "border border-bad/50 bg-bad-soft text-bad hover:bg-bad/20",
  }[variant];
  const s = { sm: "h-7 px-2.5 text-xs gap-1.5", md: "h-9 px-3.5 text-sm gap-2", lg: "h-11 px-5 text-[15px] gap-2" }[size];
  return (
    <button
      className={cx("inline-flex items-center justify-center rounded-md transition-colors disabled:cursor-not-allowed disabled:opacity-45", v, s, className)}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      {...rest}
    >
      {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
}

const TONES = {
  neutral: "border-line-2 text-ink-2 bg-panel-2",
  accent: "border-accent/50 text-accent bg-accent-soft",
  good: "border-good/50 text-good bg-good-soft",
  warn: "border-warn/50 text-warn bg-warn-soft",
  bad: "border-bad/50 text-bad bg-bad-soft",
  calc: "border-calc/50 text-calc bg-[#13213d]",
  pred: "border-pred/50 text-pred bg-[#231a3d]",
};
export type Tone = keyof typeof TONES;
export function Badge({ tone = "neutral", children, className, title }: { tone?: Tone; children: ReactNode; className?: string; title?: string }) {
  return (
    <span title={title} className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-0.5 text-[10.5px] font-semibold uppercase tracking-wider", TONES[tone], className)}>
      {children}
    </span>
  );
}

export function OriginBadge({ origin }: { origin: "measured" | "calculated" | "predicted" | string }) {
  const map: Record<string, [Tone, string, string]> = {
    measured: ["good", "Measured", "Directly obtained from an image or instrument file"],
    calculated: ["calc", "Calculated", "Derived from measured data with a documented method"],
    predicted: ["pred", "Predicted", "Output of a fitted machine-learning model; not a measurement"],
  };
  const [tone, label, title] = map[origin] ?? ["neutral", origin, origin];
  return <Badge tone={tone} title={title}>{label}</Badge>;
}

export function DemoBadge({ compact }: { compact?: boolean }) {
  return <Badge tone="warn" title="DEMO — SYNTHETIC DATA: not a laboratory measurement">{compact ? "Demo" : "Demo — synthetic data"}</Badge>;
}

export function DemoBanner({ children }: { children?: ReactNode }) {
  return (
    <div role="note" className="demo-stripe mb-4 rounded-md border border-warn/60 px-4 py-2.5 text-sm font-semibold text-warn">
      DEMO — SYNTHETIC DATA. {children ?? "These records exist to exercise the software and say nothing about real materials."}
    </div>
  );
}

export function Alert({ tone = "info", title, children }: { tone?: "info" | "warn" | "bad" | "good"; title?: ReactNode; children?: ReactNode }) {
  const Icon = { info: Info, warn: AlertTriangle, bad: XCircle, good: CheckCircle2 }[tone];
  const cls = { info: "border-accent/40 bg-accent-soft/40 text-ink-2", warn: "border-warn/50 bg-warn-soft text-[#f6d39b]", bad: "border-bad/50 bg-bad-soft text-[#f8b4b4]", good: "border-good/50 bg-good-soft text-[#a7e8cc]" }[tone];
  return (
    <div role={tone === "bad" ? "alert" : "status"} className={cx("flex gap-2.5 rounded-md border px-3 py-2.5 text-sm", cls)}>
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="min-w-0">
        {title && <div className="font-semibold">{title}</div>}
        {children && <div className={title ? "mt-0.5" : ""}>{children}</div>}
      </div>
    </div>
  );
}

export function Field({ label, hint, error, children, required, htmlFor }: { label: string; hint?: ReactNode; error?: string; children: ReactNode; required?: boolean; htmlFor?: string }) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={htmlFor} className="text-xs font-medium text-ink-2">
        {label}
        {required && <span className="text-accent"> *</span>}
      </label>
      {children}
      {error ? <p className="text-xs text-bad">{error}</p> : hint ? <p className="text-xs text-muted">{hint}</p> : null}
    </div>
  );
}

const inputCls = "h-9 rounded-md border border-line-2 bg-bg px-2.5 text-sm text-ink placeholder:text-muted/70 focus:border-accent focus:outline-none disabled:opacity-50";
/** Full width unless the caller sets its own width class. */
const widthOf = (c?: string) => (/(^|s)(max-)?w-/.test(c ?? "") ? "" : "w-full");

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(inputCls, widthOf(props.className), props.className)} />;
}
export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cx(inputCls, "pr-7", widthOf(props.className), props.className)} />;
}
export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx(inputCls, "h-auto min-h-16 w-full py-2", props.className)} />;
}

export function LabeledInput({ label, hint, error, required, ...rest }: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: ReactNode; error?: string }) {
  const id = useId();
  return (
    <Field label={label} hint={hint} error={error} required={required} htmlFor={id}>
      <Input id={id} required={required} aria-invalid={!!error || undefined} {...rest} />
    </Field>
  );
}

export function EmptyState({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-line-2 px-6 py-10 text-center">
      {icon && <div className="text-muted">{icon}</div>}
      <div className="text-sm font-semibold text-ink">{title}</div>
      {children && <div className="max-w-md text-sm text-muted">{children}</div>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 text-sm text-muted">
      <Loader2 className="size-4 animate-spin" aria-hidden /> {label}…
    </div>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "accent" | "warn" }) {
  return (
    <div className="rounded-lg border border-line bg-panel px-4 py-3">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-muted">{label}</div>
      <div className={cx("num mt-1 text-2xl font-semibold", tone === "accent" ? "text-accent" : tone === "warn" ? "text-warn" : "text-ink")}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted">{sub}</div>}
    </div>
  );
}

export function StatusDot({ status }: { status: "pass" | "warn" | "fail" | string }) {
  const c = status === "pass" ? "bg-good" : status === "warn" ? "bg-warn" : "bg-bad";
  return <span className={cx("inline-block size-2 shrink-0 rounded-full", c)} aria-label={status} />;
}

export function KV({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[minmax(110px,max-content)_1fr] gap-x-4 gap-y-1.5 text-sm">
      {items.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="min-w-0 break-words text-ink">{v ?? <span className="text-muted">not recorded</span>}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Table({ head, children, className }: { head: ReactNode[]; children: ReactNode; className?: string }) {
  return (
    <div className={cx("scroll-thin overflow-x-auto rounded-md border border-line", className)}>
      <table className="w-full border-collapse text-sm">
        <thead className="bg-panel-2 text-left text-[11px] uppercase tracking-wider text-muted">
          <tr>{head.map((h, i) => <th key={i} className="whitespace-nowrap px-3 py-2 font-semibold">{h}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-line [&_td]:whitespace-nowrap [&_td]:px-3 [&_td]:py-2 [&_td]:align-top">{children}</tbody>
      </table>
    </div>
  );
}
