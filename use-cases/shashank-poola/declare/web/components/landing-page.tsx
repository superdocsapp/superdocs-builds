import Image from "next/image";
import Link from "next/link";
import { ArrowRight01Icon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { ArrowUpRight, Check, FileCheck2, FileText, MessageSquareText, ShieldCheck, Sparkles, UsersRound } from "lucide-react";
import { SiteHeader } from "./site-header";

const steps = [
  ["01", "Add your authors", "Bring together the people behind the work."],
  ["02", "Describe contributions", "Paste your free-text contribution and disclosure notes."],
  ["03", "Review with confidence", "Approve CRediT roles before they reach your manuscript."],
];

const WorkflowIllustration = ({ step }: { step: number }) => {
  if (step === 0) return <div className="relative h-36 overflow-hidden rounded-xl bg-[#dfeee8]"><div className="absolute left-8 top-7 grid grid-cols-4 gap-2">{Array.from({ length: 12 }).map((_, index) => <span key={index} className={`size-5 rounded-md border border-[#8ba89d] ${[1, 5, 6, 10].includes(index) ? "bg-[#8ecdb8]" : "bg-white/60"}`} />)}</div><span className="absolute left-10 top-9 size-2 rounded-full bg-zinc-900" /><span className="absolute bottom-8 right-10 size-2 rounded-full bg-zinc-900" /></div>;
  if (step === 1) return <div className="relative h-36 overflow-hidden rounded-xl bg-[#f6e5eb]"><span className="absolute left-10 top-10 size-3 rounded-full border-2 border-zinc-800 bg-white" /><span className="absolute right-12 top-7 size-3 rounded-full border-2 border-zinc-800 bg-[#f0aebd]" /><span className="absolute bottom-8 left-20 size-3 rounded-full border-2 border-zinc-800 bg-[#f0aebd]" /><i className="absolute left-[3.2rem] top-[3.1rem] h-px w-28 rotate-[-15deg] bg-zinc-700" /><i className="absolute left-[5.8rem] top-[4.8rem] h-px w-20 rotate-[45deg] bg-zinc-700" /><i className="absolute left-[8rem] top-[3.6rem] h-px w-20 rotate-[-46deg] bg-zinc-700" /></div>;
  return <div className="relative h-36 overflow-hidden rounded-xl bg-[#e3edf7]"><div className="absolute left-12 top-7 h-20 w-24 border-b-2 border-l-2 border-zinc-800" /><i className="absolute left-14 top-[4.9rem] h-px w-12 rotate-[-28deg] bg-zinc-800" /><i className="absolute left-[6.6rem] top-[3.8rem] h-px w-10 rotate-[35deg] bg-zinc-800" /><i className="absolute left-[8.2rem] top-[3.1rem] h-px w-9 rotate-[-27deg] bg-zinc-800" /><span className="absolute left-14 top-[4.7rem] size-2 rounded-full border-2 border-zinc-900 bg-white" /><span className="absolute left-[6.3rem] top-[3.55rem] size-2 rounded-full border-2 border-zinc-900 bg-white" /><span className="absolute left-[8rem] top-[2.85rem] size-2 rounded-full border-2 border-zinc-900 bg-[#8cc6e3]" /></div>;
};

export const LandingPage = () => (
  <main className="min-h-svh bg-[#fdfdfc] text-[#171717]">
    <SiteHeader />

    <section className="mx-auto flex max-w-[980px] flex-col items-center px-6 pb-24 pt-20 text-center sm:pt-28">
      <div className="mb-8 flex h-24 w-48 items-center justify-center overflow-hidden rounded-[2rem] bg-[#e9f3ef] sm:h-28 sm:w-56">
        <div className="relative grid grid-cols-4 gap-2">{Array.from({ length: 16 }).map((_, index) => <span key={index} className={`size-3 rounded-sm border border-zinc-400 ${[1, 5, 6, 10, 14].includes(index) ? "bg-[#9edbc9]" : "bg-white/70"}`} />)}<span className="absolute left-1 top-1 size-2 rounded-full bg-zinc-900" /><span className="absolute bottom-1 right-1 size-2 rounded-full bg-zinc-900" /></div>
      </div>
      <p className="mb-5 text-xs font-medium uppercase tracking-[0.18em] text-zinc-500">A Slate product · Research authorship, clarified</p>
      <h1 className="max-w-4xl font-[family-name:var(--font-display)] text-5xl leading-[0.96] tracking-[-0.045em] sm:text-7xl">
        Make every contribution count.
      </h1>
      <p className="mt-7 max-w-2xl text-base leading-7 text-zinc-600 sm:text-lg">
        Slate builds focused tools for research teams. Declare turns researcher notes into clear, reviewable CRediT contributor statements — without guessing what your team meant.
      </p>
      <div className="mt-8 flex flex-wrap justify-center gap-3">
        <Link href="/dashboard" className="inline-flex items-center gap-2 rounded-full bg-zinc-900 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-zinc-700">
          Get started <ArrowUpRight className="size-4" />
        </Link>
        <Link href="#how-it-works" className="rounded-full bg-zinc-100 px-5 py-2.5 text-sm font-medium transition hover:bg-zinc-200">How it works</Link>
      </div>
    </section>

    <section id="how-it-works" className="mx-auto grid max-w-[980px] gap-5 px-6 pb-28 md:grid-cols-3 sm:px-0">
      {steps.map(([number, title, description], index) => {
        const Icon = [UsersRound, Sparkles, FileText][index]!;
        return <article key={number} className="rounded-2xl bg-[#f2f2ef] p-4 sm:p-5">
          <WorkflowIllustration step={index} />
          <div className="mt-5 flex items-center justify-between text-xs font-medium text-zinc-500"><span>{number}</span><Icon className="size-5 text-zinc-700" /></div>
          <h2 className="mt-7 text-xl font-semibold tracking-tight text-zinc-950">{title}</h2>
          <p className="mt-2 max-w-xs text-sm leading-6 text-zinc-600">{description}</p>
        </article>;
      })}
    </section>

    <section className="border-y border-zinc-200 bg-white">
      <div className="mx-auto max-w-[980px] px-6 py-20 text-center sm:px-0 sm:py-24">
        <p className="text-xs font-medium uppercase tracking-[0.16em] text-zinc-500">A connected research handoff</p>
        <h2 className="mx-auto mt-4 max-w-2xl font-[family-name:var(--font-display)] text-4xl leading-none tracking-[-0.035em] sm:text-5xl">One clear record, from authorship to manuscript.</h2>
        <p className="mx-auto mt-5 max-w-xl text-base leading-7 text-zinc-600">Declare keeps approved contribution facts together as your work moves from Slate, through the manuscript, and into the next research conversation.</p>

        <div className="mx-auto mt-9 inline-flex items-center gap-2 rounded-[1.75rem] bg-[#f0f1ee] p-3 shadow-[0_18px_45px_rgba(24,24,24,0.10)] sm:gap-4 sm:p-4">
          {[
            { src: "/icons/slate.png", name: "Slate" },
            { src: "/icons/superdocs.png", name: "SuperDocs" },
            { src: "/icons/chatgpt.png", name: "ChatGPT" },
          ].map(({ src, name }, index) => <div key={name} className="flex items-center gap-2 sm:gap-4"><div className={`flex size-14 items-center justify-center rounded-2xl border border-zinc-200 bg-white p-3 shadow-sm sm:size-16 ${name === "Slate" ? "bg-zinc-950" : ""}`}><Image src={src} alt={`${name} logo`} width={48} height={48} className={`h-full w-full object-contain ${name === "Slate" ? "brightness-0 invert" : ""}`} /></div>{index < 2 && <HugeiconsIcon icon={ArrowRight01Icon} size={18} strokeWidth={1.5} className="text-zinc-400" />}</div>)}
        </div>

        <div className="mx-auto mt-12 grid max-w-3xl gap-4 text-left sm:mt-14 sm:grid-cols-3">
          {[
            ["Slate", "Capture the people, evidence, funding, and disclosures behind the work."],
            ["SuperDocs", "Apply the approved publication statements as one proposed manuscript edit."],
            ["ChatGPT", "Carry a clear, researcher-approved record into the next working conversation."],
          ].map(([name, description]) => <div key={name} className="rounded-xl bg-[#f7f7f5] p-4"><p className="font-medium text-zinc-950">{name}</p><p className="mt-1.5 text-sm leading-6 text-zinc-600">{description}</p></div>)}
        </div>

        <Link href="/dashboard" className="mt-8 inline-flex items-center gap-2 rounded-full bg-zinc-900 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-zinc-700">Start with Declare <HugeiconsIcon icon={ArrowRight01Icon} size={16} strokeWidth={1.8} /></Link>
      </div>
    </section>

    <section id="about" className="border-y border-zinc-200 bg-white">
      <div className="mx-auto grid max-w-[980px] gap-12 px-6 py-20 sm:px-0 md:grid-cols-[0.9fr_1.1fr]">
        <h2 className="font-[family-name:var(--font-display)] text-4xl leading-none tracking-[-0.035em]">Precise enough for publication.</h2>
        <div className="space-y-5 text-base leading-7 text-zinc-600">
          <p>Declare keeps ambiguous work ambiguous, so researchers can clarify it before a role is assigned.</p>
          <ul className="space-y-3 text-zinc-800">
            {["Built around the 14 CRediT contributor roles", "Funding and conflicts kept separate", "Final statements are generated from reviewed facts only"].map((item) => <li key={item} className="flex gap-3"><Check className="mt-1 size-4 text-zinc-500" />{item}</li>)}
          </ul>
        </div>
      </div>
    </section>

    <section className="mx-auto max-w-[980px] px-6 py-24 sm:px-0">
      <div className="max-w-2xl">
        <p className="text-xs font-medium uppercase tracking-[0.16em] text-zinc-500">The Declare workflow</p>
        <h2 className="mt-4 font-[family-name:var(--font-display)] text-4xl leading-none tracking-[-0.035em] sm:text-5xl">From rough notes to a manuscript-ready record.</h2>
      </div>
      <div className="mt-12 grid gap-px overflow-hidden rounded-2xl border border-zinc-200 bg-zinc-200 md:grid-cols-4">
        {[
          ["01", "Capture", "Add authors and the notes your team already has."],
          ["02", "Map", "Declare proposes only valid CRediT roles and keeps uncertain work open."],
          ["03", "Confirm", "Review exact evidence, roles, funding and conflicts before generating language."],
          ["04", "Apply", "Send approved statements to SuperDocs, approve the change, then export."],
        ].map(([number, title, description]) => <article key={number} className="bg-[#fdfdfc] p-6"><span className="text-xs font-medium text-zinc-500">{number}</span><h3 className="mt-10 text-lg font-medium">{title}</h3><p className="mt-2 text-sm leading-6 text-zinc-600">{description}</p></article>)}
      </div>
    </section>

    <section className="border-y border-zinc-200 bg-[#f3f5f1]">
      <div className="mx-auto grid max-w-[980px] gap-12 px-6 py-24 sm:px-0 md:grid-cols-[0.85fr_1.15fr]">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.16em] text-zinc-500">A Slate product</p>
          <h2 className="mt-4 font-[family-name:var(--font-display)] text-4xl leading-none tracking-[-0.035em]">Focused tools for the parts of research that deserve care.</h2>
        </div>
        <div className="grid gap-5 sm:grid-cols-3">
          {[
            [ShieldCheck, "Controlled vocabulary", "Roles are checked against the CRediT standard before they can be used."],
            [FileCheck2, "Reviewed facts", "The final wording comes from the researcher's approved record, not a second guess."],
            [MessageSquareText, "Document handoff", "SuperDocs proposes manuscript edits that researchers can accept or reject."],
          ].map(([Icon, title, description]) => {
            const FeatureIcon = Icon as typeof ShieldCheck;
            return <article key={title as string} className="rounded-2xl bg-white p-5"><FeatureIcon className="size-5 text-zinc-500" /><h3 className="mt-10 font-medium">{title as string}</h3><p className="mt-2 text-sm leading-6 text-zinc-600">{description as string}</p></article>;
          })}
        </div>
      </div>
    </section>

    <section className="mx-auto max-w-[980px] px-6 py-24 sm:px-0">
      <div className="grid gap-12 md:grid-cols-[0.75fr_1.25fr]">
        <div><p className="text-xs font-medium uppercase tracking-[0.16em] text-zinc-500">Before submission</p><h2 className="mt-4 font-[family-name:var(--font-display)] text-4xl leading-none tracking-[-0.035em]">One small, accountable final pass.</h2></div>
        <div className="space-y-4">
          {[
            ["Does Declare decide who is an author?", "No. Your research team supplies the author list. Declare maps the described work to CRediT roles; it does not make authorship decisions."],
            ["What happens when a contribution is vague?", "It stays marked as needing clarification. Declare does not force a role when the evidence is not specific enough."],
            ["Are funding and conflicts treated as contributor roles?", "No. They are reviewed separately and only appear in their own publication statements."],
            ["How does the manuscript step work?", "After you approve the statements, SuperDocs proposes a document edit. You can inspect, approve or reject it before exporting the finished file."],
          ].map(([question, answer]) => <details key={question} className="group border-b border-zinc-200 py-4"><summary className="flex cursor-pointer list-none items-center justify-between gap-6 font-medium">{question}<span className="text-xl font-normal text-zinc-400 transition group-open:rotate-45">+</span></summary><p className="max-w-2xl pt-3 text-sm leading-6 text-zinc-600">{answer}</p></details>)}
        </div>
      </div>
    </section>

    <footer className="border-t border-zinc-200">
      <div className="mx-auto flex max-w-[980px] flex-col gap-4 px-6 py-8 text-xs text-zinc-500 sm:flex-row sm:items-center sm:justify-between sm:px-0">
        <span>© 2026 Slate. Research authorship, clearly declared.</span>
        <Link href="/dashboard" className="text-zinc-800 hover:underline">Open Declare</Link>
      </div>
    </footer>
  </main>
);
