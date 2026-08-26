import {
  LayoutDashboard,
  BarChart3,
  Building2,
  FileText,
  Sparkles,
  CalendarDays,
  ClipboardCheck,   // ← new icon
} from "lucide-react";

const navItems = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "event-data", label: "Event Data", icon: BarChart3 },
  { id: "sponsors", label: "Sponsors", icon: Building2 },
  { id: "documents", label: "Documents", icon: FileText },
  {
    id: "review",
    label: "Review Queue",
    icon: ClipboardCheck,
  },
];

function Sidebar({ activePage, setActivePage }) {
  return (
    <aside className="flex min-h-screen w-72 flex-col border-r border-slate-200 bg-white px-5 py-6">
      {/* Logo */}
      <div className="mb-10 flex items-center gap-3 px-2">
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-indigo-600 text-white shadow-lg shadow-indigo-200">
          <FileText size={25} />
        </div>

        <div>
          <h1 className="text-lg font-bold text-slate-900">ImpactFlow</h1>
          <p className="text-sm text-slate-500">Post-Event Reports</p>
        </div>
      </div>

      {/* Current Event */}
      <div className="mb-9 rounded-2xl border border-slate-200 bg-slate-50 p-4">
        <div className="flex items-center gap-3">
          <CalendarDays className="text-slate-500" size={20} />

          <div>
            <p className="text-xs text-slate-500">Current Event</p>
            <p className="mt-1 font-semibold text-slate-800">
              Tech Summit 2026
            </p>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <p className="mb-3 px-3 text-xs font-bold tracking-[0.15em] text-slate-400">
        WORKSPACE
      </p>

      <nav className="space-y-2">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = activePage === item.id;

          return (
            <button
              key={item.id}
              onClick={() => setActivePage(item.id)}
              className={`flex w-full items-center gap-3 rounded-xl px-4 py-3 text-left font-medium transition ${
                isActive
                  ? "bg-indigo-50 text-indigo-700"
                  : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
              }`}
            >
              <Icon size={21} />
              {item.label}
            </button>
          );
        })}
      </nav>

      {/* Bottom SuperDocs Card */}
      <div className="mt-auto rounded-2xl bg-indigo-50 p-5">
        <div className="flex items-center gap-2 text-sm font-semibold text-indigo-700">
          <Sparkles size={19} />
          Powered by SuperDocs
        </div>

        <p className="mt-3 text-sm leading-6 text-slate-500">
          AI-powered document workflows for your event reports.
        </p>
      </div>
    </aside>
  );
}

export default Sidebar;