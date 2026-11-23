"use client";
import "@xyflow/react/dist/style.css";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Background, Controls, Handle, Position, ReactFlow, ReactFlowProvider, useNodesState, useReactFlow,
  type Edge, type Node, type NodeProps } from "@xyflow/react";
import { Check, MoveRight, X } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Badge, Empty, FormatIcon, PageHead } from "@/components/docmap/bits";
import { ExportButton } from "@/components/docmap/export-dialog";
import { TopicPicker } from "@/components/docmap/topic-picker";
import { useToaster } from "@/components/docmap/providers";
import { patchLink, type DocDetail, type GraphT, type LinkT, type Topic } from "@/lib/api";
import { tokens, topicColors } from "@/lib/tokens";
import { useApi } from "@/lib/use-api";

type TopicData = { label: string; color: string; count: number };
type DocData = { label: string; format: string; status: string; warn: number };

const hidden = { opacity: 0, top: "50%", left: "50%", pointerEvents: "none" as const };
const ROOT = process.env.NEXT_PUBLIC_API ?? "http://localhost:8000";

function TopicNode({ data }: NodeProps<Node<TopicData>>) {
  return (
    <div data-testid="topic-node" className="flex h-[84px] w-[190px] flex-col items-center justify-center rounded-xl border-2 bg-card px-3 text-center"
      style={{ borderColor: data.color }}>
      <Handle type="target" position={Position.Top} style={hidden} isConnectable={false} />
      <div className="line-clamp-3 text-[14px] font-semibold leading-tight" title={data.label}>{data.label}</div>
      <div className="num mt-1 text-[13px] text-muted-foreground">{data.count} docs</div>
    </div>
  );
}

function DocNode({ data }: NodeProps<Node<DocData>>) {
  return (
    <div data-testid="doc-node" title={data.label}
      className="flex h-[30px] w-[300px] items-center gap-2 rounded-md border bg-card px-2.5 text-[13px]">
      <Handle type="source" position={Position.Top} style={hidden} isConnectable={false} />
      <FormatIcon format={data.format} className="size-4 shrink-0 text-muted-foreground" />
      <span className="truncate">{data.label.replace(/\.[a-z0-9]{2,5}$/i, "")}</span>
      {(data.status === "needs_ocr" || data.status === "error") && <span className="ml-auto size-2 shrink-0 rounded-full" title="needs attention" style={{ background: "var(--danger)" }} />}
      {data.warn > 0 && data.status !== "needs_ocr" && data.status !== "error" && <span className="ml-auto size-2 shrink-0 rounded-full" title="has warnings" style={{ background: "var(--warn)" }} />}
    </div>
  );
}

const nodeTypes = { topic: TopicNode, doc: DocNode };

// Geometry (flow units; at 1440 px wide the map fits at about 0.9x, so the 13 px labels stay near 12 px).
const TOPIC_W = 190, TOPIC_H = 84, DOC_W = 300, DOC_H = 30, PITCH = 38, GAP = 110, COLS = 2, COL_GAP = 50, ROW_GAP = 36;

/** Each theme is a cell: the theme box on the left, its documents stacked on the right, one straight line per link.
 *  Cells sit in a grid of COLS columns. Documents without a link go in a strip at the bottom. No layout library. */
