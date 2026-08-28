import React from "react";
import { Link } from "react-router-dom";

const baseButtonStyles =
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-white/40 disabled:pointer-events-none disabled:opacity-50";

type ButtonVariant = "default" | "secondary" | "ghost" | "gradient";
type ButtonSize = "default" | "sm" | "lg";

const buttonVariantClasses: Record<ButtonVariant, string> = {
  default: "bg-white text-black hover:bg-gray-100",
  secondary: "bg-gray-800 text-white hover:bg-gray-700",
  ghost: "hover:bg-gray-800/50 text-white",
  gradient:
    "bg-gradient-to-b from-white via-white/95 to-white/60 text-black hover:scale-105 active:scale-95",
};

const buttonSizeClasses: Record<ButtonSize, string> = {
  default: "h-10 px-4 py-2 text-sm",
  sm: "h-10 px-5 text-sm",
  lg: "h-12 px-8 text-base",
};

function buttonClasses(variant: ButtonVariant, size: ButtonSize, className: string) {
  return `${baseButtonStyles} ${buttonVariantClasses[variant]} ${buttonSizeClasses[size]} ${className}`;
}

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  children: React.ReactNode;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = "default", size = "default", className = "", children, ...props }, ref) => (
    <button
      ref={ref}
      className={buttonClasses(variant, size, className)}
      {...props}
    >
      {children}
    </button>
  )
);

Button.displayName = "Button";

interface LinkButtonProps {
  to: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
  className?: string;
  children: React.ReactNode;
}

const LinkButton = ({ to, variant = "default", size = "default", className = "", children }: LinkButtonProps) => (
  <Link to={to} className={buttonClasses(variant, size, className)}>
    {children}
  </Link>
);

// Icons
interface IconProps {
  className?: string;
  size?: number;
}

const iconProps = (size: number, className: string) => ({
  xmlns: "http://www.w3.org/2000/svg",
  width: size,
  height: size,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  className,
});

const ArrowRight = ({ className = "", size = 16 }: IconProps) => (
  <svg {...iconProps(size, className)}>
    <path d="M5 12h14" />
    <path d="m12 5 7 7-7 7" />
  </svg>
);

const Menu = ({ className = "", size = 24 }: IconProps) => (
  <svg {...iconProps(size, className)}>
    <line x1="4" x2="20" y1="12" y2="12" />
    <line x1="4" x2="20" y1="6" y2="6" />
    <line x1="4" x2="20" y1="18" y2="18" />
  </svg>
);

const X = ({ className = "", size = 24 }: IconProps) => (
  <svg {...iconProps(size, className)}>
    <path d="M18 6 6 18" />
    <path d="m6 6 12 12" />
  </svg>
);

const FileText = ({ className = "", size = 20 }: IconProps) => (
  <svg {...iconProps(size, className)}>
    <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" />
    <path d="M14 2v4a2 2 0 0 0 2 2h4" />
    <path d="M10 9H8" />
    <path d="M16 13H8" />
    <path d="M16 17H8" />
  </svg>
);

const Quote = ({ className = "", size = 20 }: IconProps) => (
  <svg {...iconProps(size, className)}>
    <path d="M3 21c3 0 7-1 7-8V5c0-1.25-.756-2.017-2-2H4c-1.25 0-2 .75-2 1.972V11c0 1.25.75 2 2 2 1 0 1 0 1 1v1c0 1-1 2-2 2s-1 .008-1 1.031V20c0 1 0 1 1 1z" />
    <path d="M15 21c3 0 7-1 7-8V5c0-1.25-.757-2.017-2-2h-4c-1.25 0-2 .75-2 1.972V11c0 1.25.75 2 2 2h.75c0 2.25.25 4-2.75 4v3c0 1 0 1 1 1z" />
  </svg>
);

const RefreshCcw = ({ className = "", size = 20 }: IconProps) => (
  <svg {...iconProps(size, className)}>
    <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
    <path d="M3 3v5h5" />
    <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" />
    <path d="M16 16h5v5" />
  </svg>
);

const ShieldCheck = ({ className = "", size = 20 }: IconProps) => (
  <svg {...iconProps(size, className)}>
    <path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z" />
    <path d="m9 12 2 2 4-4" />
  </svg>
);

