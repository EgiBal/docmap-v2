"use client";
import { useEffect, useState } from "react";
import { Check, Cloud, Copy, ExternalLink, FolderOpen, KeyRound, Laptop, Loader2, RefreshCw, X } from "lucide-react";
import { PageHead } from "@/components/docmap/bits";
import { useToaster } from "@/components/docmap/providers";
import { Button } from "@/components/ui/button";
import {
  checkSettings, openFolder, saveNimKey, saveSettings, type Preset, type Settings, type SettingsCheck,
} from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";

function CopyCmd({ cmd }: { cmd: string }) {
  const [done, setDone] = useState(false);
  return (
    <div className="mt-1.5 flex items-center gap-2 rounded-lg border bg-surface-2 py-1.5 pl-3 pr-1.5">
      <code className="num min-w-0 flex-1 overflow-x-auto whitespace-nowrap text-[13px]">{cmd}</code>
      <button type="button" aria-label={`Copy: ${cmd}`} onClick={() => { navigator.clipboard?.writeText(cmd); setDone(true); setTimeout(() => setDone(false), 1500); }}
        className="grid size-7 shrink-0 place-items-center rounded-sm text-muted-foreground hover:bg-background hover:text-foreground">
        {done ? <Check className="size-3.5 text-ok" /> : <Copy className="size-3.5" />}
      </button>
    </div>
  );
}

function Status({ check, loading }: { check: SettingsCheck | null; loading: boolean }) {
  if (loading || !check) return <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" /> Checking ...</span>;
  return (
    <span data-testid={`status-${check.preset}`} className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-sm font-medium", check.ok ? "bg-accent-soft/60 text-ok" : "bg-warn-bg text-warn")}>
      {check.ok ? <Check className="size-4" /> : <X className="size-4" />} {check.message}
    </span>
  );
}

function Choice({ on, icon: Icon, title, text, onClick, testId }: { on: boolean; icon: typeof Cloud; title: string; text: string; onClick: () => void; testId: string }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={on} data-testid={testId}
      className={cn("rounded-2xl border bg-card p-5 text-left transition-colors hover:border-primary/60", on && "border-primary ring-2 ring-primary/25")}>
      <div className="flex items-center justify-between">
        <Icon className="size-5 text-primary" aria-hidden />
        <span className={cn("grid size-5 place-items-center rounded-full border", on && "border-primary bg-primary text-primary-foreground")}>{on && <Check className="size-3" />}</span>
      </div>
      <div className="mt-3 font-semibold">{title}</div>
      <p className="mt-1 text-sm text-muted-foreground">{text}</p>
    </button>
  );
}

