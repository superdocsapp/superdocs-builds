import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SuperDocs Supplier ESG Attestation Engine",
  description: "Enterprise Supplier Code-of-Conduct & ESG Questionnaire Attestation Platform built on SuperDocs API & MCP surface.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className="antialiased min-h-screen selection:bg-emerald-500 selection:text-white">
        {children}
      </body>
    </html>
  );
}
