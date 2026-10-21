import type { Metadata } from "next";
import { Cactus_Classical_Serif, Geist, Geist_Mono } from "next/font/google"

import "./globals.css"
import { ThemeProvider } from "@/components/theme-provider"
import { cn } from "@/lib/utils";

const geist = Geist({subsets:['latin'],variable:'--font-sans'})

const fontMono = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
})

const cactus = Cactus_Classical_Serif({
  subsets: ["latin"],
  weight: "400",
  variable: "--font-display",
})

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000"),
  title: "Declare — Research authorship, clarified",
  description: "Review CRediT contribution roles and generate researcher-approved statements.",
  icons: {
    icon: [{ url: "/icons/slate.png", type: "image/png" }],
    shortcut: ["/icons/slate.png"],
    apple: [{ url: "/icons/slate.png", type: "image/png" }],
  },
  openGraph: {
    title: "Declare",
    description: "Research authorship, clarified.",
    images: ["/og.png"],
  },
  twitter: {
    card: "summary_large_image",
    title: "Declare",
    description: "Research authorship, clarified.",
    images: ["/og.png"],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={cn("antialiased", fontMono.variable, cactus.variable, "font-sans", geist.variable)}
    >
      <body>
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  )
}
