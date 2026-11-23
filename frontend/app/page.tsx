"use client";
import { useCallback, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowRight, Check, CircleHelp, Cpu, FileDown, FileText, Loader2, Lock, Network, ScanSearch, Sparkles, Upload, X,
} from "lucide-react";
import { useToaster } from "@/components/docmap/providers";
import { Empty, H2, Metric, SkeletonRows } from "@/components/docmap/bits";
import { DocTable } from "@/components/docmap/doc-table";
import { ExportButton } from "@/components/docmap/export-dialog";
import { Downloads } from "@/components/docmap/downloads";
import {
  api, fmt, PRESET_LABEL, STAGES, tokenDelta,
  type DocRow, type FileList_, type JobStatus, type Metrics, type Settings, type Topic, type UploadResult,
} from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";

const ACCEPT = ".pdf,.docx,.doc,.xlsx,.xls,.xlsm,.pptx,.ppt,.odt,.ods,.odp,.rtf,.csv,.epub";
const FORMATS = ["PDF", "Word", "Excel", "PowerPoint", "CSV", "OpenDocument", "RTF", "EPUB"];

type Picked = { name: string; state: "uploading" | "ready" | "error"; reason?: string };

function Step({ n, title, right, children }: { n: number; title: string; right?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border bg-card p-5 shadow-sm sm:p-7">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-3 text-base font-semibold">
          <span className="v-step num grid size-7 place-items-center rounded-lg bg-foreground text-sm text-background">{n}</span>{title}
        </h2>
        {right}
      </div>
      {children}
    </section>
  );
}

