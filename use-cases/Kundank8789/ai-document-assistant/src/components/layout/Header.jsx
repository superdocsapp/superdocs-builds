import { Bell, Search } from "lucide-react";

function Header() {
  return (
    <header className="flex items-center justify-between">
      <div>
        <p className="text-sm text-slate-500">Events / Tech Summit 2026</p>
        <h2 className="mt-2 text-3xl font-bold tracking-tight text-slate-900">
          Post-Event Impact Report
        </h2>
      </div>

      <div className="flex items-center gap-3">
        <button className="flex h-12 w-12 items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-600 shadow-sm transition hover:bg-slate-50">
          <Search size={21} />
        </button>

        <button className="flex h-12 w-12 items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-600 shadow-sm transition hover:bg-slate-50">
          <Bell size={21} />
        </button>

        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-slate-800 font-bold text-white">
          K
        </div>
      </div>
    </header>
  );
}

export default Header;