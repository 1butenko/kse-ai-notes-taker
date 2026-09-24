import type { NextConfig } from "next";

// Where the Next.js server reaches the API. Inside compose this is the `api` service.
// Note: rewrites are baked in at build time for `output: "standalone"`.
const apiUrl = process.env.API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    // Browser calls /api/* on the same origin; Next proxies to FastAPI (no CORS needed).
    return [{ source: "/api/:path*", destination: `${apiUrl}/:path*` }];
  },
};

export default nextConfig;