export default function Home() {
  const metrics = useApi<Metrics>("/api/metrics");
  const docs = useApi<DocRow[]>("/api/documents");
  const topics = useApi<Topic[]>("/api/topics");
  const files = useApi<FileList_>("/api/files");
  const settings = useApi<Settings>("/api/settings");
  const toaster = useToaster();
  const [job, setJob] = useState<JobStatus | null>(null);
  const [picked, setPicked] = useState<Picked[]>([]);
  const [over, setOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const polling = useRef(false);
  const running = job?.state === "running";
  const ready = picked.filter((p) => p.state === "ready").length;
  const busyUpload = picked.some((p) => p.state === "uploading");

  const reloadAll = useCallback(() => { metrics.reload(); docs.reload(); topics.reload(); files.reload(); }, [metrics, docs, topics, files]);

  // Each file is sent on its own, so one bad file never blocks the others.
  const upload = async (list: File[]) => {
    setPicked((p) => [...p.filter((x) => !list.some((f) => f.name === x.name)), ...list.map((f) => ({ name: f.name, state: "uploading" as const }))]);
    for (const f of list) {
      const fd = new FormData(); fd.append("files", f);
      let next: Picked;
      try {
        const r = await api<UploadResult>("/api/upload", { method: "POST", body: fd });
        next = r.errors.length ? { name: f.name, state: "error", reason: r.errors[0].reason } : { name: f.name, state: "ready" };
      } catch (e) { next = { name: f.name, state: "error", reason: (e as Error).message }; }
      setPicked((p) => p.map((x) => (x.name === f.name ? next : x)));
    }
  };

  const run = (kind: "convert" | "process", sample = false) => {
    if (polling.current) return;
    polling.current = true;
    toaster.show(async () => {
      try {
        await api(kind === "convert" ? "/api/convert" : "/api/process", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sample }) });
        for (;;) {
          const st = await api<JobStatus>("/api/process/status");
          setJob(st);
          if (st.state === "done") return st;
          if (st.state === "error") throw new Error(st.message);
          await new Promise((r) => setTimeout(r, 1000));
        }
      } finally { polling.current = false; reloadAll(); }
    }, kind === "convert"
      ? { loading: "Converting to Markdown", success: (s) => ["Conversion finished", (s as JobStatus).message], error: (e) => ["Conversion failed", String((e as Error).message)] }
      : { loading: "Converting and finding themes", waiting: "Convert, then themes and links", success: "Themes are ready. Check them in Review.", error: (e) => ["Processing failed", String((e as Error).message)] });
  };

  const m = metrics.data;
  const s = settings.data;
  const hasLibrary = (m?.docs ?? 0) > 0;
  const delta = m ? tokenDelta(m.tokens.saved_pct) : null;
  const pack = m?.pack;

  return (
    <div className="-mb-8">
      {/* Hero */}
      <section className="mx-auto max-w-[760px] pb-8 pt-12 text-center sm:pt-16">
        <span className="v-eyebrow inline-flex items-center gap-1.5 rounded-full border bg-card px-3 py-1 text-xs font-medium text-muted-foreground">
          <Lock className="size-3" aria-hidden /> Runs on your PC. Files are converted locally.
        </span>
        <h1 className="v-display mt-5 text-[32px] font-semibold leading-[1.15] tracking-tight sm:text-[42px]">
          Turn office files into clean Markdown, <span className="v-accent text-primary">sorted by business theme</span>
        </h1>
        <p className="mx-auto mt-4 max-w-[620px] text-base text-muted-foreground">
          Drop Word, Excel, PowerPoint or PDF files. DocMap converts them to Markdown that an AI reads well, finds the main themes,
          and lets you check every link before you export a small pack per theme.
        </p>
      </section>

      <div className="mx-auto max-w-[820px] space-y-5">
        {/* 1. Upload */}
        <Step n={1} title="Upload files">
          <div
            onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
            onDrop={(e) => { e.preventDefault(); setOver(false); if (e.dataTransfer.files.length) upload(Array.from(e.dataTransfer.files)); }}
            onClick={() => fileInput.current?.click()} role="button" tabIndex={0} data-testid="dropzone"
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.current?.click(); } }}
            aria-label="Upload files: drop them here or press Enter to choose"
            className={cn("flex min-h-[280px] cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors duration-200 ease-out hover:border-primary/60 hover:bg-surface-2/60",
              over && "border-primary bg-accent-soft/40")}>
            <div className={cn("grid size-14 place-items-center rounded-2xl bg-surface-2 text-muted-foreground transition-transform duration-200 ease-out", over && "scale-110 bg-accent-soft text-primary")} aria-hidden>
              {over ? <Upload className="size-7" /> : <FileText className="size-7" />}
            </div>
            <div>
              <div className="text-lg font-semibold">{over ? "Drop to upload" : "Drop your files here"}</div>
              <div className="mt-1 text-sm text-muted-foreground">or click to choose. You can add many files at once.</div>
            </div>
            <span className="mt-1 inline-flex h-9 items-center gap-1.5 rounded-sm bg-foreground px-4 text-sm font-medium text-background"><Upload className="size-4" aria-hidden /> Select files</span>
            <div className="mt-2 flex flex-wrap justify-center gap-1.5">
              {FORMATS.map((f) => <span key={f} className="rounded-full bg-surface-2 px-2 py-0.5 text-[11px] text-muted-foreground">{f}</span>)}
            </div>
          </div>
          <input ref={fileInput} type="file" multiple hidden accept={ACCEPT} data-testid="file-input"
            onChange={(e) => { if (e.target.files?.length) upload(Array.from(e.target.files)); e.target.value = ""; }} />

          {picked.length > 0 && (
            <ul className="mt-4 divide-y rounded-xl border" data-testid="picked">
              {picked.map((p) => (
                <li key={p.name} className="flex items-center gap-3 px-3 py-2 text-sm">
                  {p.state === "uploading" && <Loader2 className="size-4 animate-spin text-muted-foreground" aria-label="uploading" />}
                  {p.state === "ready" && <Check className="size-4 text-ok" aria-label="ready" />}
                  {p.state === "error" && <X className="size-4 text-danger" aria-label="not accepted" />}
                  <span className="min-w-0 flex-1 truncate">{p.name}</span>
                  {p.state === "error" && <span className="max-w-[55%] truncate text-xs text-danger" title={p.reason}>{p.reason}</span>}
                </li>
              ))}
            </ul>
          )}
          <p className="mt-3 text-xs text-muted-foreground">
            Large spreadsheets keep every row. DocMap only warns you when a file may be too large for an AI model.
          </p>
        </Step>

        {/* 2. Choose */}
        <Step n={2} title="Choose what to do"
          right={<Link href="/settings" className="inline-flex items-center gap-1.5 rounded-full border bg-surface px-3 py-1.5 text-sm text-muted-foreground hover:border-primary/60 hover:text-foreground" data-testid="model-badge">
            <Cpu className="size-4" aria-hidden /> AI model: <b className="font-medium text-foreground">{s ? PRESET_LABEL[s.preset] : "..."}</b> <span className="font-medium text-primary underline-offset-4 hover:underline">Change</span>
          </Link>}>
          <div className="grid gap-3 sm:grid-cols-2">
            <button type="button" data-testid="convert" disabled={running || busyUpload || ready === 0} onClick={() => run("convert")}
              className="rounded-xl border bg-surface p-4 text-left transition-colors hover:border-primary/60 hover:bg-surface-2 disabled:pointer-events-none disabled:opacity-75">
              <FileDown className="size-5 text-primary" aria-hidden />
              <div className="mt-2 font-semibold">Convert to Markdown</div>
              <div className="mt-1 text-sm text-muted-foreground">Fast. No AI is used and nothing leaves your PC. You get one .md file per document.</div>
            </button>
            <button type="button" data-testid="process" disabled={running || busyUpload || ready === 0} onClick={() => run("process")}
              className="rounded-xl border-2 border-primary/60 bg-accent-soft/40 p-4 text-left transition-colors hover:border-primary hover:bg-accent-soft/50 disabled:pointer-events-none disabled:opacity-75">
              <Sparkles className="size-5 text-primary" aria-hidden />
              <div className="mt-2 font-semibold">Convert and find themes</div>
              <div className="mt-1 text-sm text-muted-foreground">The AI model reads each document, names the business themes and links the files to them. You review the links next.</div>
            </button>
          </div>
          {ready === 0 && !running && (
            <p className="mt-3 flex flex-wrap items-center gap-x-1 rounded-xl bg-surface-2 px-3 py-2 text-sm text-muted-foreground" data-testid="upload-first">
              <Lock className="size-3.5" aria-hidden /> <b className="font-medium text-foreground">Upload files in step 1 to unlock these.</b> No files at hand?{" "}
              <button type="button" className="font-medium text-primary underline-offset-4 hover:underline" data-testid="process-sample" onClick={() => run("process", true)}>Try the 22 sample files</button>.
            </p>
          )}
          {job && job.state !== "idle" && (
            <div data-testid="progress" className="mt-4 space-y-1.5 rounded-xl bg-surface-2 p-3">
              <div className="h-1.5 overflow-hidden rounded bg-background"><div className="h-full bg-primary transition-[width] duration-200 ease-out" style={{ width: `${job.pct}%` }} /></div>
              {job.state === "error" ? <div className="text-xs text-danger">{job.message}</div> : (
                <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs" data-testid="stages">
                  {(job.kind === "convert" ? ["convert"] : [...STAGES] as string[]).map((st, i, all) => {
                    const cur = all.indexOf(job.step);
                    const state = job.state === "done" || i < cur ? "done" : i === cur ? "now" : "todo";
                    return <span key={st} data-stage={st} data-state={state} className={state === "now" ? "font-semibold text-foreground" : state === "done" ? "text-primary" : "text-muted-foreground"}>
                      {st}{state === "now" && job.total > 1 ? ` ${job.done}/${job.total}` : ""}</span>;
                  })}
                  <span className="num ml-auto text-muted-foreground" data-testid="progress-text">{job.pct}% · {job.elapsed}s</span>
                </div>
              )}
              {job.state === "done" && job.kind === "process" && (
                <Link href="/review" className="inline-flex items-center gap-1 text-sm font-medium text-primary">Review the theme links <ArrowRight className="size-4" /></Link>
              )}
            </div>
          )}
        </Step>

        {/* 3. Download */}
        <Step n={3} title="Download" right={hasLibrary ? <ExportButton /> : null}>
          <Downloads list={files.data} highlight={picked.filter((p) => p.state === "ready").map((p) => p.name)} className="border-0 p-0 sm:p-0" />
          {hasLibrary && (
            <p className="mt-4 rounded-xl bg-surface-2 p-3 text-sm text-muted-foreground">
              <b className="text-foreground">Theme packs:</b> &quot;Export context pack&quot; gives one Markdown file per theme. Send only the theme you need to an AI, not the whole library.
            </p>
          )}
        </Step>
      </div>

      {/* Library (after a theme run) */}
      {hasLibrary && m && (
        <section className="mx-auto mt-14 max-w-[820px]">
          <H2 right={m.size_warnings > 0 ? <span className="num text-xs text-warn">{m.size_warnings} too large for most LLMs</span> : null}>Your library</H2>
          <div className="grid grid-cols-2 gap-2 sm:gap-3 lg:grid-cols-4" aria-label="Summary">
            <Metric testId="m-docs" label="Documents" value={String(m.docs)} hint={`${m.docs - m.needs_ocr} converted · ${m.needs_ocr} needs OCR`} pct={(100 * (m.docs - m.needs_ocr)) / m.docs} />
            <Metric testId="m-topics" label="Themes found" value={String(m.topics)} hint={`${m.links_total} links to check`} pct={m.topics ? 100 : 0} />
            <Metric testId="m-reviews" label="Open reviews" value={String(m.open_reviews)} hint={`${m.links.accepted ?? 0} accepted · ${m.links.rejected ?? 0} rejected`} pct={m.links_total ? (100 * m.open_reviews) / m.links_total : 0} />
            {m.tokens.naive_known === false
              ? <Metric testId="m-saved" label="Markdown size" value={fmt(m.tokens.slim) + " tokens"} hint="plain-text baseline not measured for these files" />
              : <Metric testId="m-saved" label="Markdown vs plain text" value={delta!.value + " tokens"} hint={`${fmt(m.tokens.naive)} → ${fmt(m.tokens.slim)}`} pct={Math.max(0, m.tokens.saved_pct)} />}
          </div>
          {pack && pack.n_topics > 0 && (
            <p data-testid="pack-line" className="mt-2 text-[13px] text-muted-foreground">
              A typical theme pack is {fmt(pack.median_tokens)} tokens, <b className="text-foreground">{pack.median_saved_pct >= 0 ? `${pack.median_saved_pct}% smaller` : `${Math.abs(pack.median_saved_pct)}% larger`}</b> than the whole library ({fmt(pack.library_tokens)} tokens).
            </p>
          )}
          <div className="mt-4">
            {!docs.data && !docs.error && <SkeletonRows />}
            {docs.data && docs.data.length > 0 && <DocTable docs={docs.data} topics={topics.data ?? []} />}
          </div>
        </section>
      )}

      {metrics.error && <div className="mx-auto mt-6 max-w-[820px]"><Empty title="Cannot reach the DocMap API">Double-click <code>Start DocMap.bat</code> again. ({metrics.error})</Empty></div>}

      <HowItWorks />
      <Results />
      <Faq />
    </div>
  );
}

