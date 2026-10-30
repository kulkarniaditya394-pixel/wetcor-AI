import type { NextConfig } from "next";

// Hosted static demo (Netlify): exported to plain HTML/CSS/JS in `out/`; only the pre-computed showcase works.
// Enabled by NEXT_PUBLIC_STATIC_DEMO=1, or automatically on Netlify builds (NETLIFY=true) so no setting can be forgotten.
const staticDemo = process.env.NEXT_PUBLIC_STATIC_DEMO === "1" || process.env.NETLIFY === "true";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  devIndicators: false,
  agentRules: false,
  images: { unoptimized: true },
  env: { NEXT_PUBLIC_STATIC_DEMO: staticDemo ? "1" : "" }, // inlined into the browser bundle
  ...(staticDemo
    ? { output: "export" as const }
    : {
        async headers() {
          return [{ source: "/(.*)", headers: [{ key: "X-Content-Type-Options", value: "nosniff" }, { key: "Referrer-Policy", value: "no-referrer" }] }];
        },
      }),
};

export default nextConfig;
