"use client";
import { useEffect, useState } from "react";
import { Dialog } from "@base-ui/react/dialog";
import { AlertTriangle, Download, PackageOpen, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { API, api, exportQuery, fmt, type ExportPreview } from "@/lib/api";
import { cn } from "@/lib/utils";

function Toggle({ checked, onChange, label, hint, testId }: { checked: boolean; onChange: (v: boolean) => void; label: string; hint: string; testId: string }) {
  return (
    <label className="flex cursor-pointer items-start gap-3 rounded-sm border bg-surface p-3 hover:bg-surface-2">
      <input type="checkbox" data-testid={testId} className="peer sr-only" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span aria-hidden className="mt-0.5 flex h-5 w-9 shrink-0 items-center rounded-full border bg-surface-2 p-0.5 transition-colors duration-200 ease-out peer-checked:bg-primary peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-primary [&>i]:peer-checked:translate-x-4 [&>i]:peer-checked:bg-white">
        <i className="block size-3.5 rounded-full bg-muted-foreground transition-transform duration-200 ease-out" />
      </span>
      <span className="min-w-0 text-sm"><span className="block font-medium">{label}</span><span className="block text-xs text-muted-foreground">{hint}</span></span>
    </label>
  );
}

/** "Export context pack" button + dialog: per-topic token counts, size warnings, two toggles, Download. */
export function ExportButton({ className, variant = "outline" }: { className?: string; variant?: "outline" | "default" }) {
  const [open, setOpen] = useState(false);
  const [acceptedOnly, setAcceptedOnly] = useState(false);
  const [digest, setDigest] = useState(false);   // Egi's rule: full rows by default
  const q = exportQuery({ digest, acceptedOnly });
  // keyed by the options, so a stale answer is never shown for other options and no setState runs in the effect body
  const [res, setRes] = useState<{ q: string; prev?: ExportPreview; err?: string } | null>(null);
  const prev = res?.q === q ? res.prev ?? null : null;
  const err = res?.q === q ? res.err ?? null : null;

  useEffect(() => {
    if (!open) return;
    let live = true;
    api<ExportPreview>(`/api/export/preview?${q}`).then((p) => live && setRes({ q, prev: p })).catch((e) => live && setRes({ q, err: (e as Error).message }));
    return () => { live = false; };
  }, [open, q]);

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger render={<Button variant={variant} className={className} data-testid="export-open" />}>
        <PackageOpen className="size-4" /> Export context pack
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 z-40 bg-black/40 transition-opacity duration-200 ease-out data-[ending-style]:opacity-0 data-[starting-style]:opacity-0" />
        <Dialog.Popup data-testid="export-dialog"
          className="fixed left-1/2 top-1/2 z-50 flex max-h-[min(88vh,640px)] w-[min(94vw,520px)] -translate-x-1/2 -translate-y-1/2 flex-col rounded-xl border bg-card text-card-foreground shadow-xl transition-[opacity,transform] duration-200 ease-out data-[ending-style]:scale-[0.98] data-[ending-style]:opacity-0 data-[starting-style]:scale-[0.98] data-[starting-style]:opacity-0">
          <div className="flex items-start justify-between gap-3 border-b p-4">
            <div>
              <Dialog.Title className="text-base font-semibold">Export context pack</Dialog.Title>
              <Dialog.Description className="mt-0.5 text-sm text-muted-foreground">One Markdown file per topic plus an index, as a zip. Nothing is cut.</Dialog.Description>
            </div>
            <Dialog.Close aria-label="Close" className="grid size-7 shrink-0 place-items-center rounded-sm text-muted-foreground hover:bg-surface-2 hover:text-foreground"><X className="size-4" /></Dialog.Close>
          </div>

          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
            <div className="space-y-2">
              <Toggle testId="export-accepted" checked={acceptedOnly} onChange={setAcceptedOnly} label="Accepted links only" hint="Skip links that are still proposed (not yet reviewed)." />
              <Toggle testId="export-digest" checked={digest} onChange={setDigest} label="Spreadsheet summary (lossy)" hint="Big sheets become statistics plus the first rows. Off by default: every row is exported." />
            </div>

            <div>
              <div className="mb-1.5 text-xs font-medium text-muted-foreground">Files in the pack</div>
              {err && <div className="rounded-sm bg-danger-bg p-3 text-sm text-danger">Cannot build the preview: {err}</div>}
              {!err && !prev && <div className="space-y-2" aria-busy aria-label="Loading preview">{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton h-8" />)}</div>}
              {prev && prev.topics.length === 0 && <div className="rounded-sm border border-dashed p-4 text-center text-sm text-muted-foreground">No topic has documents for these settings. The zip will hold only the index.</div>}
              {prev && prev.topics.length > 0 && (
                <ul className="divide-y rounded-sm border" data-testid="export-topics">
                  {prev.topics.map((t) => (
                    <li key={t.file} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm">
                      <span className="min-w-0 flex-1 truncate" title={t.file}>{t.file.replace(/\.md$/, "")}</span>
                      <span className={cn("num text-xs", t.too_large ? "text-warn" : "text-muted-foreground")}>{fmt(t.tokens)} tokens</span>
                      {t.too_large && <span className="inline-flex items-center gap-1 rounded-sm bg-warn-bg px-2 py-0.5 text-xs font-medium text-warn"><AlertTriangle className="size-3" aria-hidden /> too large for most LLMs</span>}
                    </li>
                  ))}
                </ul>
              )}
              {prev && prev.topics.some((t) => t.too_large) && !digest && (
                <p className="mt-2 text-xs text-muted-foreground">Typical LLM context windows are 128k to 200k tokens. Nothing was cut. Split by document, use a long-context model, or turn on the spreadsheet summary.</p>
              )}
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-end gap-2 border-t p-4">
            <Dialog.Close render={<Button variant="outline" />}>Cancel</Dialog.Close>
            <a data-testid="export-download" href={`${API}/api/export?fmt=zip&${q}`} download
              className="inline-flex h-8 items-center justify-center gap-1.5 rounded-sm bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90">
              <Download className="size-4" aria-hidden /> Download zip
            </a>
          </div>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
