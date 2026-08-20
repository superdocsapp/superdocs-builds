import type { Metadata } from "next";
import "./globals.css";
import NavTabs from "./NavTabs";
import BackgroundScene from "./BackgroundScene";

export const metadata: Metadata = {
  title: "Campaign Builder — TTRPG Worldbuilding",
  description: "User-fed, multi-campaign TTRPG worldbuilding workspace, backed live by SuperDocs.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Luckiest+Guy&family=Poppins:wght@400;500;600;700;800&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <BackgroundScene />
        <div className="topbar-wrap">
          <div className="topbar">
            <div className="topbar-inner">
              <div className="brand-mark">
                <div className="brand">Campaign Builder</div>
                <div className="brand-sub">TTRPG Worldbuilding</div>
              </div>
              <NavTabs />
            </div>
          </div>
          <div className="torn-edge" aria-hidden="true" />
        </div>
        <div className="shell">{children}</div>
      </body>
    </html>
  );
}
