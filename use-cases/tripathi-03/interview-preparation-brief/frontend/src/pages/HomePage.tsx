import { Link } from "react-router-dom";
import { ArrowRight, FileSearch, ShieldCheck, Sparkles } from "lucide-react";
import { motion } from "framer-motion";

import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const features = [
  {
    title: "Evidence-first answers",
    description: "Interview answers are grounded only in resume chunks. No fabrication.",
    icon: ShieldCheck,
  },
  {
    title: "Skill gap clarity",
    description: "See matching vs missing skills with charts and actionable improvements.",
    icon: FileSearch,
  },
  {
    title: "Full prep brief",
    description: "Questions, STAR stories, technical topics, and a 30-60-90 roadmap.",
    icon: Sparkles,
  },
];

export function HomePage() {
  return (
    <div className="space-y-12">
      <section className="relative overflow-hidden rounded-2xl border border-border bg-card/70 px-6 py-14 sm:px-10">
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45 }}
          className="max-w-2xl"
        >
          <p className="mb-3 text-sm font-semibold uppercase tracking-[0.18em] text-primary">
            Interview Preparation Brief
          </p>
          <h1 className="font-display text-4xl font-bold tracking-tight text-balance sm:text-5xl">
            Walk into every interview prepared, grounded, and specific.
          </h1>
          <p className="mt-4 max-w-xl text-base text-muted-foreground sm:text-lg">
            Combine your resume, the job description, and company context into one
            professional brief — with answers that never invent experience.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link to="/upload">
              <Button size="lg">
                Start a brief <ArrowRight className="h-4 w-4" />
              </Button>
            </Link>
            <Link to="/history">
              <Button variant="outline" size="lg">
                View history
              </Button>
            </Link>
          </div>
        </motion.div>
      </section>

      <section className="grid gap-4 md:grid-cols-3">
        {features.map((feature, index) => (
          <motion.div
            key={feature.title}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 * index }}
          >
            <Card className="h-full">
              <CardHeader>
                <feature.icon className="mb-2 h-5 w-5 text-primary" />
                <CardTitle className="text-lg">{feature.title}</CardTitle>
                <CardDescription>{feature.description}</CardDescription>
              </CardHeader>
            </Card>
          </motion.div>
        ))}
      </section>
    </div>
  );
}
