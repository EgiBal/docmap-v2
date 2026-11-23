"use client";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, MoveRight, RefreshCw, X } from "lucide-react";
import { topicColors } from "@/lib/tokens";
import { Button } from "@/components/ui/button";
import { Empty, H2, Kbd, PageHead, SkeletonRows, ThemeTag } from "@/components/docmap/bits";
import { ExportButton } from "@/components/docmap/export-dialog";
import { TopicPicker } from "@/components/docmap/topic-picker";
import { useToaster } from "@/components/docmap/providers";
import { isBusy, patchLink, rescore, type LinkT, type Topic } from "@/lib/api";
import { useApi } from "@/lib/use-api";

export default function ReviewPage() {
  const queue = useApi<LinkT[]>("/api/review");
  const topicsQ = useApi<Topic[]>("/api/topics");
  const toaster = useToaster();
  const [idx, setIdx] = useState(0);
  const [picking, setPicking] = useState(false);
  const busy = useRef(false);
  const items = useMemo(() => queue.data ?? [], [queue.data]);
  const topics = useMemo(() => topicsQ.data ?? [], [topicsQ.data]);
  const cur = items[Math.min(idx, Math.max(items.length - 1, 0))];

  const act = useCallback((action: "accept" | "reject" | "move", topic?: Topic) => {
    if (!cur || busy.current) return;   // ignore keys while a save is in flight
    busy.current = true;
    const link = cur;
    setPicking(false);
    toaster.show(async () => { try { await patchLink(link.id, action, topic?.id); await queue.reload(); } finally { busy.current = false; } },
      { loading: action === "move" ? "Moving link" : action === "accept" ? "Accepting link" : "Rejecting link",
        success: [action === "move" ? `Moved to ${topic?.name}` : action === "accept" ? "Link accepted" : "Link rejected", link.doc_id],
        error: (e) => isBusy(e) ? ["Processing, try again in a moment", "A run is in progress; your decision was not saved"] : ["Could not save", String((e as Error).message)] });
  }, [cur, queue, toaster]);

  const rescoring = useRef(false);
  const doRescore = useCallback(() => {
    if (rescoring.current) return;
    rescoring.current = true;
    toaster.show(async () => { try { const r = await rescore(); await queue.reload(); return r; } finally { rescoring.current = false; } },
      { loading: "Re-scoring open links", success: (r) => [r.message, `${r.changed} changed, ${Object.keys(r.suggestions).length} suggested moves`],
        error: (e) => ["Could not re-score", String((e as Error).message)] });
  }, [queue, toaster]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key.toLowerCase();
      if (picking) {
        if (k === "escape" || k === "m") setPicking(false);
        const n = Number(k);
        if (n >= 1 && n <= 9 && topics[n - 1] && cur && topics[n - 1].id !== cur.topic_id) act("move", topics[n - 1]);
        return;
      }
      if (k === "a") act("accept");
      else if (k === "r") act("reject");
      else if (k === "m") setPicking(true);
      else if (k === "j") setIdx((i) => Math.min(i + 1, items.length - 1));
      else if (k === "k") setIdx((i) => Math.max(i - 1, 0));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [act, picking, items.length, topics, cur]);

  if (queue.error) return <Empty title="Cannot reach the API">{queue.error}</Empty>;
  if (!queue.data) return <div className="mx-auto max-w-3xl"><PageHead title="Review queue" /><SkeletonRows n={4} /></div>;
  if (!cur) return <div className="mx-auto max-w-3xl"><PageHead title="Review queue" /><Empty title="All caught up" action={<Link className="inline-flex h-8 items-center rounded-sm bg-primary px-3 text-sm font-medium text-primary-foreground" href="/map">Open the map</Link>}>No proposed links are waiting. Every suggestion has a decision.</Empty></div>;

  const pos = Math.min(idx, items.length - 1);
  const colors = topicColors(topics.map((t) => t.id));
  const colorOf = (id: number) => colors.get(id) ?? "var(--muted-c)";
  return (
    <div className="mx-auto max-w-3xl">
      <PageHead title="Review queue" sub={<span data-testid="queue-count">{items.length} open - disagreements, then lowest confidence - item {pos + 1}</span>} actions={<div className="flex flex-wrap gap-2"><Button variant="outline" data-testid="rescore" onClick={doRescore} title="Use your accepted and rejected links to update the confidence of the open ones"><RefreshCw className="size-4" /> Re-score open links</Button><ExportButton /></div>} />
      <H2 right={<span className="hidden items-center gap-3 text-xs text-muted-foreground sm:flex"><span>A accept</span><span>R reject</span><span>M move</span><span>J next</span><span>K prev</span></span>}>Review queue &middot; {pos + 1} of {items.length}</H2>

      <div key={cur.id} className="fade-in space-y-4 rounded-xl border bg-card p-[18px]" data-testid="review-card">
        <div className="flex justify-between text-xs text-muted-foreground"><span>AI suggestion</span><span>Disagreements first, then lowest confidence</span></div>
        <div className="flex flex-wrap items-center gap-2">
          <Link href={`/docs/${encodeURIComponent(cur.doc_id)}`} className="num break-all rounded-sm text-[12.5px] font-medium hover:underline">{cur.doc_id}</Link>
          <MoveRight className="size-4 text-muted-foreground" aria-hidden />
          <ThemeTag name={cur.topic_name} color={colorOf(cur.topic_id)} />
          <span className={`num rounded-sm px-1.5 py-px text-xs ${cur.confidence < 0.6 ? "bg-warn-bg text-warn" : "bg-surface-2 text-muted-foreground"}`}>{cur.confidence.toFixed(2)}</span>
        </div>

        {cur.disagreement && <div data-testid="disagree-hint" className="rounded-sm bg-warn-bg px-3 py-2 text-[13px] text-warn">AI and embeddings disagree on this link. Please check it first.</div>}
        {cur.content_changed && <div data-testid="changed-badge" className="rounded-sm bg-warn-bg px-3 py-2 text-[13px] text-warn">Content changed since review: the document was re-uploaded after your decision.</div>}
        <p className="text-[13px] text-muted-foreground">{reason(cur)}</p>
        {cur.suggestion && (
          <div data-testid="ai-hint" className="flex flex-wrap items-center gap-2 rounded-sm bg-accent-soft px-3 py-2 text-[13px]">
            <span>After your reviews, the AI now leans to <b>{cur.suggestion.topic_name}</b>. Nothing was changed.</span>
            {topics.find((t) => t.id === cur.suggestion!.topic_id) && (
              <Button size="sm" variant="outline" data-testid="ai-hint-move" onClick={() => act("move", topics.find((t) => t.id === cur.suggestion!.topic_id))}>Move there</Button>
            )}
          </div>
        )}

        <div className="space-y-2">
          {cur.evidence.length === 0 && <div className="text-sm text-muted-foreground">No passages stored.</div>}
          {cur.evidence.slice(0, 3).map((e, i) => (
            <blockquote key={i} className="rounded-r-sm border-l-2 border-primary bg-surface-2 px-3 py-2.5 text-[13px]">
              <div className="line-clamp-4 break-words">{highlight(e.snippet, cur.topic_name)}</div>
              <small className="num mt-1.5 block text-xs text-muted-foreground">{e.heading || "passage"} &middot; similarity {e.sim}</small>
            </blockquote>
          ))}
        </div>

        {picking ? (
          <div className="space-y-2">
            <div className="text-sm font-medium">Move to which theme? <span className="font-normal text-muted-foreground">(press 1-9 or click, Esc cancels)</span></div>
            <TopicPicker topics={topics} currentId={cur.topic_id} keys onPick={(t) => act("move", t)} />
          </div>
        ) : (
          <div className="flex flex-wrap gap-2">
            <Button data-testid="accept" onClick={() => act("accept")}><Check className="size-4" /> Accept <Kbd>A</Kbd></Button>
            <Button data-testid="reject" variant="outline" onClick={() => act("reject")}><X className="size-4" /> Reject <Kbd>R</Kbd></Button>
            <Button data-testid="move" variant="outline" onClick={() => setPicking(true)}><MoveRight className="size-4" /> Move <Kbd>M</Kbd></Button>
          </div>
        )}
      </div>
      <p className="mt-3 text-xs text-muted-foreground sm:hidden">Keys A, R, M, J, K work with a keyboard.</p>
    </div>
  );
}

function highlight(text: string, topic: string) {
  const words = topic.split(/[^A-Za-z]+/).filter((w) => w.length > 3).map((w) => w.toLowerCase());
  if (!words.length) return text;
  const re = new RegExp(`(${words.join("|")})`, "gi");
  return text.split(re).map((part, i) => (i % 2 ? <mark key={i} className="rounded-[2px] bg-accent-soft px-0.5 text-foreground">{part}</mark> : part));
}

function reason(l: LinkT) {
  const best = [...l.evidence].sort((a, b) => b.sim - a.sim)[0];
  return (
    <>
      The document profile and {l.evidence.length} passage{l.evidence.length === 1 ? "" : "s"} resemble the theme <b className="text-foreground">{l.topic_name}</b>
      {best ? <> (best match <span className="num">{best.sim}</span> on &ldquo;{best.heading}&rdquo;)</> : null}. Confidence <span className="num">{Math.round(l.confidence * 100)}%</span>
      {l.confidence < 0.4 ? " is low, so a human check is useful." : "."}
    </>
  );
}

