import { Building2, Users, Target, TrendingUp } from "lucide-react";

function Sponsors() {
  const sponsors = [
    {
      name: "TechNova",
      tier: "Platinum Sponsor",
      leads: 486,
      engagement: "92%",
    },
    {
      name: "CloudSphere",
      tier: "Gold Sponsor",
      leads: 312,
      engagement: "87%",
    },
    {
      name: "DataCore",
      tier: "Gold Sponsor",
      leads: 254,
      engagement: "84%",
    },
    {
      name: "Innovate Labs",
      tier: "Silver Sponsor",
      leads: 196,
      engagement: "78%",
    },
  ];

  const stats = [
    {
      title: "Total Sponsors",
      value: "12",
      icon: Building2,
      iconClass: "bg-indigo-50 text-indigo-600",
    },
    {
      title: "Sponsor Leads",
      value: "1,248",
      icon: Users,
      iconClass: "bg-orange-50 text-orange-600",
    },
    {
      title: "Avg. Engagement",
      value: "85%",
      icon: TrendingUp,
      iconClass: "bg-emerald-50 text-emerald-600",
    },
    {
      title: "Lead Conversion",
      value: "18.6%",
      icon: Target,
      iconClass: "bg-blue-50 text-blue-600",
    },
  ];

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div>
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <Building2 size={18} />
          <span>Events / Tech Summit 2026</span>
        </div>

        <h1 className="mt-3 text-4xl font-bold text-slate-900">
          Sponsors
        </h1>

        <p className="mt-2 text-lg text-slate-500">
          Track sponsor performance, leads, and engagement.
        </p>
      </div>

      {/* Stats */}
      <section className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
        {stats.map((stat) => {
          const Icon = stat.icon;

          return (
            <div
              key={stat.title}
              className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm"
            >
              <div
                className={`flex h-14 w-14 items-center justify-center rounded-2xl ${stat.iconClass}`}
              >
                <Icon size={26} />
              </div>

              <p className="mt-6 text-sm text-slate-500">
                {stat.title}
              </p>

              <h2 className="mt-2 text-4xl font-bold text-slate-900">
                {stat.value}
              </h2>
            </div>
          );
        })}
      </section>

      {/* Sponsor Performance */}
      <section className="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-slate-200 px-8 py-6">
          <div>
            <h2 className="text-2xl font-bold text-slate-900">
              Sponsor Performance
            </h2>

            <p className="mt-1 text-slate-500">
              Performance data from Tech Summit 2026.
            </p>
          </div>

          <span className="rounded-full bg-indigo-50 px-4 py-2 text-sm font-semibold text-indigo-700">
            12 Sponsors
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead className="border-b border-slate-200 bg-slate-50">
              <tr>
                <th className="px-8 py-5 text-sm font-semibold text-slate-500">
                  Sponsor
                </th>
                <th className="px-6 py-5 text-sm font-semibold text-slate-500">
                  Tier
                </th>
                <th className="px-6 py-5 text-sm font-semibold text-slate-500">
                  Leads
                </th>
                <th className="px-8 py-5 text-sm font-semibold text-slate-500">
                  Engagement
                </th>
              </tr>
            </thead>

            <tbody>
              {sponsors.map((sponsor) => (
                <tr
                  key={sponsor.name}
                  className="border-b border-slate-100 last:border-0"
                >
                  <td className="px-8 py-6 font-semibold text-slate-800">
                    {sponsor.name}
                  </td>

                  <td className="px-6 py-6">
                    <span className="rounded-full bg-slate-100 px-3 py-2 text-sm font-medium text-slate-600">
                      {sponsor.tier}
                    </span>
                  </td>

                  <td className="px-6 py-6 font-medium text-slate-700">
                    {sponsor.leads}
                  </td>

                  <td className="px-8 py-6">
                    <span className="font-semibold text-emerald-600">
                      {sponsor.engagement}
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

export default Sponsors;