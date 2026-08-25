"use client";

import React from "react";
import { LucideIcon } from "lucide-react";

interface StatCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: LucideIcon;
  trend?: string;
  trendColor?: "emerald" | "amber" | "rose" | "indigo";
}

export const StatCard: React.FC<StatCardProps> = ({
  title,
  value,
  subtitle,
  icon: Icon,
  trend,
  trendColor = "emerald",
}) => {
  const colorMap = {
    emerald: {
      badge: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
      text: "text-emerald-400",
      iconBox: "bg-emerald-500/15 border-emerald-500/30 text-emerald-400 shadow-emerald-500/10",
    },
    amber: {
      badge: "text-amber-400 bg-amber-500/10 border-amber-500/20",
      text: "text-amber-400",
      iconBox: "bg-amber-500/15 border-amber-500/30 text-amber-400 shadow-amber-500/10",
    },
    rose: {
      badge: "text-rose-400 bg-rose-500/10 border-rose-500/20",
      text: "text-rose-400",
      iconBox: "bg-rose-500/15 border-rose-500/30 text-rose-400 shadow-rose-500/10",
    },
    indigo: {
      badge: "text-indigo-400 bg-indigo-500/10 border-indigo-500/20",
      text: "text-indigo-400",
      iconBox: "bg-indigo-500/15 border-indigo-500/30 text-indigo-400 shadow-indigo-500/10",
    },
  };

  const scheme = colorMap[trendColor] || colorMap.emerald;

  return (
    <div className="glass-panel p-5 rounded-2xl relative overflow-hidden glass-card-hover group border border-white/10 shadow-xl">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">{title}</p>
          <h3 className="text-2xl font-bold text-white mt-1.5 tracking-tight group-hover:text-rose-300 transition-colors">
            {value}
          </h3>
          {subtitle && <p className="text-xs text-slate-400 mt-1 font-medium">{subtitle}</p>}
        </div>
        <div className={`p-3 rounded-xl border ${scheme.iconBox} shadow-lg flex items-center justify-center`}>
          <Icon className="w-5 h-5" />
        </div>
      </div>
      {trend && (
        <div className="mt-3.5 pt-3 border-t border-white/10 flex items-center gap-1.5 text-xs">
          <span className={`font-semibold ${scheme.text}`}>{trend}</span>
        </div>
      )}
    </div>
  );
};
