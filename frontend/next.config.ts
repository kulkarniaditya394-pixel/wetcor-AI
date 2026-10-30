import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  devIndicators: false,
  agentRules: false,
  images: { unoptimized: true },
  // Hosted static demo (Netlify): the only working page is the pre-computed showcase.
  async redirects() {
    return process.env.NEXT_PUBLIC_STATIC_DEMO === "1" ? [{ source: "/", destination: "/showcase", permanent: false }] : [];
  },
  async headers() {
    return [{ source: "/(.*)", headers: [{ key: "X-Content-Type-Options", value: "nosniff" }, { key: "Referrer-Policy", value: "no-referrer" }] }];
  },
};

export default nextConfig;
