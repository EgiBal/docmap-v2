"use client";
import { useMemo } from "react";
import { topicColors } from "@/lib/tokens";
import type { Topic } from "@/lib/api";
import { Kbd } from "@/components/docmap/bits";

/** Lists topics (number keys 1-9 pick one when `keys` is set). The current topic is disabled. */
export function TopicPicker({ topics, currentId, onPick, keys }: { topics: Topic[]; currentId: number; onPick: (t: Topic) => void; keys?: boolean }) {
  const colors = useMemo(() => topicColors(topics.map((t) => t.id)), [topics]);
  return (
    <div className="space-y-1" data-testid="topic-picker">
      {topics.map((t, i) => (
        <button key={t.id} disabled={t.id === currentId} onClick={() => onPick(t)}
          className="flex w-full items-center gap-2 rounded-sm border bg-surface px-3 py-2 text-left text-sm hover:bg-surface-2 disabled:opacity-40">
          <span className="size-[9px] rounded-full" style={{ background: colors.get(t.id) }} aria-hidden />
          <span className="flex-1 truncate">{t.name}</span>
          {keys && i < 9 && <Kbd>{i + 1}</Kbd>}
        </button>
      ))}
    </div>
  );
}
