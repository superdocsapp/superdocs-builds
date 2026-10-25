import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

export const metadata: Metadata = {
  title: {
    default: "Submittal Register — BROD-2026",
    template: "%s — SubmittalFlow",
  },
  description:
    "Submittal register, comparison review, and transmittal packet builder for construction project engineers.",
  icons: {
    icon: "/icon",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={inter.variable}>
      <body className="min-h-screen bg-[#F8FAFC] font-sans text-slate-900 antialiased">
        <Providers>
          <div className="flex h-screen overflow-hidden">
            <Sidebar />
            <div className="flex flex-1 flex-col overflow-hidden">
              <Header />
              <main
                id="main-content"
                className="flex-1 overflow-y-auto"
                tabIndex={-1}
              >
                {children}
              </main>
            </div>
          </div>
        </Providers>
      </body>
    </html>
  );
}