const Radio = ({ className = "", size = 20 }: IconProps) => (
  <svg {...iconProps(size, className)}>
    <path d="M4.9 19.1C1 15.2 1 8.8 4.9 4.9" />
    <path d="M7.8 16.2c-2.3-2.3-2.3-6.1 0-8.5" />
    <circle cx="12" cy="12" r="2" />
    <path d="M16.2 7.8c2.3 2.3 2.3 6.1 0 8.5" />
    <path d="M19.1 4.9C23 8.8 23 15.1 19.1 19" />
  </svg>
);

const Bot = ({ className = "", size = 20 }: IconProps) => (
  <svg {...iconProps(size, className)}>
    <path d="M12 8V4H8" />
    <rect width="16" height="12" x="4" y="8" rx="2" />
    <path d="M2 14h2" />
    <path d="M20 14h2" />
    <path d="M15 13v2" />
    <path d="M9 13v2" />
  </svg>
);

const Check = ({ className = "", size = 16 }: IconProps) => (
  <svg {...iconProps(size, className)}>
    <path d="M20 6 9 17l-5-5" />
  </svg>
);

const LogoMark = ({ className = "", size = 22 }: IconProps) => (
  <svg {...iconProps(size, className)} strokeWidth={1.8}>
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" />
    <path d="M14 2v6h6" />
    <path d="m9.5 14.5 2 2 3.5-3.5" />
  </svg>
);

// Dashboard Mock Component
const PIPELINE_NODES = [
  { label: "ingest", meta: "5 docs", status: "done" },
  { label: "classify", meta: "agreements · statements", status: "done" },
  { label: "extract", meta: "38 claims cited", status: "running" },
  { label: "evaluate", meta: "MF-001 … MF-004", status: "pending" },
  { label: "review", meta: "human gate", status: "pending" },
] as const;

const QUEUE_ITEMS = [
  {
    rule: "MF-001",
    title: "APR exceeds 36% cap",
    detail: "Found 41.7% effective APR in loan agreement",
    status: "pending",
    statusLabel: "Pending",
  },
  {
    rule: "MF-002",
    title: "Processing fee disclosed",
    detail: "“…a processing fee of 2.5% shall be deducted…”",
    status: "approved",
    statusLabel: "Approved",
  },
  {
    rule: "MF-003",
    title: "Rate matches latest modification",
    detail: "18.5% p.a. consistent with mod. dated 2026-06-14",
    status: "pending",
    statusLabel: "Pending",
  },
];

const nodeDotClasses: Record<string, string> = {
  done: "bg-emerald-400/80",
  running: "bg-indigo-400 animate-pulse",
  pending: "bg-gray-600",
};

const statusBadgeClasses: Record<string, string> = {
  pending: "text-amber-300 bg-amber-400/10 border-amber-400/30",
  approved: "text-emerald-300 bg-emerald-400/10 border-emerald-400/30",
};

