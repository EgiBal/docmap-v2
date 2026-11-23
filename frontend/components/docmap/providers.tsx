"use client";
import { createContext, useContext, type ReactNode } from "react";
import { ThemeProvider } from "next-themes";
import { Toaster, usePromiseToast, type PromiseToaster } from "@/components/kokonutui/promise-toast";

const Ctx = createContext<PromiseToaster | null>(null);
export const useToaster = () => useContext(Ctx)!;

function Inner({ children }: { children: ReactNode }) {
  const toaster = usePromiseToast();
  return (
    <Ctx.Provider value={toaster}>
      {children}
      <Toaster toaster={toaster} />
    </Ctx.Provider>
  );
}

export function Providers({ children }: { children: ReactNode }) {
  return (
    <ThemeProvider attribute={["class", "data-theme"]} defaultTheme="system" enableSystem>
      <Inner>{children}</Inner>
    </ThemeProvider>
  );
}