function layout(g: GraphT): { nodes: Node[]; edges: Edge[]; topicIds: number[] } {
  const topics = g.nodes.filter((n) => n.type === "topic");
  const shown = g.edges.filter((e) => e.data.status !== "rejected" && e.data.status !== "moved");
  const topicIds = topics.map((t) => Number(t.data.topic_id));
  const colors = topicColors(topicIds);
  const top: Record<string, string> = {};
  for (const e of [...shown].sort((a, b) => a.data.confidence - b.data.confidence)) top[e.source] = e.target;
  const conf: Record<string, number> = {};
  for (const e of shown) conf[e.source] = Math.max(conf[e.source] ?? 0, e.data.confidence);
  const per: Record<string, string[]> = {};
  const loose: string[] = [];
  for (const d of g.nodes.filter((n) => n.type === "doc")) (top[d.id] ? (per[top[d.id]] ??= []) : loose).push(d.id);
  for (const list of Object.values(per)) list.sort((a, b) => (conf[b] ?? 0) - (conf[a] ?? 0) || a.localeCompare(b));

  const pos: Record<string, { x: number; y: number }> = {};   // top-left corner
  const rows = Math.ceil(topics.length / COLS);
  let y0 = 0;
  for (let row = 0; row < rows; row++) {
    const cell = topics.slice(row * COLS, row * COLS + COLS);
    const dhOf = (id: string) => Math.max(0, (per[id]?.length ?? 0) * PITCH - (PITCH - DOC_H));
    const h = Math.max(TOPIC_H, ...cell.map((t) => dhOf(t.id)));
    cell.forEach((t, c) => {
      const x0 = c * (TOPIC_W + GAP + DOC_W + COL_GAP);
      const dh = dhOf(t.id);
      pos[t.id] = { x: x0, y: y0 + (h - TOPIC_H) / 2 };
      (per[t.id] ?? []).forEach((d, j) => (pos[d] = { x: x0 + TOPIC_W + GAP, y: y0 + (h - dh) / 2 + j * PITCH }));
    });
    y0 += h + ROW_GAP;
  }
  loose.forEach((id, i) => (pos[id] = { x: (i % COLS) * (TOPIC_W + GAP + DOC_W + COL_GAP) + TOPIC_W + GAP, y: y0 + 20 + Math.floor(i / COLS) * PITCH }));
  const count: Record<string, number> = {};
  Object.values(top).forEach((t) => (count[t] = (count[t] ?? 0) + 1));
  const nodes: Node[] = g.nodes.map((n) => {
    const p = pos[n.id] ?? { x: 0, y: 0 };
    if (n.type === "topic") {
      const color = colors.get(Number(n.data.topic_id)) ?? "var(--muted-c)";
      return { id: n.id, type: "topic", position: p, data: { label: String(n.data.label), color, count: count[n.id] ?? 0 }, zIndex: 2 };
    }
    return { id: n.id, type: "doc", position: p, data: { label: String(n.data.label), format: String(n.data.format), status: String(n.data.status), warn: Number(n.data.warn ?? 0) }, zIndex: 3 };
  });
  const edges: Edge[] = shown.map((e) => {
    const acc = e.data.status === "accepted";
    const op = tokens.edge.minOpacity + (tokens.edge.maxOpacity - tokens.edge.minOpacity) * Math.min(1, Math.max(0, e.data.confidence));
    return { id: e.id, source: e.source, target: e.target, type: "straight", interactionWidth: 22, data: e.data,
      style: { stroke: colors.get(e.data.topic_id), opacity: acc ? 1 : op,
        strokeWidth: acc ? tokens.edge.widthAccepted : tokens.edge.widthProposed, strokeDasharray: acc ? undefined : "6 4" } };
  });
  return { nodes, edges, topicIds };
}

