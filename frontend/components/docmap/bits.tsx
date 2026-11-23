"use client";
import { FileText, Presentation, Table2, FileType } from "lucide-react";
import { cn } from "@/lib/utils";

export function FormatIcon({ format, className }: { format: string; className?: string }) {
  const C = format === "xlsx" || format === "xls" || format === "xlsm" || format === "csv" ? Table2 : format === "pptx" ? Presentation : format === "pdf" ? FileType : FileText;
  return <C className={cn("size-4", className)} aria-hidden />;
}

export function Badge({ tone = "muted", children, className, title }: { tone?: "muted" | "ok" | "warn" | "bad"; children: React.ReactNode; className?: string; title?: string }) {
  const tones = {
    muted: "bg-surface-2 text-muted-foreground",
    ok: "text-ok",
    warn: "bg-warn-bg text-warn",
    bad: "bg-danger-bg text-danger",
  };
  return <span title={title} className={cn("inline-flex items-center rounded-sm px-2 py-0.5 text-xs font-medium", tones[tone], className)}>{children}</span>;
}

/** Theme tag: pill with a dot in the category color. */
export function ThemeTag({ name, color, className }: { name: string; color: string; className?: string }) {
  return (
    <span className={cn("inline-flex max-w-full items-center gap-1.5 whitespace-nowrap rounded-full border bg-surface-2 px-2 py-0.5 text-xs", className)}>
      <span className="size-[7px] shrink-0 rounded-full" style={{ background: color }} aria-hidden />
      <span className="truncate">{name}</span>
    </span>
  );
}

const WARN_LABEL: Record<string, string> = {
  ocr: "Some pages need OCR", hidden: "Hidden sheets included", encrypted: "Encrypted: remove the password",
  unsupported: "Unsupported file type", size: "Too large for most LLMs", other: "Note",
};

function otherLabel(text: string) {   // say what happened instead of a bare "Note"
  if (/streaming full-sheet fallback/i.test(text)) return "Fallback converter, all rows kept";
  if (/failed/i.test(text)) return "Main converter failed, fallback used";
  return text.length > 40 ? `${text.slice(0, 38)}...` : text;
}

/** Small warning chips for a document: needs-OCR pages, hidden sheets, encrypted, unsupported, size. */
export function WarnChips({ warnings, skip = [] }: { warnings: { kind: string; text: string }[]; skip?: string[] }) {
  const list = warnings.filter((w) => !skip.includes(w.kind));
  if (!list.length) return null;
  return (
    <span className="flex flex-wrap gap-1" data-testid="doc-warnings">
      {list.map((w, i) => (
        <Badge key={i} tone={w.kind === "encrypted" || w.kind === "unsupported" ? "bad" : "warn"} title={w.text}>
          {w.kind === "other" ? otherLabel(w.text) : WARN_LABEL[w.kind] ?? WARN_LABEL.other}
        </Badge>
      ))}
    </span>
  );
}

export function Kbd({ children }: { children: React.ReactNode }) {
  return <kbd className="num ml-1.5 rounded-[4px] border border-b-2 bg-surface-2 px-1.5 text-[11px] text-muted-foreground">{children}</kbd>;
}

/** Metric tile: label, big number, mono detail line, thin bar (0-100). */
export function Metric({ label, value, hint, pct, testId, loading }: { label: string; value: string; hint?: string; pct?: number; testId?: string; loading?: boolean }) {
  if (loading) return <div className="skeleton h-[112px] rounded-xl" aria-hidden />;
  return (
    <div className="fade-in rounded-xl border bg-card p-4" data-testid={testId}>
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div className="num my-1 text-[28px] font-semibold leading-tight tracking-tight">{value}</div>
      {hint && <div className="num text-xs text-muted-foreground">{hint}</div>}
      {pct != null && <div className="mt-2.5 h-1 overflow-hidden rounded bg-surface-2"><i className="block h-full bg-primary transition-[width] duration-200 ease-out" style={{ width: `${Math.max(0, Math.min(100, pct))}%` }} /></div>}
    </div>
  );
}

export function Empty({ title, children, action }: { title: string; children?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="fade-in rounded-xl border border-dashed bg-card p-10 text-center">
      <div className="font-medium">{title}</div>
      {children && <div className="mt-1 text-sm text-muted-foreground">{children}</div>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}

export function PageHead({ title, sub, actions }: { title: string; sub?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="mb-5 mt-7 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold">{title}</h1>
        {sub && <p className="mt-1 text-muted-foreground">{sub}</p>}
      </div>
      {actions}
    </div>
  );
}

export function H2({ children, right }: { children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="mb-2.5 mt-8 flex items-center justify-between gap-2">
      <h2 className="text-[13px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">{children}</h2>
      {right}
    </div>
  );
}

export function SkeletonRows({ n = 5 }: { n?: number }) {
  return <div className="space-y-2" aria-busy aria-label="Loading">{Array.from({ length: n }, (_, i) => <div key={i} className="skeleton h-9" />)}</div>;
}
