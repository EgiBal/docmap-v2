"use client";
import { useParams } from "next/navigation";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { AlertTriangle, ArrowLeft, FileDown } from "lucide-react";
import AICitations from "@/components/kokonutui/ai-citations";
import { Badge, Empty, FormatIcon, H2, SkeletonRows } from "@/components/docmap/bits";
import { fileUrl, fmt, tokenDelta, type DocDetail } from "@/lib/api";
import { useApi } from "@/lib/use-api";

const RENDER_LIMIT = 60_000;
const safeDecode = (s: string) => { try { return decodeURIComponent(s); } catch { return s; } };

export default function DocPage() {
  const { id } = useParams<{ id: string }>();
  const { data, error } = useApi<DocDetail>(`/api/documents/${encodeURIComponent(safeDecode(id))}`);
  if (error) return <Empty title="Document not found">{error}</Empty>;
  if (!data) return <div className="mt-7"><SkeletonRows n={5} /></div>;
  const md = data.markdown.slice(0, RENDER_LIMIT);
  const cut = data.markdown.length > RENDER_LIMIT || data.truncated;
  const dw = data.doc_warnings.filter((w) => w.kind !== "size");
  return (
    <div className="space-y-6 pt-5">
      <Link href="/docs" className="inline-flex items-center gap-1 rounded-sm text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" /> Documents</Link>
      <header className="flex flex-wrap items-center gap-3">
        <FormatIcon format={data.format} className="size-5 text-muted-foreground" />
        <h1 className="num min-w-0 break-all text-lg font-semibold">{data.id}</h1>
        {data.status !== "ok" && <Badge tone={data.status === "needs_ocr" || data.status === "error" ? "bad" : "warn"}>{data.status}</Badge>}
        {data.markdown && (
          <a href={fileUrl(`${data.id}.md`)} download={`${data.id}.md`} data-testid="doc-download"
            className="ml-auto inline-flex h-8 items-center gap-1.5 rounded-sm bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90">
            <FileDown className="size-4" aria-hidden /> Download .md
          </a>
        )}
      </header>

      {dw.length > 0 && (
        <div data-testid="doc-warnings-box" className="space-y-1 rounded-xl border border-warn bg-warn-bg p-3 text-sm text-warn">
          {dw.map((w, i) => <div key={i} className="flex items-start gap-2"><AlertTriangle className="mt-0.5 size-4 shrink-0" /> <span>{w.text}</span></div>)}
        </div>
      )}

      {data.size_warning && (
        <div data-testid="size-warning" className="flex items-start gap-2 rounded-xl border border-warn bg-warn-bg p-3 text-warn text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warn" /> {data.size_warning}
        </div>
      )}

      <section className="grid grid-cols-3 gap-2 sm:gap-4">
        <div className="rounded-xl border bg-card p-4"><div className="text-xs font-medium text-muted-foreground">Naive dump</div><div className="num text-2xl font-semibold">{fmt(data.tokens.naive)}</div></div>
        <div className="rounded-xl border bg-card p-4"><div className="text-xs font-medium text-muted-foreground">Slim Markdown</div><div className="num text-2xl font-semibold">{fmt(data.tokens.slim)}</div></div>
        <div className="rounded-xl border bg-card p-4"><div className="text-xs font-medium text-muted-foreground">Markdown vs plain text</div><div data-testid="doc-delta" className="num text-2xl font-semibold">{tokenDelta(data.tokens.saved_pct).value}</div><div className="mt-1 text-xs text-muted-foreground">{tokenDelta(data.tokens.saved_pct).text}</div></div>
      </section>

      <section className="space-y-3">
        <H2>Theme links and evidence</H2>
        {data.links.length === 0 && <Empty title="No links">This document has no topic links.</Empty>}
        {data.links.map((l) => (
          <div key={l.id} className="rounded-xl border bg-card p-4 space-y-2">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-medium">{l.topic_name}</span>
              <Badge tone={l.status === "accepted" ? "ok" : l.status === "rejected" || l.status === "moved" ? "bad" : "muted"}>{l.status}</Badge>
              <span className="num text-muted-foreground">confidence {Math.round(l.confidence * 100)}%{l.source === "human" ? " - set by a human" : ""}</span>
              {l.content_changed && <Badge tone="warn" title="The document was re-uploaded after this decision">content changed since review</Badge>}
              {l.disagreement && <Badge tone="warn">AI and embeddings disagree</Badge>}
            </div>
            {l.evidence.length > 0 && (
              <AICitations
                parts={[{ text: `Linked to ${l.topic_name} based on these passages`, cite: l.evidence.map((_, i) => `e${l.id}-${i}`) }]}
                sources={l.evidence.map((e, i) => ({ id: `e${l.id}-${i}`, title: e.heading || "passage", url: "#", site: `sim ${e.sim}`, snippet: e.snippet }))}
              />
            )}
          </div>
        ))}
      </section>

      <section className="space-y-3">
        <H2>Markdown</H2>
        {md ? (
          <article className="prose prose-sm dark:prose-invert max-w-none overflow-x-auto rounded-xl border bg-card p-6">
            <ReactMarkdown remarkPlugins={[remarkGfm]}
              components={{ img: () => null, a: (p) => <a href={p.href} target="_blank" rel="noopener noreferrer nofollow">{p.children}</a> }}>{md}</ReactMarkdown>
            {cut && <p data-testid="preview-cut" className="text-muted-foreground">Preview shows the first {fmt(md.length)} of about {fmt(data.total_bytes)} characters. The export contains every row.</p>}
          </article>
        ) : <Empty title="No Markdown">{data.status === "needs_ocr" ? "This scan needs OCR first." : "Nothing was converted."}</Empty>}
      </section>
    </div>
  );
}

