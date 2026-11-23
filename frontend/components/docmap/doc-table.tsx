"use client";
import Link from "next/link";
import { useMemo } from "react";
import { topicColors } from "@/lib/tokens";
import { fmt, type DocRow, type Topic } from "@/lib/api";
import { Badge, ThemeTag, WarnChips } from "@/components/docmap/bits";

const compact = (n: number) => (n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : fmt(n));

function Status({ d }: { d: DocRow }) {
  if (d.status === "needs_ocr") return <Badge tone="bad">Needs OCR</Badge>;
  if (d.status === "error") return <Badge tone="bad" title={d.note}>Error</Badge>;
  if (d.status === "unsupported") return <Badge tone="bad" title={d.note}>Unsupported</Badge>;
  if (d.size_warning) return <Badge tone="warn" title={d.size_warning} className="whitespace-normal">&asymp; {compact(d.token_count)} tokens &mdash; too large for most LLMs</Badge>;
  if (d.status === "digest") return <Badge tone="warn">Digest (lossy)</Badge>;
  const t = d.top_topic;
  if (!t) return <Badge tone="muted">No theme</Badge>;
  if (t.status === "accepted") return <Badge tone="ok" className="pl-0">Linked, reviewed</Badge>;
  if (t.confidence < 0.6) return <Badge tone="warn" className="bg-transparent pl-0">Review: <span className="num ml-1">{t.confidence.toFixed(2)}</span></Badge>;
  return <Badge tone="ok" className="pl-0">Linked</Badge>;
}

/** The mockup's file table: file, tokens before -> after, theme dot, status. */
export function DocTable({ docs, topics }: { docs: DocRow[]; topics: Topic[] }) {
  const colors = useMemo(() => topicColors(topics.map((t) => t.id)), [topics]);
  return (
    <div className="overflow-hidden rounded-xl border bg-card" data-testid="doc-table">
      <div className="hidden grid-cols-[minmax(0,2.4fr)_minmax(0,1fr)_minmax(0,1.3fr)_minmax(0,1.6fr)] gap-3 bg-surface-2 px-4 py-2.5 text-xs font-medium text-muted-foreground sm:grid">
        <div>File</div><div>Tokens</div><div>Theme</div><div>Status</div>
      </div>
      {docs.map((d) => {
        const naive = d.naive_tokens;
        return (
          <div key={d.id} data-testid="doc-row" className="fade-in grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 border-t px-4 py-2.5 first:border-t-0 hover:bg-surface-2/50 sm:grid-cols-[minmax(0,2.4fr)_minmax(0,1fr)_minmax(0,1.3fr)_minmax(0,1.6fr)]">
            <Link href={`/docs/${encodeURIComponent(d.id)}`} className="num col-span-2 truncate rounded-sm text-[12.5px] hover:underline sm:col-span-1" title={d.id}>{d.id}</Link>
            <div className="num text-[12.5px]">
              {d.status === "needs_ocr" ? <span className="text-muted-foreground">&mdash;</span> : (
                <>{naive != null && naive > d.token_count && <s className="mr-1.5 text-muted-foreground">{compact(naive)}</s>}{compact(d.token_count)}</>
              )}
            </div>
            <div className="col-start-1 row-start-3 sm:col-start-auto sm:row-start-auto">
              {d.top_topic ? <ThemeTag name={d.top_topic.name} color={colors.get(d.top_topic.id) ?? "var(--muted-c)"} /> : <span className="text-xs text-muted-foreground">No theme</span>}
            </div>
            <div className="col-span-2 flex flex-col items-start gap-1 sm:col-span-1">
              <Status d={d} />
              {(d.status === "error" || d.status === "unsupported") && d.note && <span className="text-xs text-danger">{d.note}</span>}
              <WarnChips warnings={d.warnings ?? []} skip={["size", ...(d.status === "needs_ocr" ? ["ocr"] : []), ...(d.status === "error" ? ["encrypted", "other"] : []), ...(d.status === "unsupported" ? ["unsupported"] : [])]} />
            </div>
          </div>
        );
      })}
    </div>
  );
}