const DashboardMock = React.memo(() => {
  return (
    <div className="rounded-lg overflow-hidden border border-white/10 shadow-2xl bg-[#10141f] text-left">
      <div className="flex items-center gap-3 px-4 py-2.5 border-b border-white/5 bg-[#141927]">
        <div className="flex gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-[#ff5f57]/80" />
          <span className="w-2.5 h-2.5 rounded-full bg-[#febc2e]/80" />
          <span className="w-2.5 h-2.5 rounded-full bg-[#28c840]/80" />
        </div>
        <div className="flex-1 max-w-xs mx-auto rounded-md bg-black/40 px-3 py-1 text-[11px] font-mono text-gray-500 truncate">
          app.anchora.dev/pipeline/run-47
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-5 gap-4 p-4 md:p-5 bg-app-primary">
        <div className="hidden md:flex md:col-span-2 flex-col gap-0 rounded-lg border border-white/5 bg-app-secondary p-4">
          <p className="text-[11px] uppercase tracking-widest text-gray-500 mb-4">Pipeline</p>
          {PIPELINE_NODES.map((node, i) => (
            <React.Fragment key={node.label}>
              <div className="flex items-center gap-3">
                <span className={`w-2 h-2 rounded-full shrink-0 ${nodeDotClasses[node.status]}`} />
                <span className={`font-mono text-xs ${node.status === "running" ? "text-white" : node.status === "done" ? "text-gray-300" : "text-gray-500"}`}>
                  {node.label}
                </span>
                <span className="ml-auto text-[11px] text-gray-600 truncate">{node.meta}</span>
              </div>
              {i < PIPELINE_NODES.length - 1 && (
                <span
                  className={`ml-[3.5px] w-px h-5 ${node.status === "done" ? "bg-emerald-400/40" : "bg-gray-700/60"}`}
                  aria-hidden="true"
                />
              )}
            </React.Fragment>
          ))}
        </div>

        <div className="md:col-span-3 rounded-lg border border-white/5 bg-app-secondary p-4">
          <div className="flex items-center justify-between mb-4">
            <p className="text-[11px] uppercase tracking-widest text-gray-500">Approval queue</p>
            <span className="rounded-full bg-indigo-400/10 border border-indigo-400/30 px-2 py-0.5 text-[11px] font-medium text-indigo-300">
              2 pending
            </span>
          </div>
          <div className="space-y-2.5">
            {QUEUE_ITEMS.map((item) => (
              <div key={item.rule} className="rounded-md border border-white/5 bg-app-elevated p-3">
                <div className="flex items-center gap-2 mb-1.5">
                  <span className="font-mono text-[10px] font-medium text-amber-300/90 bg-amber-400/10 border border-amber-400/20 rounded px-1.5 py-0.5">
                    {item.rule}
                  </span>
                  <span className="text-xs font-medium text-white truncate">{item.title}</span>
                  <span className={`ml-auto shrink-0 rounded-full border px-2 py-0.5 text-[10px] ${statusBadgeClasses[item.status]}`}>
                    {item.statusLabel}
                  </span>
                </div>
                <p className="text-[11px] leading-relaxed text-gray-500 truncate">{item.detail}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
});

DashboardMock.displayName = "DashboardMock";

// Navigation Component
const Navigation = React.memo(() => {
  const [mobileMenuOpen, setMobileMenuOpen] = React.useState(false);

  return (
    <header className="fixed top-0 w-full z-50 border-b border-gray-800/50 bg-[#0c0f1a]/80 backdrop-blur-md">
      <nav className="max-w-7xl mx-auto px-6 py-4">
        <div className="flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2 text-xl font-semibold text-white">
            <span className="text-white/90">
              <LogoMark size={22} />
            </span>
            Anchora
          </Link>

          <div className="hidden md:flex items-center justify-center gap-8 absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2">
            <a href="#features" className="text-sm text-white/60 hover:text-white transition-colors">
              Features
            </a>
            <a href="#rules" className="text-sm text-white/60 hover:text-white transition-colors">
              Compliance rules
            </a>
            <a href="#how-it-works" className="text-sm text-white/60 hover:text-white transition-colors">
              How it works
            </a>
          </div>

          <div className="hidden md:flex items-center gap-4">
            <LinkButton to="/review" variant="ghost" size="sm">
              Sign in
            </LinkButton>
            <LinkButton to="/pipeline" variant="default" size="sm">
              Open App
            </LinkButton>
          </div>

          <button
            type="button"
            className="md:hidden text-white"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            aria-label="Toggle menu"
          >
            {mobileMenuOpen ? <X size={24} /> : <Menu size={24} />}
          </button>
        </div>
      </nav>

      {mobileMenuOpen && (
        <div className="md:hidden bg-[#0c0f1a]/95 backdrop-blur-md border-t border-gray-800/50 animate-[slideDown_0.3s_ease-out]">
          <div className="px-6 py-4 flex flex-col gap-4">
            <a
              href="#features"
              className="text-sm text-white/60 hover:text-white transition-colors py-2"
              onClick={() => setMobileMenuOpen(false)}
            >
              Features
            </a>
            <a
              href="#rules"
              className="text-sm text-white/60 hover:text-white transition-colors py-2"
              onClick={() => setMobileMenuOpen(false)}
            >
              Compliance rules
            </a>
            <a
              href="#how-it-works"
              className="text-sm text-white/60 hover:text-white transition-colors py-2"
              onClick={() => setMobileMenuOpen(false)}
            >
              How it works
            </a>
            <div className="flex flex-col gap-2 pt-4 border-t border-gray-800/50">
              <LinkButton to="/review" variant="ghost" size="sm">
                Sign in
              </LinkButton>
              <LinkButton to="/pipeline" variant="default" size="sm">
                Open App
              </LinkButton>
            </div>
          </div>
        </div>
      )}
    </header>
  );
});

Navigation.displayName = "Navigation";

// Hero Component
const Hero = React.memo(() => {
  return (
    <section
      id="top"
      className="relative flex flex-col items-center justify-start px-6 pt-32 pb-20 md:pt-36 md:pb-24"
      style={{ animation: "fadeIn 0.6s ease-out" }}
    >
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap');

        * {
          font-family: 'Poppins', sans-serif;
        }

        @keyframes fadeIn {
          from {
            opacity: 0;
            transform: translateY(10px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        @keyframes slideDown {
          from {
            opacity: 0;
            transform: translateY(-10px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }
      `}</style>

      <aside className="mb-8 inline-flex flex-wrap items-center justify-center gap-2 px-4 py-2 rounded-full border border-gray-700 bg-gray-800/50 backdrop-blur-sm max-w-full">
        <span className="text-xs text-center whitespace-nowrap text-gray-400">
          New: MCP server + live SSE run streaming is out!
        </span>
        <a
          href="#features"
          className="flex items-center gap-1 text-xs hover:text-white transition-all active:scale-95 whitespace-nowrap text-gray-400"
          aria-label="Read more about the new release"
        >
          Read more
          <ArrowRight size={12} />
        </a>
      </aside>

      <h1
        className="text-4xl md:text-5xl lg:text-6xl font-medium text-center max-w-3xl px-6 leading-tight mb-6"
        style={{
          background: "linear-gradient(to bottom, #ffffff, #ffffff, rgba(255, 255, 255, 0.6))",
          WebkitBackgroundClip: "text",
          WebkitTextFillColor: "transparent",
          backgroundClip: "text",
          letterSpacing: "-0.05em",
        }}
      >
        Give your document pile <br />the audit trail it deserves
      </h1>

      <p className="text-sm md:text-base text-center max-w-2xl px-6 mb-10 text-gray-400">
        Agentic document intelligence for microfinance compliance — extract cited facts, evaluate YAML
        playbooks, and approve findings with human-in-the-loop review.
      </p>

      <div className="flex flex-wrap items-center justify-center gap-4 relative z-10 mb-16">
        <LinkButton to="/pipeline" variant="gradient" size="lg" className="rounded-lg">
          Run your first pile
        </LinkButton>
        <LinkButton to="/review" variant="ghost" size="lg" className="rounded-lg border border-gray-700">
          Open review queue
        </LinkButton>
      </div>

      <div className="w-full max-w-5xl relative pb-20">
        <div
          className="absolute left-1/2 w-[90%] pointer-events-none z-0 h-72 md:h-96"
          style={{
            top: "-30%",
            transform: "translateX(-50%)",
            background:
              "radial-gradient(ellipse 55% 45% at 50% 45%, rgba(99, 102, 241, 0.35), transparent 70%), radial-gradient(ellipse 35% 30% at 65% 55%, rgba(168, 85, 247, 0.18), transparent 70%)",
            filter: "blur(24px)",
          }}
          aria-hidden="true"
        />

        <div className="relative z-10">
          <DashboardMock />
        </div>
      </div>
    </section>
  );
});

Hero.displayName = "Hero";

// Feature data
const FEATURES = [
  {
    icon: Bot,
    title: "Hybrid extraction",
    description:
      "Structured extractors run first, LLM fallback per field. Deterministic speed where phrasing is fixed, model reach everywhere else.",
  },
  {
    icon: Quote,
    title: "Verbatim citations",
    description:
      "Every extracted fact is anchored to exact character offsets in the source — or explicitly flagged unverifiable. Never silently unanchored.",
  },
  {
    icon: RefreshCcw,
    title: "Kill-and-resume durability",
    description:
      "Postgres-backed per-node checkpoints mean any run resumes exactly where it stopped, even after a hard kill.",
  },
  {
    icon: ShieldCheck,
    title: "Human approval gates",
    description:
      "Low-confidence findings queue for human decisions before anything ships to the deliverable. Nothing moves without a reviewer.",
  },
  {
    icon: Radio,
    title: "Live SSE streaming",
    description:
      "Watch every pipeline node progress in real time as documents are classified, extracted, and evaluated.",
  },
  {
    icon: FileText,
    title: "PDF, DOCX & plain text",
    description:
      "Drop loan agreements, modification contracts, and repayment statements into a pile. New formats need one adapter, not a rewrite.",
  },
];

const RULES = [
  { code: "MF-001", title: "APR cap", description: "Annual percentage rate must not exceed 36%." },
  { code: "MF-002", title: "Fee disclosure", description: "Processing fee must be explicitly disclosed." },
  { code: "MF-003", title: "Rate integrity", description: "Interest rate must match the latest modification agreement." },
  { code: "MF-004", title: "Penalty cap", description: "Late payment penalty must not exceed 5% of outstanding." },
];

const STEPS = [
  {
    step: "01",
    title: "Upload your pile",
    description: "Create a pile and drop in loan agreements, modifications, and repayment statements as PDF, DOCX, or text.",
  },
  {
    step: "02",
    title: "Pick a playbook",
    description: "Compliance rules are plain YAML under rules/. Edit or add checks without touching Python.",
  },
  {
    step: "03",
    title: "Agents do the work",
    description: "13 async nodes classify, extract, and evaluate — each fact carries source provenance with exact offsets.",
  },
  {
    step: "04",
    title: "Approve & export",
    description: "Review queued findings with citations side-by-side, decide, then export the deliverable.",
  },
];

// Features Section
const FeaturesSection = React.memo(() => {
  return (
    <section id="features" className="relative px-6 py-20 md:py-28 border-t border-gray-800/50">
      <div className="max-w-7xl mx-auto">
        <p className="text-xs uppercase tracking-[0.2em] text-indigo-400 mb-3">Capabilities</p>
        <h2 className="text-3xl md:text-4xl font-medium text-white mb-4 tracking-tight">
          Built for compliance-grade extraction
        </h2>
        <p className="text-sm md:text-base text-gray-400 max-w-2xl mb-14">
          A checkpointed agent pipeline that treats every claim like it will end up in front of an auditor.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {FEATURES.map((feature) => (
            <div
              key={feature.title}
              className="group rounded-lg border border-gray-800/60 bg-app-secondary p-6 transition-colors hover:border-gray-600 hover:bg-app-surface"
            >
              <div className="inline-flex items-center justify-center w-10 h-10 rounded-md bg-gray-800/80 text-indigo-300 mb-5 group-hover:text-indigo-200 transition-colors">
                <feature.icon size={20} />
              </div>
              <h3 className="text-base font-medium text-white mb-2">{feature.title}</h3>
              <p className="text-sm leading-relaxed text-gray-400">{feature.description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
});

FeaturesSection.displayName = "FeaturesSection";

// Rules Section
const RulesSection = React.memo(() => {
  return (
    <section id="rules" className="relative px-6 py-20 md:py-28 border-t border-gray-800/50">
      <div className="max-w-7xl mx-auto grid grid-cols-1 lg:grid-cols-5 gap-12">
        <div className="lg:col-span-2">
          <p className="text-xs uppercase tracking-[0.2em] text-indigo-400 mb-3">Playbooks</p>
          <h2 className="text-3xl md:text-4xl font-medium text-white mb-4 tracking-tight">
            Rules are YAML, not code
          </h2>
          <p className="text-sm md:text-base text-gray-400 mb-6">
            The shipped <code className="text-gray-200 bg-gray-800/80 rounded px-1.5 py-0.5 text-xs">microfinance_v1</code>{" "}
            playbook evaluates four consumer-loan checks out of the box.
          </p>
          <ul className="space-y-3">
            {[
              "Add domain rules by editing YAML — no Python changes",
              "Second evaluation with new documents works as-is",
              "Every violation links back to its verbatim quote",
            ].map((item) => (
              <li key={item} className="flex items-start gap-3 text-sm text-gray-300">
                <span className="mt-0.5 text-emerald-400">
                  <Check size={16} />
                </span>
                {item}
              </li>
            ))}
          </ul>
        </div>

        <div className="lg:col-span-3 grid grid-cols-1 sm:grid-cols-2 gap-4">
          {RULES.map((rule) => (
            <div key={rule.code} className="rounded-lg border border-gray-800/60 bg-app-secondary p-6">
              <span className="inline-block text-[11px] font-mono font-medium text-amber-300/90 bg-amber-400/10 border border-amber-400/20 rounded px-2 py-0.5 mb-4">
                {rule.code}
              </span>
              <h3 className="text-base font-medium text-white mb-2">{rule.title}</h3>
              <p className="text-sm leading-relaxed text-gray-400">{rule.description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
});

RulesSection.displayName = "RulesSection";

// How It Works Section
const HowItWorksSection = React.memo(() => {
  return (
    <section id="how-it-works" className="relative px-6 py-20 md:py-28 border-t border-gray-800/50">
      <div className="max-w-7xl mx-auto">
        <p className="text-xs uppercase tracking-[0.2em] text-indigo-400 mb-3">Pipeline</p>
        <h2 className="text-3xl md:text-4xl font-medium text-white mb-14 tracking-tight">
          From raw pile to approved deliverable
        </h2>

        <ol className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-px bg-gray-800/50 rounded-lg overflow-hidden border border-gray-800/60">
          {STEPS.map((step) => (
            <li key={step.step} className="bg-[#10141f] p-6">
              <span className="block text-3xl font-medium text-white/15 mb-4">{step.step}</span>
              <h3 className="text-base font-medium text-white mb-2">{step.title}</h3>
              <p className="text-sm leading-relaxed text-gray-400">{step.description}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
});

HowItWorksSection.displayName = "HowItWorksSection";

// CTA + Footer
const FooterSection = React.memo(() => {
  return (
    <footer className="border-t border-gray-800/50">
      <section className="px-6 py-20 md:py-28">
        <div
          className="absolute inset-x-0 pointer-events-none h-64"
          style={{
            background:
              "radial-gradient(ellipse 45% 60% at 50% 100%, rgba(99, 102, 241, 0.15), transparent 70%)",
          }}
          aria-hidden="true"
        />
        <div className="relative max-w-3xl mx-auto text-center">
          <h2
            className="text-3xl md:text-5xl font-medium text-center leading-tight mb-6"
            style={{
              background: "linear-gradient(to bottom, #ffffff, #ffffff, rgba(255, 255, 255, 0.6))",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              backgroundClip: "text",
              letterSpacing: "-0.05em",
            }}
          >
            Ready to audit your first pile?
          </h2>
          <p className="text-sm md:text-base text-gray-400 mb-10">
            One command seeds a synthetic five-document demo pile against the microfinance playbook.
          </p>
          <div className="flex flex-col items-center gap-4">
            <LinkButton to="/pipeline" variant="gradient" size="lg" className="rounded-lg">
              Run the demo
              <ArrowRight size={16} />
            </LinkButton>
            <code className="text-xs text-gray-500 bg-gray-900/80 border border-gray-800 rounded-md px-3 py-2">
              make demo
            </code>
          </div>
        </div>
      </section>

      <div className="border-t border-gray-800/50">
        <div className="max-w-7xl mx-auto px-6 py-8 flex flex-col md:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2 text-sm text-white/80">
            <LogoMark size={16} />
            Anchora
          </div>
          <p className="text-xs text-gray-500">
            © 2026 Anchora · Agentic Document Intelligence for Microfinance Compliance
          </p>
          <nav className="flex items-center gap-6">
            <Link to="/pipeline" className="text-xs text-gray-500 hover:text-white transition-colors">
              Pipeline
            </Link>
            <Link to="/review" className="text-xs text-gray-500 hover:text-white transition-colors">
              Review queue
            </Link>
          </nav>
        </div>
      </div>
    </footer>
  );
});

FooterSection.displayName = "FooterSection";

// Main Component
export default function Component() {
  return (
    <main className="min-h-screen bg-[#0c0f1a] text-white overflow-x-hidden">
      <Navigation />
      <Hero />
      <FeaturesSection />
      <RulesSection />
      <HowItWorksSection />
      <FooterSection />
    </main>
  );
}
