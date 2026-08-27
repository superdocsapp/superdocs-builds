import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  agentRules: false,
  transpilePackages: [
    "@payment-security-self-assessment/evidence",
    "@payment-security-self-assessment/shared",
  ],
};

export default nextConfig;
