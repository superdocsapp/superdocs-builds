"use client";

import React from "react";
import {
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Tooltip,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Legend,
} from "recharts";
import { RiskDistributionItem, TierRiskData, PillarAverageScores } from "../types";

interface RiskDonutProps {
  data: RiskDistributionItem[];
}

const RISK_COLORS: Record<string, string> = {
  LOW: "#10b981", // Emerald
  MEDIUM: "#f59e0b", // Amber
  HIGH: "#f97316", // Orange
  CRITICAL: "#f43f5e", // Rose Red
};

const DonutCustomTooltip = ({ active, payload }: any) => {
  if (active && payload && payload.length) {
    const item = payload[0];
    const category = item.payload?.category || item.name;
    const color = RISK_COLORS[category] || item.payload?.fill || "#10b981";
    return (
      <div className="px-3.5 py-2 rounded-xl bg-slate-950/95 border border-white/20 shadow-2xl backdrop-blur-md text-xs space-y-1">
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full shadow-xs" style={{ backgroundColor: color }} />
          <span className="font-medium text-slate-300">Risk Tier:</span>
          <span className="font-bold text-white uppercase tracking-wider">{category}</span>
        </div>
        <div className="text-slate-300 text-[11px]">
          Count: <strong className="text-white font-mono text-xs">{item.value} supplier(s)</strong>
        </div>
      </div>
    );
  }
  return null;
};

export const RiskDistributionDonut: React.FC<RiskDonutProps> = ({ data }) => {
  const chartData = data.filter((d) => d.count > 0);

  return (
    <div className="glass-panel p-6 rounded-2xl flex flex-col h-[340px] border border-white/10 shadow-xl">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-sm font-bold text-white tracking-tight">Programme Risk Profile</h4>
        <span className="text-xs text-slate-400 font-mono">2026 Cycle</span>
      </div>
      <div className="flex-1 w-full relative">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={chartData}
              cx="50%"
              cy="50%"
              innerRadius={55}
              outerRadius={85}
              paddingAngle={4}
              dataKey="count"
              nameKey="category"
            >
              {chartData.map((entry, index) => (
                <Cell
                  key={`cell-${index}`}
                  fill={RISK_COLORS[entry.category] || "#64748b"}
                  stroke="#0f172a"
                  strokeWidth={2}
                />
              ))}
            </Pie>
            <Tooltip content={<DonutCustomTooltip />} />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <div className="flex justify-center flex-wrap gap-3.5 text-xs pt-2 border-t border-white/10">
        {data.map((item) => (
          <div key={item.category} className="flex items-center gap-1.5">
            <span
              className="w-2.5 h-2.5 rounded-full shadow-xs"
              style={{ backgroundColor: RISK_COLORS[item.category] || "#64748b" }}
            />
            <span className="text-slate-300 font-medium text-[11px]">
              {item.category}: <strong className="text-white">{item.count}</strong>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
};

const BarCustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    return (
      <div className="px-3.5 py-2.5 rounded-xl bg-slate-950/95 border border-white/20 shadow-2xl backdrop-blur-md text-xs space-y-1.5 min-w-[150px]">
        <div className="font-bold text-white border-b border-white/10 pb-1">{label}</div>
        {payload.map((entry: any) => (
          <div key={entry.name} className="flex items-center justify-between gap-3 text-[11px]">
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full" style={{ backgroundColor: entry.fill }} />
              <span className="text-slate-300 font-medium">{entry.name}</span>
            </div>
            <span className="font-mono font-bold text-white">{entry.value}</span>
          </div>
        ))}
      </div>
    );
  }
  return null;
};

interface TierRiskBarChartProps {
  data: TierRiskData[];
}

export const TierRiskBarChart: React.FC<TierRiskBarChartProps> = ({ data }) => {
  const formattedData = data.map((d) => ({
    name: d.tier.replace("TIER_", "T").replace("_", " "),
    "Low Risk": d.low_risk,
    "Medium Risk": d.medium_risk,
    "High Risk": d.high_risk,
    "Critical Risk": d.critical_risk,
  }));

  return (
    <div className="glass-panel p-6 rounded-2xl flex flex-col h-[340px] border border-white/10 shadow-xl">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-sm font-bold text-white tracking-tight">Risk by Supplier Tier</h4>
        <span className="text-xs text-slate-400 font-mono">T1, T2 & T3 Breakdown</span>
      </div>
      <div className="flex-1 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={formattedData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
            <XAxis dataKey="name" stroke="#cbd5e1" fontSize={11} tick={{ fill: "#cbd5e1" }} />
            <YAxis stroke="#cbd5e1" fontSize={11} tick={{ fill: "#cbd5e1" }} allowDecimals={false} />
            <Tooltip content={<BarCustomTooltip />} />
            <Legend
              wrapperStyle={{ fontSize: "11px", paddingTop: "8px" }}
              formatter={(value) => <span className="text-slate-300 font-medium">{value}</span>}
            />
            <Bar dataKey="Low Risk" stackId="a" fill="#10b981" />
            <Bar dataKey="Medium Risk" stackId="a" fill="#f59e0b" />
            <Bar dataKey="High Risk" stackId="a" fill="#f97316" />
            <Bar dataKey="Critical Risk" stackId="a" fill="#f43f5e" />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

interface PillarScoresProps {
  scores: PillarAverageScores;
}

export const PillarScoresCard: React.FC<PillarScoresProps> = ({ scores }) => {
  const pillars = [
    {
      name: "Environmental (E)",
      score: scores.environmental_avg,
      desc: "GHG Scope 1-3, ISO 14001, Clean Energy",
      color: "bg-emerald-500",
      textColor: "text-emerald-400",
    },
    {
      name: "Social & Labor (S)",
      score: scores.social_avg,
      desc: "Fair Wage, Max Hours, Anti-Forced Labor",
      color: "bg-blue-500",
      textColor: "text-blue-400",
    },
    {
      name: "Governance (G)",
      score: scores.governance_avg,
      desc: "Anti-Bribery, Whistleblower, Sub-Tier Traceability",
      color: "bg-purple-500",
      textColor: "text-purple-400",
    },
  ];

  return (
    <div className="glass-panel p-6 rounded-2xl flex flex-col justify-between h-[340px] border border-white/10 shadow-xl">
      <div>
        <div className="flex items-center justify-between mb-4">
          <h4 className="text-sm font-bold text-white tracking-tight">Average Pillar Compliance</h4>
          <span className="text-xs px-2.5 py-0.5 rounded-full bg-emerald-500/15 text-emerald-300 font-mono font-semibold border border-emerald-500/30">
            Overall: {scores.overall_compliance_avg}%
          </span>
        </div>

        <div className="space-y-4">
          {pillars.map((p) => (
            <div key={p.name} className="space-y-1.5">
              <div className="flex justify-between text-xs">
                <span className="font-semibold text-slate-200">{p.name}</span>
                <span className={`font-mono font-bold ${p.textColor}`}>{p.score}%</span>
              </div>
              <div className="w-full h-2.5 bg-slate-900 rounded-full overflow-hidden border border-white/5">
                <div
                  className={`h-full ${p.color} transition-all duration-500 rounded-full`}
                  style={{ width: `${Math.min(100, Math.max(0, p.score))}%` }}
                />
              </div>
              <p className="text-[10px] text-slate-400 font-medium">{p.desc}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="pt-3 border-t border-white/10 flex items-center justify-between text-xs text-slate-400">
        <span>Scoring Model: CSRD & ILO Frameworks</span>
        <span className="font-mono text-emerald-400 font-semibold">Audited</span>
      </div>
    </div>
  );
};
