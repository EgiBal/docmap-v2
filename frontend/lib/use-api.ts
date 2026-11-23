"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

/** Tiny fetch hook: data, error, loading, reload. */
export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    if (!path) return;
    try { setData(await api<T>(path)); setError(null); } catch (e) { setError((e as Error).message); }
    setLoading(false);
  }, [path]);
  useEffect(() => {
    if (!path) return;
    let live = true;   // state is set only after the request answers, never synchronously in the effect
    api<T>(path)
      .then((d) => { if (live) { setData(d); setError(null); setLoading(false); } })
      .catch((e) => { if (live) { setError((e as Error).message); setLoading(false); } });
    return () => { live = false; };
  }, [path]);
  return { data, error, loading, reload: load };
}
