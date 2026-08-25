import Image from "next/image";
import Link from "next/link";
import { ChevronDown } from "lucide-react";

export const SiteHeader = () => (
  <header className="mx-auto flex w-full max-w-[980px] items-center justify-between px-6 py-6 sm:px-0">
    <Link href="/" aria-label="Declare home">
      <Image src="/slatelogo.png" alt="Slate" width={128} height={38} priority className="h-8 w-auto" />
    </Link>

    <nav className="flex items-center gap-5 text-sm font-medium text-zinc-700">
      <details className="group relative hidden sm:block">
        <summary className="flex cursor-pointer list-none items-center gap-1 hover:text-black">Products <ChevronDown className="size-3.5 transition group-open:rotate-180" /></summary>
        <div className="absolute right-0 top-7 w-48 rounded-xl border border-zinc-200 bg-white p-1.5 shadow-[0_12px_30px_rgba(0,0,0,0.08)]">
          <Link href="/dashboard" className="block rounded-lg px-3 py-2.5 text-sm text-zinc-800 transition hover:bg-zinc-100"><span className="block font-medium">Declare</span><span className="mt-0.5 block text-xs font-normal text-zinc-500">Authorship & disclosures</span></Link>
        </div>
      </details>
      <Link href="/#how-it-works" className="hidden hover:text-black sm:block">How it works</Link>
      <Link href="/#about" className="hidden hover:text-black sm:block">About</Link>
      <Link href="/dashboard" className="rounded-full bg-zinc-900 px-4 py-2 text-white transition hover:bg-zinc-700">
        Get started
      </Link>
    </nav>
  </header>
);
