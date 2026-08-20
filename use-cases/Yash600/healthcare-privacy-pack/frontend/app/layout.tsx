import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { IconShield } from "./icons";

export const metadata: Metadata = {
  title: "Healthcare Compliance Workspace",
  description: "Upload real policies and procedures, discover section-level references, and keep them provably in sync as requirements change -- built on SuperDocs.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="topbar">
          <div className="topbar-inner">
            <Link href="/" className="brand-mark">
              <span className="brand-icon">
                <IconShield size={17} />
              </span>
              <div>
                <div className="brand">Healthcare Compliance Workspace</div>
                <div className="brand-sub">Policy &amp; Procedure Packs, built on SuperDocs</div>
              </div>
            </Link>
          </div>
        </div>
        <div className="shell">{children}</div>
      </body>
    </html>
  );
}
