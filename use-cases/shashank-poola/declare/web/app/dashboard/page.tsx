import Link from "next/link";
import { SiteHeader } from "@/components/site-header";
import { DeclareWorkspace } from "@/components/declare-workspace";

export default function DashboardPage() {
  return (
    <main className="min-h-svh bg-[#fdfdfc] text-[#171717]">
      <SiteHeader />
      <section className="mx-auto max-w-[980px] px-6 pb-24 pt-9 sm:px-0">
        <Link href="/" className="text-sm text-zinc-500 hover:text-zinc-900">← Back to Slate</Link>
        <p className="mt-10 text-xs font-medium uppercase tracking-[0.18em] text-zinc-500">A Slate product · Declare workspace</p>
        <h1 className="mt-3 font-[family-name:var(--font-display)] text-4xl tracking-[-0.04em] sm:text-5xl">Declare authorship with care.</h1>
        <p className="mt-4 max-w-2xl text-base leading-7 text-zinc-600">Turn researcher notes into reviewed CRediT roles, publication-ready statements, and an approved manuscript edit — all while keeping research-team decisions in your hands.</p>
        <DeclareWorkspace />
      </section>
    </main>
  );
}