const STEPS = [
  { icon: FileText, title: "Convert", text: "Each file becomes lean Markdown: headings, lists and real tables. anydoc converts first, markitdown is the fallback. Scanned pages are flagged for OCR, never sent away." },
  { icon: ScanSearch, title: "Read", text: "The AI model writes a short business profile of every document. Only the text is sent, inside clear document markers." },
  { icon: Network, title: "Find themes", text: "One call proposes 4 to 7 business themes for the whole set. Each file is then linked to its themes, with a confidence and the passages that support it." },
  { icon: Check, title: "Review and export", text: "You accept, reject or move each link on the map or in the review queue. Then export one Markdown pack per theme." },
];

function HowItWorks() {
  return (
    <section className="v-band mx-auto mt-20 max-w-[820px]" aria-labelledby="how">
      <h2 id="how" className="v-display text-center text-2xl font-semibold tracking-tight">How it works</h2>
      <p className="mx-auto mt-2 max-w-[560px] text-center text-muted-foreground">Four steps. Conversion is local. Only the theme steps use an AI model, and you choose which one.</p>
      <ol className="mt-8 grid gap-3 sm:grid-cols-2">
        {STEPS.map((st, i) => (
          <li key={st.title} className="rounded-2xl border bg-card p-5">
            <div className="flex items-center justify-between">
              <st.icon className="size-5 text-primary" aria-hidden />
              <span className="num text-xs text-muted-foreground">0{i + 1}</span>
            </div>
            <div className="mt-3 font-semibold">{st.title}</div>
            <p className="mt-1.5 text-sm text-muted-foreground">{st.text}</p>
          </li>
        ))}
      </ol>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div className="rounded-2xl border bg-card p-5">
          <div className="font-semibold">Why Markdown?</div>
          <p className="mt-1.5 text-sm text-muted-foreground">AI models read structure better than raw text. A table stays a table and a heading stays a heading. Markdown is about the same size as plain text, so the structure comes nearly free.</p>
        </div>
        <div className="rounded-2xl border bg-card p-5">
          <div className="font-semibold">Where is the real saving?</div>
          <p className="mt-1.5 text-sm text-muted-foreground">In routing. When you ask about one theme, you send only that theme&apos;s pack. In our test, 4 of 5 packs were at least 98% smaller than the whole library.</p>
        </div>
      </div>
    </section>
  );
}

