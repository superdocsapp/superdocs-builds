function MetricCard({
  icon: Icon,
  iconClass,
  title,
  value,
  subtitle,
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex items-start justify-between">
        <div
          className={`flex h-12 w-12 items-center justify-center rounded-xl ${iconClass}`}
        >
          <Icon size={24} />
        </div>

        <p className="text-right text-sm font-medium leading-6 text-slate-500">
          {title}
        </p>
      </div>

      <div className="mt-6">
        <h3 className="text-3xl font-bold text-slate-900">{value}</h3>
        <p className="mt-3 text-sm text-emerald-600">{subtitle}</p>
      </div>
    </div>
  );
}

export default MetricCard;