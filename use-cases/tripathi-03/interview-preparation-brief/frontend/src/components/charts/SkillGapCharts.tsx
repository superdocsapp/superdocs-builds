import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { SkillItem } from "@/types/brief";

type SkillGapChartsProps = {
  matching: SkillItem[];
  missing: SkillItem[];
  required?: SkillItem[];
};

export function SkillGapCharts({ matching, missing, required = [] }: SkillGapChartsProps) {
  const summary = [
    { name: "Matching", value: matching.length, fill: "hsl(var(--success))" },
    { name: "Missing", value: missing.length, fill: "hsl(var(--destructive))" },
  ];

  const topMissing = missing.slice(0, 8).map((skill) => ({
    name: skill.name.length > 18 ? `${skill.name.slice(0, 18)}…` : skill.name,
    count: 1,
  }));

  const coverage =
    required.length > 0
      ? Math.round((matching.length / Math.max(required.length, 1)) * 100)
      : matching.length + missing.length > 0
        ? Math.round((matching.length / (matching.length + missing.length)) * 100)
        : 0;

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Skill coverage</CardTitle>
          <CardDescription>
            {coverage}% match rate · {matching.length} matching · {missing.length} missing
          </CardDescription>
        </CardHeader>
        <CardContent className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={summary}
                dataKey="value"
                nameKey="name"
                innerRadius={55}
                outerRadius={85}
                paddingAngle={3}
              >
                {summary.map((entry) => (
                  <Cell key={entry.name} fill={entry.fill} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Top missing skills</CardTitle>
          <CardDescription>Prioritize these gaps before the interview</CardDescription>
        </CardHeader>
        <CardContent className="h-64">
          {topMissing.length === 0 ? (
            <p className="flex h-full items-center justify-center text-sm text-muted-foreground">
              No missing skills detected
            </p>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={topMissing} layout="vertical" margin={{ left: 12, right: 12 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" hide />
                <YAxis type="category" dataKey="name" width={110} tick={{ fontSize: 12 }} />
                <Tooltip />
                <Bar dataKey="count" fill="hsl(var(--destructive))" radius={[0, 6, 6, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