const RESULTS = [
  { value: "0.93", label: "theme accuracy on unseen files", note: "F1 score against hand labels on 19 Food Standards Agency files kept apart during development" },
  { value: "71.5%", label: "fewer tokens than uploading the files", note: "Markdown against the estimated cost of uploading the original PDFs and documents" },
  { value: "≥98%", label: "smaller per theme", note: "Send the model one theme's pack instead of the whole library (4 of 5 themes in the test)" },
  { value: "every row", label: "kept from every spreadsheet", note: "Large files are converted in full, and DocMap warns you when one is too big for most AI models" },
];

function Results() {
  return (
    <section className="mx-auto mt-20 max-w-[820px]" aria-labelledby="results">
      <h2 id="results" className="v-display text-center text-2xl font-semibold tracking-tight">What the tests show</h2>
      <p className="mx-auto mt-2 max-w-[600px] text-center text-muted-foreground">We tested DocMap on 41 UK public-sector files (Environment Agency, Defra, Food Standards Agency) against themes a person set by hand. </p>
      <div className="mt-8 grid gap-3 sm:grid-cols-2">
        {RESULTS.map((r) => (
          <div key={r.label} className="rounded-2xl border bg-card p-5">
            <div className="v-stat num text-[32px] font-semibold leading-none tracking-tight text-primary">{r.value}</div>
            <div className="mt-2 text-sm font-medium">{r.label}</div>
            <p className="mt-1.5 text-xs text-muted-foreground">{r.note}</p>
          </div>
        ))}
      </div>
      <p className="mt-3 text-center text-xs text-muted-foreground">An F1 score of 1.0 means every file got the themes a person chose. AI answers vary between runs, so DocMap asks you to review each link.</p>
    </section>
  );
}

