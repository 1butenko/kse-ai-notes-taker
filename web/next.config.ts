import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  env: {
    API_PORT: process.env.API_PORT ?? "8000",
  },
};

export default nextConfig;
