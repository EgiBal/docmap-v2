export const API = process.env.NEXT_PUBLIC_API ?? "http://localhost:8000";

/** Honest token delta, Markdown against a plain-text dump. Negative saved_pct means Markdown is larger. */
export function tokenDelta(savedPct: number): { value: string; bigger: boolean; text: string } {
  const p = Math.round(Math.abs(savedPct) * 10) / 10;
  if (savedPct < 0) return { value: `+${p}%`, bigger: true, text: `Markdown is ${p}% larger (adds headings/tables)` };
  return { value: `−${p}%`, bigger: false, text: `−${p}% tokens` };
}

export type Evidence = { chunk: string | null; heading: string; snippet: string; sim: number };
export type LinkT = {
  id: number; doc_id: string; topic_id: number; topic_name: string; score: number; confidence: number;
  status: "proposed" | "accepted" | "rejected" | "moved"; source: string; moved_to: number | null;
  reviewed_at: string | null; evidence: Evidence[]; disagreement?: boolean; content_changed?: boolean;
  suggestion?: { topic_id: number; topic_name: string } | null;
};
export type DocWarning = { kind: "ocr" | "hidden" | "encrypted" | "unsupported" | "size" | "other"; text: string };
export type Topic = { id: number; name: string; description: string; synonyms: string[]; doc_count: number };
export type DocRow = {
  id: string; format: string; status: string; token_count: number; naive_tokens: number | null; size_warning: string | null; note: string; warnings: DocWarning[];
  top_topic: { id: number; name: string; confidence: number; status: string; link_id: number } | null;
};
export type DocDetail = {
  id: string; format: string; status: string; markdown: string; truncated: boolean;
  tokens: { naive: number; slim: number; saved_pct: number }; size_warning: string | null; warnings: string[]; doc_warnings: DocWarning[];
  preview_chars: number; total_bytes: number; links: LinkT[];
};
export type Metrics = {
  docs: number; topics: number; links: Record<string, number>; links_total: number;
  tokens: { naive: number; slim: number; saved_pct: number; naive_known?: boolean }; open_reviews: number; size_warnings: number;
  pack?: { n_topics: number; median_tokens: number; largest_tokens: number; median_saved_pct: number; library_tokens: number };
  needs_ocr: number;
  last_run: { id: number; started_at: string; preset: string; n_docs: number; n_topics: number; timings: Record<string, number> } | null;
};
export type GraphT = {
  nodes: { id: string; type: "topic" | "doc"; data: Record<string, string | number> }[];
  edges: { id: string; source: string; target: string; data: { link_id: number; status: string; confidence: number; source: string; doc_id: string; topic_id: number } }[];
};
export type JobStatus = { state: "idle" | "running" | "done" | "error"; kind?: "convert" | "process" | ""; step: string; done: number; total: number; pct: number; message: string; elapsed: number };

export type UploadResult = {
  saved: string[]; unchanged: string[]; skipped: string[]; errors: { name: string; reason: string }[];
};
export type RescoreResult = {
  dry_run: boolean; n_open: number; n_reviews: number; changed: number; message: string;
  suggestions: Record<string, { topic_id: number; topic_name: string }>;
};

/** Write requests carry X-DocMap: 1; the API refuses writes without it (blocks drive-by posts from other sites). */
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const write = init?.method && init.method !== "GET";
  const headers = { ...(init?.headers as Record<string, string> | undefined), ...(write ? { "X-DocMap": "1" } : {}) };
  const r = await fetch(`${API}${path}`, { cache: "no-store", ...init, headers });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail ?? msg; } catch {}
    throw new Error(msg);
  }
  return r.json();
}

export const patchLink = (id: number, action: "accept" | "reject" | "move", topic_id?: number) =>
  api<{ link: LinkT }>(`/api/links/${id}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action, topic_id }),
  });

export const fmt = (n: number) => n.toLocaleString("en-US");

export type ExportPreview = {
  topics: { file: string; tokens: number; too_large: boolean }[]; warnings: string[]; files: string[];
  digest: boolean; accepted_only: boolean; limit: number;
};
export const exportQuery = (o: { digest: boolean; acceptedOnly: boolean }) =>
  `digest=${o.digest}&accepted_only=${o.acceptedOnly}`;

export const rescore = () => api<RescoreResult>("/api/rescore", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });

export const STAGES = ["convert", "chunk", "embed", "profile", "induce", "save"] as const;
/** A write refused because a run is in progress (HTTP 409). */
export const isBusy = (e: unknown) => /in progress/i.test(String((e as Error)?.message ?? e));


export type Preset = "nim" | "local";
export type Settings = {
  preset: Preset;
  nim: { key_set: boolean; llm: string; embed: string };
  local: { url: string; llm: string; embed: string };
  folders: { uploads: string; markdown: string; export: string };
};
export type SettingsCheck = { preset: Preset; ok: boolean; message: string; running?: boolean; installed?: string[]; missing?: string[] };
export type MdFile = { name: string; source: string; bytes: number; modified: string };
export type FileList_ = { folder: string; files: MdFile[] };

const json = (method: string, body: unknown): RequestInit => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
export const saveSettings = (preset: Preset) => api<Settings>("/api/settings", json("PUT", { preset }));
export const saveNimKey = (key: string) => api<Settings>("/api/settings/nim-key", json("POST", { key }));
export const checkSettings = (preset: Preset) => api<SettingsCheck>(`/api/settings/check?preset=${preset}`);
export const openFolder = (which: "markdown" | "export" | "uploads") => api<{ opened: string | null }>("/api/open-folder", json("POST", { which }));
export const fileUrl = (name: string) => `${API}/api/files/${encodeURIComponent(name)}`;
export const PRESET_LABEL: Record<Preset, string> = { nim: "NVIDIA NIM (cloud)", local: "Local model (Ollama)" };
export const fmtBytes = (n: number) => n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`;
