import { CalendarDays, Users, Ticket, TrendingUp } from "lucide-react";

function EventData() {
  const stats = [
    {
      label: "Total Registrations",
      value: "3,420",
      icon: Users,
      color: "bg-blue-50 text-blue-600",
    },
    {
      label: "Checked In",
      value: "2,950",
      icon: Ticket,
      color: "bg-emerald-50 text-emerald-600",
    },
    {
      label: "Attendance Rate",
      value: "86.3%",
      icon: TrendingUp,
      color: "bg-indigo-50 text-indigo-600",
    },
  ];

  const sessions = [
    {
      name: "AI & The Future of Work",
      attendees: "842",
      capacity: "900",
      status: "Completed",
    },
    {
      name: "Building Products with AI",
      attendees: "756",
      capacity: "800",
      status: "Completed",
    },
    {
      name: "Startup & Innovation Panel",
      attendees: "621",
      capacity: "700",
      status: "Completed",
    },
  ];

  return (
    <div className="space-y-8">
      {/* Page heading */}
      <div>
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <CalendarDays size={17} />
          Events / Tech Summit 2026
        </div>

        <h1 className="mt-3 text-3xl font-bold text-slate-900">
          Event Data
        </h1>

        <p className="mt-2 text-slate-500">
          Review attendance and session data before generating your impact
          report.
        </p>
      </div>

      {/* Stats */}
      <section className="grid gap-6 md:grid-cols-3">
        {stats.map((stat) => {
          const Icon = stat.icon;

          return (
            <div
              key={stat.label}
              className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"
            >
              <div
                className={`flex h-12 w-12 items-center justify-center rounded-xl ${stat.color}`}
              >
                <Icon size={24} />
              </div>

              <p className="mt-5 text-sm text-slate-500">
                {stat.label}
              </p>

              <h2 className="mt-1 text-3xl font-bold text-slate-900">
                {stat.value}
              </h2>
            </div>
          );
        })}
      </section>

      {/* Sessions table */}
      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-5">
          <div>
            <h2 className="text-lg font-bold text-slate-900">
              Session Performance
            </h2>

            <p className="mt-1 text-sm text-slate-500">
              Attendance data from Tech Summit 2026.
            </p>
          </div>

          <span className="rounded-full bg-indigo-50 px-3 py-1 text-sm font-medium text-indigo-700">
            3 Sessions
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead className="bg-slate-50 text-sm text-slate-500">
              <tr>
                <th className="px-6 py-4 font-medium">Session</th>
                <th className="px-6 py-4 font-medium">Attendees</th>
                <th className="px-6 py-4 font-medium">Capacity</th>
                <th className="px-6 py-4 font-medium">Status</th>
              </tr>
            </thead>

            <tbody>
              {sessions.map((session) => (
                <tr
                  key={session.name}
                  className="border-t border-slate-100"
                >
                  <td className="px-6 py-5 font-medium text-slate-800">
                    {session.name}
                  </td>

                  <td className="px-6 py-5 text-slate-600">
                    {session.attendees}
                  </td>

                  <td className="px-6 py-5 text-slate-600">
                    {session.capacity}
                  </td>

                  <td className="px-6 py-5">
                    <span className="rounded-full bg-emerald-50 px-3 py-1 text-sm font-medium text-emerald-700">
                      {session.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

export default EventData;