import {
  Users,
  Star,
  Building2,
  BarChart3,
} from "lucide-react";

import Header from "../components/layout/Header";
import ReportHero from "../components/dashboard/ReportHero";
import MetricCard from "../components/dashboard/MetricCard";

function Overview() {
  const metrics = [
    {
      icon: Users,
      iconClass: "bg-blue-50 text-blue-600",
      title: "Total Attendance",
      value: "2,950",
      subtitle: "18.4% vs target",
    },
    {
      icon: Star,
      iconClass: "bg-indigo-50 text-indigo-600",
      title: "Attendee Satisfaction",
      value: "4.7/5",
      subtitle: "0.4 above last year",
    },
    {
      icon: Building2,
      iconClass: "bg-orange-50 text-orange-600",
      title: "Sponsor Leads",
      value: "1,248",
      subtitle: "24% above goal",
    },
    {
      icon: BarChart3,
      iconClass: "bg-emerald-50 text-emerald-600",
      title: "Budget Utilization",
      value: "94%",
      subtitle: "₹9.4L of ₹10L spent",
    },
  ];

  return (
    <div className="space-y-8">
      <Header />

      <ReportHero />

      <section className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
        {metrics.map((metric) => (
          <MetricCard key={metric.title} {...metric} />
        ))}
      </section>
    </div>
  );
}

export default Overview;