const FAQ = [
  { q: "Do my files leave my PC?", a: "Conversion runs on your PC. With a local model (Ollama), nothing leaves your PC at all. With NVIDIA NIM, the document text (not the file) is sent to NVIDIA to find the themes." },
  { q: "Which files work?", a: "PDF, Word (.docx/.doc), Excel (.xlsx/.xls/.xlsm), PowerPoint (.pptx/.ppt), CSV, OpenDocument, RTF and EPUB. Up to 100 MB per file." },
  { q: "What about scanned PDFs?", a: "DocMap finds pages without a text layer and marks them as \"needs OCR\". It does not guess their content." },
  { q: "Is a large spreadsheet cut?", a: "No. Every row is converted. DocMap warns you when a file is too large for most AI models. A short statistical summary is available as an option when you export." },
];

function Faq() {
  return (
    <section className="mx-auto mt-20 max-w-[820px]" aria-labelledby="faq">
      <h2 id="faq" className="v-display flex items-center justify-center gap-2 text-2xl font-semibold tracking-tight"><CircleHelp className="size-5 text-muted-foreground" aria-hidden /> Questions</h2>
      <div className="mt-6 divide-y rounded-2xl border bg-card">
        {FAQ.map((f) => (
          <details key={f.q} className="group px-5 py-4">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 font-medium">
              {f.q}<span className="text-muted-foreground transition-transform duration-200 group-open:rotate-45" aria-hidden>+</span>
            </summary>
            <p className="mt-2 text-sm text-muted-foreground">{f.a}</p>
          </details>
        ))}
      </div>
    </section>
  );
}