function MapInner() {
  const graph = useApi<GraphT>("/api/graph");
  const topicsQ = useApi<Topic[]>("/api/topics");
  const toaster = useToaster();
  const { getIntersectingNodes } = useReactFlow();
  const [sel, setSel] = useState<number | null>(null);
  const [det, setDet] = useState<{ sel: number; link: LinkT | null } | null>(null);
  const [pickFor, setPickFor] = useState<number | null>(null);
  const detail = det && det.sel === sel ? det.link : null;   // derived: switching edge clears it, no effect needed
  const picking = pickFor !== null && pickFor === sel;
  const setPicking = (v: boolean) => setPickFor(v ? sel : null);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [rev, setRev] = useState(0);

  const built = useMemo(() => (graph.data ? layout(graph.data) : null), [graph.data, rev]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (built) setNodes(built.nodes); }, [built, setNodes]);

  useEffect(() => {
    if (sel == null || !graph.data) return;
    const e = graph.data.edges.find((x) => x.data.link_id === sel);
    if (!e) return;
    fetch(`${ROOT}/api/documents/${encodeURIComponent(e.data.doc_id)}`)
      .then((r) => r.json()).then((d: DocDetail) => setDet({ sel, link: d.links.find((l) => l.id === sel) ?? null }));
  }, [sel, graph.data]);

  const act = useCallback((linkId: number, action: "accept" | "reject" | "move", doc: string, topic?: Topic) => {
    setPickFor(null);
    toaster.show(async () => { await patchLink(linkId, action, topic?.id); setSel(null); await graph.reload(); await topicsQ.reload(); },
      { loading: action === "move" ? "Moving link" : action === "accept" ? "Accepting link" : "Rejecting link",
        success: [action === "move" ? `Moved to ${topic?.name}` : action === "accept" ? "Link accepted" : "Link rejected", doc],
        error: (e) => ["Could not save", String((e as Error).message)] });
  }, [graph, toaster, topicsQ]);

  const onDragStop = useCallback((_: unknown, node: Node) => {
    if (node.type !== "doc" || !graph.data) { return; }
    const target = getIntersectingNodes(node).find((n) => n.type === "topic");
    const mine = graph.data.edges.filter((e) => e.source === node.id && e.data.status !== "rejected" && e.data.status !== "moved")
      .sort((a, b) => b.data.confidence - a.data.confidence)[0];
    if (target && mine && target.id !== mine.target) {
      const t = topicsQ.data?.find((x) => `t${x.id}` === target.id);
      if (t) { act(mine.data.link_id, "move", String(node.data.label), t); return; }
    }
    setRev((r) => r + 1);   // snap back
  }, [act, getIntersectingNodes, graph.data, topicsQ.data]);

  if (graph.error) return <Empty title="Cannot reach the API">{graph.error}</Empty>;
  if (!graph.data) return <div className="skeleton mt-7 h-[420px] rounded-xl" aria-busy aria-label="Loading map" />;
  if (graph.data && graph.data.nodes.length === 0) return <Empty title="Nothing to map yet">Upload and process documents on the dashboard.</Empty>;

  return (
    <div>
      <PageHead title="Topic map" sub="Themes and the documents linked to them. Click a line to review it, drag a document onto another theme to move it." actions={<ExportButton />} />
      <div className="relative overflow-hidden rounded-xl border bg-card" data-testid="map-scroll">
        <div className="h-[calc(100vh-11rem)] min-h-[420px] min-w-[820px]" data-testid="map">
          <ReactFlow nodes={nodes} edges={built?.edges ?? []} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.04 }}
            nodesConnectable={false} minZoom={0.2} onNodesChange={onNodesChange}
            onNodeDragStop={onDragStop} onEdgeClick={(_, e) => setSel((e.data as { link_id: number }).link_id)}
            onPaneClick={() => setSel(null)} proOptions={{ hideAttribution: true }}>
            <Background gap={24} />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>

        {detail && (
          <aside className="absolute right-3 top-3 max-h-[calc(100%-1.5rem)] w-[320px] max-w-[calc(100%-1.5rem)] space-y-3 overflow-auto rounded-xl border bg-card p-4 text-sm shadow-lg" data-testid="side-panel">
            <Link href={`/docs/${encodeURIComponent(detail.doc_id)}`} className="block break-all font-medium hover:underline">{detail.doc_id}</Link>
            <div className="flex flex-wrap items-center gap-2"><MoveRight className="size-4" /> <b>{detail.topic_name}</b>
              <Badge tone={detail.status === "accepted" ? "ok" : "muted"}>{detail.status}</Badge>
              <span className="num text-muted-foreground">{Math.round(detail.confidence * 100)}%</span></div>
            <div className="space-y-2">
              {detail.evidence.slice(0, 3).map((e, i) => (
                <blockquote key={i} className="rounded-r-sm border-l-2 border-primary bg-surface-2 px-3 py-2">
                  <div className="text-xs text-muted-foreground">{e.heading} - sim {e.sim}</div>
                  <div className="line-clamp-4 break-words">{e.snippet}</div>
                </blockquote>
              ))}
            </div>
            {picking ? (
              <TopicPicker topics={topicsQ.data ?? []} currentId={detail.topic_id} onPick={(t) => act(detail.id, "move", detail.doc_id, t)} />
            ) : (
              <div className="flex flex-wrap gap-2">
                <Button size="sm" data-testid="map-accept" onClick={() => act(detail.id, "accept", detail.doc_id)}><Check className="size-4" /> Accept</Button>
                <Button size="sm" variant="outline" data-testid="map-reject" onClick={() => act(detail.id, "reject", detail.doc_id)}><X className="size-4" /> Reject</Button>
                <Button size="sm" variant="outline" data-testid="map-move" onClick={() => setPicking(true)}>Move</Button>
              </div>
            )}
          </aside>
        )}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 px-1 pt-2 text-xs text-muted-foreground">
        <span>Solid thick: accepted</span><span>Dashed: proposed, needs review</span><span>Lighter: lower confidence</span>
        <span>Click a line for the evidence. Drag a document onto another theme to move it.</span>
      </div>
    </div>
  );
}
export default function MapPage() {
  return <ReactFlowProvider><MapInner /></ReactFlowProvider>;
}


