import { Sparkles, Upload } from "lucide-react";

function ReportHero() {
  return (
    <section className="rounded-3xl bg-gradient-to-r from-indigo-600 to-indigo-500 px-8 py-10 text-white shadow-xl shadow-indigo-100">
      <div className="flex flex-col items-center justify-between gap-8 xl:flex-row">
        <div className="max-w-xl text-center xl:text-left">
          <div className="mb-5 inline-flex rounded-full border border-white/20 bg-white/10 px-4 py-2 text-xs font-bold tracking-[0.15em]">
            REPORT READY
          </div>

          <h1 className="text-4xl font-bold tracking-tight">
            Tech Summit 2026
          </h1>

          <p className="mt-4 text-lg leading-7 text-indigo-100">
            AI-powered impact analysis combining event metrics, sponsor
            delivery, attendee feedback, and event documents.
          </p>
        </div>

        <div className="flex flex-wrap justify-center gap-4">
          <button className="flex items-center gap-2 rounded-xl border border-white/30 bg-white/10 px-6 py-4 font-semibold transition hover:bg-white/20">
            <Upload size={20} />
            Add Data
          </button>

          <button className="flex items-center gap-2 rounded-xl bg-white px-6 py-4 font-semibold text-indigo-700 shadow-lg transition hover:bg-indigo-50">
            <Sparkles size={20} />
            Generate Report
          </button>
        </div>
      </div>
    </section>
  );
}

export default ReportHero;