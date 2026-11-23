"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { Moon, Sun } from "lucide-react";
import { useEffect, useState, useSyncExternalStore } from "react";
import { cn } from "@/lib/utils";
import { api, type Metrics } from "@/lib/api";

export function Nav() {
  const path = usePathname();
  const { resolvedTheme, setTheme } = useTheme();
  const mounted = useSyncExternalStore(() => () => {}, () => true, () => false);
  const [reviews, setReviews] = useState<number | null>(null);
  useEffect(() => {
    api<Metrics>("/api/metrics").then((m) => setReviews(m.open_reviews)).catch(() => setReviews(null));
  }, [path]);
  const items = [
    { href: "/", label: "Home", on: path === "/", count: null as number | null },
    { href: "/map", label: "Map", on: path.startsWith("/map"), count: null },
    { href: "/review", label: "Review", on: path.startsWith("/review"), count: reviews },
    { href: "/docs", label: "Documents", short: "Docs", on: path.startsWith("/docs"), count: null },
    { href: "/settings", label: "Settings", on: path.startsWith("/settings"), count: null },
  ];
  return (
    <header className="sticky top-0 z-30 border-b bg-surface">
      <div className="mx-auto flex h-[52px] max-w-[1200px] items-center gap-2 sm:gap-3 px-4">
        <Link href="/" className="flex items-center gap-2 rounded-sm font-semibold tracking-tight">
          <i className="block size-[18px] shrink-0 rounded-[5px] bg-primary" aria-hidden /> <span className="hidden sm:inline">DocMap</span>
        </Link>
        <nav aria-label="Main" className="ml-0 flex min-w-0 flex-1 gap-0 overflow-x-auto sm:ml-2 sm:gap-0.5">
          {items.map((it) => (
            <Link key={it.href} href={it.href} aria-current={it.on ? "page" : undefined}
              className={cn("whitespace-nowrap rounded-sm px-1.5 py-1.5 text-[13px] font-medium text-muted-foreground hover:text-foreground sm:px-2.5 sm:text-sm",
                it.on && "bg-surface-2 text-foreground")}>
              {"short" in it && it.short ? <><span className="sm:hidden">{it.short}</span><span className="hidden sm:inline">{it.label}</span></> : it.label}{it.count ? <> <span className="num" data-testid="nav-review-count">{it.count}</span></> : null}
            </Link>
          ))}
        </nav>
        <button aria-label="Toggle light or dark theme" data-testid="theme-toggle"
          className=" grid size-8 shrink-0 place-items-center rounded-sm border bg-surface text-foreground hover:bg-surface-2"
          onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}>
          {mounted && resolvedTheme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
        </button>
      </div>
    </header>
  );
}

