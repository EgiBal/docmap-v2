import type { Metadata } from "next";
import { Geist_Mono, Inter, Space_Grotesk } from "next/font/google";
import { Suspense } from "react";
import "./globals.css";
import { Providers } from "@/components/docmap/providers";
import { Nav } from "@/components/docmap/nav";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });
const grotesk = Space_Grotesk({ variable: "--font-display", subsets: ["latin"] });


export const metadata: Metadata = {
  title: "DocMap",
  description: "Office documents to lean Markdown, an AI topic map, and human review",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-variant="cohere" suppressHydrationWarning className={`${inter.variable} ${geistMono.variable} ${grotesk.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col">
        <Suspense fallback={null}><Providers>
          <div className="v-announce" aria-hidden><span className="hidden sm:inline">DocMap · Office files to Markdown, sorted by business theme. </span><u>Runs on your PC.</u></div>
          <Nav />
          <main className="mx-auto w-full max-w-[1200px] flex-1 px-4 pb-12 pt-2"><Suspense fallback={<div className="skeleton mt-6 h-24" />}>{children}</Suspense></main>
        </Providers></Suspense>
      </body>
    </html>
  );
}
