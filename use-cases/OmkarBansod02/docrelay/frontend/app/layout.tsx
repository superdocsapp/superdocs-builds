import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Geist, Geist_Mono, Source_Serif_4 } from "next/font/google";

import { AppShell } from "./components/app-shell";
import { AppProviders } from "./components/providers";
import { cn } from "@/lib/utils";

import "./globals.css";

const geistSans = Geist({
  subsets: ["latin"],
  variable: "--font-geist-sans",
});

const geistMono = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-geist-mono",
});

/**
 * The document reader is the one surface that is not product chrome, so the
 * frozen preview is set in a text face rather than the UI face. It is used
 * only inside `.document-page`.
 */
const documentSerif = Source_Serif_4({
  subsets: ["latin"],
  // The reader renders real italics (Google's SUBTITLE style), so the italic
  // face is loaded rather than synthesised by the browser.
  style: ["normal", "italic"],
  variable: "--font-document-serif",
  display: "swap",
});

export const metadata: Metadata = {
  title: "DocRelay",
  description: "Safe AI write-back for cloud documents.",
};

/**
 * Applies the stored navigation-rail preference before first paint so a
 * collapsed rail never flashes open on load. Presentation only.
 */
const SIDEBAR_BOOTSTRAP = `try{var s=localStorage.getItem("docrelay.ui.sidebar.v1");document.documentElement.dataset.sidebar=s==="collapsed"?"collapsed":"expanded"}catch(e){document.documentElement.dataset.sidebar="expanded"}`;

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html
      lang="en"
      data-sidebar="expanded"
      className={cn(
        "h-full antialiased",
        geistSans.variable,
        geistMono.variable,
        documentSerif.variable,
      )}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: SIDEBAR_BOOTSTRAP }} />
      </head>
      <body className="min-h-dvh bg-background font-sans text-foreground">
        <AppProviders>
          <AppShell>{children}</AppShell>
        </AppProviders>
      </body>
    </html>
  );
}
