// Design tokens, direction A "Calm Enterprise". Values live in app/globals.css as CSS variables
// (light on :root, dark on .dark). This file names them for TS. Keep the two in sync.
export const tokens = {
  colors: {
    bg: "var(--bg)", surface: "var(--surface)", surface2: "var(--surface-2)", border: "var(--border-c)",
    text: "var(--text)", muted: "var(--muted-c)", accent: "var(--accent-c)", accentFg: "var(--accent-fg)",
    accentSoft: "var(--accent-soft)", warn: "var(--warn)", warnBg: "var(--warn-bg)",
    danger: "var(--danger)", dangerBg: "var(--danger-bg)", ok: "var(--ok)",
  },
  status: { ok: "var(--ok)", warn: "var(--warn)", bad: "var(--danger)", edge: "var(--edge)" },
  radius: { sm: "6px", md: "8px", lg: "12px" },
  fonts: { sans: "var(--font-inter)", mono: "var(--font-geist-mono)" },
  edge: { minOpacity: 0.25, maxOpacity: 1, widthProposed: 1.5, widthAccepted: 2.5 },
} as const;

/** Topic palette: 8 category colors (CSS variables in globals.css, light and dark). */
export const PALETTE = [
  "var(--c-finance)", "var(--c-workforce)", "var(--c-environment)", "var(--c-digital)",
  "var(--c-flood)", "var(--c-6)", "var(--c-7)", "var(--c-8)",
] as const;

/** Color per topic id: rank of the id among the given ids, then the palette in order.
 *  Stable: it does not depend on topic names, so renaming a topic never changes its color. */
export function topicColors(ids: number[]): Map<number, string> {
  const sorted = [...new Set(ids)].sort((a, b) => a - b);
  return new Map(sorted.map((id, i) => [id, PALETTE[i % PALETTE.length]]));
}