export default function SettingsPage() {
  const settings = useApi<Settings>("/api/settings");
  const toaster = useToaster();
  const [preset, setPreset] = useState<Preset | null>(null);
  const [check, setCheck] = useState<Record<Preset, SettingsCheck | null>>({ nim: null, local: null });
  const [checking, setChecking] = useState<Preset | null>(null);
  const [key, setKey] = useState("");
  const s = settings.data;
  const cur = preset ?? s?.preset ?? null;

  const runCheck = async (p: Preset) => {
    setChecking(p);
    try { const c = await checkSettings(p); setCheck((x) => ({ ...x, [p]: c })); }
    catch (e) { setCheck((x) => ({ ...x, [p]: { preset: p, ok: false, message: (e as Error).message } })); }
    setChecking(null);
  };
  useEffect(() => { if (cur) runCheck(cur); }, [cur]);

  const choose = (p: Preset) => toaster.show(async () => { await saveSettings(p); setPreset(p); return p; },
    { loading: "Saving", success: (p) => [`Theme steps now use ${p === "nim" ? "NVIDIA NIM" : "the local model"}`, ""], error: (e) => ["Not saved", String((e as Error).message)] });

  const saveKey = () => toaster.show(async () => { await saveNimKey(key); setKey(""); settings.reload(); await runCheck("nim"); return true; },
    { loading: "Saving the key", success: "Key saved in backend\\.env", error: (e) => ["Key not saved", String((e as Error).message)] });

  return (
    <div className="mx-auto max-w-[820px] pb-12">
      <PageHead title="Settings" sub="Choose which AI model finds the themes. Conversion to Markdown never needs a model." />

      <h2 className="mb-3 text-sm font-semibold">AI model</h2>
      <div className="grid gap-3 sm:grid-cols-2">
        <Choice testId="choose-nim" on={cur === "nim"} icon={Cloud} title="NVIDIA NIM (cloud)" onClick={() => choose("nim")}
          text="Fast and accurate. Needs a free NVIDIA API key. The document text is sent to NVIDIA." />
        <Choice testId="choose-local" on={cur === "local"} icon={Laptop} title="Local model (Ollama)" onClick={() => choose("local")}
          text="Free and private: nothing leaves your PC. Slower. Needs about 4 GB of disk and 8 GB of RAM." />
      </div>

      {cur === "nim" && s && (
        <section className="mt-5 rounded-2xl border bg-card p-5 sm:p-6" data-testid="nim-panel">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="font-semibold">Set up NVIDIA NIM</h3>
            <div className="flex items-center gap-2"><Status check={check.nim} loading={checking === "nim"} />
              <Button variant="ghost" size="icon-sm" aria-label="Check again" onClick={() => runCheck("nim")}><RefreshCw className="size-4" /></Button></div>
          </div>
          <ol className="mt-4 space-y-4 text-sm">
            <li><b>1. Get a free key.</b> Sign in at{" "}
              <a className="inline-flex items-center gap-0.5 font-medium text-primary hover:underline" href="https://build.nvidia.com" target="_blank" rel="noopener noreferrer">build.nvidia.com <ExternalLink className="size-3" /></a>,
              open any model and click <i>Get API Key</i>. The key starts with <code className="num">nvapi-</code>.</li>
            <li><b>2. Paste it here.</b> It is saved only in <code className="num">backend\.env</code> on this PC.
              <form className="mt-2 flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); if (key.trim()) saveKey(); }}>
                <label className="relative min-w-[240px] flex-1">
                  <span className="sr-only">NVIDIA API key</span>
                  <KeyRound className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
                  <input type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} data-testid="nim-key"
                    placeholder={s.nim.key_set ? "Key saved. Paste to replace." : "nvapi-..."}
                    className="h-9 w-full rounded-sm border bg-surface pl-8 pr-2 text-sm placeholder:text-muted-foreground" />
                </label>
                <Button type="submit" size="lg" disabled={!key.trim()}>Save key</Button>
              </form>
            </li>
            <li><b>3. Check.</b> DocMap sends one tiny test request. Green means ready.</li>
          </ol>
          <p className="mt-4 text-xs text-muted-foreground">Models: <code className="num">{s.nim.llm}</code> (writing) and <code className="num">{s.nim.embed}</code> (comparing).</p>
        </section>
      )}

      {cur === "local" && s && (
        <section className="mt-5 rounded-2xl border bg-card p-5 sm:p-6" data-testid="local-panel">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="font-semibold">Set up a local model</h3>
            <div className="flex items-center gap-2"><Status check={check.local} loading={checking === "local"} />
              <Button variant="ghost" size="icon-sm" aria-label="Check again" onClick={() => runCheck("local")}><RefreshCw className="size-4" /></Button></div>
          </div>
          <ol className="mt-4 space-y-4 text-sm">
            <li><b>1. Install Ollama.</b> Download it from{" "}
              <a className="inline-flex items-center gap-0.5 font-medium text-primary hover:underline" href="https://ollama.com/download" target="_blank" rel="noopener noreferrer">ollama.com/download <ExternalLink className="size-3" /></a>{" "}
              and run the installer. Ollama then runs in the background (look for the llama icon near the clock).</li>
            <li><b>2. Get the writing model</b> (about 3.3 GB). Open PowerShell or Command Prompt and run:
              <CopyCmd cmd={`ollama pull ${s.local.llm}`} /></li>
            <li><b>3. Get the comparing model</b> (about 0.3 GB):
              <CopyCmd cmd={`ollama pull ${s.local.embed}`} /></li>
            <li><b>4. Check.</b> Click the refresh button above. Green means ready.
              {check.local && !check.local.ok && check.local.running === false && (
                <span className="mt-1 block text-xs text-muted-foreground">Ollama is installed but not running? Start it from the Start menu, or run <code className="num">ollama serve</code>.</span>)}
            </li>
          </ol>
          <p className="mt-4 text-xs text-muted-foreground">DocMap needs both models: one writes the document profiles and theme names, the other compares texts. They talk to Ollama at <code className="num">{s.local.url}</code>.</p>
        </section>
      )}

      {s && (
        <section className="mt-8">
          <h2 className="mb-3 text-sm font-semibold">Where your files are</h2>
          <ul className="divide-y rounded-2xl border bg-card">
            {([["markdown", "Converted Markdown", s.folders.markdown], ["export", "Exported theme packs", s.folders.export], ["uploads", "Uploaded originals", s.folders.uploads]] as const).map(([which, label, path]) => (
              <li key={which} className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
                <span className="min-w-0 flex-1"><span className="block font-medium">{label}</span><code className="num break-all text-xs text-muted-foreground">{path}</code></span>
                <Button variant="outline" onClick={() => openFolder(which).catch(() => {})}><FolderOpen className="size-4" /> Open</Button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
