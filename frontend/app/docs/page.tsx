"use client";
import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import { Empty, PageHead, SkeletonRows } from "@/components/docmap/bits";
import { DocTable } from "@/components/docmap/doc-table";
import type { DocRow, Topic } from "@/lib/api";
import { useApi } from "@/lib/use-api";

export default function DocumentsPage() {
  const docs = useApi<DocRow[]>("/api/documents");
  const topics = useApi<Topic[]>("/api/topics");
  const [q, setQ] = useState("");
  const shown = useMemo(() => (docs.data ?? []).filter((d) => d.id.toLowerCase().includes(q.toLowerCase()) || (d.top_topic?.name ?? "").toLowerCase().includes(q.toLowerCase())), [docs.data, q]);
  return (
    <div>
      <PageHead title="Documents" sub={docs.data ? `${docs.data.length} documents. Click a file to read its Markdown and evidence.` : "Loading documents."}
        actions={
          <label className="relative block w-full sm:w-64">
            <span className="sr-only">Filter documents</span>
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter by file or theme" data-testid="doc-filter"
              className="h-8 w-full rounded-sm border bg-surface pl-8 pr-2 text-sm placeholder:text-muted-foreground" />
          </label>} />
      {docs.error && <Empty title="Cannot reach the API">{docs.error}</Empty>}
      {!docs.data && !docs.error && <SkeletonRows n={8} />}
      {docs.data && shown.length === 0 && <Empty title={q ? "No match" : "No documents yet"}>{q ? "Try a shorter filter." : "Upload files on the dashboard."}</Empty>}
      {shown.length > 0 && <DocTable docs={shown} topics={topics.data ?? []} />}
    </div>
  );
}
