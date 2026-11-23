"use client";
import { Download, FileDown, FolderOpen } from "lucide-react";
import { Button } from "@/components/ui/button";
import { API, fileUrl, fmtBytes, openFolder, type FileList_ } from "@/lib/api";
import { useToaster } from "@/components/docmap/providers";
import { FormatIcon } from "@/components/docmap/bits";
import { cn } from "@/lib/utils";

/** "Your converted files": one Download button per Markdown file, Download all (zip), and the folder on disk. */
export function Downloads({ list, highlight = [], className }: { list: FileList_ | null; highlight?: string[]; className?: string }) {
  const toaster = useToaster();
  const files = list?.files ?? [];
  const open = () => toaster.show(async () => { await openFolder("markdown"); return true; },
    { loading: "Opening the folder", success: "Folder opened in Explorer", error: (e) => ["Cannot open the folder", String((e as Error).message)] });

  return (
    <div className={cn("rounded-2xl border bg-card p-5 sm:p-6", className)} data-testid="downloads">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-base font-semibold">Your converted files</h3>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {files.length ? `${files.length} Markdown file${files.length === 1 ? "" : "s"} ready. Download them here, or open the folder.` : "Converted files appear here, ready to download."}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" size="lg" onClick={open} data-testid="open-md-folder"><FolderOpen className="size-4" /> Open folder</Button>
          {files.length > 0 && (
            <a href={`${API}/api/files/all.zip`} download data-testid="download-all"
              className="inline-flex h-9 items-center gap-1.5 rounded-sm bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90">
              <Download className="size-4" aria-hidden /> Download all (.zip)
            </a>
          )}
        </div>
      </div>

      {list && (
        <p className="mt-3 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
          Saved on this PC in <code className="num break-all rounded-[4px] bg-surface-2 px-1.5 py-0.5 text-foreground">{list.folder}</code>
        </p>
      )}

      {list && files.length === 0 && (
        <div className="mt-4 flex flex-col items-center gap-2 rounded-xl border border-dashed px-6 py-8 text-center" data-testid="downloads-empty">
          <div className="grid size-11 place-items-center rounded-xl bg-surface-2 text-muted-foreground" aria-hidden><FileDown className="size-5" /></div>
          <div className="font-medium">No converted files yet</div>
          <div className="text-sm text-muted-foreground">After step 2, every file appears here with its own Download button.</div>
        </div>
      )}

      {files.length > 0 && (
        <ul className="mt-4 max-h-[360px] divide-y overflow-y-auto rounded-xl border" data-testid="file-list">
          {files.map((f) => {
            const ext = f.source.split(".").pop() ?? "";
            const isNew = highlight.includes(f.source);
            return (
              <li key={f.name} className={cn("flex items-center gap-3 px-3 py-2.5 text-sm", isNew && "bg-accent-soft/40")}>
                <FormatIcon format={ext} className="text-muted-foreground" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium" title={f.name}>{f.name}</span>
                  <span className="num text-xs text-muted-foreground">{fmtBytes(f.bytes)}{isNew ? " · new" : ""}</span>
                </span>
                <a href={fileUrl(f.name)} download={f.name} aria-label={`Download ${f.name}`}
                  className="inline-flex h-7 items-center gap-1 rounded-sm border px-2.5 text-xs font-medium hover:bg-surface-2">
                  <FileDown className="size-3.5" aria-hidden /> .md
                </a>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
