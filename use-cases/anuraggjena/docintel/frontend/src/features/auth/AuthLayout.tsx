import React from 'react'
import { FileText, Workflow, ShieldCheck } from 'lucide-react'

export function DocIntelLogo() {
  return (
    <div className="flex items-center gap-2.5">
      <svg
        width="32"
        height="32"
        viewBox="0 0 32 32"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="shrink-0"
      >
        <rect
          x="3"
          y="3"
          width="26"
          height="26"
          rx="6"
          stroke="#0F172A"
          strokeWidth="3.5"
        />
        <rect
          x="3"
          y="18"
          width="10"
          height="11"
          rx="2"
          fill="#2563EB"
        />
      </svg>
      <span className="text-xl font-bold tracking-tight text-slate-900">
        DocIntel
      </span>
    </div>
  )
}

interface AuthLayoutProps {
  children: React.ReactNode
}

export function AuthLayout({ children }: AuthLayoutProps) {
  return (
    <div className="min-h-screen w-full flex flex-col lg:flex-row bg-white text-slate-900 font-sans antialiased selection:bg-blue-100 selection:text-blue-900">
      {/* Left Column: Brand & Product Value Props with Light Grey Background */}
      <div className="w-full lg:w-1/2 flex flex-col justify-between p-8 sm:p-12 lg:p-16 xl:p-20 2xl:p-24 bg-slate-50/80 border-b lg:border-b-0 lg:border-r border-slate-200/80">
        <div className="max-w-[540px] mx-auto lg:mx-0 w-full">
          {/* Logo */}
          <div className="mb-12 lg:mb-16">
            <DocIntelLogo />
          </div>

          {/* Hero Heading & Subtitle */}
          <div className="space-y-4">
            <h1 className="text-3xl sm:text-4xl lg:text-[46px] xl:text-5xl font-serif font-normal text-slate-950 tracking-tight leading-[1.15]">
              AI workflows for
              <br />
              document intelligence
            </h1>
            <p className="text-slate-600 text-base sm:text-lg leading-relaxed pt-1">
              DocIntel helps teams analyze complex documents, apply expert reasoning,
              and produce audit-ready outputs with confidence.
            </p>
          </div>

          {/* Feature Badges */}
          <div className="mt-10 lg:mt-12 space-y-6">
            {/* Feature 1: Structured Analysis */}
            <div className="flex items-start gap-4 group">
              <div className="p-3 rounded-xl border border-slate-200/90 bg-white text-blue-600 shrink-0 mt-0.5 shadow-sm">
                <FileText className="w-5 h-5 stroke-[1.75]" />
              </div>
              <div className="space-y-1">
                <h3 className="text-base font-semibold text-slate-900">
                  Structured Analysis
                </h3>
                <p className="text-sm text-slate-500 leading-relaxed">
                  Extract facts and insights from unstructured documents.
                </p>
              </div>
            </div>

            {/* Feature 2: Expert Workflows */}
            <div className="flex items-start gap-4 group">
              <div className="p-3 rounded-xl border border-slate-200/90 bg-white text-blue-600 shrink-0 mt-0.5 shadow-sm">
                <Workflow className="w-5 h-5 stroke-[1.75]" />
              </div>
              <div className="space-y-1">
                <h3 className="text-base font-semibold text-slate-900">
                  Expert Workflows
                </h3>
                <p className="text-sm text-slate-500 leading-relaxed">
                  Built for tariff classification, compliance, and more.
                </p>
              </div>
            </div>

            {/* Feature 3: Audit Ready */}
            <div className="flex items-start gap-4 group">
              <div className="p-3 rounded-xl border border-slate-200/90 bg-white text-blue-600 shrink-0 mt-0.5 shadow-sm">
                <ShieldCheck className="w-5 h-5 stroke-[1.75]" />
              </div>
              <div className="space-y-1">
                <h3 className="text-base font-semibold text-slate-900">
                  Audit Ready
                </h3>
                <p className="text-sm text-slate-500 leading-relaxed">
                  Traceable reasoning, citations, and versioned outputs.
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Footer Attribution */}
        <div className="max-w-[540px] mx-auto lg:mx-0 w-full mt-12 lg:mt-16 pt-4 text-xs sm:text-sm text-slate-400 font-normal">
          ~ made by Anurag Jena.
        </div>
      </div>

      {/* Right Column: Spacious Authentication Form Container */}
      <div className="w-full lg:w-1/2 flex flex-col items-center justify-center p-8 sm:p-12 lg:p-16 xl:p-20 bg-white">
        <div className="w-full max-w-[420px]">
          {children}
        </div>
      </div>
    </div>
  )
}
